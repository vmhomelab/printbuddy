"""Phone launcher: access addresses may embed each other, launcher routes exist."""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from backend.app.services import access_addresses


@pytest.fixture
def no_trusted_env(monkeypatch):
    from backend.app import main as main_module

    monkeypatch.setattr(main_module, "_TRUSTED_FRAME_ORIGINS", ())


@pytest.mark.asyncio
@pytest.mark.integration
async def test_access_addresses_may_frame_the_app(async_client: AsyncClient, monkeypatch, no_trusted_env):
    monkeypatch.setattr(access_addresses, "_csp_origins", ("http://192.168.1.10:8000", "https://box.tail1234.ts.net"))
    resp = await async_client.get("/api/v1/auth/status")
    assert "X-Frame-Options" not in resp.headers
    csp = resp.headers["Content-Security-Policy"]
    assert "frame-ancestors 'self' http://192.168.1.10:8000 https://box.tail1234.ts.net;" in csp
    # The launcher probes the addresses with an image request
    assert "http://192.168.1.10:8000" in csp.split("img-src")[1].split(";")[0]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_access_addresses_keeps_strict_framing(async_client: AsyncClient, monkeypatch, no_trusted_env):
    monkeypatch.setattr(access_addresses, "_csp_origins", ())
    resp = await async_client.get("/api/v1/auth/status")
    assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_saving_access_addresses_updates_framing(async_client: AsyncClient, monkeypatch, no_trusted_env):
    monkeypatch.setattr(access_addresses, "_csp_origins", ())
    value = json.dumps([{"name": "LAN", "url": "http://10.0.0.5:8000/"}])
    resp = await async_client.patch("/api/v1/settings/", json={"access_addresses": value})
    assert resp.status_code == 200
    resp = await async_client.get("/api/v1/auth/status")
    assert "frame-ancestors 'self' http://10.0.0.5:8000;" in resp.headers["Content-Security-Policy"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_launcher_routes_are_not_swallowed_by_the_spa(async_client: AsyncClient, tmp_path, monkeypatch):
    from backend.app import main as main_module

    (tmp_path / "launch.html").write_text("<!doctype html><title>launcher</title>")
    (tmp_path / "launch.js").write_text("console.log('launcher')")
    monkeypatch.setattr(main_module.app_settings, "static_dir", tmp_path)

    html = await async_client.get("/launch.html")
    assert html.status_code == 200
    assert "launcher" in html.text
    assert html.headers["content-type"].startswith("text/html")
    assert "no-cache" in html.headers["cache-control"]

    js = await async_client.get("/launch.js")
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("application/javascript")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_launcher_csp_does_not_depend_on_the_address_list(
    async_client: AsyncClient, tmp_path, monkeypatch, no_trusted_env
):
    """The SW replays the launcher's headers offline, so probing must not be
    limited to whatever addresses were configured when it was cached."""
    from backend.app import main as main_module

    (tmp_path / "launch.html").write_text("<!doctype html><title>launcher</title>")
    monkeypatch.setattr(main_module.app_settings, "static_dir", tmp_path)
    monkeypatch.setattr(access_addresses, "_csp_origins", ())

    resp = await async_client.get("/launch.html")
    csp = resp.headers["Content-Security-Policy"]
    img_src = csp.split("img-src")[1].split(";")[0]
    assert " http:" in img_src and " https:" in img_src
    assert "frame-src 'self' http: https:" in csp
    assert "frame-ancestors 'none'" in csp
