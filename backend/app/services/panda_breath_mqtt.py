"""MQTT bridge for BIQU Panda Breath Mod.

The community Panda Breath bridge exposes its Home Assistant-style control
surface over MQTT under a configurable topic prefix (default
``panda_breath_mod``). Printbuddy talks to that same topic contract directly so
users can monitor and control Panda Breath from Settings without running Home
Assistant.
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
    drying_temperature: float | None = None
    drying_time_hours: float | None = None
    slicer_target: float | None = None
    mode: str | None = None
    status: str | None = None
    lock_status: str | None = None
    fan_on: bool | None = None
    power_on: bool | None = None
    work_on: bool | None = None
    slicer_priority_mode: bool | None = None
    version: str | None = None
    last_seen: datetime | None = None
    raw: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.last_seen:
            data["last_seen"] = self.last_seen.isoformat()
        return data


class PandaBreathMQTTService:
    """Subscribe/publish client for the Panda Breath MQTT topic contract."""

    NUMERIC_TOPICS = {
        "soll": "chamber_target",
        "ist": "chamber_actual",
        "bed": "bed_temperature",
        "limit": "bed_limit",
        "filtertemp": "filter_activation_temp",
        "dry_temp": "drying_temperature",
        "dry_time": "drying_time_hours",
        "slicer_soll": "slicer_target",
        "slicer_target_temp": "slicer_target",
    }
    TEXT_TOPICS = {
        "panda_modus": "mode",
        "status": "status",
        "lock_status": "lock_status",
        "version": "version",
        "fw_version": "version",
    }
    BOOL_TOPICS = {
        "fan": "fan_on",
        "panda_power": "power_on",
        "work_on": "work_on",
        "slicer_priority_mode": "slicer_priority_mode",
    }
    COMMAND_TOPICS = {
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

    def __init__(self) -> None:
        self.client: mqtt.Client | None = None
        self.enabled = False
        self.connected = False
        self.topic_prefix = "panda_breath_mod"
        self._broker = ""
        self._port = 1883
        self._username = ""
        self._password = ""
        self._use_tls = False
        self._lock = threading.Lock()
        self._disconnection_event: threading.Event | None = None
        self.state = PandaBreathState()

    async def configure(self, settings: dict[str, Any]) -> bool:
        """Configure the Panda Breath MQTT client from app settings."""

        enabled = bool(settings.get("panda_breath_enabled", False))
        broker = str(settings.get("mqtt_broker") or "")
        port = int(settings.get("mqtt_port") or 1883)
        username = str(settings.get("mqtt_username") or "")
        password = str(settings.get("mqtt_password") or "")
        use_tls = bool(settings.get("mqtt_use_tls", False))
        topic_prefix = str(settings.get("panda_breath_topic_prefix") or "panda_breath_mod").strip().strip("/")

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
        self.topic_prefix = topic_prefix or "panda_breath_mod"

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
        now = datetime.now(timezone.utc)
        with self._lock:
            self.state.raw[suffix] = payload
            self.state.last_seen = now
            if suffix in self.NUMERIC_TOPICS:
                try:
                    setattr(self.state, self.NUMERIC_TOPICS[suffix], float(payload))
                except ValueError:
                    logger.debug("Ignoring non-numeric Panda Breath payload %s=%r", suffix, payload)
            elif suffix in self.TEXT_TOPICS:
                setattr(self.state, self.TEXT_TOPICS[suffix], payload)
            elif suffix in self.BOOL_TOPICS:
                setattr(self.state, self.BOOL_TOPICS[suffix], payload.upper() in {"ON", "1", "TRUE"})

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

    def publish_command(self, command: str, value: Any = None) -> bool:
        """Publish a Panda Breath command using the community bridge topics."""
        if command not in self.COMMAND_TOPICS:
            raise ValueError(f"Unsupported Panda Breath command: {command}")
        if not self.enabled or not self.connected or not self.client:
            return False

        topic = f"{self.topic_prefix}/{self.COMMAND_TOPICS[command]}"
        payload = self._payload_for_command(command, value)
        with self._lock:
            self.client.publish(topic, payload, qos=1, retain=False)
        return True

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
            "state": self.state.to_dict(),
        }


panda_breath_mqtt = PandaBreathMQTTService()
