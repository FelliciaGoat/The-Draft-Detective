"""Health check."""

import logging

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.analytics import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description=(
        "`database` is checked with a real query. `mqtt` is `connected`, `disconnected` or `disabled`. "
        "Status is `healthy` when everything enabled works, `degraded` if MQTT is enabled but not "
        "connected, and `unhealthy` (HTTP 503) if the database is down."
    ),
    responses={503: {"description": "Database unavailable"}},
)
def health(request: Request, response: Response, db: Session = Depends(get_db)) -> HealthResponse:
    """Report the state of the database and the MQTT connection."""
    try:
        db.execute(text("SELECT 1"))
        database = "connected"
    except SQLAlchemyError:
        logger.exception("Health check: database unavailable")
        database = "disconnected"

    mqtt_status = request.app.state.mqtt.status
    if database == "disconnected":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        overall = "unhealthy"
    elif mqtt_status == "disconnected":
        overall = "degraded"
    else:
        overall = "healthy"
    return HealthResponse(status=overall, database=database, mqtt=mqtt_status)
