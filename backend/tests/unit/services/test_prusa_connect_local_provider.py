import json

import httpx
import pytest

from backend.app.schemas.printer import PrinterCreate
from backend.app.services.printer_providers import prusaconnectlocal
from backend.app.services.printer_providers.factory import create_printer_client
from backend.app.services.printer_providers.prusaconnectlocal import (
    PrusaConnectLocalError,
    PrusaConnectLocalPrinterClient,
    build_prusa_connect_local_base_url,
    list_prusa_connect_local_devices,
    prusa_connect_local_serial,
    summarize_prusa_connect_local_device,
)

DEVICE_ID = "9f2a4c18-6d3b-4e07-b5a1-8c0f2d7e4b93"


def _device(device_id=DEVICE_ID, *, state="PRINTING", connected=True, retired=None):
    device = {
        "kind": "printer",
        "id": device_id,
        "name": "CoreOne 29876543",
        "vendor": "Prusa",
        "model": "CoreOne",
        "firmware": "6.4.0-0",
        "serial": "29876543",
        "unit_uid": "",
        "connected": connected,
        "actions": ["observe", "operate"],
        "capabilities": ["core.command.pause_print"],
        "state": {
            "/state": state,
            "/temperature/bed": 59.9,
            "/temperature/bed_target": 60,
            "/tools/0/nozzle_temp": 214.8,
            "/tools/0/nozzle_target_temp": 215,
        },
        "job": {
            "device_job_id": "41",
            "path": "/usb/benchy.bgcode",
            "display_name": "Benchy",
            "state": state,
            "progress": 37,
            "time_remaining_ms": 2160000,
            "running": state == "PRINTING",
        },
    }
    if retired:
        device["retired"] = retired
    return device


def test_base_url_defaults_to_port_8080():
    assert build_prusa_connect_local_base_url("192.168.1.5") == "http://192.168.1.5:8080/"
    assert build_prusa_connect_local_base_url("192.168.1.5:9000") == "http://192.168.1.5:9000/"
    assert build_prusa_connect_local_base_url("ignored", "https://pcl.local") == "https://pcl.local/"


def test_list_devices_walks_every_page_and_sends_bearer_token():
    devices = [_device(f"id-{i}") for i in range(3)] + [_device("old", retired={"reason": "re-registered"})]
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization"))
        offset = int(request.url.params.get("offset", 0))
        return httpx.Response(200, json={"items": devices[offset : offset + 2], "total": len(devices)})

    result = list_prusa_connect_local_devices("http://pcl:8080/", "secret", transport=httpx.MockTransport(handler))

    assert [device["id"] for device in result] == ["id-0", "id-1", "id-2"]
    assert seen_auth == ["Bearer secret", "Bearer secret"]


def test_list_devices_raises_problem_code_on_auth_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"code": "core.auth/UNAUTHENTICATED", "detail": "no credential"})

    with pytest.raises(PrusaConnectLocalError) as exc:
        list_prusa_connect_local_devices("http://pcl:8080/", "bad", transport=httpx.MockTransport(handler))
    assert exc.value.status_code == 401
    assert exc.value.code == "core.auth/UNAUTHENTICATED"


def test_summary_and_serial():
    summary = summarize_prusa_connect_local_device(_device())
    assert summary["vendor"] == "Prusa"
    assert summary["model"] == "CoreOne"
    assert summary["state"] == "PRINTING"
    assert summary["can_operate"] is True
    assert prusa_connect_local_serial(summary["id"], summary["serial"]) == "PCL-29876543"


def test_status_update_maps_state_temperatures_and_job(monkeypatch):
    started = []
    client = PrusaConnectLocalPrinterClient(
        "http://pcl:8080/", device_id=DEVICE_ID, api_key="secret", on_print_start=started.append
    )
    devices = iter([_device(state="IDLE"), _device(state="PRINTING")])
    monkeypatch.setattr(client, "_json", lambda method, path, **kwargs: next(devices))

    client.request_status_update()
    client.request_status_update()

    assert client.state.state == "RUNNING"
    assert client.state.connected is True
    assert client.state.progress == 37.0
    assert client.state.remaining_time == 36
    assert client.state.subtask_name == "Benchy"
    assert client.state.temperatures["nozzle"] == 214.8
    assert client.state.temperatures["bed_target"] == 60.0
    assert started and started[0]["filename"] == "Benchy"


def test_disconnected_device_reads_offline(monkeypatch):
    client = PrusaConnectLocalPrinterClient("http://pcl:8080/", device_id=DEVICE_ID, api_key="secret")
    monkeypatch.setattr(client, "_json", lambda method, path, **kwargs: _device(connected=False))
    client.request_status_update()
    assert client.state.state == "OFFLINE"
    assert client.state.connected is False


def test_commands_use_core_verbs(monkeypatch):
    calls = []
    client = PrusaConnectLocalPrinterClient("http://pcl:8080/", device_id=DEVICE_ID, api_key="secret")

    def fake_json(method, path, **kwargs):
        calls.append((method, path, kwargs.get("json")))
        return {"ok": True, "command_id": "c1"}

    monkeypatch.setattr(client, "_json", fake_json)

    assert client.pause_print()
    assert client.set_nozzle_temperature(215)
    method, path, payload = calls[1]
    assert method == "post"
    assert path == f"api/v1/devices/{DEVICE_ID}/commands"
    assert calls[0][2]["verb"] == "core.command.pause_print"
    assert payload["verb"] == "core.command.set_nozzle_temperature"
    assert payload["args"] == {"nozzle_temperature": "215"}


