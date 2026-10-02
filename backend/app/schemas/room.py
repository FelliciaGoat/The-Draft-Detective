"""Room schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RoomBase(BaseModel):
    """Fields shared by create and read."""

    name: str = Field(min_length=1, max_length=100, description="Unique room name")
    building: str = Field(default="Main Building", min_length=1, max_length=100)
    floor: int = Field(default=0, ge=-5, le=200)
    zone: str | None = Field(default=None, max_length=100)
    climate_zone: str | None = Field(default=None, max_length=50, description="e.g. Composite, Hot & Dry")
    hvac_power_kw: float | None = Field(
        default=None,
        gt=0,
        le=1000,
        description="Optional rated HVAC power (kW), used ONLY for the energy ESTIMATE",
    )


class RoomCreate(RoomBase):
    """Body of POST /rooms."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Room A-101",
                    "building": "Main Building",
                    "floor": 1,
                    "zone": "North Wing",
                    "climate_zone": "Composite",
                }
            ]
        }
    )


class RoomUpdate(BaseModel):
    """Body of PUT /rooms/{id}. Only the fields you send are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    building: str | None = Field(default=None, min_length=1, max_length=100)
    floor: int | None = Field(default=None, ge=-5, le=200)
    zone: str | None = Field(default=None, max_length=100)
    climate_zone: str | None = Field(default=None, max_length=50)
    hvac_power_kw: float | None = Field(default=None, gt=0, le=1000)


class RoomRead(RoomBase):
    """A room as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
