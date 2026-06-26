"""
Unified API schemas for request/response standardization.

All endpoints use these schemas for consistency across the platform.
"""

from typing import Any, Dict, List, Optional, Generic, TypeVar
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, validator


T = TypeVar('T')


# ─── Common Enums ───

class StatusEnum(str, Enum):
    """Standard status values for responses."""
    SUCCESS = "success"
    FAILURE = "failure"
    ERROR = "error"
    PENDING = "pending"


class SortOrder(str, Enum):
    """Sort direction."""
    ASC = "asc"
    DESC = "desc"


# ─── Pagination ───

class PaginationParams(BaseModel):
    """Standard pagination parameters."""
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

    class Config:
        schema_extra = {
            "example": {
                "limit": 50,
                "offset": 0
            }
        }


class PaginationMeta(BaseModel):
    """Pagination metadata."""
    limit: int
    offset: int
    total: int
    has_more: bool = Field(default=False)

    @validator('has_more', always=True)
    def calculate_has_more(cls, v, values):
        if 'limit' in values and 'offset' in values and 'total' in values:
            return values['offset'] + values['limit'] < values['total']
        return False


# ─── Filtering & Sorting ───

class FilterOperator(str, Enum):
    """Filter operators."""
    EQ = "eq"          # equals
    NE = "ne"          # not equals
    GT = "gt"          # greater than
    GTE = "gte"        # greater than or equal
    LT = "lt"          # less than
    LTE = "lte"        # less than or equal
    IN = "in"          # in list
    CONTAINS = "contains"  # string contains


class SortBy(BaseModel):
    """Sort specification."""
    field: str
    order: SortOrder = SortOrder.DESC


class FilterSpec(BaseModel):
    """Filter specification."""
    field: str
    operator: FilterOperator
    value: Any


class QueryParams(BaseModel):
    """Standard query parameters for list endpoints."""
    limit: int = Field(default=50, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
    sort_by: Optional[str] = None
    sort_order: SortOrder = SortOrder.DESC
    filters: Optional[List[FilterSpec]] = None

    class Config:
        schema_extra = {
            "example": {
                "limit": 50,
                "offset": 0,
                "sort_by": "created_at",
                "sort_order": "desc",
                "filters": [
                    {
                        "field": "status",
                        "operator": "eq",
                        "value": "success"
                    }
                ]
            }
        }


# ─── Error Response ───

class ErrorDetail(BaseModel):
    """Error detail with field and code."""
    field: Optional[str] = None
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Standard error response."""
    status: StatusEnum = StatusEnum.ERROR
    error_code: str
    message: str
    details: Optional[List[ErrorDetail]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: Optional[str] = None

    class Config:
        schema_extra = {
            "example": {
                "status": "error",
                "error_code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "details": [
                    {
                        "field": "email",
                        "code": "INVALID_FORMAT",
                        "message": "Invalid email format"
                    }
                ],
                "timestamp": "2026-06-26T16:22:00Z",
                "request_id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }


# ─── Generic Response Wrapper ───

class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response."""
    status: StatusEnum = StatusEnum.SUCCESS
    data: List[T]
    pagination: PaginationMeta
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: Optional[str] = None


class DataResponse(BaseModel, Generic[T]):
    """Single data response."""
    status: StatusEnum = StatusEnum.SUCCESS
    data: T
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: Optional[str] = None


class MessageResponse(BaseModel):
    """Simple message response."""
    status: StatusEnum = StatusEnum.SUCCESS
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: Optional[str] = None


class ValidationErrorResponse(ErrorResponse):
    """Validation error response (422)."""
    error_code: str = "VALIDATION_ERROR"


# ─── Auth Schemas ───

class LoginRequest(BaseModel):
    """Login request."""
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)

    class Config:
        schema_extra = {
            "example": {
                "username": "admin",
                "password": "password123"
            }
        }


class TokenResponse(BaseModel):
    """Auth token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: Optional[Dict[str, Any]] = None


class CurrentUserResponse(BaseModel):
    """Current user info."""
    id: int
    username: str
    role: str
    created_at: datetime


# ─── Metrics Schemas ───

class MetricTileConfig(BaseModel):
    """Metric tile configuration."""
    key: str
    label: str
    query: str
    unit: str
    thresholds: Dict[str, int]


class MetricValue(BaseModel):
    """Individual metric value."""
    key: str
    value: Optional[float] = None
    status: str  # "Aktiv", "Warnung", "Kritisch", "ERROR"
    unit: str
    timestamp: datetime


class MetricsResponse(BaseModel):
    """Live metrics response."""
    metrics: Dict[str, MetricValue]
    last_updated: datetime
    cached: bool
    cache_age_seconds: int


# ─── Health Schemas ───

class HealthCheckDetail(BaseModel):
    """Individual health check result."""
    status: str  # "ok", "error", "degraded"
    response_time_ms: int = 0
    details: Optional[Dict[str, Any]] = None


class HealthResponse(BaseModel):
    """Deep health check response."""
    status: str  # "healthy", "degraded", "unhealthy"
    timestamp: datetime
    response_time_ms: int
    checks: Dict[str, HealthCheckDetail]


# ─── Audit Schemas ───

class AuditLogEntry(BaseModel):
    """Audit log entry."""
    id: int
    timestamp: datetime
    event_type: str
    actor: str
    operation_status: str
    detail_message: Optional[str] = None
    request_id: Optional[str] = None
    ip_address: Optional[str] = None


class AuditLogResponse(PaginatedResponse[AuditLogEntry]):
    """Paginated audit logs."""
    pass


# ─── Job Execution Schemas ───

class JobExecutionResponse(BaseModel):
    """Job execution record."""
    id: int
    job_name: str
    job_type: str
    sector_id: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    status: str
    rows_processed: Optional[int] = None
    rows_failed: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
