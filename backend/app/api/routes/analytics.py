"""Analytics, dashboard and energy endpoints (read-only)."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_settings
from app.core.config import Settings
from app.models.room import Room
from app.schemas.analytics import (
    DashboardSummary,
    EnergyEstimateResponse,
    HistoryPoint,
    RoomAnalyticsResponse,
)
from app.services import analytics_service
from app.services.energy import estimate_energy_savings

router = APIRouter(tags=["Analytics"])


def _room_or_404(db: Session, room_id: int) -> Room:
    """Load a room or raise HTTP 404."""
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Room {room_id} not found")
    return room


@router.get(
    "/rooms/{room_id}/analytics",
    response_model=RoomAnalyticsResponse,
    summary="Current analytics of a room",
    description=(
        "Latest occupancy confidence, thermal anomaly, recommendation and ESTIMATED energy for one room. "
        "If no data has arrived yet, or the newest data is older than `DATA_STALE_SECONDS`, the room is "
        "reported as `uncertain` with `insufficient_data` instead of repeating an old answer."
    ),
    responses={404: {"description": "Room not found"}},
)
def room_analytics(
    room_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RoomAnalyticsResponse:
    """Return the current analytics of one room."""
    room = _room_or_404(db, room_id)
    return analytics_service.get_room_analytics(db, room, settings)


@router.get(
    "/rooms/{room_id}/history",
    response_model=list[HistoryPoint],
    summary="Recent history of a room (for charts)",
    responses={404: {"description": "Room not found"}},
)
def room_history(
    room_id: int,
    limit: int = Query(100, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> list[HistoryPoint]:
    """Return the latest `limit` analytics points, oldest first."""
    _room_or_404(db, room_id)
    return analytics_service.get_history(db, room_id, limit)


@router.get(
    "/dashboard/summary",
    response_model=DashboardSummary,
    summary="Building-level dashboard numbers",
    description=(
        "Counts of occupied / vacant / uncertain rooms, thermal anomalies (leak CANDIDATES) and ESTIMATED "
        "energy savings for today and this month. Rooms without fresh data are counted as uncertain. "
        "`includes_simulated_data` tells the UI when simulation mode contributed."
    ),
)
def dashboard_summary(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> DashboardSummary:
    """Return the dashboard summary."""
    return analytics_service.get_dashboard_summary(db, settings)


@router.get(
    "/energy/estimate",
    response_model=EnergyEstimateResponse,
    summary="What-if energy estimate calculator",
    description=(
        "estimated_energy_saved_kwh = hvac_power_kw x avoided_runtime_hours (per day). "
        "Monthly = x30, annual = x365. ALWAYS an estimate, never a measurement."
    ),
    responses={422: {"description": "Invalid inputs"}},
)
def energy_estimate(
    hvac_power_kw: float = Query(..., ge=0, le=1000, description="Rated HVAC power in kW"),
    avoided_runtime_hours: float = Query(..., ge=0, le=24, description="Avoided runtime per day, hours"),
) -> EnergyEstimateResponse:
    """Return an ESTIMATE of energy savings."""
    estimate = estimate_energy_savings(hvac_power_kw, avoided_runtime_hours)
    return EnergyEstimateResponse(
        hvac_power_kw=estimate.hvac_power_kw,
        avoided_runtime_hours_per_day=estimate.avoided_runtime_hours_per_day,
        estimated_energy_saved_kwh=estimate.estimated_energy_saved_kwh,
        estimated_daily_savings_kwh=estimate.estimated_daily_savings_kwh,
        estimated_monthly_savings_kwh=estimate.estimated_monthly_savings_kwh,
        estimated_annual_savings_kwh=estimate.estimated_annual_savings_kwh,
        assumptions=estimate.assumptions,
        disclaimer=estimate.disclaimer,
    )
