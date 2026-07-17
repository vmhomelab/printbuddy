"""MQTT bridge for BIQU Panda Breath.

Panda Breath can expose Home Assistant MQTT entities directly from the device.
The native topic shape observed from the device is::

    panda_breath/<device_id>/state         # JSON state document
    panda_breath/<device_id>/availability  # online/offline
    panda_breath/<device_id>/command       # JSON command document

Older community bridge scripts used one topic per value under a prefix such as
``panda_breath_mod/ist`` and ``panda_breath_mod/soll``. Printbuddy supports both
contracts so existing setups keep working while native Panda Breath MQTT can be
used directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


@dataclass
class PandaBreathState:
    """Latest MQTT state observed from Panda Breath."""

    chamber_target: float | None = None
    chamber_actual: float | None = None
    bed_temperature: float | None = None
    bed_limit: float | None = None
    filter_activation_temp: float | None = None
    heater_trigger_temp: float | None = None
    custom_temp: float | None = None
    custom_timer_hours: float | None = None
    drying_temperature: float | None = None
    drying_time_hours: float | None = None
    drying_remaining_min: float | None = None
    slicer_target: float | None = None
    mode: str | None = None
    filament_drying_mode: str | None = None
    status: str | None = None
    lock_status: str | None = None
    fan_on: bool | None = None
    power_on: bool | None = None
    work_on: bool | None = None
    drying_running: bool | None = None
    slicer_priority_mode: bool | None = None
    printer_sn: str | None = None
    printer_bind: str | None = None
    printer_ip: str | None = None
    printer_name: str | None = None
    version: str | None = None
    availability: str | None = None
    device_id: str | None = None
    last_seen: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.last_seen:
            data["last_seen"] = self.last_seen.isoformat()
        return data


class PandaBreathMQTTService:
    """Subscribe/publish client for Panda Breath MQTT topic contracts."""

    # Native device payload keys from the Home Assistant MQTT config.
    JSON_NUMERIC_FIELDS = {
        "chamber_temp": "chamber_actual",
        "target_temp": "chamber_target",
        "filter_temp": "filter_activation_temp",
        "heater_temp": "heater_trigger_temp",
        "custom_temp": "custom_temp",
        "custom_timer": "custom_timer_hours",
        "drying_remaining_min": "drying_remaining_min",
    }
    JSON_TEXT_FIELDS = {
        "mode": "mode",
        "filament_drying_mode": "filament_drying_mode",
        "printer_sn": "printer_sn",
        "printer_bind": "printer_bind",
        "printer_ip": "printer_ip",
        "printer_name": "printer_name",
    }
    JSON_BOOL_FIELDS = {
        "work_on": "work_on",
        "drying_running": "drying_running",
    }
    JSON_COMMAND_KEYS = {
        "work_on": "work_on",
        "mode": "mode",
        "filament_drying_mode": "filament_drying_mode",
        "chamber_target": "target_temp",
        "target_temp": "target_temp",
        "filter_activation_temp": "filter_temp",
        "filter_temp": "filter_temp",
        "heater_trigger_temp": "heater_temp",
        "heater_temp": "heater_temp",
        "custom_temp": "custom_temp",
        "custom_timer": "custom_timer",
        "drying_running": "drying_running",
    }

    # Older community bridge topic suffixes.
    NUMERIC_TOPICS = {
        "soll": "chamber_target",
        "ist": "chamber_actual",
        "bed": "bed_temperature",
        "bett": "bed_temperature",
        "limit": "bed_limit",
        "bett_limit": "bed_limit",
        "filtertemp": "filter_activation_temp",
        "filter_temp": "filter_activation_temp",
        "heater_temp": "heater_trigger_temp",
        "custom_temp": "custom_temp",
        "custom_timer": "custom_timer_hours",
        "dry_temp": "drying_temperature",
        "drying_temperature": "drying_temperature",
        "dry_time": "drying_time_hours",
        "drying_time": "drying_time_hours",
        "drying_remaining_min": "drying_remaining_min",
        "slicer_soll": "slicer_target",
        "slicer_target": "slicer_target",
        "slicer_target_temp": "slicer_target",
    }
    TEXT_TOPICS = {
        "panda_modus": "mode",
        "mode": "mode",
        "filament_drying_mode": "filament_drying_mode",
        "status": "status",
        "lock_status": "lock_status",
        "printer_sn": "printer_sn",
        "printer_bind": "printer_bind",
        "printer_ip": "printer_ip",
        "printer_name": "printer_name",
        "version": "version",
        "fw_version": "version",
    }
    BOOL_TOPICS = {
        "fan": "fan_on",
        "panda_power": "power_on",
        "work": "work_on",
        "work_on": "work_on",
        "drying_running": "drying_running",
        "slicer_priority_mode": "slicer_priority_mode",
    }
    LEGACY_COMMAND_TOPICS = {
        "manual": "manual/set",
        "auto": "auto/set",
        "drying": "drying/set",
        "stop": "heizung_stop/set",
        "unlock": "unlock/set",
        "power": "panda_power/set",
        "work_on": "work_on/set",
        "slicer_priority_mode": "slicer_priority_mode/set",
        "chamber_target": "soll/set",
        "bed_limit": "limit/set",
        "filter_activation_temp": "filtertemp/set",
        "drying_temperature": "dry_temp/set",
        "drying_time_hours": "dry_time/set",
    }
    # Backwards-compatible public alias used by existing tests/callers.
    COMMAND_TOPICS = LEGACY_COMMAND_TOPICS

    def __init__(self) -> None:
        self.client: mqtt.Client | None = None
        self.enabled = False
        self.connected = False
        self.topic_prefix = "panda_breath"
        self._broker = ""
        self._port = 1883
        self._username = ""
        self._password = ""
        self._use_tls = False
        self._lock = threading.Lock()
        self._disconnection_event: threading.Event | None = None
        self.state = PandaBreathState()
        self.device_states: dict[str, PandaBreathState] = {}

    async def configure(self, settings: dict[str, Any]) -> bool:
        """Configure the Panda Breath MQTT client from app settings."""

        enabled = bool(settings.get("panda_breath_enabled", False))
        broker = str(settings.get("mqtt_broker") or "")
        port = int(settings.get("mqtt_port") or 1883)
        username = str(settings.get("mqtt_username") or "")
        password = str(settings.get("mqtt_password") or "")
        use_tls = bool(settings.get("mqtt_use_tls", False))
        topic_prefix = str(settings.get("panda_breath_topic_prefix") or "panda_breath").strip().strip("/")

        if not enabled:
            self.enabled = False
            await self.disconnect()
            return True

        if not broker:
            logger.warning("Panda Breath MQTT enabled but no broker configured")
            self.enabled = True
            self._broker = ""
            self.connected = False
            return False

        changed = (
            self._broker != broker
            or self._port != port
            or self._username != username
            or self._password != password
            or self._use_tls != use_tls
            or self.topic_prefix != topic_prefix
        )

        self.enabled = True
        self._broker = broker
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self.topic_prefix = topic_prefix or "panda_breath"

        if changed and self.client:
            await self.disconnect()

        if not self.client or not self.connected:
            return await self._connect()
        self._subscribe()
        return True

    async def _connect(self) -> bool:
        try:
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"printbuddy-panda-breath-{id(self)}",
                protocol=mqtt.MQTTv311,
            )
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            if self._username:
                self.client.username_pw_set(self._username, self._password)
            if self._use_tls:
                self.client.tls_set(cert_reqs=ssl.CERT_NONE)
                self.client.tls_insecure_set(True)

            await asyncio.wait_for(
                asyncio.to_thread(self.client.connect_async, self._broker, self._port, 60),
                timeout=3.0,
            )
            self.client.loop_start()
            await asyncio.sleep(1.0)
            if self.connected:
                self._subscribe()
            return True
        except Exception as exc:
            logger.warning("Panda Breath MQTT connection failed: %s", exc)
            self.connected = False
            return False

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: dict,
        reason_code: int | mqtt.ReasonCode,
        properties: mqtt.Properties | None = None,
    ) -> None:
        rc = reason_code if isinstance(reason_code, int) else reason_code.value
        self.connected = rc == 0
        if self.connected:
            logger.info("Panda Breath MQTT connected to %s:%s", self._broker, self._port)
            self._subscribe()
        else:
            logger.warning("Panda Breath MQTT connect failed: %s", reason_code)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags_or_rc: dict | int | mqtt.ReasonCode,
        reason_code: int | mqtt.ReasonCode | None = None,
        properties: mqtt.Properties | None = None,
    ) -> None:
        self.connected = False
        if self._disconnection_event:
            self._disconnection_event.set()

    def _subscribe(self) -> None:
        if not self.client:
            return
        self.client.subscribe(f"{self.topic_prefix}/#", qos=1)

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        topic = msg.topic or ""
        prefix = f"{self.topic_prefix}/"
        if not topic.startswith(prefix):
            return
        suffix = topic[len(prefix) :]
        payload = msg.payload.decode("utf-8", errors="replace").strip()
        self.apply_message(suffix, payload)

    def apply_message(self, suffix: str, payload: str) -> None:
        """Apply one raw topic suffix/payload pair to the in-memory state."""
        suffix = suffix.strip("/")
        now = datetime.now(timezone.utc)
        with self._lock:
            # Native Panda Breath shape: <device_id>/state with one JSON document.
            if suffix.endswith("/state"):
                device_id = suffix.rsplit("/", 1)[0]
                if device_id:
                    state = self._state_for_device(device_id)
                    state.raw[suffix] = self._raw_payload(payload)
                    state.last_seen = now
                    state.device_id = device_id
                    self.state = state
                else:
                    self.state.raw[suffix] = self._raw_payload(payload)
                    self.state.last_seen = now
                    state = self.state
                self._apply_json_state(payload, state)
                return

            # Native availability topic: <device_id>/availability.
            if suffix.endswith("/availability"):
                device_id = suffix.rsplit("/", 1)[0]
                if device_id:
                    state = self._state_for_device(device_id)
                    state.raw[suffix] = self._raw_payload(payload)
                    state.last_seen = now
                    state.device_id = device_id
                    state.availability = payload
                    self.state = state
                else:
                    self.state.raw[suffix] = self._raw_payload(payload)
                    self.state.last_seen = now
                    self.state.availability = payload
                self.connected = (
                    any(
                        device.availability and device.availability.strip().lower() == "online"
                        for device in self.device_states.values()
                    )
                    or payload.strip().lower() == "online"
                )
                return

            self.state.raw[suffix] = self._raw_payload(payload)
            self.state.last_seen = now

            # Also accept a bare "state" suffix if the configured prefix already
            # includes the device id, e.g. panda_breath/9C139E456884.
            if suffix == "state":
                self._apply_json_state(payload, self.state)
                return
            if suffix == "availability":
                self.state.availability = payload
                self.connected = payload.strip().lower() == "online"
                return

            if suffix in self.NUMERIC_TOPICS:
                self._set_numeric(self.NUMERIC_TOPICS[suffix], payload, self.state)
            elif suffix in self.TEXT_TOPICS:
                setattr(self.state, self.TEXT_TOPICS[suffix], payload)
            elif suffix in self.BOOL_TOPICS:
                setattr(self.state, self.BOOL_TOPICS[suffix], self._to_bool(payload))

    def _state_for_device(self, device_id: str) -> PandaBreathState:
        if device_id not in self.device_states:
            self.device_states[device_id] = PandaBreathState(device_id=device_id)
        return self.device_states[device_id]

    def _apply_json_state(self, payload: str, state: PandaBreathState | None = None) -> None:
        target = state or self.state
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.debug("Ignoring non-JSON Panda Breath state payload: %r", payload)
            return
        if not isinstance(data, dict):
            return
        target.raw["state_json"] = data

        for key, attr in self.JSON_NUMERIC_FIELDS.items():
            if key in data:
                self._set_numeric(attr, data[key], target)
        for key, attr in self.JSON_TEXT_FIELDS.items():
            if key in data:
                value = data[key]
                setattr(target, attr, None if value is None else str(value))
        for key, attr in self.JSON_BOOL_FIELDS.items():
            if key in data:
                setattr(target, attr, self._to_bool(data[key]))

    def _set_numeric(self, attr: str, value: Any, state: PandaBreathState | None = None) -> None:
        try:
            setattr(state or self.state, attr, float(value))
        except (TypeError, ValueError):
            logger.debug("Ignoring non-numeric Panda Breath payload %s=%r", attr, value)

    @staticmethod
    def _to_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized in {"on", "1", "true", "yes", "ja", "online"}:
            return True
        if normalized in {"off", "0", "false", "no", "nein", "offline"}:
            return False
        return bool(normalized)

    @staticmethod
    def _raw_payload(payload: str) -> Any:
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload

    async def disconnect(self, timeout: float = 0) -> None:
        if self.client:
            try:
                self._disconnection_event = threading.Event()
                self.client.disconnect()
                await asyncio.to_thread(self._disconnection_event.wait, timeout=timeout)
                self.client.loop_stop()
            except Exception as exc:
                logger.debug("Panda Breath MQTT disconnect ignored: %s", exc)
            finally:
                self.client = None
                self.connected = False

    def publish_command(self, command: str, value: Any = None, device_id: str | None = None) -> bool:
        """Publish a Panda Breath command.

        When using native BIQU topics and multiple Panda Breath devices are known,
        ``device_id`` targets the command at the assigned device instead of the
        most recently observed state device.
        """
        if command not in self.LEGACY_COMMAND_TOPICS and command not in self.JSON_COMMAND_KEYS:
            raise ValueError(f"Unsupported Panda Breath command: {command}")
        if not self.enabled or not self.connected or not self.client:
            return False

        topic, payload = self._command_topic_payload(command, value, device_id=device_id)
        with self._lock:
            self.client.publish(topic, payload, qos=1, retain=False)
        return True

    def _command_topic_payload(self, command: str, value: Any, device_id: str | None = None) -> tuple[str, str]:
        if self._uses_native_device_topics():
            command_key = self.JSON_COMMAND_KEYS.get(command)
            if not command_key:
                # Map button-style aliases onto the native mode selector.
                if command == "auto":
                    command_key, value = "mode", "auto mode"
                elif command in {"power", "manual"}:
                    command_key, value = "mode", "power on"
                elif command == "drying":
                    command_key, value = "mode", "filament drying"
                elif command == "stop":
                    command_key, value = "work_on", "OFF"
                else:
                    raise ValueError(f"Unsupported Panda Breath native command: {command}")
            if value is None:
                raise ValueError(f"Command {command} requires a value")
            return f"{self._native_device_prefix(device_id=device_id)}/command", json.dumps({command_key: value})

        return f"{self.topic_prefix}/{self.LEGACY_COMMAND_TOPICS[command]}", self._payload_for_command(command, value)

    def _uses_native_device_topics(self) -> bool:
        return self.topic_prefix.startswith("panda_breath") and self.topic_prefix != "panda_breath_mod"

    def _native_device_prefix(self, device_id: str | None = None) -> str:
        if self.topic_prefix.count("/") >= 1:
            return self.topic_prefix
        if device_id:
            return f"{self.topic_prefix}/{device_id}"
        if self.state.device_id:
            return f"{self.topic_prefix}/{self.state.device_id}"
        raise ValueError(
            "Panda Breath device id is unknown; wait for a state/availability message or set the prefix to panda_breath/<device_id>"
        )

    @staticmethod
    def _payload_for_command(command: str, value: Any) -> str:
        if command in {"manual", "auto", "drying", "stop", "unlock"}:
            return "PRESS"
        if command in {"power", "work_on", "slicer_priority_mode"}:
            if isinstance(value, str):
                is_on = value.strip().lower() in {"on", "1", "true", "yes"}
            else:
                is_on = bool(value)
            return "ON" if is_on else "OFF"
        if value is None:
            raise ValueError(f"Command {command} requires a value")
        return str(value)

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "connected": self.connected,
            "broker": self._broker if self.enabled else "",
            "port": self._port if self.enabled else 0,
            "topic_prefix": self.topic_prefix,
            "device_id": self.state.device_id,
            "availability": self.state.availability,
            "state": self.state.to_dict(),
            "devices": {device_id: state.to_dict() for device_id, state in self.device_states.items()},
        }


panda_breath_mqtt = PandaBreathMQTTService()
