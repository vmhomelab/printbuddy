"""Unit tests for access-address parsing, validation and classification."""

import json

import pytest

from backend.app.services.access_addresses import (
    classify_host,
    get_csp_origins,
    normalize_origin,
    parse_access_addresses,
    update_csp_origins,
    validate_access_addresses,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://192.168.1.10:8000/", "http://192.168.1.10:8000"),
        ("https://printbuddy.tail1234.ts.net/queue?x=1", "https://printbuddy.tail1234.ts.net"),
        ("http://[fd7a:115c:a1e0::1]:8000", "http://[fd7a:115c:a1e0::1]:8000"),
        ("javascript:alert(1)", None),
        ("ftp://example.com", None),
        ("http://", None),
        ("http://bad host;", None),
        ("http://example.com:99999", None),
    ],
)
def test_normalize_origin(url, expected):
    assert normalize_origin(url) == expected


@pytest.mark.parametrize(
    ("host", "kind"),
    [
        ("100.101.102.103", "tailscale"),
        ("box.tail1234.ts.net", "tailscale"),
        ("fd7a:115c:a1e0::1", "tailscale"),
        ("192.168.1.10", "lan"),
        ("10.0.0.5", "lan"),
        ("printbuddy.local", "lan"),
        ("127.0.0.1", "local"),
        ("localhost", "local"),
        ("printbuddy.example.com", "public"),
        ("8.8.8.8", "public"),
    ],
)
def test_classify_host(host, kind):
    assert classify_host(host) == kind


def test_parse_drops_invalid_entries_and_normalizes():
    raw = json.dumps(
        [
            {"name": "LAN", "url": "http://192.168.1.10:8000/"},
            {"name": "bad", "url": "javascript:alert(1)"},
            "not-a-dict",
            {"url": "https://box.tail1234.ts.net"},
        ]
    )
    assert parse_access_addresses(raw) == [
        {"name": "LAN", "url": "http://192.168.1.10:8000"},
        {"name": "https://box.tail1234.ts.net", "url": "https://box.tail1234.ts.net"},
    ]
    assert parse_access_addresses("garbage") == []
    assert parse_access_addresses(None) == []


def test_validate_rejects_invalid_and_too_many():
    with pytest.raises(ValueError):
        validate_access_addresses(json.dumps([{"name": "x", "url": "javascript:alert(1)"}]))
    with pytest.raises(ValueError):
        validate_access_addresses(json.dumps({"name": "x"}))
    with pytest.raises(ValueError):
        validate_access_addresses(json.dumps([{"url": f"http://10.0.0.{i}"} for i in range(11)]))


def test_csp_origins_follow_setting():
    update_csp_origins(json.dumps([{"name": "a", "url": "http://10.0.0.1:8000/x"}]))
    assert get_csp_origins() == ("http://10.0.0.1:8000",)
    update_csp_origins("[]")
    assert get_csp_origins() == ()
