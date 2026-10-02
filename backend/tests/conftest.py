"""Shared test fixtures.

The environment is configured BEFORE the app is imported so the tests use their own temporary
SQLite file and never touch your real database.
"""

import os
import tempfile
from pathlib import Path

_TMP_DIR = tempfile.mkdtemp(prefix="occupancy-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TMP_DIR) / 'test.db'}"
os.environ["DEVICE_API_KEY"] = "test-key"
os.environ["MQTT_ENABLED"] = "false"
os.environ["SEED_DEMO_DATA"] = "false"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database.database import Base, engine  # noqa: E402
from app.main import create_app  # noqa: E402

API_KEY = "test-key"


@pytest.fixture()
def client():
    """A TestClient (with app startup/shutdown) on a fresh, empty database."""
    import app.models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Headers an ESP32 would send."""
    return {"X-API-Key": API_KEY}


@pytest.fixture()
def room(client) -> dict:
    """A room created through the API (id 1 on a fresh database)."""
    response = client.post(
        "/api/v1/rooms",
        json={
            "name": "Room A-101",
            "building": "Main Building",
            "floor": 1,
            "zone": "North Wing",
            "climate_zone": "Composite",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()
