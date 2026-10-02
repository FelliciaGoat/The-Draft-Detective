"""Sensor schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import SensorStatus, SensorType


class SensorCreate(BaseModel):
    """Body of POST /sensors."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"room_id": 1, "sensor_type": "acoustic", "device_id": "ESP32-A101", "status": "active"}
            ]
        }
    )

    room_id: int = Field(ge=1)
    sensor_type: SensorType
    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$")
    status: SensorStatus = SensorStatus.ACTIVE


class SensorUpdate(BaseModel):
    """Body of PUT /sensors/{id}. Only the fields you send are changed."""

    room_id: int | None = Field(default=None, ge=1)
    sensor_type: SensorType | None = None
    device_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$")
    status: SensorStatus | None = None


class SensorRead(BaseModel):
    """A sensor as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    sensor_type: SensorType
    device_id: str
    status: SensorStatus
    last_seen: datetime | None
    created_at: datetime
