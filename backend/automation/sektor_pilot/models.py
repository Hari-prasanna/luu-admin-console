"""
Shared domain models for Sektor Pilot.

Centralising Pydantic models, enums, and dataclasses here keeps individual
modules free of inline schema definitions and guarantees a single source of
truth for every data shape that crosses module boundaries.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from backend.automation.sektor_pilot.sector_config import get_sector_config


# ─── Enumerations ─────────────────────────────────────────────────────────────


class AuditActionType(str, Enum):
    """Actions that can be recorded in the audit ledger."""

    START_DOCKER = "START_DOCKER"
    PAUSE_DOCKER = "PAUSE_DOCKER"
    STOP_DOCKER = "STOP_DOCKER"
    IDLE_SHUTDOWN = "IDLE_SHUTDOWN"


class AuditStatusType(str, Enum):
    """Outcome status for an audit entry."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PENDING = "PENDING"


class ContainerState(str, Enum):
    """Lifecycle states a sector worker container can be in."""

    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    IDLE = "IDLE"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


# ─── Dataclasses ──────────────────────────────────────────────────────────────


@dataclass
class ContainerCommandResult:
    """
    Structured result from a Docker subprocess invocation.

    Using a dataclass instead of a raw tuple makes callers
    reference fields by name, eliminating positional ambiguity.
    """

    return_code: int
    standard_output: str
    standard_error: str

    @property
    def succeeded(self) -> bool:
        """True when the command exited with return code 0."""
        return self.return_code == 0


# ─── Pydantic Request / Response Models ───────────────────────────────────────


class _SectorWorkerBaseRequest(BaseModel):
    """Base request payload with dynamic sector validation."""

    sector_id: str = Field(..., description="Sector identifier")
    user: str = Field(default="system", description="Initiating user (recorded in audit log)")

    @field_validator("sector_id")
    @classmethod
    def validate_sector_id(cls, value: str) -> str:
        """Validate sector_id against active sector registry (no hardcoded IDs)."""
        get_sector_config(value)
        return value


class SectorWorkerStartRequest(_SectorWorkerBaseRequest):
    """Request payload to start a sector automation worker container."""

    oracle_env_path: str = Field(default="oracle.env", description="Path to oracle.env credentials file")


class SectorWorkerPauseRequest(_SectorWorkerBaseRequest):
    """Request payload to pause a running sector worker."""


class SectorWorkerStopRequest(_SectorWorkerBaseRequest):
    """Request payload to stop and remove a sector worker container."""


class ActionResponse(BaseModel):
    """Uniform response envelope for all container-control operations."""

    success: bool
    state: str
    message: str
    sector_id: str


class StatusResponse(BaseModel):
    """Current lifecycle state for a single sector worker container."""

    sector_id: str
    container_name: str
    state: str
    container_id: Optional[str] = None
    started_at: Optional[float] = None
    paused_at: Optional[float] = None
    idle_timeout_seconds: Optional[int] = None


class SectorListItem(BaseModel):
    """Compact descriptor used in the sector list endpoint."""

    sector_id: str
    name: str
    description: str


# ─── Audit Models ─────────────────────────────────────────────────────────────


@dataclass
class AuditEntry:
    """
    Fully-typed audit record passed to AuditLedger.log_action().

    Keeping this as a dataclass (not Pydantic) avoids coupling the internal
    logging layer to HTTP validation concerns.
    """

    spreadsheet_id: str
    sheet_name: str
    user: str
    action: AuditActionType
    sector_id: str
    status: AuditStatusType
    message: str = ""


# ─── Sector Configuration Model ───────────────────────────────────────────────


class SectorConfig(BaseModel):
    """
    Validated configuration for a single sector instance.

    Pydantic validation runs on construction, so invalid configs
    raise immediately at module load time rather than at request time.
    """

    sector_id: str
    name: str
    description: str
    spreadsheet_id: str
    test_sheet_name: str
    trigger_cell: str
    sektor_sheet_name: str
    audit_sheet_name: str
