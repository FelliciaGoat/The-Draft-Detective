"""Simulation mode: realistic FAKE sensor data so the whole backend can be demonstrated without hardware.

Everything generated here is labelled SIMULATED:
  * the reading and analytics rows have `is_simulated = true`, `source = "simulation"`,
    `scenario = <name>` and the device id is `SIMULATOR-<room_id>`;
  * every API response and WebSocket message carries `simulated: true`;
  * the dashboard summary reports `includes_simulated_data`.

Readings flow through exactly the same pipeline as real ones (`IngestionService`), so the
occupancy / thermal / fusion / energy results are genuine outputs of the real algorithms.

Timing note: the engines use the READING timestamps, not the wall clock, so a whole scenario
can be computed instantly ("batch" mode). In "realtime" mode readings are streamed with pauses
so a dashboard can watch the transitions live.
"""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.enums import ReadingSource, SimulationScenario
from app.core.timeutils import utcnow
from app.models.reading import RoomAnalytics, SensorReading
from app.models.room import Room
from app.schemas.analytics import RoomUpdateMessage
from app.schemas.reading import ReadingCreate
from app.schemas.simulation import (
    ScenarioInfo,
    SimulationRequest,
    SimulationResponse,
    SimulationTransition,
)
from app.services.ingestion import IngestionService, IngestResult, RoomNotFoundError

logger = logging.getLogger(__name__)

MAX_READINGS_PER_RUN = 5000
DEMO_LEAVE_AT = 300  # seconds: the person leaves the room
DEMO_ANOMALY_AT = 900  # seconds: the exterior-wall temperature starts to climb
DEMO_ANOMALY_RAMP = 120.0
ANOMALY_RAMP_SECONDS = 120.0


class SimulationError(ValueError):
    """Raised for invalid simulation requests (mapped to HTTP 422)."""


SCENARIOS: dict[SimulationScenario, ScenarioInfo] = {
    SimulationScenario.OCCUPIED_ROOM: ScenarioInfo(
        name=SimulationScenario.OCCUPIED_ROOM,
        description="People talking and moving. Only the minimal sensor set: acoustic + two temperatures.",
        expected_outcome="uncertain for ~30 s, then occupied -> normal_operation.",
        recommended_min_duration=300,
    ),
    SimulationScenario.EMPTY_ROOM: ScenarioInfo(
        name=SimulationScenario.EMPTY_ROOM,
        description="Quiet room, HVAC reported OFF.",
        expected_outcome="uncertain, then vacant after the persistence period -> normal_operation (nothing to save).",
        recommended_min_duration=600,
    ),
    SimulationScenario.EMPTY_ROOM_HVAC_ON: ScenarioInfo(
        name=SimulationScenario.EMPTY_ROOM_HVAC_ON,
        description="Quiet room while the HVAC is running.",
        expected_outcome="vacant after the persistence period -> energy_saving_mode, estimated energy accumulates.",
        recommended_min_duration=900,
    ),
    SimulationScenario.OCCUPIED_NORMAL_THERMAL: ScenarioInfo(
        name=SimulationScenario.OCCUPIED_NORMAL_THERMAL,
        description="Occupied room with a normal, moderate window/room temperature difference.",
        expected_outcome="occupied -> normal_operation; thermal score stays near 0 (a moderate delta-T is not a leak).",
        recommended_min_duration=600,
    ),
    SimulationScenario.THERMAL_ANOMALY: ScenarioInfo(
        name=SimulationScenario.THERMAL_ANOMALY,
        description="Occupied room; the edge temperature drifts far away from the room temperature.",
        expected_outcome="occupied, then a persistent large delta-T -> leak_candidate -> inspect_envelope.",
        recommended_min_duration=900,
    ),
    SimulationScenario.NOISY_ACOUSTIC: ScenarioInfo(
        name=SimulationScenario.NOISY_ACOUSTIC,
        description="Erratic ambient noise (corridor, construction) with spikes but no clear occupancy pattern.",
        expected_outcome="stays uncertain -> maintain_safe_state (the system refuses to guess).",
        recommended_min_duration=600,
    ),
    SimulationScenario.DEMO_STORY: ScenarioInfo(
        name=SimulationScenario.DEMO_STORY,
        description=(
            "Room A-101 demo: occupied (24 C, edge 25 C) -> person leaves at 5 min -> vacant with HVAC on -> "
            "exterior-wall temperature climbs from 15 min."
        ),
        expected_outcome=(
            "occupied/normal_operation -> vacant/energy_saving_mode (~11 min) -> "
            "thermal anomaly / inspect_envelope (~22 min)."
        ),
        recommended_min_duration=1800,
    ),
}
DEMO_MIN_DURATION = 1500


