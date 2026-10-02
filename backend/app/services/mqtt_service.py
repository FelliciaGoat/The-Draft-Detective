"""MQTT subscriber for ESP32 sensor messages.

Topic format:   building/{building_id}/room/{room_id}/sensors
Example:        building/main/room/1/sensors
Payload (JSON): {"device_id": "ESP32-A101", "acoustic_level": 0.72,
                 "room_temperature": 24.8, "edge_temperature": 29.6}

* `{room_id}` is the numeric database id of the room.
* `{building_id}` is informational (logged); routing uses the room id.
* The payload has the same fields as POST /readings, except `room_id` (it comes from the topic).

Does not block FastAPI: paho-mqtt runs its own network thread (`loop_start`). Each message is
validated, stored and analysed in that thread with its own database session, then pushed to
WebSocket clients through the thread-safe manager.

Authentication: MQTT messages are protected by the broker (username/password / TLS), not by
the HTTP `X-API-Key`. Configure your broker accordingly for anything beyond a prototype.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Literal

import paho.mqtt.client as mqtt
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import ReadingSource
from app.schemas.reading import ReadingCreate
from app.services.ingestion import IngestionService, RoomNotFoundError

logger = logging.getLogger(__name__)

TOPIC_PATTERN = re.compile(r"^building/(?P<building>[^/]+)/room/(?P<room>\d+)/sensors$")

MqttStatus = Literal["connected", "disconnected", "disabled"]


def parse_topic(topic: str) -> tuple[str, int] | None:
    """Return (building_id, room_id) for a valid sensor topic, else None."""
    match = TOPIC_PATTERN.match(topic)
    if match is None:
        return None
    return match.group("building"), int(match.group("room"))


class MqttService:
    """Owns the MQTT client and turns messages into pipeline calls."""

    def __init__(
        self,
        settings: Settings,
        ingestion: IngestionService,
        session_factory: Callable[[], Session],
    ) -> None:
        self.settings = settings
        self.ingestion = ingestion
        self.session_factory = session_factory
        self._client: mqtt.Client | None = None
        self._connected = False

    # ----------------------------------------------------------- status
    @property
    def enabled(self) -> bool:
        """MQTT is used only when explicitly enabled and a broker is configured."""
        return self.settings.mqtt_enabled and bool(self.settings.mqtt_broker)

    @property
    def status(self) -> MqttStatus:
        """'disabled', 'connected' or 'disconnected' (for the health check)."""
        if self._client is None:
            return "disabled" if not self.enabled else "disconnected"
        return "connected" if self._connected else "disconnected"

    # --------------------------------------------------------- lifecycle
    def start(self) -> None:
        """Connect in the background. Never raises if the broker is down; paho keeps retrying."""
        if not self.enabled:
            logger.info("MQTT is disabled (set MQTT_ENABLED=true to enable it)")
            return
        s = self.settings
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=s.mqtt_client_id)
        if s.mqtt_username:
            client.username_pw_set(s.mqtt_username, s.mqtt_password or None)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.connect_async(s.mqtt_broker, s.mqtt_port, keepalive=60)
        client.loop_start()  # network loop runs in its own thread
        self._client = client
        logger.info("MQTT client started, connecting to %s:%s", s.mqtt_broker, s.mqtt_port)

    def stop(self) -> None:
        """Disconnect and stop the network thread."""
        if self._client is None:
            return
        self._client.loop_stop()
        self._client.disconnect()
        self._client = None
        self._connected = False
        logger.info("MQTT client stopped")

    # --------------------------------------------------------- callbacks
    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:  # noqa: ANN001
        """Subscribe (again) every time we (re)connect."""
        if reason_code.is_failure:
            logger.error("MQTT connection refused: %s", reason_code)
            return
        self._connected = True
        client.subscribe(self.settings.mqtt_topic, qos=1)
        logger.info("MQTT connected; subscribed to '%s'", self.settings.mqtt_topic)

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties=None) -> None:  # noqa: ANN001
        """Track connection state; paho reconnects automatically."""
        self._connected = False
        logger.warning("MQTT disconnected (%s); will retry", reason_code)

    def _on_message(self, _client, _userdata, msg) -> None:  # noqa: ANN001
        """Called from paho's thread for every message."""
        self.handle_message(msg.topic, msg.payload)

    # ---------------------------------------------------- message handling
    def handle_message(self, topic: str, payload: bytes) -> bool:
        """Validate, store and analyse one MQTT message. Returns True on success; never raises."""
        parsed = parse_topic(topic)
        if parsed is None:
            logger.warning("Ignoring message on unexpected topic '%s'", topic)
            return False
        building_id, room_id = parsed

        try:
            body = json.loads(payload)
            if not isinstance(body, dict):
                raise ValueError("payload must be a JSON object")
            if "room_id" in body and body["room_id"] != room_id:
                raise ValueError("room_id in payload does not match the topic")
            body["room_id"] = room_id  # the topic is the source of truth
            reading = ReadingCreate.model_validate(body)
        except (ValueError, ValidationError) as exc:  # JSONDecodeError is a ValueError
            logger.warning("Rejected MQTT message on '%s': %s", topic, exc)
            return False

        try:
            with self.session_factory() as db:
                self.ingestion.ingest(db, reading, source=ReadingSource.MQTT)
        except RoomNotFoundError:
            logger.warning("MQTT message for unknown room %s (building '%s') dropped", room_id, building_id)
            return False
        except Exception:
            logger.exception("Failed to process MQTT message on '%s'", topic)
            return False
        return True
