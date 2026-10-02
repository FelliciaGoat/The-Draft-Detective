"""Reading schemas: what devices send and what the API returns.

Validation philosophy: reject values that are physically impossible or typical sensor
error codes, so bad data never reaches the analytics engines.
"""

from datetime import datetime, timedelta
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.timeutils import ensure_utc, utcnow
from app.schemas.analytics import RoomUpdateMessage

# Room / window temperatures in degrees C. The range deliberately excludes the classic
# error codes of the popular DS18B20 sensor: -127 (sensor missing) and 85.0 (power-on default).
Celsius = Annotated[float, Field(ge=-40.0, le=80.0, allow_inf_nan=False)]
Unit = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
Percent = Annotated[float, Field(ge=0.0, le=100.0, allow_inf_nan=False)]
Ppm = Annotated[float, Field(ge=200.0, le=10000.0, allow_inf_nan=False)]
Kilowatt = Annotated[float, Field(ge=0.0, le=1000.0, allow_inf_nan=False)]

MAX_FUTURE_SKEW = timedelta(minutes=5)


class ReadingCreate(BaseModel):
    """Body of POST /readings (and of every MQTT message once the room id is known).

    Every measurement is optional; at least one must be present. Unknown fields are
    REJECTED on purpose: this is what stops a firmware bug from uploading raw audio.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "device_id": "ESP32-A101",
                    "room_id": 1,
                    "acoustic_level": 0.72,
                    "room_temperature": 24.8,
                    "edge_temperature": 29.6,
                    "humidity": 54.0,
                },
                {
                    "device_id": "ESP32-A101",
                    "room_id": 1,
                    "timestamp": "2026-09-29T10:30:00Z",
                    "acoustic_level": 0.05,
                    "room_temperature": 24.1,
                    "edge_temperature": 25.0,
                },
            ]
        },
    )

    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$")
    room_id: int = Field(ge=1)
    timestamp: datetime | None = Field(
        default=None,
        description="ISO-8601. Omit it to use the server time (recommended unless the ESP32 has a synced "
        "clock). Timestamps more than 5 minutes in the future are rejected.",
    )
    acoustic_level: Unit | None = Field(
        default=None,
        description="Normalised loudness 0..1 computed ON the device. Never send raw audio.",
    )
    room_temperature: Celsius | None = Field(default=None, description="Room air temperature, deg C")
    edge_temperature: Celsius | None = Field(
        default=None, description="Window / exterior-wall surface temperature, deg C"
    )
    humidity: Percent | None = Field(default=None, description="Relative humidity, %")
    co2_ppm: Ppm | None = Field(default=None, description="Optional CO2 concentration, ppm")
    hvac_on: bool | None = Field(default=None, description="Optional: is the HVAC currently running?")
    hvac_power_kw: Kilowatt | None = Field(
        default=None, description="Optional: rated/measured HVAC power, kW (used for the energy ESTIMATE)"
    )
    simulated: bool = Field(default=False, description="Label data that does not come from real sensors")

    @field_validator("timestamp")
    @classmethod
    def _normalise_timestamp(cls, value: datetime | None) -> datetime | None:
        """Convert to aware UTC (naive input is assumed to be UTC)."""
        return None if value is None else ensure_utc(value)

    @model_validator(mode="after")
    def _check_content(self) -> "ReadingCreate":
        """Require at least one measurement and reject timestamps far in the future."""
        measurements = (
            self.acoustic_level,
            self.room_temperature,
            self.edge_temperature,
            self.humidity,
            self.co2_ppm,
        )
        if all(value is None for value in measurements):
            raise ValueError("At least one sensor value must be provided")
        if self.timestamp is not None and not self.simulated:
            if self.timestamp > utcnow() + MAX_FUTURE_SKEW:
                raise ValueError("timestamp is more than 5 minutes in the future; check the device clock")
        return self


class ReadingRead(BaseModel):
    """A stored reading."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    device_id: str
    timestamp: datetime
    acoustic_level: float | None
    room_temperature: float | None
    edge_temperature: float | None
    humidity: float | None
    co2_ppm: float | None
    hvac_on: bool | None
    hvac_power_kw: float | None
    is_simulated: bool
    source: str
    scenario: str | None


class ReadingIngestResponse(BaseModel):
    """Returned after a reading was stored and analysed."""

    reading_id: int
    analytics_id: int
    simulated: bool
    result: RoomUpdateMessage