def test_command_args_render_booleans_lowercase(monkeypatch):
    calls = []
    client = PrusaConnectLocalPrinterClient("http://pcl:8080/", device_id=DEVICE_ID, api_key="secret")
    monkeypatch.setattr(client, "_json", lambda method, path, **kwargs: calls.append(kwargs["json"]) or {"ok": True})

    assert client.send_command("set_tool_high_flow", {"high_flow": True, "tool": 0})
    assert client.send_command("move", {"x": 2.5, "feedrate": 3000})

    assert calls[0]["args"] == {"high_flow": "true", "tool": "0"}
    assert calls[1]["args"] == {"x": "2.5", "feedrate": "3000"}


def test_control_snapshot_keeps_only_panel_verbs():
    device = _device(state="IDLE")
    device["state"].update({"/axis/x": 25.0, "/speed": 110, "/flow": 95, "/network/hostname": "core"})
    device["tools"] = {
        "tool_count": 1,
        "tools": {
            "0": {
                "active": True,
                "features": {"nozzle_diameter": 0.6, "nozzle_high_flow": True, "nozzle_hardened": False},
                "material_package_instance": {"package": {"material": {"abbreviation": "PETG"}}},
            }
        },
    }
    capabilities = {
        "capabilities": [
            {"key": "core.command.set_speed", "arguments": [{"name": "speed", "type": "integer", "minimum": 20}]},
            {"key": "core.command.send_gcode", "arguments": [{"name": "gcode", "type": "string"}]},
            {"key": "core.command.home", "arguments": [{"name": "axis", "enum": ["X", "XY"], "key": "ignored"}]},
            {"key": "core.feature.file_upload", "arguments": []},
        ]
    }

    snapshot = prusaconnectlocal.summarize_prusa_connect_local_controls(device, capabilities)

    assert set(snapshot["verbs"]) == {"set_speed", "home"}
    assert snapshot["verbs"]["home"] == [{"name": "axis", "enum": ["X", "XY"]}]
    assert snapshot["position"] == {"x": 25.0, "y": None, "z": None}
    assert snapshot["speed"] == 110.0
    assert snapshot["flow"] == 95.0
    assert snapshot["hostname"] == "core"
    assert snapshot["can_operate"] is True
    assert snapshot["temperatures"]["nozzle"] == 214.8
    assert snapshot["tools"] == [
        {
            "index": 0,
            "active": True,
            "nozzle_diameter": 0.6,
            "high_flow": True,
            "hardened": False,
            "material": "PETG",
            "nozzle_temp": 214.8,
            "nozzle_target_temp": 215.0,
        }
    ]


def test_list_cameras_filters_by_device_and_sends_token():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.headers.get("authorization"), request.url.params.get("device")))
        return httpx.Response(
            200,
            json={
                "items": [
                    {"name": "cam", "device_id": DEVICE_ID, "serving": True, "stream": True, "snapshot": True},
                    {"name": "", "device_id": DEVICE_ID},
                ]
            },
        )

    cameras = prusaconnectlocal.list_prusa_connect_local_cameras(
        "http://pcl:8080/", "secret", device_id=DEVICE_ID, transport=httpx.MockTransport(handler)
    )

    assert seen == [("Bearer secret", DEVICE_ID)]
    assert cameras == [
        {"name": "cam", "device_id": DEVICE_ID, "serving": True, "stream": True, "snapshot": True, "watch": False}
    ]


def test_pick_camera_prefers_serving_stream_and_skips_webrtc_only():
    cameras = [
        {"name": "h264", "serving": True, "stream": False, "snapshot": False, "watch": True},
        {"name": "stills", "serving": True, "stream": False, "snapshot": True, "watch": False},
        {"name": "offline", "serving": False, "stream": True, "snapshot": True, "watch": False},
        {"name": "live", "serving": True, "stream": True, "snapshot": True, "watch": False},
    ]
    assert prusaconnectlocal.pick_prusa_connect_local_camera(cameras)["name"] == "live"
    assert prusaconnectlocal.pick_prusa_connect_local_camera(cameras[:1]) is None
    assert prusaconnectlocal.prusa_connect_local_camera_options(None) == {
        "pcl_camera": None,
        "pcl_camera_stream": None,
        "pcl_camera_snapshot": None,
    }


def test_refused_command_returns_false(monkeypatch):
    client = PrusaConnectLocalPrinterClient("http://pcl:8080/", device_id=DEVICE_ID, api_key="secret")
    monkeypatch.setattr(client, "_json", lambda *args, **kwargs: {"ok": False})
    assert client.stop_print() is False


def test_factory_and_schema_defaults():
    printer = PrinterCreate(
        name="CoreOne",
        provider="prusaconnectlocal",
        ip_address="192.168.1.5",
        auth_token="secret",
        provider_options=json.dumps({"pcl_device_id": DEVICE_ID}),
    )
    assert printer.serial_number.startswith("PCL-")
    assert printer.api_url == "http://192.168.1.5:8080"

    client = create_printer_client(printer)
    assert isinstance(client, prusaconnectlocal.PrusaConnectLocalPrinterClient)
    assert client.device_id == DEVICE_ID
    assert client.base_url == "http://192.168.1.5:8080/"
    assert client._headers["Authorization"] == "Bearer secret"
