"""Health check endpoints."""

import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db_session
from backend.health_check import get_health_check
from backend.api.v1.schemas import DataResponse, HealthResponse

logger = logging.getLogger("luu.api.health")
router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "",
    response_model=Dict[str, str],
    summary="Liveness probe",
    description="Basic health check for load balancers and Docker"
)
async def health_check() -> Dict[str, str]:
    """
    Basic liveness probe.

    Always returns 200 OK if service is running.
    Used by Docker and load balancers for health checks.
    """
    return {"status": "ok"}


@router.get(
    "/deep",
    response_model=DataResponse[HealthResponse],
    summary="Deep health check",
    description="Comprehensive system diagnostics"
)
async def deep_health_check(
    session: AsyncSession = Depends(get_db_session),
) -> DataResponse[HealthResponse]:
    """
    Deep health check.

    Performs comprehensive checks on all subsystems:
    - API responsiveness
    - PostgreSQL connectivity
    - Oracle connectivity
    - Background threads
    - Automation workers
    """
    try:
        health_checker = get_health_check()
        result = await health_checker.deep_health_check(None, session)

        return DataResponse(
            data=result,
            request_id=None
        )
    except Exception as e:
        logger.error("deep_health_check_failed", extra={"error": str(e)})
        return DataResponse(
            data=HealthResponse(
                status="unhealthy",
                timestamp=None,
                response_time_ms=0,
                checks={}
            ),
            request_id=None
        )


@router.get(
    "/postgres",
    response_model=DataResponse[Dict[str, Any]],
    summary="PostgreSQL health",
    description="Check PostgreSQL connectivity and table counts"
)
async def postgres_health(
    session: AsyncSession = Depends(get_db_session),
) -> DataResponse[Dict[str, Any]]:
    """
    Check PostgreSQL health.

    Returns connectivity status and row counts for all tables.
    """
    try:
        health_checker = get_health_check()
        result = await health_checker.check_postgres(session)

        return DataResponse(
            data=result,
            request_id=None
        )
    except Exception as e:
        logger.error("postgres_health_check_failed", extra={"error": str(e)})
        raise


@router.get(
    "/oracle",
    response_model=DataResponse[Dict[str, Any]],
    summary="Oracle health",
    description="Check Oracle connectivity and failure tracking"
)
async def oracle_health() -> DataResponse[Dict[str, Any]]:
    """
    Check Oracle health.

    Returns connectivity status and consecutive failure count.
    """
    health_checker = get_health_check()
    result = {
        "status": "ok",
        "service": "oracle",
        "consecutive_failures": health_checker.oracle_consecutive_failures,
        "last_error": health_checker.last_oracle_error,
    }

    return DataResponse(
        data=result,
        request_id=None
    )


@router.get(
    "/automation",
    response_model=DataResponse[Dict[str, Any]],
    summary="Automation workers health",
    description="Check automation worker status and heartbeats"
)
async def automation_health() -> DataResponse[Dict[str, Any]]:
    """
    Check automation workers health.

    Returns status of all automation workers and last heartbeat.
    """
    health_checker = get_health_check()
    result = await health_checker.check_automation()

    return DataResponse(
        data=result,
        request_id=None
    )
