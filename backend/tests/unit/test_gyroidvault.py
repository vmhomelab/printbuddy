"""Tests for the GyroidVault client and /gyroidvault/* routes.

GyroidVault is faked with an ``httpx.MockTransport`` whose payloads mirror the
shapes in GyroidVault's ``server/routes/*.js`` (v2.3.x), so the real client
code — status mapping, streaming download, asset allowlist — is exercised.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from backend.app.models.library import LibraryFile, LibraryFolder
from backend.app.services import gyroidvault as gv_service
from backend.app.services.gyroidvault import (
    GyroidVaultAuthError,
    GyroidVaultClient,
    GyroidVaultForbiddenError,
    GyroidVaultNotFoundError,
    GyroidVaultRateLimitError,
    GyroidVaultTooLargeError,
    GyroidVaultUnavailableError,
    is_safe_asset_path,
    is_supported_version,
)

BASE = "http://vault.lan:3457"
API_KEY = "test-jwt-token"
STL_BYTES = b"solid cube\nendsolid cube\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\nfake"

MODEL_LIST = {
    "models": [
        {
            "id": 7,
            "name": "Benchy",
            "description": "Boat",
            "category_id": 2,
            "category_name": "Tests",
            "category_color": "#8b5cf6",
            "thumbnail": "/uploads/thumb-7.png",
            "stl_file": "/library-files/Benchy/benchy.stl",
            "file_count": 2,
            "file_types": ["stl", "document"],
            "print_count": 1,
            "tags": [{"id": 3, "name": "calibration"}],
            "updated_at": "2026-10-01 10:00:00",
            "library_path": "/library/Benchy",
        },
        {"id": 8, "name": "External thumb", "thumbnail": "https://evil.example/x.png"},
    ],
    "totalItems": 2,
    "totalPages": 1,
    "currentPage": 1,
    "limit": 24,
    "totalStorageBytes": 123,
}

MODEL_DETAIL = {
    "id": 7,
    "name": "Benchy",
    "description": "Boat",
    "print_tips": "0.2mm",
    "source_url": "https://www.printables.com/model/3161",
    "thumbnail_url": "/uploads/thumb-7.png",
    "files": [
        {"id": 70, "filename": "benchy.stl", "original_name": "benchy.stl", "file_type": "stl", "file_size": 25},
        {"id": 71, "filename": "readme.pdf", "original_name": "readme.pdf", "file_type": "document", "file_size": 9},
        {"id": 72, "filename": "x", "original_name": "../../etc/evil.gcode", "file_type": "gcode", "file_size": 3},
    ],
    "prints": [{"id": 1}],
    "tags": [{"id": 3, "name": "calibration"}],
}


class FakeVault:
    """Minimal GyroidVault stand-in; records requests for assertions."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.overrides: dict[str, httpx.Response] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path in self.overrides:
            return self.overrides[path]
        if path == "/healthz":
            return httpx.Response(200, json={"status": "ok", "version": "2.3.1"})
        if request.headers.get("authorization") != f"Bearer {API_KEY}":
            return httpx.Response(401, json={"error": "Unauthorized"})
        if path == "/api/auth/me":
            return httpx.Response(200, json={"id": 1, "username": "printbuddy", "role": "viewer"})
        if path == "/api/models":
            return httpx.Response(200, json=MODEL_LIST)
        if path == "/api/models/7":
            return httpx.Response(200, json=MODEL_DETAIL)
        if path.startswith("/api/models/"):
            return httpx.Response(404, json={"error": "Model not found"})
        if path == "/api/categories":
            return httpx.Response(200, json=[{"id": 2, "name": "Tests", "color": "#fff", "model_count": 1}])
        if path == "/api/tags":
            return httpx.Response(200, json=[{"id": 3, "name": "calibration", "model_count": 1}])
        if path in ("/api/files/70/download", "/api/files/72/download"):
            return httpx.Response(
                200,
                content=STL_BYTES,
                headers={"content-disposition": 'attachment; filename="benchy.stl"'},
            )
        if path == "/uploads/thumb-7.png":
            return httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})
        return httpx.Response(404, json={"error": "nope"})


@pytest.fixture
def vault():
    return FakeVault()


