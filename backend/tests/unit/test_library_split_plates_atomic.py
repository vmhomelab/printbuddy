"""Split-plate library persist slices all plates before writing DB rows."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.app.api.routes.library import slice_and_persist
from backend.app.schemas.slicer import SliceRequest


def _slice_request(**overrides) -> SliceRequest:
    data = {
        "printer_preset": {"source": "local", "id": "1"},
        "process_preset": {"source": "local", "id": "2"},
        "filament_presets": [{"source": "local", "id": "3"}],
        "plate": 0,
        "split_plates": True,
        "export_3mf": True,
    }
    data.update(overrides)
    return SliceRequest.model_validate(data)


@pytest.mark.asyncio
async def test_split_plates_uses_discovered_ids_not_contiguous_range():
    """Sparse plates [1, 3] must not invent plate 2."""
    db = AsyncMock()
    results = []

    async def fake_run(_db, *, request, **_kwargs):
        results.append(request.plate)
        return (
            SimpleNamespace(
                content=b"gcode",
                print_time_seconds=10,
                filament_used_g=1.0,
                filament_used_mm=100.0,
            ),
            False,
        )

    async def fake_persist(_db, **kwargs):
        return SimpleNamespace(id=kwargs["plate_number"], filename=kwargs["out_filename"]), 1.0, 100.0

    persist = AsyncMock(side_effect=fake_persist)

    with (
        patch(
            "backend.app.api.routes.library.discover_plate_indices_from_bytes",
            return_value=[1, 3],
        ),
        patch("backend.app.api.routes.library._run_slicer_with_fallback", new=fake_run),
        patch("backend.app.api.routes.library._persist_sliced_library_file", new=persist),
        patch("backend.app.services.slice_dispatch.slice_dispatch.set_progress"),
    ):
        response = await slice_and_persist(
            db,
            model_bytes=b"fake-3mf",
            model_filename="model.3mf",
            folder_id=None,
            extra_metadata=None,
            request=_slice_request(),
            current_user_id=1,
            job_id=None,
        )

    assert results == [1, 3]
    assert response.library_file_ids == [1, 3]
    assert persist.await_count == 2
    for call in persist.await_args_list:
        assert call.kwargs.get("commit") is False
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_split_plates_skips_persist_when_later_plate_fails():
    db = AsyncMock()

    async def fake_run(_db, *, request, **_kwargs):
        if request.plate == 3:
            raise RuntimeError("slice failed on plate 3")
        return (
            SimpleNamespace(
                content=b"gcode",
                print_time_seconds=10,
                filament_used_g=1.0,
                filament_used_mm=100.0,
            ),
            False,
        )

    persist = AsyncMock()

    with (
        patch(
            "backend.app.api.routes.library.discover_plate_indices_from_bytes",
            return_value=[1, 3],
        ),
        patch("backend.app.api.routes.library._run_slicer_with_fallback", new=fake_run),
        patch("backend.app.api.routes.library._persist_sliced_library_file", new=persist),
        patch("backend.app.services.slice_dispatch.slice_dispatch.set_progress"),
        pytest.raises(RuntimeError, match="plate 3"),
    ):
        await slice_and_persist(
            db,
            model_bytes=b"fake-3mf",
            model_filename="model.3mf",
            folder_id=None,
            extra_metadata=None,
            request=_slice_request(),
            current_user_id=1,
            job_id=None,
        )

    persist.assert_not_awaited()
    db.commit.assert_not_awaited()
