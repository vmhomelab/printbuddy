"""GyroidVault API client.

Thin async client for a self-hosted `GyroidVault <https://github.com/TeeCodeDev/GyroidVault>`_
instance (AGPL-3.0, Node/Express). Printbuddy only talks to it over HTTP — no
code is shared — so it can browse the vault and import model files into the
Printbuddy library.

GyroidVault has no versioned/public API contract. The endpoints used here were
taken from its server source (``server/routes/*.js``, v2.3.x):

- ``GET  /healthz``                      → ``{status, version, ...}`` (no auth)
- ``GET  /api/auth/me``                  → current user (validates the API key)
- ``GET  /api/models``                   → paginated model list
- ``GET  /api/models/:id``               → model detail incl. ``files``
- ``GET  /api/categories`` / ``/api/tags``
- ``GET  /api/files/:id/download``       → raw file bytes

Authentication is a bearer JWT that the user generates inside GyroidVault
(``POST /api/auth/api-key``). Those keys never expire and cannot be revoked
individually, so callers must store them encrypted and never return them to
the browser.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx

logger = logging.getLogger(__name__)

# Downloads stream straight to disk; this only guards against a runaway or
# malicious upstream filling the data volume.
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
MAX_ASSET_BYTES = 10 * 1024 * 1024  # 10 MiB thumbnails

# Paths under which GyroidVault serves thumbnails / previews. The asset proxy
# only ever fetches these, so it cannot be abused to reach arbitrary API routes.
_ASSET_PATH_RE = re.compile(r"^/(?:uploads|library-files)/[^?#]+$|^/api/files/\d+/stream$")

_CONTENT_DISPOSITION_RE = re.compile(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", re.IGNORECASE)

# Minimum GyroidVault version this client was written against.
MIN_SUPPORTED_VERSION = (2, 3, 0)


class GyroidVaultError(Exception):
    """Base error for GyroidVault calls."""


class GyroidVaultUnavailableError(GyroidVaultError):
    """Instance unreachable, timed out, or returned a 5xx."""


class GyroidVaultAuthError(GyroidVaultError):
    """API key missing, invalid, or rejected."""


class GyroidVaultForbiddenError(GyroidVaultError):
    """Key is valid but not allowed to see this resource (private collection)."""


class GyroidVaultNotFoundError(GyroidVaultError):
    """Model or file does not exist."""


class GyroidVaultRateLimitError(GyroidVaultError):
    """GyroidVault's rate limiter kicked in (downloads: 60 per 15 min)."""


class GyroidVaultTooLargeError(GyroidVaultError):
    """Upstream file exceeds the configured download limit."""


def normalize_base_url(url: str) -> str:
    """Strip whitespace and trailing slashes so path joining stays predictable."""
    return (url or "").strip().rstrip("/")


def is_safe_asset_path(path: str) -> bool:
    """True if *path* is a GyroidVault-relative thumbnail/preview path we may proxy."""
    if not path or not isinstance(path, str):
        return False
    if ".." in unquote(path) or "\\" in path or "//" in path:
        return False
    return bool(_ASSET_PATH_RE.match(path))


def parse_version(value: str | None) -> tuple[int, ...] | None:
    if not value or not isinstance(value, str):
        return None
    parts = re.findall(r"\d+", value)
    if not parts:
        return None
    return tuple(int(p) for p in parts[:3])


def is_supported_version(value: str | None) -> bool:
    parsed = parse_version(value)
    return parsed is not None and parsed >= MIN_SUPPORTED_VERSION


def _filename_from_headers(headers: httpx.Headers) -> str | None:
    disposition = headers.get("content-disposition")
    if not disposition:
        return None
    match = _CONTENT_DISPOSITION_RE.search(disposition)
    if not match:
        return None
    name = os.path.basename(unquote(match.group(1)).strip())
    return name or None


