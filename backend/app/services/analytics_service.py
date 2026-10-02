"""Read-side analytics: build API responses from stored `RoomAnalytics` rows.

Also contains the freshness rule: if the newest data is older than DATA_STALE_SECONDS the
room is reported as `uncertain` / `insufficient_data` instead of repeating an old answer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.core.enums import RecommendedAction, RoomState
from app.core.timeutils import local_day_start, local_month_start, utcnow
from app.models.reading import RoomAnalytics
from app.models.room import Room
from app.schemas.analytics import (
    DashboardSummary,
    EnergyOut,
    HistoryPoint,
    OccupancyOut,
    RecommendationOut,
    RoomAnalyticsResponse,
    RoomUpdateMessage,
    TemperatureOut,
    ThermalAnomalyBlock,
    ThermalOut,
)


def data_age_seconds(timestamp: datetime, now: datetime) -> float:
    """Age of a data point in seconds (never negative, so accelerated simulations count as fresh)."""
    return max(0.0, (now - timestamp).total_seconds())


def get_latest_analytics(db: Session, room_id: int) -> RoomAnalytics | None:
    """Most recently processed analytics row of a room (with its reading loaded)."""
    stmt = (
        select(RoomAnalytics)
        .options(joinedload(RoomAnalytics.reading))
        .where(RoomAnalytics.room_id == room_id)
        .order_by(RoomAnalytics.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def build_update_message(row: RoomAnalytics) -> RoomUpdateMessage:
    """Convert a stored analytics row to the message used by REST responses and the WebSocket."""
    reading = row.reading
    return RoomUpdateMessage(
        room_id=row.room_id,
        timestamp=row.timestamp,
        simulated=row.is_simulated,
        room_state=RoomState(row.room_state),
        temperature=TemperatureOut(
            room=reading.room_temperature, edge=reading.edge_temperature, delta=row.delta_temperature
        ),
        occupancy=OccupancyOut(
            state=RoomState(row.occupancy_state) if row.occupancy_state else RoomState.UNCERTAIN,
            confidence=row.occupancy_confidence,
            activity_score=row.activity_score,
        ),
        thermal=ThermalOut(
            delta_temperature=row.delta_temperature,
            thermal_anomaly_score=row.thermal_anomaly_score,
            leak_candidate=row.leak_candidate,
            explanation=row.thermal_explanation or "",
        ),
        recommendation=RecommendationOut(
            action=RecommendedAction(row.recommended_action), reason=row.recommendation_reason
        ),
    )


def _energy_totals(
    db: Session, start: datetime, room_id: int | None = None
) -> tuple[float, float, bool]:
    """Sum ESTIMATED kWh and avoided runtime (hours) since `start`; also report if simulated rows contributed."""
    conditions = [RoomAnalytics.timestamp >= start]
    if room_id is not None:
        conditions.append(RoomAnalytics.room_id == room_id)
    kwh, seconds = db.execute(
        select(
            func.coalesce(func.sum(RoomAnalytics.estimated_energy_kwh), 0.0),
            func.coalesce(func.sum(RoomAnalytics.avoided_runtime_seconds), 0.0),
        ).where(*conditions)
    ).one()
    has_simulated = bool(
        db.scalar(select(exists().where(*conditions, RoomAnalytics.is_simulated.is_(True))))
    )
    return float(kwh), float(seconds) / 3600.0, has_simulated


def get_room_analytics(
    db: Session, room: Room, settings: Settings, now: datetime | None = None
) -> RoomAnalyticsResponse:
    """Build the GET /rooms/{id}/analytics response, handling 'no data yet' and 'stale data'."""
    now = now or utcnow()
    day_start = local_day_start(now, settings.dashboard_utc_offset_minutes)
    kwh_today, hours_today, _ = _energy_totals(db, day_start, room.id)
    energy = EnergyOut(
        estimated_savings_kwh_today=round(kwh_today, 3), avoided_runtime_hours_today=round(hours_today, 3)
    )

    row = get_latest_analytics(db, room.id)
    if row is None:
        return RoomAnalyticsResponse(
            room_id=room.id,
            room_name=room.name,
            has_data=False,
            stale=False,
            simulated=False,
            last_updated=None,
            data_age_seconds=None,
            current_state=RoomState.UNCERTAIN,
            occupancy_confidence=None,
            temperature=TemperatureOut(),
            thermal_anomaly=ThermalAnomalyBlock(),
            recommendation=RecommendationOut(
                action=RecommendedAction.INSUFFICIENT_DATA, reason="No sensor data has been received yet."
            ),
            energy=energy,
        )

    age = data_age_seconds(row.timestamp, now)
    stale = age > settings.data_stale_seconds
    message = build_update_message(row)

    if stale:
        return RoomAnalyticsResponse(
            room_id=room.id,
            room_name=room.name,
            has_data=True,
            stale=True,
            simulated=row.is_simulated,
            last_updated=row.timestamp,
            data_age_seconds=round(age, 1),
            current_state=RoomState.UNCERTAIN,
            occupancy_confidence=None,
            temperature=message.temperature,
            thermal_anomaly=ThermalAnomalyBlock(),
            recommendation=RecommendationOut(
                action=RecommendedAction.INSUFFICIENT_DATA,
                reason=f"No fresh sensor data for {age:.0f} s (limit {settings.data_stale_seconds:.0f} s).",
            ),
            energy=energy,
        )

    return RoomAnalyticsResponse(
        room_id=room.id,
        room_name=room.name,
        has_data=True,
        stale=False,
        simulated=row.is_simulated,
        last_updated=row.timestamp,
        data_age_seconds=round(age, 1),
        current_state=message.room_state,
        occupancy_confidence=row.occupancy_confidence,
        temperature=message.temperature,
        thermal_anomaly=ThermalAnomalyBlock(
            score=row.thermal_anomaly_score,
            leak_candidate=row.leak_candidate,
            explanation=row.thermal_explanation or "",
        ),
        recommendation=message.recommendation,
        energy=energy,
    )


def get_history(db: Session, room_id: int, limit: int = 100) -> list[HistoryPoint]:
    """Latest `limit` analytics points of a room, oldest first (ready for a chart)."""
    stmt = (
        select(RoomAnalytics)
        .options(joinedload(RoomAnalytics.reading))
        .where(RoomAnalytics.room_id == room_id)
        .order_by(RoomAnalytics.id.desc())
        .limit(limit)
    )
    rows = list(db.scalars(stmt).all())
    rows.reverse()
    return [
        HistoryPoint(
            timestamp=r.timestamp,
            simulated=r.is_simulated,
            room_state=RoomState(r.room_state),
            occupancy_confidence=r.occupancy_confidence,
            activity_score=r.activity_score,
            room_temperature=r.reading.room_temperature,
            edge_temperature=r.reading.edge_temperature,
            delta_temperature=r.delta_temperature,
            thermal_anomaly_score=r.thermal_anomaly_score,
            leak_candidate=r.leak_candidate,
            recommended_action=RecommendedAction(r.recommended_action),
        )
        for r in rows
    ]


def get_dashboard_summary(db: Session, settings: Settings, now: datetime | None = None) -> DashboardSummary:
    """Building-level numbers for the dashboard. Rooms without fresh data count as 'uncertain'."""
    now = now or utcnow()
    total_rooms = db.scalar(select(func.count()).select_from(Room)) or 0

    latest_ids = select(func.max(RoomAnalytics.id)).group_by(RoomAnalytics.room_id)
    latest_rows = db.scalars(select(RoomAnalytics).where(RoomAnalytics.id.in_(latest_ids))).all()

    occupied = vacant = anomalies = saving = 0
    fresh_rooms = 0
    fresh_simulated = False
    for row in latest_rows:
        if data_age_seconds(row.timestamp, now) > settings.data_stale_seconds:
            continue
        fresh_rooms += 1
        fresh_simulated = fresh_simulated or row.is_simulated
        occupied += row.room_state == RoomState.OCCUPIED.value
        vacant += row.room_state == RoomState.VACANT.value
        anomalies += bool(row.leak_candidate)
        saving += row.recommended_action == RecommendedAction.ENERGY_SAVING_MODE.value

    offset = settings.dashboard_utc_offset_minutes
    kwh_today, _, sim_today = _energy_totals(db, local_day_start(now, offset))
    kwh_month, _, sim_month = _energy_totals(db, local_month_start(now, offset))

    return DashboardSummary(
        total_rooms=total_rooms,
        occupied_rooms=occupied,
        vacant_rooms=vacant,
        uncertain_rooms=total_rooms - occupied - vacant,
        thermal_anomalies=anomalies,
        rooms_recommended_for_energy_saving=saving,
        estimated_energy_saved_today=round(kwh_today, 3),
        estimated_energy_saved_this_month=round(kwh_month, 3),
        includes_simulated_data=fresh_simulated or sim_today or sim_month,
        rooms_without_fresh_data=total_rooms - fresh_rooms,
        generated_at=now,
    )
