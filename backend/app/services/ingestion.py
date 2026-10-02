"""The analysis pipeline shared by REST, MQTT and simulation.

    validated reading -> store -> occupancy -> thermal -> fusion -> energy -> store analytics
                      -> notify WebSocket clients

Keeping this in ONE place guarantees that a reading gets exactly the same treatment no matter
how it arrived.

Per-room engine state (rolling windows, persistence timers) lives in memory in the
`EngineRegistry`. After a server restart the engines "warm up" again from the next readings
(the room simply starts as `uncertain`), which is the safe behaviour.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import ReadingSource, RecommendedAction
from app.core.timeutils import utcnow
from app.models.reading import RoomAnalytics, SensorReading
from app.models.room import Room
from app.models.sensor import Sensor
from app.schemas.analytics import RoomUpdateMessage
from app.schemas.reading import ReadingCreate
from app.services.analytics_service import build_update_message
from app.services.energy import energy_for_interval_kwh
from app.services.occupancy import (
    OccupancyConfig,
    OccupancyFeatures,
    OccupancyModel,
    OccupancyPrediction,
    RuleBasedOccupancyModel,
)
from app.services.sensor_fusion import FusionConfig, FusionInput, FusionResult, fuse
from app.services.thermal import ThermalAnalyzer, ThermalConfig, ThermalResult

logger = logging.getLogger(__name__)


class RoomNotFoundError(Exception):
    """Raised when a reading refers to a room that does not exist."""


@dataclass
class RoomEngines:
    """All in-memory analysis state of one room."""

    occupancy: OccupancyModel
    thermal: ThermalAnalyzer
    last_timestamp: datetime | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class EngineRegistry:
    """Creates and keeps one set of engines per room (thread-safe)."""

    def __init__(
        self,
        occupancy_factory: Callable[[], OccupancyModel],
        thermal_config: ThermalConfig,
    ) -> None:
        # Swap `occupancy_factory` to plug in a TinyML / scikit-learn / ONNX model.
        self._occupancy_factory = occupancy_factory
        self._thermal_config = thermal_config
        self._rooms: dict[int, RoomEngines] = {}
        self._guard = threading.Lock()

    def get(self, room_id: int) -> RoomEngines:
        """Return the engines of a room, creating them on first use."""
        with self._guard:
            engines = self._rooms.get(room_id)
            if engines is None:
                engines = RoomEngines(
                    occupancy=self._occupancy_factory(), thermal=ThermalAnalyzer(self._thermal_config)
                )
                self._rooms[room_id] = engines
            return engines

    def reset(self, room_id: int) -> None:
        """Forget a room's history (new simulation, deleted room)."""
        with self._guard:
            self._rooms.pop(room_id, None)

    def reset_all(self) -> None:
        """Forget everything."""
        with self._guard:
            self._rooms.clear()

    def set_occupancy_factory(self, factory: Callable[[], OccupancyModel]) -> None:
        """Plug in a different occupancy model (TinyML, scikit-learn, ONNX...) and restart all rooms."""
        with self._guard:
            self._occupancy_factory = factory
            self._rooms.clear()


@dataclass
class IngestResult:
    """What `IngestionService.ingest` returns."""

    reading: SensorReading
    analytics: RoomAnalytics
    message: RoomUpdateMessage
    occupancy: OccupancyPrediction | None
    thermal: ThermalResult
    fusion: FusionResult


Notifier = Callable[[int, RoomUpdateMessage], None]


