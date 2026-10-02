"""Application entry point: builds the FastAPI app and wires the services together.

Run:  uvicorn app.main:app --reload
Docs: http://localhost:8000/docs   and   http://localhost:8000/redoc
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analytics, health, readings, rooms, sensors, simulation, ws
from app.core.config import Settings, get_settings
from app.core.logging_config import setup_logging
from app.database.database import SessionLocal
from app.database.init_db import init_db, seed_demo_data
from app.services.ingestion import IngestionService, build_registry
from app.services.mqtt_service import MqttService
from app.services.occupancy import OccupancyConfig
from app.services.simulation import SimulationManager
from app.services.thermal import ThermalConfig
from app.services.websocket_manager import ConnectionManager

API_PREFIX = "/api/v1"
logger = logging.getLogger("app")

DESCRIPTION = """
Backend for the **Acoustic Occupancy & Thermal Leak Dual-Tracker**.

It receives room-level sensor data (acoustic level + room temperature + window/exterior-wall
temperature, optionally humidity / CO2 / HVAC state) from an ESP32 over **REST or MQTT** and produces:

* an **occupancy confidence** and a room state (`occupied`, `vacant`, `uncertain`)
* a **thermal anomaly score** and a **leak candidate** flag
* a **recommendation** and an **estimated** energy-saving opportunity

**Honest limits:** sound does not perfectly reveal occupancy, and two temperature sensors cannot prove a
leak. Results are *confidence*, *anomaly* and *candidate* values that should trigger a human check.
Energy numbers are **estimates**, never measurements. Raw audio is never stored.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start and stop background services (database, MQTT, simulation)."""
    settings: Settings = get_settings()
    setup_logging(settings.log_level)

    # Validate algorithm thresholds early: a bad .env fails at startup, not at 3 a.m.
    OccupancyConfig.from_settings(settings)
    ThermalConfig.from_settings(settings)

    init_db()
    if settings.seed_demo_data:
        with SessionLocal() as db:
            seed_demo_data(db)

    ws_manager = ConnectionManager()
    ws_manager.bind_loop(asyncio.get_running_loop())
    ingestion = IngestionService(settings, build_registry(settings), notifier=ws_manager.publish_threadsafe)
    mqtt_service = MqttService(settings, ingestion, SessionLocal)
    simulation_manager = SimulationManager(ingestion, SessionLocal)

    app.state.ws_manager = ws_manager
    app.state.ingestion = ingestion
    app.state.mqtt = mqtt_service
    app.state.simulation = simulation_manager

    mqtt_service.start()
    logger.info("%s v%s started", settings.app_name, settings.app_version)
    try:
        yield
    finally:
        await simulation_manager.shutdown()
        mqtt_service.stop()
        logger.info("Application stopped")


def create_app() -> FastAPI:
    """Application factory (also used by the tests)."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        health.router,
        rooms.router,
        sensors.router,
        readings.router,
        analytics.router,
        simulation.router,
    ):
        app.include_router(router, prefix=API_PREFIX)
    app.include_router(ws.router)  # WebSocket path is /ws/rooms/{room_id}

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        """Tiny landing response that points to the docs."""
        return {"name": settings.app_name, "docs": "/docs", "redoc": "/redoc", "health": f"{API_PREFIX}/health"}

    return app


app = create_app()
