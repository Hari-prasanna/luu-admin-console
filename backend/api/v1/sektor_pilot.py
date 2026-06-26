"""
FastAPI routes for Sektor Pilot control and monitoring.

Exposes endpoints for starting, pausing, stopping, and checking sector automation workers.
Per Clean Code Chapter 3: DRY helpers eliminate repeated try/except patterns.
Per Clean Code Chapter 7: specific typed exception handling — no bare except blocks.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException

from backend.config import Constants
from backend.exceptions import (
    ConfigurationError,
    DockerExecutionError,
    GoogleSheetsAuthenticationError,
    GoogleSheetsDataError,
    GoogleSheetsNetworkError,
)
from backend.models import (
    SectorWorkerStartRequest,
    SectorWorkerPauseRequest,
    SectorWorkerStopRequest,
    WorkerActionResponse,
    WorkerStatusResponse,
    SectorInfo,
    HealthCheckResponse,
)
from backend.automation.sektor_pilot.executor import ContainerManager, ContainerState
from backend.automation.sektor_pilot.sector_config import get_sector_config, list_sectors
from backend.repositories import AuditRepository
from backend.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sektor-pilot", tags=["sektor-pilot"])

# Module-level singletons (initialized once on import)
_container_manager = ContainerManager()


# ─── Audit Logging Helper ───


async def _log_worker_action(
    user_identifier: str,
    event_type: str,
    sector_id: str,
    success: bool,
    message: str = "",
) -> None:
    """
    Log worker action to database audit log (non-blocking).

    Args:
        user_identifier: User who initiated the action
        event_type: Action type (START_WORKER, PAUSE_WORKER, STOP_WORKER)
        sector_id: Sector that was actioned
        success: Whether the action succeeded
        message: Optional detail message
    """
    try:
        async with AsyncSessionLocal() as session:
            audit_repo = AuditRepository(session)
            await audit_repo.create({
                "actor": user_identifier,
                "event_type": event_type,
                "status": "success" if success else "failure",
                "description": message or f"{event_type.lower()} for sector {sector_id}",
                "metadata": {"sector_id": sector_id},
            })
            await session.commit()
    except Exception as audit_error:
        logger.warning("audit_logging_failed", extra={"sector_id": sector_id, "error": str(audit_error)})


# ─── Shared Action Dispatch Helper ───


def _log_key_for(prefix: str, operation_description: str) -> str:
    """Build a structured log key from a prefix and operation description."""
    return f"{prefix}_{operation_description.replace(' ', '_')}"


def _raise_for_configuration_error(
    caught_exception: Exception,
    sector_id: str,
    operation_description: str,
) -> None:
    """Log and raise HTTPException 400 for unknown sector configuration errors."""
    logger.error(_log_key_for("configuration_error", operation_description), extra={"sector_id": sector_id, "error": str(caught_exception)})
    raise HTTPException(status_code=400, detail=f"Unknown sector: {sector_id}") from caught_exception


def _raise_for_docker_error(
    caught_exception: DockerExecutionError,
    sector_id: str,
    operation_description: str,
) -> None:
    """Log and raise HTTPException 500 for Docker execution failures."""
    logger.error(_log_key_for("docker_error", operation_description), extra={"sector_id": sector_id, "error": str(caught_exception)})
    raise HTTPException(status_code=500, detail=Constants.ERROR_DOCKER_EXECUTION_FAILED) from caught_exception


def _raise_http_exception_for_sector_error(
    caught_exception: Exception,
    sector_id: str,
    operation_description: str,
) -> None:
    """
    Map sector-level exceptions to appropriate HTTPException responses.

    Args:
        caught_exception: Exception caught in endpoint handler
        sector_id: Sector that was being actioned
        operation_description: Short label for log keys (e.g., "starting worker")

    Raises:
        HTTPException: 400 for unknown sector, 500 for Docker/unexpected errors
    """
    if isinstance(caught_exception, (ConfigurationError, ValueError)):
        _raise_for_configuration_error(caught_exception, sector_id, operation_description)

    if isinstance(caught_exception, DockerExecutionError):
        _raise_for_docker_error(caught_exception, sector_id, operation_description)

    logger.exception(_log_key_for("unexpected_error", operation_description), extra={"sector_id": sector_id}, exc_info=caught_exception)
    raise HTTPException(status_code=500, detail=f"Failed {operation_description}") from caught_exception


async def _execute_worker_action(
    sector_id: str,
    user_identifier: str,
    event_type: str,
    container_operation_callable: callable,
    operation_description: str,
) -> WorkerActionResponse:
    """
    Execute a container lifecycle action with audit logging and error handling.

    Args:
        sector_id: Sector to action
        user_identifier: User initiating the action
        event_type: Action type for audit log
        container_operation_callable: Zero-arg callable that performs the container action
        operation_description: Description of operation for error logging

    Returns:
        WorkerActionResponse with success, state, message, sector_id

    Raises:
        HTTPException: On configuration or Docker errors
    """
    try:
        get_sector_config(sector_id)
        container_action_result = container_operation_callable()

        await _log_worker_action(
            user_identifier, event_type, sector_id,
            container_action_result["success"],
            container_action_result.get("message", "")
        )

        return WorkerActionResponse(
            success=container_action_result["success"],
            state=container_action_result["state"],
            message=container_action_result["message"],
            sector_id=sector_id,
        )

    except Exception as sector_action_failure:
        await _log_worker_action(
            user_identifier, event_type, sector_id, False,
            f"Failed: {str(sector_action_failure)}"
        )
        _raise_http_exception_for_sector_error(
            sector_action_failure, sector_id, operation_description
        )


# ─── Routes ───


@router.get("/sectors", response_model=List[SectorInfo])
async def list_available_sectors() -> List[SectorInfo]:
    """List all configured sector instances."""
    try:
        available_sectors = list_sectors()
        return [SectorInfo(**sector_dict) for sector_dict in available_sectors]
    except ConfigurationError as config_failure:
        logger.error(
            "configuration_error_listing_sectors",
            extra={"error": str(config_failure)},
        )
        raise HTTPException(
            status_code=500,
            detail=Constants.ERROR_CONFIGURATION_INVALID,
        ) from config_failure


@router.post("/start", response_model=WorkerActionResponse)
async def start_worker(request: SectorWorkerStartRequest) -> WorkerActionResponse:
    """
    Start a sector automation worker in a Docker container.

    Args:
        request: Start request with sector_id, user, oracle_env_path

    Returns:
        WorkerActionResponse with success, state, message, sector_id

    Raises:
        HTTPException: 400 for unknown sector, 500 for Docker/system errors
    """
    sector_config = get_sector_config(request.sector_id)
    if not sector_config.get("spreadsheet_id"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Spreadsheet ID is not configured for sector: {request.sector_id}. "
                f"Set environment variable for this sector before starting worker."
            ),
        )

    return await _execute_worker_action(
        sector_id=request.sector_id,
        user_identifier=request.user,
        event_type="START_WORKER",
        container_operation_callable=lambda: _container_manager.start(
            request.sector_id, request.oracle_env_path
        ),
        operation_description="starting worker",
    )


@router.post("/pause", response_model=WorkerActionResponse)
async def pause_worker(request: SectorWorkerPauseRequest) -> WorkerActionResponse:
    """
    Pause a running sector worker (suspends polling, keeps container alive).

    Args:
        request: Pause request with sector_id, user

    Returns:
        WorkerActionResponse with success, state, message, sector_id

    Raises:
        HTTPException: 400 for unknown sector, 500 for Docker/system errors
    """
    return await _execute_worker_action(
        sector_id=request.sector_id,
        user_identifier=request.user,
        event_type="PAUSE_WORKER",
        container_operation_callable=lambda: _container_manager.pause(request.sector_id),
        operation_description="pausing worker",
    )


@router.post("/stop", response_model=WorkerActionResponse)
async def stop_worker(request: SectorWorkerStopRequest) -> WorkerActionResponse:
    """
    Stop and remove a sector automation worker container.

    Args:
        request: Stop request with sector_id, user

    Returns:
        WorkerActionResponse with success, state, message, sector_id

    Raises:
        HTTPException: 400 for unknown sector, 500 for Docker/system errors
    """
    return await _execute_worker_action(
        sector_id=request.sector_id,
        user_identifier=request.user,
        event_type="STOP_WORKER",
        container_operation_callable=lambda: _container_manager.stop(request.sector_id),
        operation_description="stopping worker",
    )


@router.get("/status/{sector_id}", response_model=WorkerStatusResponse)
async def get_sector_status(sector_id: str) -> WorkerStatusResponse:
    """
    Get current status of a specific sector worker.

    Args:
        sector_id: Sector identifier

    Returns:
        WorkerStatusResponse with state and container metadata

    Raises:
        HTTPException: 400 for unknown sector, 500 for system errors
    """
    try:
        get_sector_config(sector_id)
        sector_status_dict = _container_manager.get_status(sector_id)
        return WorkerStatusResponse(**sector_status_dict)

    except (ConfigurationError, ValueError) as config_failure:
        logger.error(
            "configuration_error_getting_status",
            extra={"sector_id": sector_id, "error": str(config_failure)},
        )
        raise HTTPException(
            status_code=400,
            detail=f"Unknown sector: {sector_id}",
        ) from config_failure
    except DockerExecutionError as docker_failure:
        logger.error(
            "docker_error_getting_status",
            extra={"sector_id": sector_id, "error": str(docker_failure)},
        )
        raise HTTPException(
            status_code=500,
            detail=Constants.ERROR_DOCKER_EXECUTION_FAILED,
        ) from docker_failure


@router.get("/status", response_model=List[WorkerStatusResponse])
async def get_all_sector_statuses() -> List[WorkerStatusResponse]:
    """
    Get status of all sector workers.

    Returns:
        List of WorkerStatusResponse objects for all sector instances

    Raises:
        HTTPException: 500 for system errors
    """
    try:
        all_sector_statuses = _container_manager.get_all_status()
        return [WorkerStatusResponse(**status_dict) for status_dict in all_sector_statuses]
    except DockerExecutionError as docker_failure:
        logger.exception(
            "docker_error_getting_all_statuses",
            exc_info=docker_failure,
        )
        raise HTTPException(
            status_code=500,
            detail=Constants.ERROR_DOCKER_EXECUTION_FAILED,
        ) from docker_failure


@router.get("/health", response_model=HealthCheckResponse)
async def health_check() -> HealthCheckResponse:
    """Health check endpoint for Sektor Pilot service."""
    return HealthCheckResponse(status="ok", service="sektor-pilot")
