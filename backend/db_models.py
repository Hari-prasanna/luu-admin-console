"""
SQLAlchemy ORM models for PostgreSQL persistence.

Defines schema for metrics history, audit logs, pipeline runs, and notifications.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean, Index, ForeignKey
from sqlalchemy.sql import func

from backend.database import Base


class MetricHistory(Base):
    """Historical record of metric values for analytics."""

    __tablename__ = "metric_history"

    id = Column(Integer, primary_key=True, index=True)
    metric_key = Column(String(100), nullable=False, index=True)
    metric_value = Column(Float, nullable=False)
    metric_status = Column(String(20), nullable=False)  # Aktiv, Warnung, Kritisch, ERROR
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_metric_key_timestamp", "metric_key", "timestamp"),
    )


class AuditLog(Base):
    """Audit trail for all system operations."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    actor = Column(String(100), nullable=False)
    actor_role = Column(String(20), nullable=False)
    operation_status = Column(String(20), nullable=False)  # success, failure, blocked
    detail_message = Column(Text, nullable=True)
    endpoint_path = Column(String(255), nullable=True)
    request_id = Column(String(36), nullable=True, index=True)
    ip_address = Column(String(50), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_event_type_timestamp", "event_type", "timestamp"),
        Index("idx_actor_timestamp", "actor", "timestamp"),
        Index("idx_request_id", "request_id"),
    )


class PipelineRun(Base):
    """Record of pipeline/worker executions."""

    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True, index=True)
    pipeline_name = Column(String(100), nullable=False, index=True)
    sector_id = Column(String(50), nullable=True)
    status = Column(String(20), nullable=False)  # RUNNING, PAUSED, STOPPED, ERROR, SUCCESS
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    rows_processed = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String(100), nullable=True)
    request_id = Column(String(36), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_pipeline_name_started", "pipeline_name", "started_at"),
        Index("idx_sector_id_started", "sector_id", "started_at"),
    )


class Notification(Base):
    """Notification/alert history for state changes."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    alert_type = Column(String(50), nullable=False, index=True)  # state_change, threshold, error
    metric_key = Column(String(100), nullable=True, index=True)
    previous_state = Column(String(20), nullable=True)
    current_state = Column(String(20), nullable=True)
    message = Column(Text, nullable=False)
    sent_to = Column(String(255), nullable=True)  # webhook URL or channel
    delivery_status = Column(String(20), nullable=False)  # pending, sent, failed
    error_details = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_notification_alert_type_timestamp", "alert_type", "timestamp"),
        Index("idx_notification_metric_key_timestamp", "metric_key", "timestamp"),
    )


class User(Base):
    """User accounts."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)  # admin, user
    panels_json = Column(Text, nullable=False, server_default='[]')
    is_active = Column(Boolean, nullable=False, server_default='true', index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserAccessSCD2(Base):
    """Type-2 history of user profile and panel access changes."""

    __tablename__ = "user_access_scd2"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    username = Column(String(100), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    password_hash = Column(String(255), nullable=False)
    panels_json = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False)
    operation_type = Column(String(20), nullable=False)  # create, update, delete, migrate
    changed_by = Column(String(100), nullable=False)
    change_reason = Column(Text, nullable=True)
    valid_from = Column(DateTime(timezone=True), nullable=False, index=True)
    valid_to = Column(DateTime(timezone=True), nullable=True, index=True)
    is_current = Column(Boolean, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_user_access_scd2_user_current", "user_id", "is_current"),
        Index("idx_user_access_scd2_user_window", "user_id", "valid_from", "valid_to"),
    )


class OperationLog(Base):
    """Immutable event stream of all system operations."""

    __tablename__ = "operation_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    service = Column(String(100), nullable=False)  # internal-transport-api, sektor-worker, system
    event = Column(String(100), nullable=False, index=True)
    level = Column(String(20), nullable=False)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    request_id = Column(String(36), nullable=True, index=True)
    status = Column(String(20), nullable=True)  # success, failure, retry, timeout, skipped
    duration_ms = Column(Integer, nullable=True)
    error_code = Column(String(100), nullable=True, index=True)
    error_message = Column(Text, nullable=True)
    context_data = Column(Text, nullable=True)  # Stores JSON context
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_operation_logs_timestamp_service", "timestamp", "service"),
        Index("idx_operation_logs_event_status", "event", "status"),
    )


class JobExecution(Base):
    """Detailed job/pipeline run tracking for metrics."""

    __tablename__ = "job_executions"

    id = Column(Integer, primary_key=True, index=True)
    job_name = Column(String(255), nullable=False, index=True)
    job_type = Column(String(50), nullable=False)  # metric_refresh, sector_worker, audit
    sector_id = Column(String(100), nullable=True, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False)  # running, success, failure, timeout
    rows_processed = Column(Integer, nullable=True)
    rows_failed = Column(Integer, nullable=True)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    request_id = Column(String(36), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_job_executions_job_name_started", "job_name", "started_at"),
        Index("idx_job_executions_status_started", "status", "started_at"),
    )


class UserFeedback(Base):
    """User-submitted feedback stored from the profile menu."""

    __tablename__ = "user_feedback"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=False, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    category = Column(String(50), nullable=True)          # general, bug, feature, ui_ux
    rating = Column(Integer, nullable=True)               # 1-5
    message = Column(Text, nullable=False)
    page_context = Column(String(200), nullable=True)     # current panel/page
    submitted_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_user_feedback_username_submitted", "username", "submitted_at"),
    )
