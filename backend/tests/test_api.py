"""API tests: validation, auth, CRUD, analytics, dashboard, health, CORS and WebSocket."""

from datetime import timedelta

import pytest
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from app.api.deps import get_settings
from app.core.config import Settings
from app.core.enums import RoomState
from app.core.timeutils import utcnow
from app.schemas.reading import ReadingCreate
from app.services.occupancy import OccupancyModel, OccupancyPrediction

API = "/api/v1"
KEY = {"X-API-Key": "test-key"}


def reading(**overrides) -> dict:
    """A valid ESP32 payload; override or remove fields per test."""
    payload = {
        "device_id": "ESP32-A101",
        "room_id": 1,
        "acoustic_level": 0.72,
        "room_temperature": 24.8,
        "edge_temperature": 29.6,
        "humidity": 54.0,
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------- schema level
def test_schema_accepts_the_documented_esp32_payload():
    parsed = ReadingCreate.model_validate(
        {
            "device_id": "ESP32-A101",
            "room_id": 1,
            "timestamp": utcnow().isoformat(),
            "acoustic_level": 0.72,
            "room_temperature": 24.8,
            "edge_temperature": 29.6,
            "humidity": 54.0,
        }
    )
    assert parsed.timestamp.tzinfo is not None


def test_schema_accepts_a_past_timestamp_with_z_suffix_and_normalises_offsets():
    parsed = ReadingCreate.model_validate(
        {"device_id": "x", "room_id": 1, "acoustic_level": 0.1, "timestamp": "2026-09-29T10:30:00+05:30"}
    )
    assert parsed.timestamp.hour == 5 and parsed.timestamp.minute == 0  # converted to UTC


def test_schema_optional_fields_are_truly_optional():
    parsed = ReadingCreate(device_id="ESP32-A101", room_id=1, acoustic_level=0.2)
    assert parsed.room_temperature is None and parsed.humidity is None and parsed.timestamp is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("room_temperature", -127.0),  # DS18B20 "sensor missing"
        ("room_temperature", 85.0),  # DS18B20 power-on default
        ("edge_temperature", 200.0),
        ("edge_temperature", -60.0),
        ("acoustic_level", 1.5),
        ("acoustic_level", -0.1),
        ("humidity", 120.0),
        ("humidity", -5.0),
        ("co2_ppm", 50.0),
        ("room_temperature", float("nan")),
        ("acoustic_level", float("inf")),
    ],
)
def test_schema_rejects_obviously_invalid_values(field, value):
    with pytest.raises(ValidationError):
        ReadingCreate.model_validate({"device_id": "ESP32-A101", "room_id": 1, "acoustic_level": 0.5, field: value})


def test_schema_requires_at_least_one_measurement():
    with pytest.raises(ValidationError):
        ReadingCreate(device_id="ESP32-A101", room_id=1)


def test_schema_rejects_unknown_fields_such_as_raw_audio():
    with pytest.raises(ValidationError):
        ReadingCreate.model_validate({"device_id": "x", "room_id": 1, "acoustic_level": 0.5, "raw_audio": [1, 2, 3]})


