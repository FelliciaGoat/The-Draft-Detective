"""Room endpoints (CRUD). Routes only translate HTTP <-> database; there is no analytics logic here."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_ingestion
from app.models.room import Room
from app.schemas.room import RoomCreate, RoomRead, RoomUpdate
from app.services.ingestion import IngestionService

router = APIRouter(prefix="/rooms", tags=["Rooms"])


def _get_room_or_404(db: Session, room_id: int) -> Room:
    """Load a room or raise HTTP 404."""
    room = db.get(Room, room_id)
    if room is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Room {room_id} not found")
    return room


@router.get("", response_model=list[RoomRead], summary="List rooms")
def list_rooms(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Room]:
    """Return all rooms ordered by id."""
    return list(db.scalars(select(Room).order_by(Room.id).offset(skip).limit(limit)).all())


@router.get(
    "/{room_id}",
    response_model=RoomRead,
    summary="Get one room",
    responses={404: {"description": "Room not found"}},
)
def get_room(room_id: int, db: Session = Depends(get_db)) -> Room:
    """Return a single room."""
    return _get_room_or_404(db, room_id)


@router.post(
    "",
    response_model=RoomRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a room",
    responses={409: {"description": "A room with this name already exists"}},
)
def create_room(payload: RoomCreate, db: Session = Depends(get_db)) -> Room:
    """Create a room. The name must be unique."""
    room = Room(**payload.model_dump())
    db.add(room)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"A room named '{payload.name}' already exists")
    return room


@router.put(
    "/{room_id}",
    response_model=RoomRead,
    summary="Update a room",
    responses={404: {"description": "Room not found"}, 409: {"description": "Name already used"}},
)
def update_room(room_id: int, payload: RoomUpdate, db: Session = Depends(get_db)) -> Room:
    """Update the fields you send (fields you omit are left unchanged)."""
    room = _get_room_or_404(db, room_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None and field in {"name", "building", "floor"}:
            continue  # these columns are not nullable
        setattr(room, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A room with this name already exists")
    return room


@router.delete(
    "/{room_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a room and all of its data",
    responses={404: {"description": "Room not found"}},
)
def delete_room(
    room_id: int,
    db: Session = Depends(get_db),
    ingestion: IngestionService = Depends(get_ingestion),
) -> Response:
    """Delete a room together with its sensors, readings and analytics."""
    room = _get_room_or_404(db, room_id)
    db.delete(room)
    db.commit()
    ingestion.registry.reset(room_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
