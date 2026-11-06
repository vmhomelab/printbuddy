"""Tests for resolving a preset's effective values via the sidecar.

The slice modal's settings panel needs the values a preset actually sets, not
the option schema's compiled-in defaults. Only the sidecar can answer that: a
"Standard" pick is a ``{inherits: ...}`` stub on our side, and local/cloud
presets are deltas whose remainder lives in the sidecar's bundled profile tree.
"""

import json

import httpx
import pytest

from backend.app.services.slicer_api import SlicerApiService, SlicerApiUnavailableError

PROCESS_STUB = json.dumps({"inherits": "0.20mm Standard @BBL X1C", "from": "system"})


def _service(handler) -> SlicerApiService:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return SlicerApiService("http://sidecar:3003", client=client)


class TestResolveProfile:
    @pytest.mark.asyncio
    async def test_returns_the_flattened_values(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/profiles/resolve"
            body = json.loads(request.content)
            assert body["category"] == "process"
            # The stub goes out as an object, not a JSON string.
            assert body["profile"]["inherits"] == "0.20mm Standard @BBL X1C"
            return httpx.Response(200, json={"profile": {"line_width": "0.42", "wall_loops": "2"}})

        service = _service(handler)
        result = await service.resolve_profile(PROCESS_STUB, "process")
        assert result.values == {"line_width": "0.42", "wall_loops": "2"}
        assert result.reason == "ok"

    @pytest.mark.asyncio
    async def test_a_sidecar_without_the_endpoint_is_reported_as_outdated(self):
        # Older images 404 here. This is the dominant case in practice -- an
        # install pulls SIDECAR_TAG:-latest regardless of its own release
        # channel -- and it is the one with a fix the user can act on, so it
        # must not be flattened into the generic failure.
        service = _service(lambda request: httpx.Response(404, json={"message": "Not Found"}))
        result = await service.resolve_profile(PROCESS_STUB, "process")
        assert result.values is None
        assert result.reason == "sidecar_outdated"

    @pytest.mark.asyncio
    async def test_a_sidecar_error_is_not_reported_as_outdated(self):
        # A broken sidecar and an old one call for different advice.
        service = _service(lambda request: httpx.Response(500, json={"message": "boom"}))
        result = await service.resolve_profile(PROCESS_STUB, "process")
        assert result.values is None
        assert result.reason == "sidecar_unavailable"

    @pytest.mark.asyncio
    async def test_unreachable_sidecar_still_raises(self):
        # Distinct from "too old": the caller reports this as slicing being
        # unavailable rather than silently showing defaults forever.
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        with pytest.raises(SlicerApiUnavailableError):
            await _service(handler).resolve_profile(PROCESS_STUB, "process")

    @pytest.mark.asyncio
    async def test_unparseable_preset_content_blames_the_preset(self):
        service = _service(lambda request: httpx.Response(200, json={"profile": {}}))
        result = await service.resolve_profile("not json", "process")
        assert result.values is None
        assert result.reason == "preset_unresolved"

    @pytest.mark.asyncio
    async def test_a_response_without_a_profile_object_returns_no_values(self):
        # Guards against reading a differently-shaped body as if it were values.
        service = _service(lambda request: httpx.Response(200, json={"ok": True}))
        result = await service.resolve_profile(PROCESS_STUB, "process")
        assert result.values is None
        assert result.reason == "sidecar_unavailable"

    @pytest.mark.asyncio
    async def test_an_already_flat_preset_round_trips(self):
        flat = json.dumps({"line_width": "0.45", "type": "process"})

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert "inherits" not in body["profile"]
            return httpx.Response(200, json={"profile": json.loads(flat)})

        assert (await _service(handler).resolve_profile(flat, "process")).values == {
            "line_width": "0.45",
            "type": "process",
        }
