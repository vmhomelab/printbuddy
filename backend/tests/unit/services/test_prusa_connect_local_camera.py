import json
from types import SimpleNamespace

from backend.app.services.elegoo_camera import get_effective_camera_source, prusa_connect_local_camera_headers


def _printer(**overrides):
    values = {
        "provider": "prusaconnectlocal",
        "ip_address": "192.168.1.5",
        "api_url": "http://192.168.1.5:8080",
        "auth_token": "secret",
        "provider_options": json.dumps(
            {
                "pcl_device_id": "dev-1",
                "pcl_camera": "core one cam",
                "pcl_camera_stream": True,
                "pcl_camera_snapshot": True,
            }
        ),
        "external_camera_enabled": False,
        "external_camera_url": None,
        "external_camera_type": None,
        "external_camera_snapshot_url": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_declared_camera_becomes_derived_stream_with_bearer_header():
    source = get_effective_camera_source(_printer())

    assert source.enabled is True
    assert source.derived is True
    assert source.camera_type == "mjpeg"
    assert source.url == "http://192.168.1.5:8080/api/v1/cameras/core%20one%20cam/stream"
    assert source.snapshot_url == "http://192.168.1.5:8080/api/v1/cameras/core%20one%20cam/snapshot"
    assert source.headers == {"Authorization": "Bearer secret"}


def test_snapshot_only_camera_is_polled():
    printer = _printer(provider_options=json.dumps({"pcl_camera": "cam", "pcl_camera_stream": False}))
    source = get_effective_camera_source(printer)

    assert source.camera_type == "snapshot"
    assert source.url.endswith("/api/v1/cameras/cam/snapshot")


def test_no_declared_camera_means_no_camera():
    source = get_effective_camera_source(_printer(provider_options=json.dumps({"pcl_device_id": "dev-1"})))
    assert source.enabled is False
    assert source.headers is None


def test_manual_camera_keeps_priority_and_only_pcl_urls_get_the_token():
    pcl_url = "http://192.168.1.5:8080/api/v1/cameras/cam/stream"
    manual_pcl = get_effective_camera_source(
        _printer(external_camera_enabled=True, external_camera_url=pcl_url, external_camera_type="mjpeg")
    )
    assert manual_pcl.derived is False
    assert manual_pcl.headers == {"Authorization": "Bearer secret"}

    third_party = get_effective_camera_source(
        _printer(
            external_camera_enabled=True, external_camera_url="http://192.168.1.9/stream", external_camera_type="mjpeg"
        )
    )
    assert third_party.url == "http://192.168.1.9/stream"
    assert third_party.headers is None


def test_token_is_never_attached_for_other_providers():
    printer = _printer(provider="prusalink")
    assert prusa_connect_local_camera_headers(printer, "http://192.168.1.5:8080/api/v1/cameras/cam/stream") is None
