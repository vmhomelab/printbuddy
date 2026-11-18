"""Integration tests for managing the "Report failed print" reasons (defaults, custom, icons)."""

import io
from datetime import datetime

import pytest
from httpx import AsyncClient
from PIL import Image

from backend.app.core.config import settings

API = "/api/v1/custom-failure-reports"


@pytest.fixture(autouse=True)
async def _seed_default_reasons(db_session):
    """The app seeds the default reasons at startup (init_db), which the test client skips."""
    from backend.app.services.custom_failure_reasons import ensure_default_reasons

    await ensure_default_reasons(db_session)


async def _report(client: AsyncClient, printer_id: int, archive_id: int, reason: str, **extra):
    response = await client.post(
        f"{API}/",
        json={"printer_id": printer_id, "archive_id": archive_id, "custom_failure_reason": reason, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _reasons(client: AsyncClient, include_hidden: bool = False) -> list[dict]:
    response = await client.get(f"{API}/reasons/", params={"include_hidden": include_hidden})
    assert response.status_code == 200, response.text
    return response.json()


async def _reason_id(client: AsyncClient, code: str) -> int:
    return next(r["id"] for r in await _reasons(client, include_hidden=True) if r["code"] == code)


def _png_bytes(size: tuple[int, int]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", size, (255, 0, 0, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


class TestManageReasons:
    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_add_custom_reason_and_report_with_it(self, async_client, printer_factory, archive_factory):
        response = await async_client.post(
            f"{API}/reasons/",
            json={"title": "Druckkopf-Crash", "subtitle": "Kollision, Düse abgerissen", "icon": "Zap"},
        )
        assert response.status_code == 200, response.text
        reason = response.json()
        assert reason["code"].startswith("custom_")
        assert reason["is_system"] is False
        assert [r["code"] for r in await _reasons(async_client)][-1] == reason["code"]

        printer = await printer_factory(name="X1C")
        archive = await archive_factory(printer.id)
        report = await _report(async_client, printer.id, archive.id, reason["code"])
        assert report["custom_failure_reason"] == reason["code"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rejects_missing_title_and_bad_icon_name(self, async_client):
        assert (await async_client.post(f"{API}/reasons/", json={"title": "   "})).status_code == 400
        assert (await async_client.post(f"{API}/reasons/", json={"title": "A", "icon": "../x"})).status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_limit_of_100_reasons(self, async_client):
        for i in range(86):  # 14 defaults + 86 custom = 100
            assert (await async_client.post(f"{API}/reasons/", json={"title": f"R{i}"})).status_code == 200
        response = await async_client.post(f"{API}/reasons/", json={"title": "one too many"})
        assert response.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_hiding_default_keeps_its_reports_and_counts(self, async_client, printer_factory, archive_factory):
        printer = await printer_factory(name="P1S")
        archive = await archive_factory(printer.id)
        await _report(async_client, printer.id, archive.id, "fail_reason_06")

        reason_id = await _reason_id(async_client, "fail_reason_06")
        response = await async_client.delete(f"{API}/reasons/{reason_id}")
        assert response.json() == {"status": "hidden"}
        assert "fail_reason_06" not in [r["code"] for r in await _reasons(async_client)]

        # The old report still counts; the hidden reason stays listed because it has a report.
        stats = (await async_client.get(f"{API}/stats")).json()
        assert stats["total"] == 1
        assert stats["reasons"][0]["reason"] == "fail_reason_06"
        assert len(stats["reasons"]) == 14

        # New reports can't pick it, but the existing report may keep it when edited.
        other = await archive_factory(printer.id, started_at=datetime(2026, 11, 4, 9, 0))
        response = await async_client.post(
            f"{API}/",
            json={"printer_id": printer.id, "archive_id": other.id, "custom_failure_reason": "fail_reason_06"},
        )
        assert response.status_code == 400
        report = (await async_client.get(f"{API}/")).json()[0]
        response = await async_client.patch(
            f"{API}/{report['id']}", json={"custom_failure_reason": "fail_reason_06", "comment": "still true"}
        )
        assert response.status_code == 200

        assert (await async_client.post(f"{API}/reasons/restore-defaults")).json() == {"restored": 1}
        assert "fail_reason_06" in [r["code"] for r in await _reasons(async_client)]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_hidden_reason_without_reports_leaves_statistics(self, async_client):
        reason_id = await _reason_id(async_client, "fail_reason_09")
        await async_client.delete(f"{API}/reasons/{reason_id}")
        stats = (await async_client.get(f"{API}/stats")).json()
        assert "fail_reason_09" not in [r["reason"] for r in stats["reasons"]]
        assert len(stats["reasons"]) == 13

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_unused_custom_reason_is_deleted_used_one_hidden(
        self, async_client, printer_factory, archive_factory
    ):
        unused = (await async_client.post(f"{API}/reasons/", json={"title": "Unused"})).json()
        used = (await async_client.post(f"{API}/reasons/", json={"title": "Used"})).json()
        printer = await printer_factory(name="K1")
        archive = await archive_factory(printer.id)
        await _report(async_client, printer.id, archive.id, used["code"])

        assert (await async_client.delete(f"{API}/reasons/{unused['id']}")).json() == {"status": "deleted"}
        assert (await async_client.delete(f"{API}/reasons/{used['id']}")).json() == {"status": "hidden"}
        codes = [r["code"] for r in await _reasons(async_client, include_hidden=True)]
        assert unused["code"] not in codes
        assert used["code"] in codes

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_default_icon_follows_code_until_one_is_picked(self, async_client, monkeypatch):
        from backend.app.services import custom_failure_reasons as reasons_service

        reason_id = await _reason_id(async_client, "fail_reason_04")
        # Editing only the text must not pin the icon.
        await async_client.patch(f"{API}/reasons/{reason_id}", json={"title": "Slicer"})
        monkeypatch.setitem(reasons_service.DEFAULT_ICONS, "fail_reason_04", "Zap")
        reason = next(r for r in await _reasons(async_client) if r["code"] == "fail_reason_04")
        assert reason["icon"] == "Zap"

        # Once the user picks an icon, it stays.
        await async_client.patch(f"{API}/reasons/{reason_id}", json={"icon": "Flame"})
        monkeypatch.setitem(reasons_service.DEFAULT_ICONS, "fail_reason_04", "Ruler")
        reason = next(r for r in await _reasons(async_client) if r["code"] == "fail_reason_04")
        assert reason["icon"] == "Flame"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_edit_default_text_and_reset_to_translation(self, async_client):
        reason_id = await _reason_id(async_client, "fail_reason_01")
        response = await async_client.patch(
            f"{API}/reasons/{reason_id}",
            json={"title": "Düse dicht", "subtitle": "Nichts kommt raus", "icon": "Flame"},
        )
        assert response.json()["title"] == "Düse dicht"
        assert response.json()["icon"] == "Flame"

        response = await async_client.patch(f"{API}/reasons/{reason_id}", json={"title": "", "subtitle": ""})
        assert response.status_code == 200
        assert response.json()["title"] is None  # back to the translated default text
        assert response.json()["subtitle"] is None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_custom_reason_needs_a_title_when_edited(self, async_client):
        reason = (await async_client.post(f"{API}/reasons/", json={"title": "Mine"})).json()
        response = await async_client.patch(f"{API}/reasons/{reason['id']}", json={"title": " "})
        assert response.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_reorder(self, async_client):
        reasons = await _reasons(async_client)
        response = await async_client.put(f"{API}/reasons/order", json={"ids": [reasons[2]["id"], reasons[0]["id"]]})
        assert response.status_code == 200
        codes = [r["code"] for r in await _reasons(async_client)]
        assert codes[:3] == ["fail_reason_03", "fail_reason_01", "fail_reason_02"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_custom_icon_is_scaled_to_500px_and_removable(self, async_client, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "archive_dir", tmp_path)
        reason_id = await _reason_id(async_client, "fail_reason_02")

        response = await async_client.post(
            f"{API}/reasons/{reason_id}/icon", files={"file": ("big.png", _png_bytes((1200, 800)), "image/png")}
        )
        assert response.status_code == 200, response.text
        stored = tmp_path / "failure_reason_icons" / response.json()["custom_icon_filename"]
        with Image.open(stored) as image:
            assert image.size == (500, 333)

        icon = await async_client.get(f"{API}/reasons/{reason_id}/icon")
        assert icon.status_code == 200
        assert icon.headers["content-type"] == "image/png"

        response = await async_client.delete(f"{API}/reasons/{reason_id}/icon")
        assert response.json()["custom_icon_filename"] is None
        assert not stored.exists()
        assert (await async_client.get(f"{API}/reasons/{reason_id}/icon")).status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_small_icon_is_kept_at_its_size(self, async_client, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "archive_dir", tmp_path)
        reason_id = await _reason_id(async_client, "fail_reason_03")
        response = await async_client.post(
            f"{API}/reasons/{reason_id}/icon", files={"file": ("small.png", _png_bytes((64, 64)), "image/png")}
        )
        with Image.open(tmp_path / "failure_reason_icons" / response.json()["custom_icon_filename"]) as image:
            assert image.size == (64, 64)

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rejects_non_image_upload(self, async_client, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "archive_dir", tmp_path)
        reason_id = await _reason_id(async_client, "fail_reason_02")
        response = await async_client.post(
            f"{API}/reasons/{reason_id}/icon", files={"file": ("fake.png", b"not an image", "image/png")}
        )
        assert response.status_code == 400
        response = await async_client.post(
            f"{API}/reasons/{reason_id}/icon", files={"file": ("doc.pdf", b"%PDF", "application/pdf")}
        )
        assert response.status_code == 400