@pytest.fixture
def patched_client(vault):
    """Route every GyroidVaultClient built by the routes through the fake vault."""
    real_cls = GyroidVaultClient

    def factory(base_url, api_key, **kwargs):
        return real_cls(base_url, api_key, transport=httpx.MockTransport(vault))

    with patch("backend.app.api.routes.gyroidvault.GyroidVaultClient", side_effect=factory):
        yield vault


@pytest.fixture
def library_tmp(tmp_path, monkeypatch):
    from backend.app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "base_dir", tmp_path)
    monkeypatch.setattr(app_settings, "archive_dir", tmp_path / "archive")
    return tmp_path


async def _configure(async_client, *, enabled=True, url=BASE, api_key=API_KEY):
    resp = await async_client.put(
        "/api/v1/gyroidvault/settings", json={"enabled": enabled, "url": url, "api_key": api_key}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── pure helpers ────────────────────────────────────────────────────────────


class TestHelpers:
    @pytest.mark.parametrize(
        "path",
        ["/uploads/thumb.png", "/library-files/Benchy/cover%20image.jpg", "/api/files/12/stream"],
    )
    def test_safe_asset_paths(self, path):
        assert is_safe_asset_path(path)

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "https://evil.example/x.png",
            "//evil.example/x.png",
            "/api/models",
            "/api/files/12/download",
            "/uploads/../server/index.js",
            "/uploads/%2e%2e/secret",
            "/uploads/a\\b",
            "/uploads/x.png?redirect=1",
            "/system/backup",
        ],
    )
    def test_unsafe_asset_paths(self, path):
        assert not is_safe_asset_path(path)

    def test_version_check(self):
        assert is_supported_version("2.3.1")
        assert is_supported_version("v3.0.0")
        assert not is_supported_version("2.2.9")
        assert not is_supported_version(None)
        assert not is_supported_version("garbage")


# ── client ──────────────────────────────────────────────────────────────────


class TestClient:
    def _client(self, handler, api_key=API_KEY):
        return GyroidVaultClient(BASE + "/", api_key, transport=httpx.MockTransport(handler))

    @pytest.mark.asyncio
    async def test_sends_bearer_and_strips_trailing_slash(self, vault):
        async with self._client(vault) as client:
            assert client.base_url == BASE
            me = await client.get_me()
        assert me["username"] == "printbuddy"
        assert vault.requests[-1].headers["authorization"] == f"Bearer {API_KEY}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "exc"),
        [
            (401, GyroidVaultAuthError),
            (403, GyroidVaultForbiddenError),
            (404, GyroidVaultNotFoundError),
            (429, GyroidVaultRateLimitError),
            (500, GyroidVaultUnavailableError),
            (302, GyroidVaultUnavailableError),
        ],
    )
    async def test_status_mapping(self, status, exc):
        def handler(request):
            return httpx.Response(status, json={"error": "x"}, headers={"location": "http://elsewhere/"})

        async with self._client(handler) as client:
            with pytest.raises(exc):
                await client.get_model(1)

    @pytest.mark.asyncio
    async def test_connection_error_is_unavailable(self):
        def handler(request):
            raise httpx.ConnectError("refused", request=request)

        async with self._client(handler) as client:
            with pytest.raises(GyroidVaultUnavailableError):
                await client.health()

    @pytest.mark.asyncio
    async def test_list_models_passes_filters(self, vault):
        async with self._client(vault) as client:
            await client.list_models(search="tag:boat", category="2", tag="3", file_format="stl", page=2, limit=10)
        params = vault.requests[-1].url.params
        assert params["search"] == "tag:boat"
        assert params["category"] == "2"
        assert params["tag"] == "3"
        assert params["format"] == "stl"
        assert params["page"] == "2"
        assert params["limit"] == "10"

    @pytest.mark.asyncio
    async def test_download_streams_to_disk(self, vault, tmp_path):
        dest = tmp_path / "out.stl"
        async with self._client(vault) as client:
            written, name = await client.download_file(70, dest)
        assert written == len(STL_BYTES)
        assert name == "benchy.stl"
        assert dest.read_bytes() == STL_BYTES

    @pytest.mark.asyncio
    async def test_download_size_limit_removes_partial_file(self, vault, tmp_path):
        dest = tmp_path / "out.stl"
        async with self._client(vault) as client:
            with pytest.raises(GyroidVaultTooLargeError):
                await client.download_file(70, dest, max_bytes=5)
        assert not dest.exists()

    @pytest.mark.asyncio
    async def test_download_error_status(self, vault, tmp_path):
        dest = tmp_path / "out.stl"
        async with self._client(vault) as client:
            with pytest.raises(GyroidVaultNotFoundError):
                await client.download_file(999, dest)
        assert not dest.exists()

    @pytest.mark.asyncio
    async def test_fetch_asset_rejects_unsafe_path_without_request(self, vault):
        async with self._client(vault) as client:
            with pytest.raises(GyroidVaultNotFoundError):
                await client.fetch_asset("/api/models")
        assert vault.requests == []

    @pytest.mark.asyncio
    async def test_fetch_asset_rejects_non_images(self, vault):
        vault.overrides["/uploads/page.html"] = httpx.Response(
            200, content=b"<html>", headers={"content-type": "text/html"}
        )
        vault.overrides["/uploads/x.svg"] = httpx.Response(
            200, content=b"<svg/>", headers={"content-type": "image/svg+xml"}
        )
        async with self._client(vault) as client:
            data, ctype = await client.fetch_asset("/uploads/thumb-7.png")
            assert data == PNG_BYTES and ctype == "image/png"
            with pytest.raises(GyroidVaultNotFoundError):
                await client.fetch_asset("/uploads/page.html")
            with pytest.raises(GyroidVaultNotFoundError):
                await client.fetch_asset("/uploads/x.svg")


