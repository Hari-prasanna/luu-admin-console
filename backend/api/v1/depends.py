"""Dependency injection container for v1 API.

This module centralizes all service instantiation and dependency resolution.
All routes import services from here rather than instantiating directly.

Usage in routes:
    from backend.api.v1.depends import get_metric_service

    @router.get("/metrics")
    async def get_metrics(service: MetricService = Depends(get_metric_service)):
        return await service.get_live_metrics()

Benefits:
    - Single source of truth for service creation
    - Easy to swap implementations in tests
    - Consistent dependency patterns
    - FastAPI handles async resolution
"""

from functools import lru_cache
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db_session
from backend.services import (
    MetricService,
    AuditService,
    NotificationService,
    PipelineService,
)
from backend.config import Settings, get_settings


# ─── Configuration ───

@lru_cache(maxsize=1)
def get_settings_cached() -> Settings:
    """Get cached settings (singleton).

    Caches since settings don't change at runtime.
    """
    return get_settings()


# ─── Core Services ───

async def get_metric_service(
    session: AsyncSession = Depends(get_db_session),
) -> MetricService:
    """Get metric service with injected session."""
    return MetricService(session)


async def get_audit_service(
    session: AsyncSession = Depends(get_db_session),
) -> AuditService:
    """Get audit service with injected session."""
    return AuditService(session)


async def get_notification_service(
    session: AsyncSession = Depends(get_db_session),
) -> NotificationService:
    """Get notification service with injected session."""
    return NotificationService(session)


async def get_pipeline_service(
    session: AsyncSession = Depends(get_db_session),
) -> PipelineService:
    """Get pipeline service with injected session."""
    return PipelineService(session)


# ─── Future Services (Stubs for expansion) ───

# async def get_analytics_service(
#     session: AsyncSession = Depends(get_db_session),
# ) -> AnalyticsService:
#     """Get analytics service."""
#     return AnalyticsService(session)

# async def get_automation_service(
#     session: AsyncSession = Depends(get_db_session),
# ) -> AutomationService:
#     """Get automation service."""
#     return AutomationService(session)

# async def get_reporting_service(
#     session: AsyncSession = Depends(get_db_session),
# ) -> ReportingService:
#     """Get reporting service."""
#     return ReportingService(session)
