"""Simulation-mode tests."""

import time

import pytest

from app.core.enums import SimulationScenario
from app.services.simulation import SimulationError, generate_samples

API = "/api/v1"
KEY = {"X-API-Key": "test-key"}


def generate(client, **overrides):
    body = {"room_id": 1, "scenario": "demo_story", "duration": 1800, "interval": 10, "seed": 7}
    body.update(overrides)
    return client.post(f"{API}/simulation/generate", json=body, headers=KEY)


def sequence(transitions) -> list[tuple[str, str]]:
    return [(t["room_state"], t["recommended_action"]) for t in transitions]


# --------------------------------------------------------------------- basics
def test_scenarios_are_listed(client):
    names = {s["name"] for s in client.get(f"{API}/simulation/scenarios").json()}
    assert names == {s.value for s in SimulationScenario}


def test_simulation_requires_the_api_key(client, room):
    body = {"room_id": 1, "scenario": "empty_room", "duration": 600, "interval": 10}
    assert client.post(f"{API}/simulation/generate", json=body).status_code == 401


def test_unknown_room_and_bad_parameters(client, room):
    assert generate(client, room_id=99).status_code == 404
    assert generate(client, duration=600).status_code == 422  # demo_story needs >= 1500 s
    assert generate(client, scenario="empty_room", duration=10, interval=10).status_code == 422
    assert generate(client, scenario="nonsense").status_code == 422
    assert generate(client, scenario="empty_room", interval=0).status_code == 422


def test_generator_is_deterministic_and_within_sensor_ranges():
    a = generate_samples(SimulationScenario.NOISY_ACOUSTIC, 600, 10, seed=1)
    b = generate_samples(SimulationScenario.NOISY_ACOUSTIC, 600, 10, seed=1)
    assert a == b
    assert all(0 <= s.acoustic_level <= 1 for s in a)
    with pytest.raises(SimulationError):
        generate_samples(SimulationScenario.EMPTY_ROOM, 10, 10)


# ------------------------------------------------------------ the demo story
def test_demo_story_produces_the_required_transitions(client, room):
    response = generate(client)
    assert response.status_code == 200
    body = response.json()
    assert body["simulated"] is True and "SIMULATED" in body["notice"]
    assert body["mode"] == "batch" and body["status"] == "completed"
    assert body["readings_generated"] == body["readings_planned"] == 180

    steps = sequence(body["transitions"])
    assert ("occupied", "normal_operation") in steps
    assert ("vacant", "energy_saving_mode") in steps
    assert ("vacant", "inspect_envelope") in steps
    assert steps.index(("occupied", "normal_operation")) < steps.index(("vacant", "energy_saving_mode"))
    assert steps.index(("vacant", "energy_saving_mode")) < steps.index(("vacant", "inspect_envelope"))

    final = body["final_state"]
    assert final["simulated"] is True
    assert final["thermal"]["leak_candidate"] is True
    assert final["recommendation"]["action"] == "inspect_envelope"


def test_simulated_data_is_labelled_everywhere(client, room):
    generate(client)
    readings = client.get(f"{API}/readings", params={"limit": 1000}).json()
    assert len(readings) == 180
    assert all(r["is_simulated"] and r["source"] == "simulation" and r["scenario"] == "demo_story" for r in readings)
    assert all(r["device_id"] == "SIMULATOR-1" for r in readings)
    analytics = client.get(f"{API}/rooms/1/analytics").json()
    assert analytics["simulated"] is True
    assert client.get(f"{API}/readings", params={"include_simulated": False}).json() == []


def test_simulated_readings_do_not_make_registered_sensors_look_alive(client, room):
    client.post(f"{API}/sensors", json={"room_id": 1, "sensor_type": "acoustic", "device_id": "SIMULATOR-1"})
    generate(client, scenario="empty_room", duration=600)
    assert client.get(f"{API}/sensors").json()[0]["last_seen"] is None


# ------------------------------------------------------------ every scenario
@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("occupied_room", ("occupied", "normal_operation")),
        ("empty_room", ("vacant", "normal_operation")),
        ("empty_room_hvac_on", ("vacant", "energy_saving_mode")),
        ("occupied_normal_thermal", ("occupied", "normal_operation")),
        ("thermal_anomaly", ("occupied", "inspect_envelope")),
    ],
)
def test_scenario_outcomes(client, room, scenario, expected):
    body = generate(client, scenario=scenario, duration=900).json()
    assert sequence(body["transitions"])[-1] == expected