class GyroidVaultClient:
    """Per-request client. Always ``await close()`` (or use ``async with``)."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        headers = {"Accept": "application/json", "User-Agent": "Printbuddy-GyroidVault/1.0"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        # follow_redirects stays off: a redirect could point the authenticated
        # request (and the bearer token) at an arbitrary host.
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout, read=max(timeout, 60.0)),
            follow_redirects=False,
            transport=transport,
        )

    async def __aenter__(self) -> GyroidVaultClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # ── low level ───────────────────────────────────────────────────────────

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        code = response.status_code
        if code < 400:
            if 300 <= code < 400:
                raise GyroidVaultUnavailableError(f"GyroidVault answered with an unexpected redirect ({code})")
            return
        message = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                message = str(body.get("error") or "")
        except ValueError:
            pass
        if code == 401:
            raise GyroidVaultAuthError(message or "GyroidVault rejected the API key")
        if code == 403:
            raise GyroidVaultForbiddenError(message or "Access denied by GyroidVault")
        if code == 404:
            raise GyroidVaultNotFoundError(message or "Not found in GyroidVault")
        if code == 429:
            raise GyroidVaultRateLimitError(message or "GyroidVault rate limit reached, try again later")
        raise GyroidVaultUnavailableError(message or f"GyroidVault returned HTTP {code}")

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise GyroidVaultUnavailableError("GyroidVault timed out") from exc
        except httpx.HTTPError as exc:
            raise GyroidVaultUnavailableError(f"Cannot reach GyroidVault: {exc.__class__.__name__}") from exc
        self._raise_for_status(response)
        try:
            return response.json()
        except ValueError as exc:
            raise GyroidVaultUnavailableError("GyroidVault returned a non-JSON response") from exc

    # ── endpoints ───────────────────────────────────────────────────────────

    async def health(self) -> dict:
        data = await self._get_json("/healthz")
        return data if isinstance(data, dict) else {}

    async def get_me(self) -> dict:
        data = await self._get_json("/api/auth/me")
        if not isinstance(data, dict):
            raise GyroidVaultAuthError("GyroidVault did not return a user for this API key")
        return data

    async def list_models(
        self,
        *,
        search: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        file_format: str | None = None,
        sort: str = "updated",
        order: str | None = None,
        page: int = 1,
        limit: int = 24,
    ) -> dict:
        params: dict[str, Any] = {"sort": sort, "page": page, "limit": limit}
        if search:
            params["search"] = search
        if category:
            params["category"] = category
        if tag:
            params["tag"] = tag
        if file_format:
            params["format"] = file_format
        if order:
            params["order"] = order
        data = await self._get_json("/api/models", params=params)
        return data if isinstance(data, dict) else {}

    async def get_model(self, model_id: int) -> dict:
        data = await self._get_json(f"/api/models/{int(model_id)}")
        if not isinstance(data, dict):
            raise GyroidVaultNotFoundError("Model not found in GyroidVault")
        return data

    async def list_categories(self) -> list[dict]:
        data = await self._get_json("/api/categories")
        return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []

    async def list_tags(self) -> list[dict]:
        data = await self._get_json("/api/tags")
        return [t for t in data if isinstance(t, dict)] if isinstance(data, list) else []

    async def download_file(
        self,
        file_id: int,
        dest_path: Path,
        *,
        max_bytes: int = MAX_DOWNLOAD_BYTES,
    ) -> tuple[int, str | None]:
        """Stream ``/api/files/:id/download`` into *dest_path*.

        Returns ``(bytes_written, filename_from_headers)``. On any error the
        partial file is removed.
        """
        written = 0
        try:
            async with self._client.stream("GET", f"/api/files/{int(file_id)}/download") as response:
                if response.status_code >= 300:
                    await response.aread()
                    self._raise_for_status(response)
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise GyroidVaultTooLargeError("File is larger than the import limit")
                filename = _filename_from_headers(response.headers)
                with open(dest_path, "wb") as fh:
                    async for chunk in response.aiter_bytes():
                        written += len(chunk)
                        if written > max_bytes:
                            raise GyroidVaultTooLargeError("File is larger than the import limit")
                        fh.write(chunk)
        except GyroidVaultError:
            dest_path.unlink(missing_ok=True)
            raise
        except httpx.TimeoutException as exc:
            dest_path.unlink(missing_ok=True)
            raise GyroidVaultUnavailableError("GyroidVault timed out during download") from exc
        except httpx.HTTPError as exc:
            dest_path.unlink(missing_ok=True)
            raise GyroidVaultUnavailableError(f"Download from GyroidVault failed: {exc.__class__.__name__}") from exc
        except OSError:
            dest_path.unlink(missing_ok=True)
            raise
        return written, filename

    async def fetch_asset(self, path: str, *, max_bytes: int = MAX_ASSET_BYTES) -> tuple[bytes, str]:
        """Fetch a thumbnail/preview image. Only image responses are returned."""
        if not is_safe_asset_path(path):
            raise GyroidVaultNotFoundError("Unsupported asset path")
        buf = bytearray()
        try:
            async with self._client.stream("GET", path) as response:
                if response.status_code >= 300:
                    await response.aread()
                    self._raise_for_status(response)
                content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if not content_type.startswith("image/") or content_type == "image/svg+xml":
                    raise GyroidVaultNotFoundError("Asset is not a raster image")
                async for chunk in response.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise GyroidVaultTooLargeError("Thumbnail too large")
        except httpx.TimeoutException as exc:
            raise GyroidVaultUnavailableError("GyroidVault timed out") from exc
        except httpx.HTTPError as exc:
            raise GyroidVaultUnavailableError(f"Cannot reach GyroidVault: {exc.__class__.__name__}") from exc
        return bytes(buf), content_type
