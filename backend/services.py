"""
Business logic and service layer.

Mediates between API routes and data repositories.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories import (
    MetricRepository,
    AuditRepository,
    PipelineRunRepository,
    NotificationRepository,
)


class MetricService:
    """Handles metric recording and retrieval."""

    def __init__(self, db: AsyncSession):
        self.repo = MetricRepository(db)

    async def record_metric(
        self,
        metric_key: str,
        metric_value: float,
        metric_status: str,
        timestamp: Optional[datetime] = None,
    ):
        """Record a metric value to history."""
        if timestamp is None:
            timestamp = datetime.utcnow()

        return await self.repo.create(
            metric_key=metric_key,
            metric_value=metric_value,
            metric_status=metric_status,
            timestamp=timestamp,
        )

    async def get_metric_history(
        self,
        metric_key: str,
        start_date: datetime,
        end_date: datetime,
    ):
        """Retrieve metric history for analytics."""
        return await self.repo.get_by_metric_and_date_range(
            metric_key=metric_key,
            start_date=start_date,
            end_date=end_date,
        )

    async def get_latest_metrics(self, metric_key: str, limit: int = 24):
        """Get latest metric values for charting."""
        return await self.repo.get_latest_by_metric(metric_key=metric_key, limit=limit)


class AuditService:
    """Handles audit logging and retrieval."""

    def __init__(self, db: AsyncSession):
        self.repo = AuditRepository(db)

    async def log_event(
        self,
        event_type: str,
        actor: str,
        actor_role: str,
        operation_status: str,
        detail_message: Optional[str] = None,
        endpoint_path: Optional[str] = None,
        request_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ):
        """Log an audit event."""
        return await self.repo.create(
            event_type=event_type,
            actor=actor,
            actor_role=actor_role,
            operation_status=operation_status,
            detail_message=detail_message,
            endpoint_path=endpoint_path,
            request_id=request_id,
            ip_address=ip_address,
        )

    async def get_logs_for_period(
        self,
        start_date: datetime,
        end_date: datetime,
        event_type: Optional[str] = None,
        actor: Optional[str] = None,
    ):
        """Retrieve audit logs for reporting."""
        return await self.repo.get_by_date_range(
            start_date=start_date,
            end_date=end_date,
            event_type=event_type,
            actor=actor,
        )

    async def get_request_trace(self, request_id: str):
        """Get all events for a single request."""
        return await self.repo.get_by_request_id(request_id=request_id)


class PipelineService:
    """Handles pipeline execution tracking."""

    def __init__(self, db: AsyncSession):
        self.repo = PipelineRunRepository(db)

    async def start_run(
        self,
        pipeline_name: str,
        sector_id: Optional[str] = None,
        triggered_by: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        """Record pipeline start."""
        return await self.repo.create(
            pipeline_name=pipeline_name,
            sector_id=sector_id,
            status="RUNNING",
            started_at=datetime.utcnow(),
            triggered_by=triggered_by,
            request_id=request_id,
        )

    async def complete_run(
        self,
        run_id: int,
        status: str,
        rows_processed: Optional[int] = None,
        error_message: Optional[str] = None,
    ):
        """Record pipeline completion."""
        return await self.repo.update_completion(
            run_id=run_id,
            status=status,
            rows_processed=rows_processed,
            error_message=error_message,
        )

    async def get_pipeline_history(
        self,
        pipeline_name: str,
        start_date: datetime,
        end_date: datetime,
    ):
        """Get pipeline execution history."""
        return await self.repo.get_by_pipeline_and_date_range(
            pipeline_name=pipeline_name,
            start_date=start_date,
            end_date=end_date,
        )


class NotificationService:
    """Handles notifications and alerts."""

    def __init__(self, db: AsyncSession):
        self.repo = NotificationRepository(db)

    async def create_notification(
        self,
        alert_type: str,
        message: str,
        metric_key: Optional[str] = None,
        previous_state: Optional[str] = None,
        current_state: Optional[str] = None,
        sent_to: Optional[str] = None,
    ):
        """Create a notification alert."""
        return await self.repo.create(
            alert_type=alert_type,
            message=message,
            metric_key=metric_key,
            previous_state=previous_state,
            current_state=current_state,
            sent_to=sent_to,
        )

    async def mark_delivered(
        self,
        notification_id: int,
        success: bool = True,
        error_details: Optional[str] = None,
    ):
        """Mark notification as delivered."""
        return await self.repo.mark_delivered(
            notification_id=notification_id,
            success=success,
            error_details=error_details,
        )

    async def get_pending_notifications(self, limit: int = 100):
        """Get undelivered notifications for retry."""
        return await self.repo.get_failed_notifications(limit=limit)