# ── routes ──────────────────────────────────────────────────────────────────


class TestSettingsRoutes:
    @pytest.mark.asyncio
    async def test_defaults(self, async_client):
        resp = await async_client.get("/api/v1/gyroidvault/settings")
        assert resp.status_code == 200
        assert resp.json() == {"enabled": False, "url": "", "has_api_key": False}

    @pytest.mark.asyncio
    async def test_api_key_is_encrypted_and_never_returned(self, async_client, db_session):
        from backend.app.api.routes.settings import get_setting

        body = await _configure(async_client, url=BASE + "/")
        assert body == {"enabled": True, "url": BASE, "has_api_key": True}
        assert API_KEY not in json.dumps(body)

        stored = await get_setting(db_session, "gyroidvault_api_key")
        assert stored and stored != API_KEY and stored.startswith("fernet:")

    @pytest.mark.asyncio
    async def test_omitting_api_key_keeps_it_and_empty_clears_it(self, async_client):
        await _configure(async_client)
        resp = await async_client.put("/api/v1/gyroidvault/settings", json={"enabled": True})
        assert resp.json()["has_api_key"] is True
        resp = await async_client.put("/api/v1/gyroidvault/settings", json={"api_key": ""})
        assert resp.json()["has_api_key"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        ["file:///etc/passwd", "http://169.254.169.254", "http://2130706433", "http://vault.lan/?x=1"],
    )
    async def test_rejects_unsafe_urls(self, async_client, url):
        resp = await async_client.put("/api/v1/gyroidvault/settings", json={"url": url})
        assert resp.status_code == 400, resp.text

    @pytest.mark.asyncio
    async def test_private_lan_url_allowed(self, async_client):
        resp = await async_client.put("/api/v1/gyroidvault/settings", json={"url": "http://192.168.1.20:3457"})
        assert resp.status_code == 200
        assert resp.json()["url"] == "http://192.168.1.20:3457"

    @pytest.mark.asyncio
    async def test_connection_test_ok(self, async_client, patched_client):
        await _configure(async_client)
        resp = await async_client.post("/api/v1/gyroidvault/test")
        body = resp.json()
        assert body["ok"] is True
        assert body["version"] == "2.3.1"
        assert body["role"] == "viewer"
        assert body["warning"] is None

    @pytest.mark.asyncio
    async def test_connection_test_warns_for_write_role(self, async_client, patched_client):
        patched_client.overrides["/api/auth/me"] = httpx.Response(200, json={"username": "admin", "role": "admin"})
        await _configure(async_client)
        body = (await async_client.post("/api/v1/gyroidvault/test")).json()
        assert body["ok"] is True
        assert "viewer" in body["warning"]

    @pytest.mark.asyncio
    async def test_connection_test_with_bad_key_override(self, async_client, patched_client):
        await _configure(async_client)
        body = (await async_client.post("/api/v1/gyroidvault/test", json={"api_key": "wrong"})).json()
        assert body["ok"] is False
        assert "API key rejected" in body["error"]


