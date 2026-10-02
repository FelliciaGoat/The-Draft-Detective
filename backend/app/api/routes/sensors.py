"""Sensor endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.enums import SensorType
from app.models.room import Room
from app.models.sensor import Sensor
from app.schemas.sensor import SensorCreate, SensorRead, SensorUpdate

router = APIRouter(prefix="/sensors", tags=["Sensors"])


def _get_sensor_or_404(db: Session, sensor_id: int) -> Sensor:
    """Load a sensor or raise HTTP 404."""
    sensor = db.get(Sensor, sensor_id)
    if sensor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sensor {sensor_id} not found")
    return sensor


def _require_room(db: Session, room_id: int) -> None:
    """Raise HTTP 404 if the room does not exist."""
    if db.get(Room, room_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Room {room_id} not found")


@router.get("", response_model=list[SensorRead], summary="List sensors")
def list_sensors(
    room_id: int | None = Query(None, description="Only sensors of this room"),
    sensor_type: SensorType | None = Query(None),
    db: Session = Depends(get_db),
) -> list[Sensor]:
    """Return sensors, optionally filtered by room and/or type."""
    stmt = select(Sensor).order_by(Sensor.id)
    if room_id is not None:
        stmt = stmt.where(Sensor.room_id == room_id)
    if sensor_type is not None:
        stmt = stmt.where(Sensor.sensor_type == sensor_type.value)
    return list(db.scalars(stmt).all())


@router.get(
    "/{sensor_id}",
    response_model=SensorRead,
    summary="Get one sensor",
    responses={404: {"description": "Sensor not found"}},
)
def get_sensor(sensor_id: int, db: Session = Depends(get_db)) -> Sensor:
    """Return a single sensor."""
    return _get_sensor_or_404(db, sensor_id)


@router.post(
    "",
    response_model=SensorRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a sensor",
    responses={
        404: {"description": "Room not found"},
        409: {"description": "This device already has a sensor of that type"},
    },
)
def create_sensor(payload: SensorCreate, db: Session = Depends(get_db)) -> Sensor:
    """Register a sensor for a room. One (device_id, sensor_type) pair can exist only once."""
    _require_room(db, payload.room_id)
    sensor = Sensor(
        room_id=payload.room_id,
        sensor_type=payload.sensor_type.value,
        device_id=payload.device_id,
        status=payload.status.value,
    )
    db.add(sensor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Device '{payload.device_id}' already has a '{payload.sensor_type.value}' sensor",
        )
    return sensor


@router.put(
    "/{sensor_id}",
    response_model=SensorRead,
    summary="Update a sensor",
    responses={404: {"description": "Sensor or room not found"}, 409: {"description": "Duplicate sensor"}},
)
def update_sensor(sensor_id: int, payload: SensorUpdate, db: Session = Depends(get_db)) -> Sensor:
    """Update the fields you send (fields you omit are left unchanged)."""
    sensor = _get_sensor_or_404(db, sensor_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if "room_id" in changes:
        _require_room(db, changes["room_id"])
    for field, value in changes.items():
        setattr(sensor, field, value.value if hasattr(value, "value") else value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This device already has a sensor of that type")
    return sensor