class IngestionService:
    """Runs the full analysis pipeline for one reading."""

    def __init__(self, settings: Settings, registry: EngineRegistry, notifier: Notifier | None = None) -> None:
        self.settings = settings
        self.registry = registry
        self.fusion_config = FusionConfig.from_settings(settings)
        self.notifier = notifier  # e.g. the WebSocket manager's thread-safe publish method

    def ingest(
        self,
        db: Session,
        data: ReadingCreate,
        source: ReadingSource = ReadingSource.REST,
        scenario: str | None = None,
        notify: bool = True,
    ) -> IngestResult:
        """Store a reading, analyse it, store the analytics, and (optionally) notify dashboards.

        Raises RoomNotFoundError if `data.room_id` does not exist.
        """
        room = db.get(Room, data.room_id)
        if room is None:
            raise RoomNotFoundError(f"Room {data.room_id} does not exist")

        timestamp = data.timestamp or utcnow()
        engines = self.registry.get(room.id)

        with engines.lock:
            reading = SensorReading(
                room_id=room.id,
                device_id=data.device_id,
                timestamp=timestamp,
                acoustic_level=data.acoustic_level,
                room_temperature=data.room_temperature,
                edge_temperature=data.edge_temperature,
                humidity=data.humidity,
                co2_ppm=data.co2_ppm,
                hvac_on=data.hvac_on,
                hvac_power_kw=data.hvac_power_kw,
                is_simulated=data.simulated,
                source=source.value,
                scenario=scenario,
            )
            db.add(reading)
            db.flush()  # assigns reading.id

            # Engines use a non-decreasing clock even if a device sends an older timestamp.
            effective_ts = timestamp
            if engines.last_timestamp is not None and effective_ts < engines.last_timestamp:
                effective_ts = engines.last_timestamp

            # 1. occupancy (needs the acoustic feature)
            occupancy: OccupancyPrediction | None = None
            if data.acoustic_level is not None:
                occupancy = engines.occupancy.predict(
                    OccupancyFeatures(
                        timestamp=effective_ts,
                        acoustic_level=data.acoustic_level,
                        co2_ppm=data.co2_ppm,
                        humidity=data.humidity,
                    )
                )

            # 2. thermal (needs both temperatures)
            if data.room_temperature is not None and data.edge_temperature is not None:
                thermal = engines.thermal.update(effective_ts, data.room_temperature, data.edge_temperature)
            else:
                thermal = ThermalResult.no_data()

            # 3. fusion
            fusion = fuse(
                FusionInput(
                    thermal=thermal,
                    occupancy=occupancy,
                    hvac_on=data.hvac_on,
                    humidity=data.humidity,
                    co2_ppm=data.co2_ppm,
                ),
                self.fusion_config,
            )

            # 4. ESTIMATED energy opportunity for the time since the previous reading
            avoided_seconds = 0.0
            energy_kwh = 0.0
            if fusion.recommended_action == RecommendedAction.ENERGY_SAVING_MODE and engines.last_timestamp:
                gap = (effective_ts - engines.last_timestamp).total_seconds()
                avoided_seconds = min(max(gap, 0.0), self.settings.energy_max_interval_seconds)
                power_kw = data.hvac_power_kw or room.hvac_power_kw or self.settings.default_hvac_power_kw
                energy_kwh = energy_for_interval_kwh(power_kw, avoided_seconds)

            engines.last_timestamp = effective_ts

            analytics = RoomAnalytics(
                room_id=room.id,
                reading_id=reading.id,
                device_id=data.device_id,
                timestamp=timestamp,
                is_simulated=data.simulated,
                occupancy_state=occupancy.state.value if occupancy else None,
                occupancy_confidence=fusion.occupancy_confidence,
                activity_score=occupancy.activity_score if occupancy else None,
                delta_temperature=thermal.delta_temperature,
                thermal_anomaly_score=thermal.thermal_anomaly_score,
                leak_candidate=fusion.leak_candidate,
                thermal_explanation=thermal.explanation,
                room_state=fusion.room_state.value,
                recommended_action=fusion.recommended_action.value,
                recommendation_reason=fusion.reason,
                hvac_on=data.hvac_on,
                avoided_runtime_seconds=round(avoided_seconds, 3),
                estimated_energy_kwh=round(energy_kwh, 6),
            )
            analytics.reading = reading
            db.add(analytics)

            if not data.simulated:  # fake data must never make a real sensor look alive
                db.execute(
                    update(Sensor).where(Sensor.device_id == data.device_id).values(last_seen=utcnow())
                )
            db.commit()

        message = build_update_message(analytics)
        if notify and self.notifier is not None:
            try:
                self.notifier(room.id, message)
            except Exception:  # a broken dashboard connection must never break ingestion
                logger.exception("Failed to notify WebSocket clients for room %s", room.id)

        return IngestResult(
            reading=reading,
            analytics=analytics,
            message=message,
            occupancy=occupancy,
            thermal=thermal,
            fusion=fusion,
        )


def build_registry(settings: Settings) -> EngineRegistry:
    """Create the default registry: rule-based occupancy model + thermal analyzer."""
    occupancy_config = OccupancyConfig.from_settings(settings)
    return EngineRegistry(
        occupancy_factory=lambda: RuleBasedOccupancyModel(occupancy_config),
        thermal_config=ThermalConfig.from_settings(settings),
    )
