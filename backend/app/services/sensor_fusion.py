"""Sensor fusion: combine the occupancy and thermal results into one recommendation.

The rules are intentionally simple, ordered and explainable. Persistence (time filtering)
already happened inside the occupancy and thermal engines, so this module is stateless and
easy to test.

Safety principle: whenever data is missing or contradictory the result is
`uncertain` + `maintain_safe_state` / `insufficient_data`. The system never recommends
energy saving on a guess.

Rule order (first match wins)
-----------------------------
1. No acoustic AND no temperature data           -> insufficient_data
2. Thermal leak candidate                        -> inspect_envelope   (does not depend on occupancy)
3. No acoustic data                              -> insufficient_data  (state uncertain)
4. Contradiction (vacant but CO2 is high)        -> maintain_safe_state (state uncertain)
5. Occupancy state uncertain                     -> maintain_safe_state
6. Occupied                                      -> normal_operation
7. Vacant + HVAC running (or unknown)            -> energy_saving_mode
8. Vacant + HVAC known to be off                 -> normal_operation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.enums import RecommendedAction, RoomState
from app.services.occupancy import OccupancyPrediction
from app.services.thermal import ThermalResult

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass(frozen=True)
class FusionConfig:
    """Configuration of the fusion rules."""

    co2_occupied_ppm: float = 1000.0
    humidity_high_pct: float = 70.0
    assume_hvac_on_when_unknown: bool = True
    co2_confidence_boost: float = 0.10

    @classmethod
    def from_settings(cls, settings: Settings) -> FusionConfig:
        """Build the config from application settings."""
        return cls(
            co2_occupied_ppm=settings.co2_occupied_ppm,
            humidity_high_pct=settings.humidity_high_pct,
            assume_hvac_on_when_unknown=settings.assume_hvac_on_when_unknown,
        )


@dataclass(frozen=True)
class FusionInput:
    """Everything fusion may look at. Only `thermal` is mandatory; the rest can be missing."""

    thermal: ThermalResult
    occupancy: OccupancyPrediction | None = None
    hvac_on: bool | None = None
    humidity: float | None = None
    co2_ppm: float | None = None


@dataclass(frozen=True)
class FusionResult:
    """Combined output."""

    room_state: RoomState
    occupancy_confidence: float | None
    thermal_anomaly_score: float | None
    leak_candidate: bool
    recommended_action: RecommendedAction
    reason: str
    notes: tuple[str, ...] = field(default_factory=tuple)


def fuse(data: FusionInput, config: FusionConfig | None = None) -> FusionResult:
    """Apply the ordered rules and return the fused room assessment."""
    cfg = config or FusionConfig()
    occ, thermal = data.occupancy, data.thermal
    notes: list[str] = []

    confidence = occ.occupancy_confidence if occ else None
    high_co2 = data.co2_ppm is not None and data.co2_ppm >= cfg.co2_occupied_ppm

    # Weak supporting evidence: high CO2 makes "occupied" a bit more believable.
    if occ and occ.state == RoomState.OCCUPIED and high_co2 and confidence is not None:
        confidence = round(min(0.98, confidence + cfg.co2_confidence_boost), 3)
        notes.append("High CO2 supports the occupied state.")
    if data.humidity is not None and data.humidity >= cfg.humidity_high_pct and thermal.leak_candidate:
        notes.append("High humidity near a leak candidate: also check for condensation or moisture.")

    def result(state: RoomState, action: RecommendedAction, reason: str) -> FusionResult:
        return FusionResult(
            room_state=state,
            occupancy_confidence=confidence,
            thermal_anomaly_score=thermal.thermal_anomaly_score,
            leak_candidate=thermal.leak_candidate,
            recommended_action=action,
            reason=reason,
            notes=tuple(notes),
        )

    # 1. nothing usable
    if occ is None and not thermal.has_data:
        return result(
            RoomState.UNCERTAIN, RecommendedAction.INSUFFICIENT_DATA, "No acoustic or temperature data received."
        )

    # 2. thermal candidate has priority; it is independent of who is in the room
    if thermal.leak_candidate:
        state = occ.state if occ else RoomState.UNCERTAIN
        if occ and occ.state == RoomState.VACANT and high_co2:
            state = RoomState.UNCERTAIN
        return result(
            state,
            RecommendedAction.INSPECT_ENVELOPE,
            "Persistent thermal differential detected (leak candidate, not confirmed).",
        )

    # 3. no acoustic information -> occupancy unknown
    if occ is None:
        return result(
            RoomState.UNCERTAIN,
            RecommendedAction.INSUFFICIENT_DATA,
            "No acoustic data, so occupancy cannot be estimated.",
        )

    # 4. contradiction
    if occ.state == RoomState.VACANT and high_co2:
        notes.append("Acoustic data says vacant but CO2 is high.")
        return result(
            RoomState.UNCERTAIN,
            RecommendedAction.MAINTAIN_SAFE_STATE,
            "Contradictory data (acoustics say vacant, CO2 says people may be present); staying in a safe state.",
        )

    # 5. uncertain occupancy
    if occ.state == RoomState.UNCERTAIN:
        return result(
            RoomState.UNCERTAIN,
            RecommendedAction.MAINTAIN_SAFE_STATE,
            "Occupancy is uncertain; keeping current comfort settings.",
        )

    # 6. occupied
    if occ.state == RoomState.OCCUPIED:
        return result(RoomState.OCCUPIED, RecommendedAction.NORMAL_OPERATION, "Room appears occupied.")

    # 7 / 8. vacant
    if data.hvac_on is True:
        return result(
            RoomState.VACANT,
            RecommendedAction.ENERGY_SAVING_MODE,
            "Room appears vacant while the HVAC is running.",
        )
    if data.hvac_on is None and cfg.assume_hvac_on_when_unknown:
        notes.append("HVAC state was not reported; assuming it may be running.")
        return result(
            RoomState.VACANT,
            RecommendedAction.ENERGY_SAVING_MODE,
            "Room appears vacant (HVAC state unknown, assumed possibly running).",
        )
    return result(RoomState.VACANT, RecommendedAction.NORMAL_OPERATION, "Room appears vacant and the HVAC is off.")
