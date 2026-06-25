"""
FastAPI routes for Sektor Pilot control and monitoring.

Exposes endpoints for starting, pausing, stopping, and checking sector automation workers.
Per Clean Code Chapter 3: DRY helpers eliminate repeated try/except patterns.
Per Clean Code Chapter 7: specific typed exception handling — no bare except blocks.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.config import Constants
from backend.exceptions import (
    ConfigurationError,
    DockerExecutionError,
    GoogleSheetsAuthenticationError,
    GoogleSheetsNetworkError,
)
from backend.automation.sektor_pilot.executor import ContainerManager, ContainerState
from backend.automation.sektor_pilot.sector_config import get_sector_config, list_sectors
from backend.automation.sektor_pilot.repository import (
    AuditLedger,
    AuditActionType,
    AuditOperationStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sektor-pilot", tags=["sektor-pilot"])

# Module-level singletons (initialized once on import)
_container_manager = ContainerManager()
_audit_ledger = AuditLedger()


# ─── Request / Response Models ───


class SectorWorkerStartRequest(BaseModel):
    """Request body for starting a sector automation worker."""

    sector_id: str = Field(
        ..., description="Sector identifier (bsf_halle1, bsf_bestand, akl_bestand)"
    )
    user: str = Field(default="system", description="User identifier for audit logging")
    oracle_env_path: str = Field(default="oracle.env", description="Path to oracle.env")


class SectorWorkerPauseRequest(BaseModel):
    """Request body for pausing a sector automation worker."""

    sector_id: str = Field(..., description="Sector identifier")
    user: str = Field(default="system", description="User identifier for audit logging")


class SectorWorkerStopRequest(BaseModel):
    """Request body for stopping a sector automation worker."""

    sector_id: str = Field(..., description="Sector identifier")
    user: str = Field(default="system", description="User identifier for audit logging")


class WorkerActionResponse(BaseModel):
    """Response from action endpoints (start / pause / stop)."""

    success: bool = Field(..., description="Whether the action succeeded")
    state: str = Field(..., description="Container state after the action")
    message: str = Field(..., description="Human-readable action result message")
    sector_id: str = Field(..., description="Sector that was actioned")


class WorkerStatusResponse(BaseModel):
    """Response from status endpoints."""

    sector_id: str
    container_name: str
    state: str
    container_id: str | None
    started_at: float | None
    paused_at: float | None


class SectorInfo(BaseModel):
    """Summary information about a configured sector."""

    sector_id: str
    name: str
    description: str


class HealthCheckResponse(BaseModel):
    """Response from the health check endpoint."""

    status: str
    service: str


# ─── Audit Logging Helper ───


async def _call_audit_ledger(
    spreadsheet_id: str,
    audit_sheet_name: str,
    user_identifier: str,
    audit_action_type: str,
    sector_id: str,
    operation_succeeded: bool,
    operation_message: str,
) -> None:
    """
    Invoke the audit ledger and swallow Google Sheets errors (non-blocking).

    Logs all failures locally so the primary API response is never blocked.

    Args:
        spreadsheet_id: Google Sheets document ID
        audit_sheet_name: Sheet tab name for audit log
        user_identifier: User who initiated the action
        audit_action_type: Action string (START_DOCKER, PAUSE_DOCKER, STOP_DOCKER)
        sector_id: Sector affected by the action
        operation_succeeded: Whether the action completed successfully
        operation_message: Optional detail message for the audit entry
    """
    audit_status = AuditOperationStatus.SUCCESS if operation_succeeded else AuditOperationStatus.FAILURE
    try:
        await _audit_ledger.log_action(
            spreadsheet_id=spreadsheet_id,
            sheet_name=audit_sheet_name,
            user=user_identifier,
            action=AuditActionType(audit_action_type),
            sector_id=sector_id,
            status=audit_status,
            message=operation_message,
        )
    except GoogleSheetsAuthenticationError as auth_failure:
        logger.error("audit_logging_failed_authentication", extra={"sector_id": sector_id, "error": str(auth_failure)})
        return
    except GoogleSheetsNetworkError as network_failure:
        logger.warning("audit_logging_failed_network", extra={"sector_id": sector_id, "error": str(network_failure)})
        return
    logger.info("audit_entry_logged", extra={"user": user_identifier, "action": audit_action_type, "sector_id": sector_id, "success": operation_succeeded})


async def _log_worker_action_to_audit_sheet(
    spreadsheet_id: str,
    audit_sheet_name: str,
    console_logs_sheet_name: str,
    user_identifier: str,
    audit_action_type: str,
    sector_id: str,
    operation_succeeded: bool,
    operation_message: str = "",
) -> None:
    """
    Append a worker action entry to both audit log and console_logs sheets (non-blocking).

    Args:
        spreadsheet_id: Google Sheets document ID
        audit_sheet_name: Sheet tab name for detailed audit log
        console_logs_sheet_name: Sheet tab name for console_logs (flat format)
        user_identifier: User who initiated the action
        audit_action_type: Action string (START_DOCKER, PAUSE_DOCKER, STOP_DOCKER)
        sector_id: Sector affected by the action
        operation_succeeded: Whether the action completed successfully
        operation_message: Optional detail message for the audit entry
    """
    await _call_audit_ledger(
        spreadsheet_id, audit_sheet_name, user_identifier,
        audit_action_type, sector_id, operation_succeeded, operation_message,
    )

    try:
        await _audit_ledger.log_console_action(
            spreadsheet_id=spreadsheet_id,
            sheet_name=console_logs_sheet_name,
            action_triggered=audit_action_type,
            target_name=sector_id,
        )
    except (GoogleSheetsAuthenticationError, GoogleSheetsNetworkError, GoogleSheetsDataError) as sheets_failure:
        logger.warning("console_action_logging_failed", extra={"sector_id": sector_id, "error": str(sheets_failure)})


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


async def _execute_worker_action_with_audit(
    sector_id: str,
    user_identifier: str,
    audit_action_type: str,
    container_operation_callable: callable,
) -> WorkerActionResponse:
    """
    Execute a container lifecycle action with audit logging and error mapping.

    Shared by start / pause / stop endpoints to eliminate repetition.

    Args:
        sector_id: Sector to action
        user_identifier: User initiating the action (for audit log)
        audit_action_type: Audit action string (START_DOCKER, PAUSE_DOCKER, STOP_DOCKER)
        container_operation_callable: Zero-arg callable that performs the container action

    Returns:
        WorkerActionResponse with success, state, message, sector_id

    Raises:
        HTTPException: On configuration or Docker errors
    """
    try:
        sector_config = get_sector_config(sector_id)
        container_action_result = container_operation_callable()

        await _log_worker_action_to_audit_sheet(
            spreadsheet_id=sector_config["spreadsheet_id"],
            audit_sheet_name=sector_config["audit_sheet_name"],
            console_logs_sheet_name=sector_config.get("console_logs_sheet_name", "console_logs"),
            user_identifier=user_identifier,
            audit_action_type=audit_action_type,
            sector_id=sector_id,
            operation_succeeded=container_action_result["success"],
            operation_message=container_action_result.get("message", ""),
        )

        return WorkerActionResponse(
            success=container_action_result["success"],
            state=container_action_result["state"],
            message=container_action_result["message"],
            sector_id=sector_id,
        )

    except Exception as sector_action_failure:
        _raise_http_exception_for_sector_error(
            sector_action_failure, sector_id, audit_action_type.lower().replace("_", " ")
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
    return await _execute_worker_action_with_audit(
        sector_id=request.sector_id,
        user_identifier=request.user,
        audit_action_type="START_DOCKER",
        container_operation_callable=lambda: _container_manager.start(
            request.sector_id, request.oracle_env_path
        ),
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
    return await _execute_worker_action_with_audit(
        sector_id=request.sector_id,
        user_identifier=request.user,
        audit_action_type="PAUSE_DOCKER",
        container_operation_callable=lambda: _container_manager.pause(request.sector_id),
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
    return await _execute_worker_action_with_audit(
        sector_id=request.sector_id,
        user_identifier=request.user,
        audit_action_type="STOP_DOCKER",
        container_operation_callable=lambda: _container_manager.stop(request.sector_id),
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
