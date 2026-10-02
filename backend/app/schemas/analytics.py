"""Analytics, dashboard and health schemas (the contract with the Next.js frontend)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import RecommendedAction, RoomState

ENERGY_DISCLAIMER = (
    "ESTIMATE only: rated HVAC power x time the room was recommended for energy-saving mode. "
    "It is NOT a measured saving. Measured savings need a power meter and a baseline."
)


class TemperatureOut(BaseModel):
    """Latest temperatures (deg C)."""

    room: float | None = None
    edge: float | None = None
    delta: float | None = None


class OccupancyOut(BaseModel):
    """Occupancy engine result. `confidence` is P(occupied): 0 = surely empty, 1 = surely occupied."""

    state: RoomState
    confidence: float | None = Field(default=None, ge=0, le=1)
    activity_score: float | None = Field(default=None, ge=0, le=1)


class ThermalOut(BaseModel):
    """Thermal engine result. A `leak_candidate` is a reason to inspect, not proof of a leak."""

    delta_temperature: float | None = None
    thermal_anomaly_score: float | None = Field(default=None, ge=0, le=1)
    leak_candidate: bool = False
    explanation: str = ""


class RecommendationOut(BaseModel):
    """What the system suggests. It never controls equipment by itself."""

    action: RecommendedAction
    reason: str


class RoomUpdateMessage(BaseModel):
    """Message pushed over the WebSocket after every processed reading (also returned by POST /readings)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "room_id": 1,
                    "timestamp": "2026-09-29T10:30:00Z",
                    "simulated": False,
                    "room_state": "occupied",
                    "temperature": {"room": 24.8, "edge": 29.6, "delta": 4.8},
                    "occupancy": {"state": "occupied", "confidence": 0.86, "activity_score": 0.44},
                    "thermal": {
                        "delta_temperature": 4.8,
                        "thermal_anomaly_score": 0.71,
                        "leak_candidate": True,
                        "explanation": "Persistent temperature differential detected near the building envelope.",
                    },
                    "recommendation": {
                        "action": "inspect_envelope",
                        "reason": "Persistent thermal differential detected.",
                    },
                }
            ]
        }
    )

    room_id: int
    timestamp: datetime
    simulated: bool = Field(description="True when the data came from simulation mode, not real sensors")
    room_state: RoomState
    temperature: TemperatureOut
    occupancy: OccupancyOut
    thermal: ThermalOut
    recommendation: RecommendationOut


class EnergyOut(BaseModel):
    """Energy block. ESTIMATED and MEASURED savings are separate fields so the UI can never mix them up."""

    basis: Literal["estimated"] = "estimated"
    estimated_savings_kwh_today: float = 0.0
    avoided_runtime_hours_today: float = 0.0
    measured_savings_kwh_today: float | None = Field(
        default=None, description="Always null until a power meter + baseline are integrated"
    )
    disclaimer: str = ENERGY_DISCLAIMER


class ThermalAnomalyBlock(BaseModel):
    """Thermal part of the room analytics response."""

    score: float | None = None
    leak_candidate: bool = False
    explanation: str = ""


class RoomAnalyticsResponse(BaseModel):
    """Response of GET /rooms/{room_id}/analytics."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "room_id": 1,
                    "room_name": "Room A-101",
                    "has_data": True,
                    "stale": False,
                    "simulated": False,
                    "last_updated": "2026-09-29T10:30:00Z",
                    "data_age_seconds": 4.2,
                    "current_state": "occupied",
                    "occupancy_confidence": 0.88,
                    "temperature": {"room": 24.7, "edge": 29.4, "delta": 4.7},
                    "thermal_anomaly": {
                        "score": 0.76,
                        "leak_candidate": True,
                        "explanation": "Persistent temperature differential detected near the building envelope.",
                    },
                    "recommendation": {
                        "action": "inspect_envelope",
                        "reason": "Persistent thermal differential detected.",
                    },
                    "energy": {
                        "basis": "estimated",
                        "estimated_savings_kwh_today": 1.4,
                        "avoided_runtime_hours_today": 0.93,
                        "measured_savings_kwh_today": None,
                        "disclaimer": ENERGY_DISCLAIMER,
                    },
                }
            ]
        }
    )

    room_id: int
    room_name: str
    has_data: bool = Field(description="False until the first reading arrives")
    stale: bool = Field(description="True when the newest data is older than DATA_STALE_SECONDS")
    simulated: bool
    last_updated: datetime | None
    data_age_seconds: float | None
    current_state: RoomState
    occupancy_confidence: float | None
    temperature: TemperatureOut
    thermal_anomaly: ThermalAnomalyBlock
    recommendation: RecommendationOut
    energy: EnergyOut


class HistoryPoint(BaseModel):
    """One point of a room's history (for charts)."""

    timestamp: datetime
    simulated: bool
    room_state: RoomState
    occupancy_confidence: float | None
    activity_score: float | None
    room_temperature: float | None
    edge_temperature: float | None
    delta_temperature: float | None
    thermal_anomaly_score: float | None
    leak_candidate: bool
    recommended_action: RecommendedAction


class DashboardSummary(BaseModel):
    """Response of GET /dashboard/summary."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "total_rooms": 12,
                    "occupied_rooms": 5,
                    "vacant_rooms": 4,
                    "uncertain_rooms": 3,
                    "thermal_anomalies": 1,
                    "rooms_recommended_for_energy_saving": 3,
                    "estimated_energy_saved_today": 4.2,
                    "estimated_energy_saved_this_month": 61.5,
                    "energy_unit": "kWh",
                    "energy_basis": "estimated",
                    "measured_energy_saved_today": None,
                    "includes_simulated_data": False,
                    "rooms_without_fresh_data": 3,
                    "generated_at": "2026-09-29T10:30:00Z",
                }
            ]
        }
    )

    total_rooms: int
    occupied_rooms: int
    vacant_rooms: int
    uncertain_rooms: int = Field(description="Includes rooms with no data or stale data")
    thermal_anomalies: int = Field(description="Rooms currently flagged as leak CANDIDATES")
    rooms_recommended_for_energy_saving: int
    estimated_energy_saved_today: float = Field(description="kWh, ESTIMATED")
    estimated_energy_saved_this_month: float = Field(description="kWh, ESTIMATED")
    energy_unit: Literal["kWh"] = "kWh"
    energy_basis: Literal["estimated"] = "estimated"
    measured_energy_saved_today: float | None = None
    includes_simulated_data: bool = Field(description="True if any counted energy or state came from simulation")
    rooms_without_fresh_data: int
    generated_at: datetime


class EnergyEstimateResponse(BaseModel):
    """Response of GET /energy/estimate (what-if calculator)."""

    basis: Literal["estimated"] = "estimated"
    is_measured: Literal[False] = False
    hvac_power_kw: float
    avoided_runtime_hours_per_day: float
    estimated_energy_saved_kwh: float
    estimated_daily_savings_kwh: float
    estimated_monthly_savings_kwh: float
    estimated_annual_savings_kwh: float
    assumptions: dict[str, float]
    disclaimer: str


class HealthResponse(BaseModel):
    """Response of GET /health."""

    status: Literal["healthy", "degraded", "unhealthy"]
    database: Literal["connected", "disconnected"]
    mqtt: Literal["connected", "disconnected", "disabled"]
