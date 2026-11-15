"""Unit tests for the OctoPrint subnet scanner probe logic."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.app.services.discovery import OctoPrintSubnetScanner, parse_octoprint_scan_ports

# Recorded from OctoPrint 1.11.8's bundled Discovery plugin.
DISCOVERY_XML = (Path(__file__).resolve().parents[1] / "_fixtures" / "octoprint" / "discovery.xml").read_text()


def _response(status_code: int, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


def _client(routes: dict[str, object]) -> AsyncMock:
    client = AsyncMock()

    async def get(url: str):
        result = routes.get(url, _response(404))
        if isinstance(result, Exception):
            raise result
        return result

    client.get = AsyncMock(side_effect=get)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def test_parse_ports_default_and_custom():
    assert parse_octoprint_scan_ports(None) == [5000, 80]
    assert parse_octoprint_scan_ports("") == [5000, 80]
    assert parse_octoprint_scan_ports("80,5000,80") == [80, 5000]
    assert parse_octoprint_scan_ports([5001]) == [5001]


def test_parse_ports_reads_environment(monkeypatch):
    monkeypatch.setenv("DISCOVERY_OCTOPRINT_PORTS", "8080")

    assert parse_octoprint_scan_ports(None) == [8080]


@pytest.mark.asyncio
async def test_probe_identifies_octoprint_via_discovery_plugin():
    scanner = OctoPrintSubnetScanner()
    client = _client({"http://192.168.1.60:5000/plugin/discovery/discovery.xml": _response(200, DISCOVERY_XML)})

    with patch("httpx.AsyncClient", return_value=client):
        await scanner._do_probe("192.168.1.60", timeout=0.5, ports=[5000, 80])

    [hit] = scanner.discovered_printers
    assert hit.name == "OctoPrint instance on vm"
    assert hit.api_url == "http://192.168.1.60:5000"
    assert hit.serial == "OCTOPRINT-192-168-1-60"
    assert hit.needs_auth is True


@pytest.mark.asyncio
async def test_probe_falls_back_to_login_page_on_octopi_port_80():
    scanner = OctoPrintSubnetScanner()
    client = _client(
        {
            "http://192.168.1.61:5000/plugin/discovery/discovery.xml": httpx.ConnectError("refused"),
            "http://192.168.1.61/plugin/discovery/discovery.xml": _response(404),
            "http://192.168.1.61/login": _response(200, "<html><head><title>OctoPrint Login</title></head></html>"),
        }
    )

    with patch("httpx.AsyncClient", return_value=client):
        await scanner._do_probe("192.168.1.61", timeout=0.5, ports=[5000, 80])

    [hit] = scanner.discovered_printers
    assert hit.name == "OctoPrint (192.168.1.61)"
    assert hit.api_url == "http://192.168.1.61"


@pytest.mark.asyncio
async def test_probe_ignores_other_http_services():
    scanner = OctoPrintSubnetScanner()
    client = _client(
        {
            "http://192.168.1.62:5000/plugin/discovery/discovery.xml": _response(200, "<root>Some UPnP device</root>"),
            "http://192.168.1.62:5000/login": _response(200, "<html><title>Router login</title></html>"),
            "http://192.168.1.62/plugin/discovery/discovery.xml": _response(401),
            "http://192.168.1.62/login": _response(401),
        }
    )

    with patch("httpx.AsyncClient", return_value=client):
        await scanner._do_probe("192.168.1.62", timeout=0.5, ports=[5000, 80])

    assert scanner.discovered_printers == []