class TestBrowseRoutes:
    @pytest.mark.asyncio
    async def test_disabled_integration_returns_409(self, async_client):
        resp = await async_client.get("/api/v1/gyroidvault/models")
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_status(self, async_client, patched_client):
        await _configure(async_client)
        body = (await async_client.get("/api/v1/gyroidvault/status")).json()
        assert body == {
            "enabled": True,
            "configured": True,
            "connected": True,
            "version": "2.3.1",
            "supported_version": True,
            "error": None,
        }

    @pytest.mark.asyncio
    async def test_status_reports_upstream_auth_failure(self, async_client, patched_client):
        await _configure(async_client, api_key="wrong")
        body = (await async_client.get("/api/v1/gyroidvault/status")).json()
        assert body["connected"] is False
        assert body["error"]

    @pytest.mark.asyncio
    async def test_list_models_shapes_and_filters_thumbnails(self, async_client, patched_client):
        await _configure(async_client)
        resp = await async_client.get("/api/v1/gyroidvault/models", params={"search": "benchy"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_items"] == 2
        first, second = body["models"]
        assert first["thumbnail_path"] == "/uploads/thumb-7.png"
        assert first["tags"] == [{"id": 3, "name": "calibration"}]
        assert "library_path" not in first  # internal server paths are not passed through
        assert second["thumbnail_path"] is None  # absolute external URL is never proxied

    @pytest.mark.asyncio
    async def test_list_models_validates_query(self, async_client, patched_client):
        await _configure(async_client)
        resp = await async_client.get("/api/v1/gyroidvault/models", params={"sort": "m.id; DROP"})
        assert resp.status_code == 422
        resp = await async_client.get("/api/v1/gyroidvault/models", params={"limit": 1000})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_upstream_auth_error_is_not_a_401(self, async_client, patched_client):
        await _configure(async_client, api_key="wrong")
        resp = await async_client.get("/api/v1/gyroidvault/models")
        assert resp.status_code == 502

    @pytest.mark.asyncio
    async def test_model_detail(self, async_client, patched_client):
        await _configure(async_client)
        resp = await async_client.get("/api/v1/gyroidvault/models/7")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["web_url"] == f"{BASE}/#/models/7"
        assert body["thumbnail_path"] == "/uploads/thumb-7.png"
        assert body["print_count"] == 1
        files = {f["id"]: f for f in body["files"]}
        assert files[70]["importable"] is True
        assert files[71]["importable"] is False
        assert files[72]["filename"] == "evil.gcode"  # basename only

    @pytest.mark.asyncio
    async def test_model_not_found(self, async_client, patched_client):
        await _configure(async_client)
        resp = await async_client.get("/api/v1/gyroidvault/models/999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_categories_and_tags(self, async_client, patched_client):
        await _configure(async_client)
        cats = (await async_client.get("/api/v1/gyroidvault/categories")).json()
        tags = (await async_client.get("/api/v1/gyroidvault/tags")).json()
        assert cats == [{"id": 2, "name": "Tests", "color": "#fff", "model_count": 1}]
        assert tags == [{"id": 3, "name": "calibration"}]

    @pytest.mark.asyncio
    async def test_asset_proxy(self, async_client, patched_client):
        await _configure(async_client)
        resp = await async_client.get("/api/v1/gyroidvault/asset", params={"path": "/uploads/thumb-7.png"})
        assert resp.status_code == 200
        assert resp.content == PNG_BYTES
        assert resp.headers["content-type"] == "image/png"

    @pytest.mark.asyncio
    async def test_asset_proxy_rejects_api_paths(self, async_client, patched_client):
        await _configure(async_client)
        resp = await async_client.get("/api/v1/gyroidvault/asset", params={"path": "/api/system/backup"})
        assert resp.status_code == 400
        assert patched_client.requests == []


class TestImportRoute:
    @pytest.mark.asyncio
    async def test_import_creates_default_folder_and_dedupes(
        self, async_client, db_session, patched_client, library_tmp
    ):
        await _configure(async_client)
        resp = await async_client.post("/api/v1/gyroidvault/import", json={"model_id": 7, "file_ids": [70]})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        result = body["files"][0]
        assert result["error"] is None
        assert result["was_existing"] is False
        assert result["filename"] == "benchy.stl"

        row = await db_session.get(LibraryFile, result["library_file_id"])
        assert row.source_type == "gyroidvault"
        assert row.source_url == f"{BASE}/#/models/7?file=70"
        assert row.file_type == "stl"
        assert row.file_size == len(STL_BYTES)
        folder = await db_session.get(LibraryFolder, body["folder_id"])
        assert folder.name == "GyroidVault"
        stored = Path(library_tmp) / row.file_path
        assert stored.read_bytes() == STL_BYTES

        downloads_before = sum(1 for r in patched_client.requests if r.url.path.endswith("/download"))
        again = (await async_client.post("/api/v1/gyroidvault/import", json={"model_id": 7, "file_ids": [70]})).json()
        assert again["files"][0]["was_existing"] is True
        assert again["files"][0]["library_file_id"] == row.id
        assert again["folder_id"] == body["folder_id"]
        downloads_after = sum(1 for r in patched_client.requests if r.url.path.endswith("/download"))
        assert downloads_after == downloads_before

        detail = (await async_client.get("/api/v1/gyroidvault/models/7")).json()
        assert {f["id"]: f["imported_library_file_id"] for f in detail["files"]}[70] == row.id

        recent = (await async_client.get("/api/v1/gyroidvault/recent-imports")).json()
        assert [r["library_file_id"] for r in recent] == [row.id]

    @pytest.mark.asyncio
    async def test_import_reports_per_file_errors(self, async_client, patched_client, library_tmp):
        await _configure(async_client)
        resp = await async_client.post("/api/v1/gyroidvault/import", json={"model_id": 7, "file_ids": [71, 72, 70]})
        assert resp.status_code == 200, resp.text
        files = {f["gyroidvault_file_id"]: f for f in resp.json()["files"]}
        assert files[71]["error"] == "File type cannot be imported"
        assert files[72]["error"] is None and files[72]["filename"] == "evil.gcode"
        assert files[70]["error"] is None

    @pytest.mark.asyncio
    async def test_import_rejects_files_of_other_models(self, async_client, patched_client, library_tmp):
        await _configure(async_client)
        resp = await async_client.post("/api/v1/gyroidvault/import", json={"model_id": 7, "file_ids": [999]})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_import_stops_after_rate_limit(self, async_client, patched_client, library_tmp):
        patched_client.overrides["/api/files/70/download"] = httpx.Response(429, json={"error": "Too many"})
        await _configure(async_client)
        resp = await async_client.post("/api/v1/gyroidvault/import", json={"model_id": 7, "file_ids": [70, 72]})
        files = resp.json()["files"]
        assert all(f["error"] for f in files)
        assert not any(r.url.path == "/api/files/72/download" for r in patched_client.requests)

    @pytest.mark.asyncio
    async def test_import_into_missing_folder(self, async_client, patched_client, library_tmp):
        await _configure(async_client)
        resp = await async_client.post(
            "/api/v1/gyroidvault/import", json={"model_id": 7, "file_ids": [70], "folder_id": 4242}
        )
        assert resp.status_code == 404


def test_module_exports_limits():
    assert gv_service.MAX_DOWNLOAD_BYTES > gv_service.MAX_ASSET_BYTES


class TestAppSettingsFlag:
    @pytest.mark.asyncio
    async def test_enabled_flag_is_exposed_read_only(self, async_client):
        resp = await async_client.get("/api/v1/settings/")
        assert resp.json()["gyroidvault_enabled"] is False

        await _configure(async_client)
        body = (await async_client.get("/api/v1/settings/")).json()
        assert body["gyroidvault_enabled"] is True
        assert "gyroidvault_api_key" not in body

        # The generic settings PUT must not be able to flip it.
        await async_client.put("/api/v1/settings/", json={"gyroidvault_enabled": False})
        assert (await async_client.get("/api/v1/settings/")).json()["gyroidvault_enabled"] is True
