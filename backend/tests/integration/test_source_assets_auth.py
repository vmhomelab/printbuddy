"""Source-snapshot images must load with auth enabled.

The "Source details" panel of a library file shows images from the saved
source snapshot through ``<img>`` tags, which cannot send an Authorization
header. The route authenticates the ``?token=`` media token and file
ownership itself (#3025), but the auth middleware matches
``PUBLIC_API_PATTERNS`` by substring and had no entry for ``/source-assets/``.
With auth enabled it answered 401 before the route's token check ran. Only the
cover survived, by accident: ``cover.png`` contains the ``/cover`` pattern meant
for printer covers. Every ``gallery-NN`` image was broken. Same fault class as
the ``/source-dl/`` fix (#3029).
"""

from __future__ import annotations

import json
import zipfile

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _admin_jwt(async_client: AsyncClient, suffix: str) -> str:
    setup = await async_client.post(
        "/api/v1/auth/setup",
        json={"auth_enabled": True, "admin_username": f"srcassets{suffix}", "admin_password": "AdminPass1!"},
    )
    assert setup.status_code in (200, 201), setup.text
    login = await async_client.post(
        "/api/v1/auth/login",
        json={"username": f"srcassets{suffix}", "password": "AdminPass1!"},
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def _media_token(async_client: AsyncClient, jwt: str) -> str:
    response = await async_client.post("/api/v1/auth/media-token", headers={"Authorization": f"Bearer {jwt}"})
    assert response.status_code == 200, response.text
    return response.json()["token"]


async def _file_with_snapshot(db_session, tmp_path, monkeypatch) -> int:
    from backend.app.api.routes import library
    from backend.app.models.library import LibraryFile

    monkeypatch.setattr(library.app_settings, "base_dir", tmp_path)
    monkeypatch.setattr(library.app_settings, "archive_dir", tmp_path)
    snapshot_path = tmp_path / "library/source-snapshots/model.zip"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "source_type": "makerworld",
        "model_id": 26,
        "profile_id": 2601,
        "title": "Archived model",
        "source_url": "https://makerworld.com/models/26#profileId-2601",
        "captured_at": "2026-09-10T09:00:00+00:00",
        "images": [{"name": "cover.png", "role": "cover"}, {"name": "gallery-01.png", "role": "gallery"}],
    }
    with zipfile.ZipFile(snapshot_path, "w") as archive:
        archive.writestr("snapshot.json", json.dumps(manifest))
        archive.writestr("cover.png", b"png-bytes")
        archive.writestr("gallery-01.png", b"gallery-bytes")

    row = LibraryFile(
        filename="model.3mf",
        file_path="library/files/model.3mf",
        file_type="3mf",
        file_size=4,
        source_type="makerworld",
        source_url=manifest["source_url"],
        source_snapshot_path="library/source-snapshots/model.zip",
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row.id


class TestTheSourceAssetReachesItsHandler:
    async def test_the_pattern_list_covers_the_source_assets_route(self):
        from backend.app.main import PUBLIC_API_PATTERNS

        # A gallery name: "cover.png" would match the unrelated "/cover" entry.
        path = "/api/v1/library/files/5/source-assets/gallery-01.png"
        assert any(p in path for p in PUBLIC_API_PATTERNS)

    async def test_the_image_loads_with_a_media_token_and_auth_enabled(
        self, async_client: AsyncClient, db_session, tmp_path, monkeypatch
    ):
        jwt = await _admin_jwt(async_client, "ok")
        file_id = await _file_with_snapshot(db_session, tmp_path, monkeypatch)
        token = await _media_token(async_client, jwt)

        # No Authorization header -- exactly what an <img> tag sends.
        response = await async_client.get(f"/api/v1/library/files/{file_id}/source-assets/gallery-01.png?token={token}")
        assert response.status_code == 200, response.text
        assert response.content == b"gallery-bytes"

    async def test_no_token_is_still_refused(self, async_client: AsyncClient, db_session, tmp_path, monkeypatch):
        """The middleware stepping aside must not make the route public."""
        await _admin_jwt(async_client, "none")
        file_id = await _file_with_snapshot(db_session, tmp_path, monkeypatch)

        response = await async_client.get(f"/api/v1/library/files/{file_id}/source-assets/gallery-01.png")
        assert response.status_code == 401

    async def test_a_garbage_token_is_refused(self, async_client: AsyncClient, db_session, tmp_path, monkeypatch):
        await _admin_jwt(async_client, "bad")
        file_id = await _file_with_snapshot(db_session, tmp_path, monkeypatch)

        response = await async_client.get(
            f"/api/v1/library/files/{file_id}/source-assets/gallery-01.png?token=not-a-real-token"
        )
        assert response.status_code == 401
