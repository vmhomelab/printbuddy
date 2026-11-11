"""The {finish_photo_url} link opens with authentication on too.

The archive photo route needs a media token when authentication is on, and
nothing tapping a link in Telegram, CallMeBot or a Home Assistant notification
has one, so the link answered 401. With authentication on, the link now points
at a notification photo instead: an unguessable name that opens that one photo
for 3 days. With authentication off it stays the archive link, which needs no
login and doesn't expire.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.utils import notification_photos

ARCHIVE_ID = 42
FILENAME = "finish_20260101_120000_abcd1234.jpg"


@pytest.fixture
def photo(tmp_path, monkeypatch):
    """A finish photo on disk, and the notification photo store under tmp_path."""
    monkeypatch.setattr(notification_photos.settings, "base_dir", tmp_path)
    path = tmp_path / FILENAME
    path.write_bytes(b"\xff\xd8finish-photo")
    return path


async def _call(*, auth_on, external_url="https://printbuddy.example", photo_path=None, auth_error=False):
    from backend.app.main import _finish_photo_for_notification

    auth = AsyncMock(side_effect=RuntimeError("db down")) if auth_error else AsyncMock(return_value=auth_on)
    with (
        patch("backend.app.api.routes.settings.get_setting", AsyncMock(return_value=external_url)),
        patch("backend.app.core.auth.is_auth_enabled", auth),
        patch("backend.app.utils.archive_paths.find_archive_photo", return_value=photo_path),
    ):
        return await _finish_photo_for_notification(AsyncMock(), SimpleNamespace(), ARCHIVE_ID, FILENAME)


class TestFinishPhotoLink:
    @pytest.mark.asyncio
    async def test_auth_off_keeps_the_archive_link(self, photo):
        url, data = await _call(auth_on=False, photo_path=photo)

        assert url == f"https://printbuddy.example/api/v1/archives/{ARCHIVE_ID}/photos/{FILENAME}"
        assert data == photo.read_bytes()

    @pytest.mark.asyncio
    async def test_auth_off_without_external_url_is_relative(self, photo):
        url, _ = await _call(auth_on=False, external_url=None, photo_path=photo)

        assert url == f"/api/v1/archives/{ARCHIVE_ID}/photos/{FILENAME}"

    @pytest.mark.asyncio
    async def test_auth_on_links_a_notification_photo_that_serves_the_same_bytes(self, photo):
        url, data = await _call(auth_on=True, photo_path=photo)

        prefix = "https://printbuddy.example/api/v1/notifications/photos/"
        assert url.startswith(prefix)
        served = notification_photos.find_notification_photo(url[len(prefix) :])
        assert served is not None
        assert served.read_bytes() == photo.read_bytes()
        assert data == photo.read_bytes()

    @pytest.mark.asyncio
    async def test_auth_check_failing_is_treated_as_auth_on(self, photo):
        url, _ = await _call(auth_on=False, auth_error=True, photo_path=photo)

        assert "/api/v1/notifications/photos/" in url

    @pytest.mark.asyncio
    async def test_auth_on_without_the_photo_gives_no_link(self, photo):
        # A link to the archive route would only answer 401, so none at all.
        assert await _call(auth_on=True, photo_path=None) == (None, None)

    @pytest.mark.asyncio
    async def test_oversized_photo_is_linked_but_not_attached(self, photo):
        photo.write_bytes(b"\xff" * 2_500_001)

        url, data = await _call(auth_on=True, photo_path=photo)

        assert url is not None
        assert data is None
