"""Room model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timeutils import utcnow
from app.database.database import Base, UTCDateTime

if TYPE_CHECKING:
    from app.models.reading import RoomAnalytics, SensorReading
    from app.models.sensor import Sensor


class Room(Base):
    """A monitored room. Sensors, readings and analytics all hang off a room."""

    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    building: Mapped[str] = mapped_column(String(100), nullable=False, default="Main Building")
    floor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    climate_zone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Optional per-room HVAC rating used by the ENERGY ESTIMATE (falls back to DEFAULT_HVAC_POWER_KW).
    hvac_power_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    # passive_deletes=True: the database's ON DELETE CASCADE removes children efficiently.
    sensors: Mapped[list[Sensor]] = relationship(back_populates="room", passive_deletes=True)
    readings: Mapped[list[SensorReading]] = relationship(back_populates="room", passive_deletes=True)
    analytics: Mapped[list[RoomAnalytics]] = relationship(back_populates="room", passive_deletes=True)