@dataclass(frozen=True)
class SimSample:
    """One generated set of sensor values at a time offset from the start of the run."""

    offset_seconds: float
    acoustic_level: float
    room_temperature: float
    edge_temperature: float
    humidity: float | None
    hvac_on: bool | None


# ------------------------------------------------------------------ signal helpers
def _clip01(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


def _occupied_acoustic(rng: np.random.Generator) -> float:
    """Moderate activity: steady talking with occasional louder bursts."""
    level = 0.40 + rng.normal(0, 0.09)
    if rng.random() < 0.15:
        level += rng.uniform(0.0, 0.25)
    return _clip01(level)


def _quiet_acoustic(rng: np.random.Generator) -> float:
    """Empty room: near-silence with a very rare door/pipe bump."""
    level = 0.03 + abs(rng.normal(0, 0.015))
    if rng.random() < 0.004:
        level += 0.22
    return _clip01(level)


def _noisy_acoustic(rng: np.random.Generator) -> float:
    """Erratic mid-level noise with random spikes; no sustained pattern."""
    level = 0.20 + rng.normal(0, 0.05)
    if rng.random() < 0.05:
        level = rng.uniform(0.5, 0.85)
    return _clip01(level)


def _room_temperature(rng: np.random.Generator, t: float) -> float:
    return 24.0 + 0.3 * math.sin(2 * math.pi * t / 1800.0) + rng.normal(0, 0.08)


def _humidity(rng: np.random.Generator, t: float) -> float:
    return float(min(100.0, max(0.0, 50.0 + 2.0 * math.sin(2 * math.pi * t / 2400.0) + rng.normal(0, 0.5))))


def generate_samples(
    scenario: SimulationScenario, duration: int, interval: int, seed: int | None = None
) -> list[SimSample]:
    """Generate the sensor values of a scenario (pure function, no database)."""
    if duration < 2 * interval:
        raise SimulationError("duration must be at least twice the interval")
    if scenario == SimulationScenario.DEMO_STORY and duration < DEMO_MIN_DURATION:
        raise SimulationError(
            f"demo_story needs duration >= {DEMO_MIN_DURATION} s so the whole story fits (default persistence "
            "times are 5 minutes); use 1800."
        )
    offsets = list(range(0, duration, interval))
    if len(offsets) > MAX_READINGS_PER_RUN:
        raise SimulationError(f"Too many readings ({len(offsets)}); maximum is {MAX_READINGS_PER_RUN}")

    rng = np.random.default_rng(seed)
    samples: list[SimSample] = []
    for offset in offsets:
        t = float(offset)
        room = _room_temperature(rng, t)
        humidity: float | None = _humidity(rng, t)
        hvac_on: bool | None = True

        if scenario == SimulationScenario.OCCUPIED_ROOM:
            acoustic = _occupied_acoustic(rng)
            edge = room + 1.0 + rng.normal(0, 0.15)
            humidity, hvac_on = None, None  # minimal prototype: acoustic + temperatures only
        elif scenario == SimulationScenario.EMPTY_ROOM:
            acoustic = _quiet_acoustic(rng)
            edge = room + 1.0 + rng.normal(0, 0.15)
            hvac_on = False
        elif scenario == SimulationScenario.EMPTY_ROOM_HVAC_ON:
            acoustic = _quiet_acoustic(rng)
            edge = room + 1.0 + rng.normal(0, 0.15)
        elif scenario == SimulationScenario.OCCUPIED_NORMAL_THERMAL:
            acoustic = _occupied_acoustic(rng)
            edge = room + 1.5 + 0.8 * math.sin(2 * math.pi * t / 900.0) + rng.normal(0, 0.2)
        elif scenario == SimulationScenario.THERMAL_ANOMALY:
            acoustic = _occupied_acoustic(rng)
            ramp = min(1.0, max(0.0, (t - 0.2 * duration) / ANOMALY_RAMP_SECONDS))
            edge = room + 1.0 + 7.0 * ramp + rng.normal(0, 0.2)
        elif scenario == SimulationScenario.NOISY_ACOUSTIC:
            acoustic = _noisy_acoustic(rng)
            edge = room + 1.0 + rng.normal(0, 0.15)
        else:  # DEMO_STORY
            room = 24.0 + rng.normal(0, 0.05)
            acoustic = _occupied_acoustic(rng) if t < DEMO_LEAVE_AT else _quiet_acoustic(rng)
            ramp = min(1.0, max(0.0, (t - DEMO_ANOMALY_AT) / DEMO_ANOMALY_RAMP))
            edge = 25.0 + 7.5 * ramp + rng.normal(0, 0.1)

        samples.append(
            SimSample(
                offset_seconds=t,
                acoustic_level=round(acoustic, 3),
                room_temperature=round(room, 2),
                edge_temperature=round(edge, 2),
                humidity=None if humidity is None else round(humidity, 1),
                hvac_on=hvac_on,
            )
        )
    return samples


# ------------------------------------------------------------------------ runs
@dataclass
class SimulationRun:
    """Book-keeping of one simulation run."""

    run_id: str
    mode: str  # "batch" | "realtime"
    scenario: SimulationScenario
    room_id: int
    device_id: str
    interval: int
    speed: float
    samples: list[SimSample]
    start_time: datetime
    status: str = "running"
    generated: int = 0
    transitions: list[SimulationTransition] = field(default_factory=list)
    final_state: RoomUpdateMessage | None = None
    error: str | None = None
    cancel_requested: bool = False
    clear_previous: bool = True
    _last_key: tuple | None = None

    @property
    def end_time(self) -> datetime:
        """Timestamp of the last planned reading."""
        return self.start_time + timedelta(seconds=self.samples[-1].offset_seconds)

    def record(self, result: IngestResult) -> None:
        """Track state changes for the response (the story of the run)."""
        message = result.message
        key = (message.room_state, message.recommendation.action, message.thermal.leak_candidate)
        if key != self._last_key:
            self._last_key = key
            self.transitions.append(
                SimulationTransition(
                    timestamp=message.timestamp,
                    room_state=message.room_state,
                    recommended_action=message.recommendation.action,
                    occupancy_confidence=message.occupancy.confidence,
                    thermal_anomaly_score=message.thermal.thermal_anomaly_score,
                    leak_candidate=message.thermal.leak_candidate,
                )
            )
        self.final_state = message
        self.generated += 1


class SimulationManager:
    """Creates and runs simulations (batch or realtime background streaming)."""

    def __init__(self, ingestion: IngestionService, session_factory: Callable[[], Session]) -> None:
        self.ingestion = ingestion
        self.session_factory = session_factory
        self._runs: dict[str, SimulationRun] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._active_by_room: dict[int, str] = {}

    # ----------------------------------------------------------- preparation
    def prepare(self, request: SimulationRequest) -> SimulationRun:
        """Validate the request and generate the samples (no readings are stored yet)."""
        with self.session_factory() as db:
            if db.get(Room, request.room_id) is None:
                raise RoomNotFoundError(f"Room {request.room_id} does not exist")
        samples = generate_samples(request.scenario, request.duration, request.interval, request.seed)
        now = utcnow()
        start = now if request.realtime else now - timedelta(seconds=samples[-1].offset_seconds)
        run = SimulationRun(
            run_id=uuid.uuid4().hex[:12],
            mode="realtime" if request.realtime else "batch",
            scenario=request.scenario,
            room_id=request.room_id,
            device_id=f"SIMULATOR-{request.room_id}",
            interval=request.interval,
            speed=request.speed,
            samples=samples,
            start_time=start,
            clear_previous=request.clear_previous,
        )
        self._runs[run.run_id] = run
        while len(self._runs) > 50:  # keep memory bounded
            self._runs.pop(next(iter(self._runs)))
        return run

    def _clear_previous_simulation(self, room_id: int) -> None:
        """Delete earlier SIMULATED rows of a room (real sensor data is never touched)."""
        with self.session_factory() as db:
            db.execute(
                delete(RoomAnalytics).where(RoomAnalytics.room_id == room_id, RoomAnalytics.is_simulated.is_(True))
            )
            db.execute(
                delete(SensorReading).where(SensorReading.room_id == room_id, SensorReading.is_simulated.is_(True))
            )
            db.commit()

    def _ingest_sample(self, run: SimulationRun, sample: SimSample, notify: bool) -> None:
        """Store and analyse one simulated reading."""
        data = ReadingCreate(
            device_id=run.device_id,
            room_id=run.room_id,
            timestamp=run.start_time + timedelta(seconds=sample.offset_seconds),
            acoustic_level=sample.acoustic_level,
            room_temperature=sample.room_temperature,
            edge_temperature=sample.edge_temperature,
            humidity=sample.humidity,
            hvac_on=sample.hvac_on,
            simulated=True,
        )
        with self.session_factory() as db:
            result = self.ingestion.ingest(
                db, data, source=ReadingSource.SIMULATION, scenario=run.scenario.value, notify=notify
            )
        run.record(result)

    # ----------------------------------------------------------------- batch
    def run_batch(self, run: SimulationRun) -> SimulationRun:
        """Compute the whole scenario immediately (blocking; call it in a thread)."""
        self.ingestion.registry.reset(run.room_id)  # start from a clean 'unknown' state
        last = len(run.samples) - 1
        try:
            if run.clear_previous:
                self._clear_previous_simulation(run.room_id)
            for i, sample in enumerate(run.samples):
                self._ingest_sample(run, sample, notify=(i == last))
            run.status = "completed"
        except Exception as exc:
            logger.exception("Simulation %s failed", run.run_id)
            run.status, run.error = "failed", str(exc)
        return run

    # -------------------------------------------------------------- realtime
    def start_realtime(self, run: SimulationRun) -> None:
        """Stream the readings in the background (must be called inside the event loop)."""
        previous_id = self._active_by_room.get(run.room_id)
        if previous_id:
            self.stop(previous_id)
        self.ingestion.registry.reset(run.room_id)
        task = asyncio.create_task(self._run_realtime(run), name=f"simulation-{run.run_id}")
        self._tasks[run.run_id] = task
        self._active_by_room[run.room_id] = run.run_id
        task.add_done_callback(lambda _t, rid=run.run_id: self._tasks.pop(rid, None))

    async def _run_realtime(self, run: SimulationRun) -> None:
        """Background loop: one reading per (interval / speed) real seconds."""
        last = len(run.samples) - 1
        try:
            if run.clear_previous:
                await run_in_threadpool(self._clear_previous_simulation, run.room_id)
            for i, sample in enumerate(run.samples):
                if run.cancel_requested:
                    run.status = "stopped"
                    return
                await run_in_threadpool(self._ingest_sample, run, sample, True)
                if i < last:
                    await asyncio.sleep(run.interval / run.speed)
            run.status = "completed"
        except asyncio.CancelledError:
            run.status = "stopped"
            raise
        except Exception as exc:
            logger.exception("Realtime simulation %s failed", run.run_id)
            run.status, run.error = "failed", str(exc)
        finally:
            if self._active_by_room.get(run.room_id) == run.run_id:
                self._active_by_room.pop(run.room_id, None)

    # --------------------------------------------------------------- control
    def get(self, run_id: str) -> SimulationRun | None:
        """Look up a run."""
        return self._runs.get(run_id)

    def stop(self, run_id: str) -> bool:
        """Ask a realtime run to stop. Returns False if the run does not exist."""
        run = self._runs.get(run_id)
        if run is None:
            return False
        run.cancel_requested = True
        task = self._tasks.get(run_id)
        if task and not task.done():
            task.cancel()
        if run.status == "running":
            run.status = "stopped"
        return True

    async def shutdown(self) -> None:
        """Cancel all background runs (application shutdown)."""
        for run_id in list(self._tasks):
            self.stop(run_id)
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    # -------------------------------------------------------------- response
    @staticmethod
    def to_response(run: SimulationRun) -> SimulationResponse:
        """Convert a run into the API response."""
        return SimulationResponse(
            run_id=run.run_id,
            mode=run.mode,  # type: ignore[arg-type]
            status=run.status,  # type: ignore[arg-type]
            scenario=run.scenario,
            room_id=run.room_id,
            device_id=run.device_id,
            readings_planned=len(run.samples),
            readings_generated=run.generated,
            start_time=run.start_time,
            end_time=run.end_time,
            transitions=list(run.transitions),
            final_state=run.final_state,
            error=run.error,
        )
