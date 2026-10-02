"""Shared FastAPI dependencies: settings, database session, services and API-key security."""

import secrets

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings
from app.database.database import get_db  # re-exported for the routes
from app.services.ingestion import IngestionService
from app.services.mqtt_service import MqttService
from app.services.simulation import SimulationManager
from app.services.websocket_manager import ConnectionManager

__all__ = [
    "get_db",
    "get_settings",
    "get_ingestion",
    "get_mqtt",
    "get_simulation_manager",
    "get_ws_manager",
    "require_device_api_key",
]

# Shows an "Authorize" button in /docs so you can paste the key once.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="Device API key (DEVICE_API_KEY)")


def require_device_api_key(
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    """Reject requests without the correct `X-API-Key` header.

    Fails closed: if DEVICE_API_KEY is not configured on the server, nothing is accepted.
    """
    if not settings.device_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DEVICE_API_KEY is not configured on the server.",
        )
    if not api_key or not secrets.compare_digest(api_key.encode(), settings.device_api_key.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )


def get_ingestion(request: Request) -> IngestionService:
    """The shared ingestion pipeline (created at startup)."""
    return request.app.state.ingestion


def get_ws_manager(request: Request) -> ConnectionManager:
    """The shared WebSocket connection manager."""
    return request.app.state.ws_manager


def get_mqtt(request: Request) -> MqttService:
    """The shared MQTT service."""
    return request.app.state.mqtt


def get_simulation_manager(request: Request) -> SimulationManager:
    """The shared simulation manager."""
    return request.app.state.simulation
