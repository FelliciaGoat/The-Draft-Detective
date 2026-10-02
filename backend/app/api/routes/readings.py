"""Reading endpoints: this is where the ESP32 sends its data over HTTP."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_ingestion, require_device_api_key
from app.core.enums import ReadingSource
from app.models.reading import SensorReading
from app.schemas.reading import ReadingCreate, ReadingIngestResponse, ReadingRead
from app.services.ingestion import IngestionService, RoomNotFoundError

router = APIRouter(prefix="/readings", tags=["Readings"])


@router.post(
    "",
    response_model=ReadingIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send a sensor reading (ESP32)",
    description=(
        "Stores one reading and runs the full pipeline: occupancy -> thermal anomaly -> sensor fusion -> "
        "energy estimate. Requires the `X-API-Key` header. All measurements are optional, but at least one "
        "is needed. Never send raw audio: only the normalised `acoustic_level` (0..1)."
    ),
    responses={
        401: {"description": "Missing or wrong X-API-Key"},
        404: {"description": "Unknown room"},
        422: {"description": "Invalid sensor values"},
    },
)
def create_reading(
    payload: ReadingCreate,
    db: Session = Depends(get_db),
    ingestion: IngestionService = Depends(get_ingestion),
    _: None = Depends(require_device_api_key),
) -> ReadingIngestResponse:
    """Receive, validate, store and analyse one reading."""
    try:
        result = ingestion.ingest(db, payload, source=ReadingSource.REST)
    except RoomNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return ReadingIngestResponse(
        reading_id=result.reading.id,
        analytics_id=result.analytics.id,
        simulated=payload.simulated,
        result=result.message,
    )


@router.get("", response_model=list[ReadingRead], summary="List stored readings (newest first)")
def list_readings(
    room_id: int | None = Query(None),
    device_id: str | None = Query(None),
    include_simulated: bool = Query(True),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[SensorReading]:
    """Return stored readings, newest first. Simulated readings are labelled `is_simulated`."""
    stmt = select(SensorReading).order_by(SensorReading.id.desc()).limit(limit)
    if room_id is not None:
        stmt = stmt.where(SensorReading.room_id == room_id)
    if device_id is not None:
        stmt = stmt.where(SensorReading.device_id == device_id)
    if not include_simulated:
        stmt = stmt.where(SensorReading.is_simulated.is_(False))
    return list(db.scalars(stmt).all())