# --------------------------------------------------------------------- basics
def test_docs_and_redoc_and_openapi_are_available(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"]


def test_health_reports_database_and_mqtt(client):
    response = client.get(f"{API}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "connected", "mqtt": "disabled"}


def test_cors_allows_the_nextjs_origin_only(client):
    ok = client.options(
        f"{API}/rooms",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    other = client.options(
        f"{API}/rooms",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in other.headers


# ---------------------------------------------------------------------- rooms
def test_room_crud_lifecycle(client):
    created = client.post(f"{API}/rooms", json={"name": "Room B-202", "floor": 2, "zone": "East"})
    assert created.status_code == 201
    room_id = created.json()["id"]

    assert client.get(f"{API}/rooms/{room_id}").json()["name"] == "Room B-202"
    assert [r["id"] for r in client.get(f"{API}/rooms").json()] == [room_id]

    updated = client.put(f"{API}/rooms/{room_id}", json={"zone": "West", "climate_zone": "Composite"})
    assert updated.status_code == 200
    assert updated.json()["zone"] == "West" and updated.json()["name"] == "Room B-202"

    assert client.delete(f"{API}/rooms/{room_id}").status_code == 204
    assert client.get(f"{API}/rooms/{room_id}").status_code == 404


def test_room_errors(client, room):
    assert client.post(f"{API}/rooms", json={"name": room["name"]}).status_code == 409
    assert client.post(f"{API}/rooms", json={"name": ""}).status_code == 422
    assert client.get(f"{API}/rooms/999").status_code == 404
    assert client.put(f"{API}/rooms/999", json={"zone": "x"}).status_code == 404
    assert client.delete(f"{API}/rooms/999").status_code == 404


def test_deleting_a_room_removes_its_readings(client, room):
    client.post(f"{API}/readings", json=reading(), headers=KEY)
    assert len(client.get(f"{API}/readings", params={"room_id": 1}).json()) == 1
    client.delete(f"{API}/rooms/1")
    assert client.get(f"{API}/readings", params={"room_id": 1}).json() == []


# -------------------------------------------------------------------- sensors
def test_sensor_lifecycle_and_errors(client, room):
    body = {"room_id": 1, "sensor_type": "acoustic", "device_id": "ESP32-A101"}
    created = client.post(f"{API}/sensors", json=body)
    assert created.status_code == 201
    sensor_id = created.json()["id"]
    assert created.json()["status"] == "active" and created.json()["last_seen"] is None

    assert client.post(f"{API}/sensors", json=body).status_code == 409  # duplicate device + type
    assert client.post(f"{API}/sensors", json={**body, "room_id": 99}).status_code == 404
    assert client.post(f"{API}/sensors", json={**body, "sensor_type": "lidar"}).status_code == 422

    assert client.get(f"{API}/sensors/{sensor_id}").json()["device_id"] == "ESP32-A101"
    assert client.get(f"{API}/sensors/999").status_code == 404
    assert len(client.get(f"{API}/sensors", params={"room_id": 1}).json()) == 1
    assert client.get(f"{API}/sensors", params={"sensor_type": "co2"}).json() == []

    updated = client.put(f"{API}/sensors/{sensor_id}", json={"status": "fault"})
    assert updated.status_code == 200 and updated.json()["status"] == "fault"
    assert client.put(f"{API}/sensors/999", json={"status": "fault"}).status_code == 404


def test_reading_updates_last_seen_of_the_registered_device(client, room):
    client.post(f"{API}/sensors", json={"room_id": 1, "sensor_type": "acoustic", "device_id": "ESP32-A101"})
    client.post(f"{API}/readings", json=reading(), headers=KEY)
    assert client.get(f"{API}/sensors").json()[0]["last_seen"] is not None


# ------------------------------------------------------------------- readings
def test_valid_reading_is_stored_and_analysed(client, room):
    response = client.post(f"{API}/readings", json=reading(), headers=KEY)
    assert response.status_code == 201
    body = response.json()
    assert body["reading_id"] >= 1 and body["simulated"] is False
    result = body["result"]
    assert result["room_id"] == 1
    assert result["thermal"]["delta_temperature"] == pytest.approx(4.8)
    assert result["occupancy"]["state"] == "uncertain"  # first reading: not enough persistence yet
    assert result["recommendation"]["action"] == "maintain_safe_state"

    stored = client.get(f"{API}/readings").json()
    assert len(stored) == 1 and stored[0]["source"] == "rest" and stored[0]["is_simulated"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"acoustic_level": 0.3},
        {"room_temperature": 24.0, "edge_temperature": 25.0},
        {"humidity": 50.0},
    ],
)
def test_partial_payloads_are_accepted(client, room, payload):
    body = {"device_id": "ESP32-A101", "room_id": 1, **payload}
    response = client.post(f"{API}/readings", json=body, headers=KEY)
    assert response.status_code == 201, response.text


def test_missing_data_leads_to_insufficient_data(client, room):
    response = client.post(f"{API}/readings", json={"device_id": "ESP32-A101", "room_id": 1, "humidity": 50}, headers=KEY)
    assert response.json()["result"]["recommendation"]["action"] == "insufficient_data"
    assert response.json()["result"]["room_state"] == "uncertain"


@pytest.mark.parametrize(
    "overrides",
    [
        {"room_temperature": -127.0},
        {"room_temperature": 85.0},
        {"edge_temperature": 500},
        {"room_temperature": "warm"},
        {"acoustic_level": 1.5},
        {"acoustic_level": -0.2},
        {"humidity": 130},
        {"device_id": ""},
        {"device_id": "bad id with spaces"},
        {"room_id": 0},
        {"raw_audio": [0.1, 0.2]},
        {"timestamp": "not-a-date"},
    ],
)
def test_invalid_readings_are_rejected_with_422(client, room, overrides):
    response = client.post(f"{API}/readings", json=reading(**overrides), headers=KEY)
    assert response.status_code == 422
    assert client.get(f"{API}/readings").json() == []  # nothing was stored


def test_empty_reading_is_rejected(client, room):
    response = client.post(f"{API}/readings", json={"device_id": "ESP32-A101", "room_id": 1}, headers=KEY)
    assert response.status_code == 422


def test_timestamp_far_in_the_future_is_rejected(client, room):
    future = (utcnow() + timedelta(minutes=30)).isoformat()
    assert client.post(f"{API}/readings", json=reading(timestamp=future), headers=KEY).status_code == 422


def test_unknown_room_is_404(client):
    assert client.post(f"{API}/readings", json=reading(room_id=42), headers=KEY).status_code == 404


def test_api_key_is_required(client, room):
    assert client.post(f"{API}/readings", json=reading()).status_code == 401
    assert client.post(f"{API}/readings", json=reading(), headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.post(f"{API}/readings", json=reading(), headers={"X-API-Key": "test-key"}).status_code == 201


def test_server_refuses_everything_when_no_api_key_is_configured(client, room):
    client.app.dependency_overrides[get_settings] = lambda: Settings(device_api_key="", _env_file=None)
    try:
        assert client.post(f"{API}/readings", json=reading(), headers=KEY).status_code == 503
    finally:
        client.app.dependency_overrides.clear()


# ------------------------------------------------------------------ analytics
def test_analytics_without_data_is_insufficient_data(client, room):
    body = client.get(f"{API}/rooms/1/analytics").json()
    assert body["has_data"] is False
    assert body["current_state"] == "uncertain"
    assert body["recommendation"]["action"] == "insufficient_data"
    assert body["energy"]["measured_savings_kwh_today"] is None


def test_analytics_for_unknown_room_is_404(client):
    assert client.get(f"{API}/rooms/9/analytics").status_code == 404


def test_analytics_has_the_documented_shape(client, room):
    client.post(f"{API}/readings", json=reading(), headers=KEY)
    body = client.get(f"{API}/rooms/1/analytics").json()
    for key in (
        "room_id",
        "current_state",
        "occupancy_confidence",
        "temperature",
        "thermal_anomaly",
        "recommendation",
        "energy",
    ):
        assert key in body
    assert body["temperature"] == {"room": 24.8, "edge": 29.6, "delta": 4.8}
    assert set(body["thermal_anomaly"]) >= {"score", "leak_candidate"}
    assert set(body["recommendation"]) == {"action", "reason"}
    assert body["energy"]["basis"] == "estimated"
    assert "estimated_savings_kwh_today" in body["energy"]
    assert body["stale"] is False and body["simulated"] is False


def test_old_data_is_reported_as_stale_uncertain(client, room):
    old = (utcnow() - timedelta(hours=1)).isoformat()
    client.post(f"{API}/readings", json=reading(timestamp=old), headers=KEY)
    body = client.get(f"{API}/rooms/1/analytics").json()
    assert body["stale"] is True
    assert body["current_state"] == "uncertain"
    assert body["recommendation"]["action"] == "insufficient_data"


def test_history_is_returned_oldest_first(client, room):
    base = utcnow() - timedelta(minutes=5)
    for i in range(3):
        ts = (base + timedelta(seconds=10 * i)).isoformat()
        client.post(f"{API}/readings", json=reading(timestamp=ts), headers=KEY)
    history = client.get(f"{API}/rooms/1/history").json()
    assert len(history) == 3
    assert [p["timestamp"] for p in history] == sorted(p["timestamp"] for p in history)
    assert client.get(f"{API}/rooms/77/history").status_code == 404


def test_energy_estimate_endpoint(client):
    body = client.get(f"{API}/energy/estimate", params={"hvac_power_kw": 1.5, "avoided_runtime_hours": 4}).json()
    assert body["estimated_energy_saved_kwh"] == 6.0
    assert body["estimated_monthly_savings_kwh"] == 180.0
    assert body["is_measured"] is False and body["basis"] == "estimated"
    assert client.get(f"{API}/energy/estimate", params={"hvac_power_kw": 1, "avoided_runtime_hours": 30}).status_code == 422


# ------------------------------------------------------------------ dashboard
def test_dashboard_with_no_rooms_or_data(client):
    body = client.get(f"{API}/dashboard/summary").json()
    assert body["total_rooms"] == 0 and body["estimated_energy_saved_today"] == 0
    assert body["includes_simulated_data"] is False


def test_dashboard_counts_rooms_and_treats_missing_data_as_uncertain(client, room):
    client.post(f"{API}/rooms", json={"name": "Room B-202"})
    body = client.get(f"{API}/dashboard/summary").json()
    assert body["total_rooms"] == 2 and body["uncertain_rooms"] == 2
    assert body["rooms_without_fresh_data"] == 2


def test_dashboard_after_a_simulated_vacant_room_with_hvac_running(client, room):
    client.post(f"{API}/rooms", json={"name": "Room B-202"})
    run = client.post(
        f"{API}/simulation/generate",
        headers=KEY,
        json={"room_id": 1, "scenario": "empty_room_hvac_on", "duration": 900, "interval": 10, "seed": 3},
    )
    assert run.status_code == 200
    body = client.get(f"{API}/dashboard/summary").json()
    assert body["total_rooms"] == 2
    assert body["vacant_rooms"] == 1 and body["uncertain_rooms"] == 1
    assert body["rooms_recommended_for_energy_saving"] == 1
    assert body["estimated_energy_saved_today"] > 0
    assert body["estimated_energy_saved_this_month"] >= body["estimated_energy_saved_today"]
    assert body["includes_simulated_data"] is True
    assert body["measured_energy_saved_today"] is None and body["energy_basis"] == "estimated"


# ------------------------------------------------------------------ websocket
def test_websocket_receives_updates_after_new_readings(client, room):
    with client.websocket_connect("/ws/rooms/1") as ws:
        client.post(f"{API}/readings", json=reading(), headers=KEY)
        message = ws.receive_json()
    assert message["room_id"] == 1
    assert {"occupancy", "thermal", "recommendation"} <= set(message)
    assert message["thermal"]["delta_temperature"] == pytest.approx(4.8)
    assert message["simulated"] is False


def test_websocket_sends_the_latest_state_immediately_on_connect(client, room):
    client.post(f"{API}/readings", json=reading(), headers=KEY)
    with client.websocket_connect("/ws/rooms/1") as ws:
        assert ws.receive_json()["room_id"] == 1


def test_websocket_only_delivers_the_requested_room(client, room):
    client.post(f"{API}/rooms", json={"name": "Room B-202"})
    with client.websocket_connect("/ws/rooms/2") as ws_other:
        client.post(f"{API}/readings", json=reading(room_id=1), headers=KEY)
        client.post(f"{API}/readings", json=reading(room_id=2), headers=KEY)
        assert ws_other.receive_json()["room_id"] == 2


def test_websocket_for_unknown_room_is_closed_with_4404(client):
    with pytest.raises(WebSocketDisconnect) as info:
        with client.websocket_connect("/ws/rooms/999") as ws:
            ws.receive_json()
    assert info.value.code == 4404


# ------------------------------------------------------- model replaceability
class AlwaysOccupied(OccupancyModel):
    """Stand-in for a future TinyML / ONNX model: same interface, different brain."""

    name = "always_occupied_stub"

    def predict(self, features) -> OccupancyPrediction:
        return OccupancyPrediction(
            state=RoomState.OCCUPIED,
            occupancy_confidence=0.9,
            activity_score=0.5,
            evidence="high",
            reason="stub",
            model_name=self.name,
        )

    def reset(self) -> None:
        pass


def test_occupancy_model_can_be_swapped_without_changing_the_api(client, room):
    client.app.state.ingestion.registry.set_occupancy_factory(AlwaysOccupied)
    body = client.post(f"{API}/readings", json=reading(acoustic_level=0.0), headers=KEY).json()
    assert body["result"]["occupancy"]["state"] == "occupied"
    assert body["result"]["occupancy"]["confidence"] == 0.9
    assert set(body["result"]) == {
        "room_id",
        "timestamp",
        "simulated",
        "room_state",
        "temperature",
        "occupancy",
        "thermal",
        "recommendation",
    }
