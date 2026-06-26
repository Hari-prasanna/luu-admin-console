"""
Pydantic models for LUU Q-Console backend.

Provides type-safe request/response schemas and domain models.
Enforces Clean Code principle: explicit contracts for all APIs.
"""

from typing import Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


# ─── Domain Enums ───

class TileStatus(str, Enum):
    """Tile metric status colors."""

    AKTIV = "Aktiv"  # Green: value ≤ green threshold
    WARNUNG = "Warnung"  # Amber: green < value ≤ amber threshold
    KRITISCH = "Kritisch"  # Red: value > amber threshold
    ERROR = "ERROR"  # Error state


class MetricDataType(str, Enum):
    """Supported metric data types."""

    INTEGER = "integer"
    FLOAT = "float"
    STRING = "string"


# ─── Tile Configuration Models ───

class TileThresholds(BaseModel):
    """Thresholds for tile status coloring."""

    green_threshold: int | float = Field(..., description="Value ≤ this → Aktiv")
    amber_threshold: int | float = Field(..., description="Value ≤ this → Warnung")


class TileConfig(BaseModel):
    """Configuration for a single tile in the dashboard."""

    key: str = Field(..., description="Unique identifier (must match icon filename)")
    label: str = Field(..., description="Display name shown on dashboard")
    query: str = Field(..., description="SQL filename in queries/ directory")
    unit: str = Field(..., description="Unit of measurement (e.g., 'units', 'kg')")
    thresholds: TileThresholds


class MetricValue(BaseModel):
    """A single metric value with status information."""

    tile_key: str
    value: int | float | str
    status: TileStatus
    unit: str
    timestamp: datetime


class MetricsResponse(BaseModel):
    """Response from /api/metrics endpoint."""

    metrics: dict[str, MetricValue] = Field(..., description="Map of tile_key → MetricValue")
    timestamp: datetime
    query_duration_milliseconds: float


class ConfigResponse(BaseModel):
    """Response from /api/config endpoint."""

    tiles: list[TileConfig]
    refresh_interval_milliseconds: int
    timestamp: datetime


# ─── Validation Models ───

class AuditEntry(BaseModel):
    """An entry in the system audit log."""

    timestamp: datetime
    user_role: str = Field(..., description="User ID or role identifier")
    action: str = Field(..., description="Action performed (START_DOCKER, PAUSE, etc.)")
    target_sector: str | None = Field(None, description="Sector affected by action")
    status: str = Field(..., description="SUCCESS or FAILURE")
    message: str = Field(..., description="Details about the action")


class SystemStatus(BaseModel):
    """Overall system health status."""

    status: str = Field(..., description="ok, degraded, error")
    oracle_connection: bool = Field(..., description="Is Oracle reachable?")
    google_sheets_auth: bool = Field(..., description="Are Google Sheets credentials valid?")
    last_check_timestamp: datetime
    diagnostics: dict[str, Any] = Field(default_factory=dict, description="Debug info")


# ─── Sektor Pilot Models (from backend.automation.sektor_pilot.models) ───
# These are imported from the submodule to maintain single source of truth

from backend.automation.sektor_pilot.models import (
    SectorWorkerStartRequest,
    SectorWorkerPauseRequest,
    SectorWorkerStopRequest,
    ActionResponse as WorkerActionResponse,
    StatusResponse as WorkerStatusResponse,
    SectorListItem as SectorInfo,
)


class HealthCheckResponse(BaseModel):
    """Response from the health check endpoint."""

    status: str
    service: str
