"""Access addresses: the URLs under which this Printbuddy instance is reachable.

Admins list e.g. a LAN address (http://192.168.1.10:8000), a Tailscale address
(https://printbuddy.tailnet.ts.net) and a public domain. The frontend shows the
connection the user is currently on, offers QR codes to open the others on a
phone, and lets the user switch between them.

To check whether another address is reachable from the *browser*, the frontend
loads a tiny image from that origin. The SPA's CSP only allows same-origin
images, so the configured origins are added to ``img-src`` via the cache here.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

MAX_ADDRESSES = 10
MAX_NAME_LENGTH = 50
MAX_URL_LENGTH = 300

# Origins (scheme://host[:port]) of the configured addresses, used by the CSP
# middleware. Refreshed whenever the setting is read or written.
_csp_origins: tuple[str, ...] = ()

_TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_TAILSCALE_ULA = ipaddress.ip_network("fd7a:115c:a1e0::/48")


def normalize_origin(url: str) -> str | None:
    """Return ``scheme://host[:port]`` for an http(s) URL, or None if invalid."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH:
        return None
    try:
        parts = urlsplit(url.strip())
        port = parts.port  # raises ValueError on garbage ports
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname
    if any(c in host for c in " ;,'\"<>\\"):
        return None
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    return f"{parts.scheme}://{host}" + (f":{port}" if port else "")


def classify_host(host: str) -> str:
    """Classify a hostname/IP as ``tailscale``, ``lan``, ``local`` or ``public``."""
    host = host.strip("[]").lower()
    if host.endswith(".ts.net"):
        return "tailscale"
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".lan") or host.endswith(".home.arpa"):
        return "lan" if host != "localhost" else "local"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "public"
    if ip in _TAILSCALE_CGNAT or ip in _TAILSCALE_ULA:
        return "tailscale"
    if ip.is_loopback:
        return "local"
    if ip.is_private or ip.is_link_local:
        return "lan"
    return "public"


def parse_access_addresses(raw: str | None) -> list[dict]:
    """Parse and sanitize the stored JSON list of ``{name, url}`` entries."""
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data[:MAX_ADDRESSES]:
        if not isinstance(item, dict):
            continue
        origin = normalize_origin(str(item.get("url", "")))
        if not origin:
            continue
        name = str(item.get("name") or "").strip()[:MAX_NAME_LENGTH]
        out.append({"name": name or origin, "url": origin})
    return out


def validate_access_addresses(raw: str) -> str:
    """Validate a setting value; returns the normalized JSON string."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ValueError("access_addresses must be a JSON list") from exc
    if not isinstance(data, list):
        raise ValueError("access_addresses must be a JSON list")
    if len(data) > MAX_ADDRESSES:
        raise ValueError(f"at most {MAX_ADDRESSES} access addresses are allowed")
    for item in data:
        if not isinstance(item, dict) or not normalize_origin(str(item.get("url", ""))):
            raise ValueError(f"invalid access address: {item!r}")
    return json.dumps(parse_access_addresses(raw))


def update_csp_origins(raw: str | None) -> None:
    global _csp_origins
    _csp_origins = tuple(sorted({a["url"] for a in parse_access_addresses(raw)}))


def get_csp_origins() -> tuple[str, ...]:
    return _csp_origins