def test_normal_thermal_scenario_never_raises_a_leak_candidate(client, room):
    body = generate(client, scenario="occupied_normal_thermal", duration=900).json()
    assert not any(t["leak_candidate"] for t in body["transitions"])
    history = client.get(f"{API}/rooms/1/history", params={"limit": 500}).json()
    assert max(p["thermal_anomaly_score"] for p in history) < 0.2


def test_noisy_environment_stays_uncertain_and_safe(client, room):
    body = generate(client, scenario="noisy_acoustic", duration=900).json()
    assert sequence(body["transitions"]) == [("uncertain", "maintain_safe_state")]


def test_energy_estimate_accumulates_only_while_energy_saving_is_recommended(client, room):
    generate(client, scenario="occupied_room", duration=900)
    assert client.get(f"{API}/rooms/1/analytics").json()["energy"]["estimated_savings_kwh_today"] == 0
    generate(client, scenario="empty_room_hvac_on", duration=900)
    energy = client.get(f"{API}/rooms/1/analytics").json()["energy"]
    assert energy["estimated_savings_kwh_today"] > 0
    assert energy["basis"] == "estimated" and energy["measured_savings_kwh_today"] is None


# ------------------------------------------------------ clearing and real data
def test_rerunning_a_simulation_does_not_double_the_estimates(client, room):
    generate(client, scenario="empty_room_hvac_on", duration=900)
    first = client.get(f"{API}/rooms/1/analytics").json()["energy"]["estimated_savings_kwh_today"]
    generate(client, scenario="empty_room_hvac_on", duration=900)
    second = client.get(f"{API}/rooms/1/analytics").json()["energy"]["estimated_savings_kwh_today"]
    assert second == pytest.approx(first)
    generate(client, scenario="empty_room_hvac_on", duration=900, clear_previous=False)
    third = client.get(f"{API}/rooms/1/analytics").json()["energy"]["estimated_savings_kwh_today"]
    assert third == pytest.approx(2 * first, rel=0.01)


def test_real_readings_are_never_deleted_by_a_simulation(client, room):
    real = {"device_id": "ESP32-A101", "room_id": 1, "acoustic_level": 0.3, "room_temperature": 24, "edge_temperature": 25}
    assert client.post(f"{API}/readings", json=real, headers=KEY).status_code == 201
    generate(client, scenario="empty_room", duration=600)
    generate(client, scenario="empty_room", duration=600)
    real_rows = client.get(f"{API}/readings", params={"include_simulated": False}).json()
    assert len(real_rows) == 1 and real_rows[0]["device_id"] == "ESP32-A101"


# ------------------------------------------------------------------- realtime
def wait_for_status(client, run_id: str, wanted: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"{API}/simulation/runs/{run_id}").json()
        if body["status"] == wanted:
            return body
        time.sleep(0.05)
    raise AssertionError(f"run never reached '{wanted}': {body}")


def test_realtime_simulation_streams_over_websocket(client, room):
    with client.websocket_connect("/ws/rooms/1") as ws:
        response = generate(client, scenario="occupied_room", duration=20, interval=2, realtime=True, speed=500)
        assert response.status_code == 202
        assert response.json()["mode"] == "realtime"
        first = ws.receive_json()
        assert first["room_id"] == 1 and first["simulated"] is True
    done = wait_for_status(client, response.json()["run_id"], "completed")
    assert done["readings_generated"] == done["readings_planned"] == 10


def test_realtime_simulation_can_be_stopped(client, room):
    response = generate(client, scenario="occupied_room", duration=100, interval=10, realtime=True, speed=1)
    run_id = response.json()["run_id"]
    stopped = client.post(f"{API}/simulation/runs/{run_id}/stop", headers=KEY)
    assert stopped.status_code == 200
    body = wait_for_status(client, run_id, "stopped")
    assert body["readings_generated"] < body["readings_planned"]
    assert client.post(f"{API}/simulation/runs/nope/stop", headers=KEY).status_code == 404
    assert client.get(f"{API}/simulation/runs/nope").status_code == 404


def test_simulation_can_be_disabled(client, room):
    from app.api.deps import get_settings
    from app.core.config import Settings

    client.app.dependency_overrides[get_settings] = lambda: Settings(
        device_api_key="test-key", simulation_enabled=False, _env_file=None
    )
    try:
        assert generate(client, scenario="empty_room", duration=600).status_code == 404
        assert client.get(f"{API}/simulation/scenarios").status_code == 404
    finally:
        client.app.dependency_overrides.clear()
