"""Historical data models: raw-ish sensor readings and the analytics computed from them.

PRIVACY BY DESIGN
-----------------
Raw audio is NEVER stored (and never even accepted by the API). The ESP32 must turn the
microphone signal into a single normalised loudness number (`acoustic_level`, 0..1) on the
device. Only that derived feature, plus derived scores (`activity_score`,
`occupancy_confidence`), is kept. A loudness number cannot be turned back into speech.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timeutils import utcnow
from app.database.database import Base, UTCDateTime

if TYPE_CHECKING:
    from app.models.room import Room


class SensorReading(Base):
    """One message from a device. All measurement columns are optional (partial payloads are OK)."""

    __tablename__ = "sensor_readings"
    __table_args__ = (
        Index("ix_readings_room_timestamp", "room_id", "timestamp"),
        Index("ix_readings_device_timestamp", "device_id", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)

    # Derived acoustic feature only (0..1). No raw audio, ever.
    acoustic_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    room_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)  # deg C
    edge_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)  # deg C (window / exterior wall)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)  # % RH
    co2_ppm: Mapped[float | None] = mapped_column(Float, nullable=True)
    hvac_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hvac_power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Provenance: simulated data is always labelled so it can never pass as real.
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="rest")
    scenario: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    room: Mapped[Room] = relationship(back_populates="readings")


class RoomAnalytics(Base):
    """Result of running the whole analysis pipeline for one reading."""

    __tablename__ = "room_analytics"
    __table_args__ = (Index("ix_analytics_room_timestamp", "room_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reading_id: Mapped[int] = mapped_column(
        ForeignKey("sensor_readings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Occupancy engine output
    occupancy_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    occupancy_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # P(occupied), 0..1
    activity_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # smoothed rolling loudness

    # Thermal engine output
    delta_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    thermal_anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    leak_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    thermal_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Sensor fusion output
    room_state: Mapped[str] = mapped_column(String(16), nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    recommendation_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    hvac_on: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # ESTIMATED energy opportunity attributed to the time since the previous reading.
    avoided_runtime_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    estimated_energy_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    room: Mapped[Room] = relationship(back_populates="analytics")
    reading: Mapped[SensorReading] = relationship()
