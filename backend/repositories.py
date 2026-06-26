"""
Repository pattern for data access layer.

Abstracts database operations for each entity.
"""

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db_models import (
    MetricHistory,
    AuditLog,
    PipelineRun,
    Notification,
    User,
)


class MetricRepository:
    """Data access for metrics history."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        metric_key: str,
        metric_value: float,
        metric_status: str,
        timestamp: datetime,
    ) -> MetricHistory:
        """Record a metric value."""
        record = MetricHistory(
            metric_key=metric_key,
            metric_value=metric_value,
            metric_status=metric_status,
            timestamp=timestamp,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get_by_metric_and_date_range(
        self,
        metric_key: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[MetricHistory]:
        """Fetch metric history for time range."""
        stmt = select(MetricHistory).where(
            and_(
                MetricHistory.metric_key == metric_key,
                MetricHistory.timestamp >= start_date,
                MetricHistory.timestamp <= end_date,
            )
        ).order_by(MetricHistory.timestamp)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_latest_by_metric(self, metric_key: str, limit: int = 24) -> List[MetricHistory]:
        """Fetch latest N records for a metric."""
        stmt = (
            select(MetricHistory)
            .where(MetricHistory.metric_key == metric_key)
            .order_by(desc(MetricHistory.timestamp))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()


class AuditRepository:
    """Data access for audit logs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        event_type: str,
        actor: str,
        actor_role: str,
        operation_status: str,
        detail_message: Optional[str] = None,
        endpoint_path: Optional[str] = None,
        request_id: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> AuditLog:
        """Record an audit event."""
        record = AuditLog(
            event_type=event_type,
            actor=actor,
            actor_role=actor_role,
            operation_status=operation_status,
            detail_message=detail_message,
            endpoint_path=endpoint_path,
            request_id=request_id,
            ip_address=ip_address,
            timestamp=datetime.utcnow(),
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def get_by_date_range(
        self,
        start_date: datetime,
        end_date: datetime,
        event_type: Optional[str] = None,
        actor: Optional[str] = None,
    ) -> List[AuditLog]:
        """Fetch audit logs for time range with optional filters."""
        filters = [
            AuditLog.timestamp >= start_date,
            AuditLog.timestamp <= end_date,
        ]
        if event_type:
            filters.append(AuditLog.event_type == event_type)
        if actor:
            filters.append(AuditLog.actor == actor)

        stmt = select(AuditLog).where(and_(*filters)).order_by(desc(AuditLog.timestamp))
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_request_id(self, request_id: str) -> List[AuditLog]:
        """Fetch all audit entries for a request."""
        stmt = (
            select(AuditLog)
            .where(AuditLog.request_id == request_id)
            .order_by(AuditLog.timestamp)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()


class PipelineRunRepository:
    """Data access for pipeline executions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        pipeline_name: str,
        status: str,
        started_at: datetime,
        sector_id: Optional[str] = None,
        triggered_by: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> PipelineRun:
        """Record pipeline start."""
        record = PipelineRun(
            pipeline_name=pipeline_name,
            sector_id=sector_id,
            status=status,
            started_at=started_at,
            triggered_by=triggered_by,
            request_id=request_id,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def update_completion(
        self,
        run_id: int,
        status: str,
        rows_processed: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> PipelineRun:
        """Mark pipeline as completed."""
        record = await self.db.get(PipelineRun, run_id)
        if record:
            record.status = status
            record.ended_at = datetime.utcnow()
            record.rows_processed = rows_processed
            record.error_message = error_message
            if record.started_at and record.ended_at:
                record.duration_seconds = int((record.ended_at - record.started_at).total_seconds())
            await self.db.commit()
            await self.db.refresh(record)
        return record

    async def get_by_pipeline_and_date_range(
        self,
        pipeline_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> List[PipelineRun]:
        """Fetch pipeline runs for time range."""
        stmt = select(PipelineRun).where(
            and_(
                PipelineRun.pipeline_name == pipeline_name,
                PipelineRun.started_at >= start_date,
                PipelineRun.started_at <= end_date,
            )
        ).order_by(desc(PipelineRun.started_at))
        result = await self.db.execute(stmt)
        return result.scalars().all()


class NotificationRepository:
    """Data access for notifications."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        alert_type: str,
        message: str,
        metric_key: Optional[str] = None,
        previous_state: Optional[str] = None,
        current_state: Optional[str] = None,
        sent_to: Optional[str] = None,
    ) -> Notification:
        """Record a notification."""
        record = Notification(
            alert_type=alert_type,
            metric_key=metric_key,
            previous_state=previous_state,
            current_state=current_state,
            message=message,
            sent_to=sent_to,
            delivery_status="pending",
            timestamp=datetime.utcnow(),
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def mark_delivered(
        self,
        notification_id: int,
        success: bool = True,
        error_details: Optional[str] = None,
    ) -> Notification:
        """Update delivery status."""
        record = await self.db.get(Notification, notification_id)
        if record:
            record.delivery_status = "sent" if success else "failed"
            record.error_details = error_details
            await self.db.commit()
            await self.db.refresh(record)
        return record

    async def get_failed_notifications(self, limit: int = 100) -> List[Notification]:
        """Fetch undelivered notifications."""
        stmt = (
            select(Notification)
            .where(Notification.delivery_status == "pending")
            .order_by(Notification.timestamp)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()
