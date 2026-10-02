"""Sensor model (a registered physical or virtual sensor attached to a room)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SensorStatus
from app.core.timeutils import utcnow
from app.database.database import Base, UTCDateTime

if TYPE_CHECKING:
    from app.models.room import Room


class Sensor(Base):
    """One sensor of one type. A single ESP32 (`device_id`) usually owns several sensors."""

    __tablename__ = "sensors"
    __table_args__ = (
        UniqueConstraint("device_id", "sensor_type", name="uq_sensor_device_type"),
        Index("ix_sensors_room_type", "room_id", "sensor_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sensor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=SensorStatus.ACTIVE.value)
    last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, default=utcnow)

    room: Mapped[Room] = relationship(back_populates="sensors")
