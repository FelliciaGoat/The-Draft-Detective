"""MQTT tests. The message handler is tested directly, so no broker is needed."""

import json

import pytest

from app.core.config import Settings, get_settings
from app.database.database import SessionLocal
from app.services.mqtt_service import MqttService, parse_topic

API = "/api/v1"
TOPIC = "building/main/room/1/sensors"
PAYLOAD = {
    "device_id": "ESP32-A101",
    "acoustic_level": 0.72,
    "room_temperature": 24.8,
    "edge_temperature": 29.6,
}


@pytest.fixture()
def mqtt(client, room) -> MqttService:
    """An MqttService wired to the app's real pipeline (client is not started)."""
    return MqttService(get_settings(), client.app.state.ingestion, SessionLocal)


def send(service: MqttService, payload, topic: str = TOPIC) -> bool:
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return service.handle_message(topic, raw)


def test_topic_parsing():
    assert parse_topic("building/main/room/101/sensors") == ("main", 101)
    assert parse_topic("building/north-wing/room/7/sensors") == ("north-wing", 7)
    for bad in ("building/main/room/abc/sensors", "building/main/room/1", "other/main/room/1/sensors", ""):
        assert parse_topic(bad) is None


def test_valid_message_is_stored_analysed_and_visible_through_the_api(client, mqtt):
    assert send(mqtt, PAYLOAD) is True
    readings = client.get(f"{API}/readings").json()
    assert len(readings) == 1
    assert readings[0]["source"] == "mqtt" and readings[0]["room_id"] == 1
    analytics = client.get(f"{API}/rooms/1/analytics").json()
    assert analytics["has_data"] is True
    assert analytics["temperature"]["delta"] == pytest.approx(4.8)


def test_message_is_pushed_to_websocket_clients(client, mqtt):
    with client.websocket_connect("/ws/rooms/1") as ws:
        assert send(mqtt, PAYLOAD) is True  # processed like the paho thread would
        assert ws.receive_json()["room_id"] == 1


def test_matching_room_id_in_payload_is_accepted(mqtt):
    assert send(mqtt, {**PAYLOAD, "room_id": 1}) is True


@pytest.mark.parametrize(
    "payload",
    [
        b"not json at all",
        b"[1, 2, 3]",
        {"device_id": "ESP32-A101"},  # no measurement
        {**PAYLOAD, "room_temperature": -127},  # sensor error code
        {**PAYLOAD, "acoustic_level": 5},
        {**PAYLOAD, "raw_audio": [0.1]},
        {**PAYLOAD, "room_id": 2},  # contradicts the topic
    ],
)
def test_invalid_messages_are_rejected_and_never_stored(client, mqtt, payload):
    assert send(mqtt, payload) is False
    assert client.get(f"{API}/readings").json() == []


def test_message_for_unknown_room_or_wrong_topic_is_dropped(client, mqtt):
    assert send(mqtt, PAYLOAD, topic="building/main/room/99/sensors") is False
    assert send(mqtt, PAYLOAD, topic="something/else") is False
    assert client.get(f"{API}/readings").json() == []


def test_status_is_disabled_when_mqtt_is_off(client):
    service = MqttService(Settings(mqtt_enabled=False, _env_file=None), client.app.state.ingestion, SessionLocal)
    assert service.status == "disabled"
    service.start()  # must be a harmless no-op
    assert service.status == "disabled"
    service.stop()


def test_status_is_disconnected_before_the_broker_answers(client):
    service = MqttService(Settings(mqtt_enabled=True, mqtt_broker="localhost", _env_file=None), client.app.state.ingestion, SessionLocal)
    assert service.status == "disconnected"
