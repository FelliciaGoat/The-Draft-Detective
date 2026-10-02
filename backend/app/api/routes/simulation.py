"""Simulation endpoints (demo without hardware). All generated data is labelled SIMULATED."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_settings, get_simulation_manager, require_device_api_key
from app.core.config import Settings
from app.schemas.simulation import ScenarioInfo, SimulationRequest, SimulationResponse
from app.services.ingestion import RoomNotFoundError
from app.services.simulation import SCENARIOS, SimulationError, SimulationManager


def _require_enabled(settings: Settings = Depends(get_settings)) -> None:
    """Simulation can be switched off in production with SIMULATION_ENABLED=false."""
    if not settings.simulation_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Simulation mode is disabled")


router = APIRouter(prefix="/simulation", tags=["Simulation"], dependencies=[Depends(_require_enabled)])


@router.get("/scenarios", response_model=list[ScenarioInfo], summary="List simulation scenarios")
def list_scenarios() -> list[ScenarioInfo]:
    """Describe the available scenarios and what each one should demonstrate."""
    return list(SCENARIOS.values())


@router.post(
    "/generate",
    response_model=SimulationResponse,
    summary="Generate SIMULATED sensor readings for a room",
    description=(
        "Runs realistic fake readings through the REAL analysis pipeline. Requires `X-API-Key`.\n\n"
        "* `realtime=false` (default): everything is computed immediately; the response lists the "
        "state `transitions` (e.g. occupied -> vacant/energy_saving_mode -> inspect_envelope).\n"
        "* `realtime=true`: readings stream in the background (HTTP 202) so a dashboard connected to "
        "`/ws/rooms/{room_id}` can watch the transitions live. Use `speed` to accelerate time.\n\n"
        "Every row, response and WebSocket message is marked `simulated: true`."
    ),
    responses={
        202: {"description": "Realtime simulation started in the background"},
        401: {"description": "Missing or wrong X-API-Key"},
        404: {"description": "Unknown room"},
        422: {"description": "Invalid parameters"},
    },
    dependencies=[Depends(require_device_api_key)],
)
async def generate(
    request: SimulationRequest,
    response: Response,
    manager: SimulationManager = Depends(get_simulation_manager),
) -> SimulationResponse:
    """Create a simulation run (batch or realtime)."""
    try:
        run = await run_in_threadpool(manager.prepare, request)
    except RoomNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except SimulationError as exc:
        raise HTTPException(422, str(exc))  # 422 = invalid request (constant name differs across Starlette versions)

    if request.realtime:
        manager.start_realtime(run)
        response.status_code = status.HTTP_202_ACCEPTED
    else:
        await run_in_threadpool(manager.run_batch, run)
    return manager.to_response(run)


@router.get(
    "/runs/{run_id}",
    response_model=SimulationResponse,
    summary="Status of a simulation run",
    responses={404: {"description": "Unknown run"}},
)
def get_run(run_id: str, manager: SimulationManager = Depends(get_simulation_manager)) -> SimulationResponse:
    """Progress and transitions of a (possibly still running) simulation."""
    run = manager.get(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Simulation run '{run_id}' not found")
    return manager.to_response(run)


@router.post(
    "/runs/{run_id}/stop",
    response_model=SimulationResponse,
    summary="Stop a realtime simulation",
    dependencies=[Depends(require_device_api_key)],
    responses={404: {"description": "Unknown run"}},
)
def stop_run(run_id: str, manager: SimulationManager = Depends(get_simulation_manager)) -> SimulationResponse:
    """Stop a running realtime simulation."""
    if not manager.stop(run_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Simulation run '{run_id}' not found")
    return manager.to_response(manager.get(run_id))  # type: ignore[arg-type]
