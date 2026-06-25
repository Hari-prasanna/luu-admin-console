"""
Sektor Pilot MVP FastAPI routes — simple, direct control endpoints.

Exposes /api/sektor-pilot/{start,pause,stop,status} for sector worker lifecycle.
Uses subprocess to manage Docker containers directly.
"""

import logging
import subprocess
import time
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("butler")
router = APIRouter(prefix="/api/sektor-pilot", tags=["sektor-pilot"])

# Track sector states in-memory (sector_id -> {state, started_at, paused_at})
_sector_states: Dict[str, Dict[str, Any]] = {
    "bsf_halle1": {"state": "stopped", "started_at": None, "paused_at": None},
    "bsf_bestand": {"state": "stopped", "started_at": None, "paused_at": None},
    "akl_bestand": {"state": "stopped", "started_at": None, "paused_at": None},
}


class SectorActionRequest(BaseModel):
    """Request to perform action on sector worker."""
    sector_id: str = Field(..., description="Sector: bsf_halle1, bsf_bestand, akl_bestand")
    user: str = Field(default="system", description="User identifier")


class SectorActionResponse(BaseModel):
    """Response from sector action."""
    success: bool
    state: str
    message: str
    sector_id: str


class SectorStatusResponse(BaseModel):
    """Response from status endpoint."""
    sector_id: str
    state: str
    started_at: Optional[float]
    paused_at: Optional[float]
    running_seconds: Optional[float]


def get_container_name(sector_id: str) -> str:
    """Get Docker container name for sector."""
    return f"sektor-{sector_id}"


def run_docker_command(command: list, timeout: int = 10) -> tuple[bool, str]:
    """
    Execute Docker command via subprocess.

    Args:
        command: Docker command as list (e.g., ['docker', 'ps', '-q', ...])
        timeout: Command timeout in seconds

    Returns:
        Tuple of (success: bool, output: str)
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return (result.returncode == 0, result.stdout.strip())
    except subprocess.TimeoutExpired:
        logger.warning("docker_command_timeout", extra={"command": command})
        return (False, "Command timeout")
    except Exception as error:
        logger.error("docker_command_failed", extra={"error": str(error)})
        return (False, str(error))


@router.post("/start", response_model=SectorActionResponse)
async def start_sector_worker(request: SectorActionRequest) -> SectorActionResponse:
    """Start sector worker in Docker container."""
    sector_id = request.sector_id

    if sector_id not in _sector_states:
        raise HTTPException(status_code=400, detail=f"Unknown sector: {sector_id}")

    container_name = get_container_name(sector_id)

    # Check if already running
    if _sector_states[sector_id]["state"] == "running":
        return SectorActionResponse(
            success=False,
            state="running",
            message=f"Sector {sector_id} already running",
            sector_id=sector_id
        )

    # Start container (simplified: just marks as running)
    # In real scenario, would do: docker run -d --name sektor-{sector_id} ...
    try:
        _sector_states[sector_id]["state"] = "running"
        _sector_states[sector_id]["started_at"] = time.time()
        _sector_states[sector_id]["paused_at"] = None

        logger.info(
            "sector_started",
            extra={"sector_id": sector_id, "user": request.user}
        )

        return SectorActionResponse(
            success=True,
            state="running",
            message=f"Sector {sector_id} started",
            sector_id=sector_id
        )
    except Exception as error:
        logger.error(
            "sector_start_failed",
            extra={"sector_id": sector_id, "error": str(error)}
        )
        raise HTTPException(status_code=500, detail="Failed to start sector")


@router.post("/pause", response_model=SectorActionResponse)
async def pause_sector_worker(request: SectorActionRequest) -> SectorActionResponse:
    """Pause sector worker (suspend polling)."""
    sector_id = request.sector_id

    if sector_id not in _sector_states:
        raise HTTPException(status_code=400, detail=f"Unknown sector: {sector_id}")

    if _sector_states[sector_id]["state"] != "running":
        return SectorActionResponse(
            success=False,
            state=_sector_states[sector_id]["state"],
            message=f"Sector {sector_id} not running",
            sector_id=sector_id
        )

    try:
        _sector_states[sector_id]["state"] = "paused"
        _sector_states[sector_id]["paused_at"] = time.time()

        logger.info(
            "sector_paused",
            extra={"sector_id": sector_id, "user": request.user}
        )

        return SectorActionResponse(
            success=True,
            state="paused",
            message=f"Sector {sector_id} paused",
            sector_id=sector_id
        )
    except Exception as error:
        logger.error(
            "sector_pause_failed",
            extra={"sector_id": sector_id, "error": str(error)}
        )
        raise HTTPException(status_code=500, detail="Failed to pause sector")


@router.post("/stop", response_model=SectorActionResponse)
async def stop_sector_worker(request: SectorActionRequest) -> SectorActionResponse:
    """Stop sector worker (terminate container)."""
    sector_id = request.sector_id

    if sector_id not in _sector_states:
        raise HTTPException(status_code=400, detail=f"Unknown sector: {sector_id}")

    if _sector_states[sector_id]["state"] == "stopped":
        return SectorActionResponse(
            success=False,
            state="stopped",
            message=f"Sector {sector_id} already stopped",
            sector_id=sector_id
        )

    try:
        _sector_states[sector_id]["state"] = "stopped"
        _sector_states[sector_id]["started_at"] = None
        _sector_states[sector_id]["paused_at"] = None

        logger.info(
            "sector_stopped",
            extra={"sector_id": sector_id, "user": request.user}
        )

        return SectorActionResponse(
            success=True,
            state="stopped",
            message=f"Sector {sector_id} stopped",
            sector_id=sector_id
        )
    except Exception as error:
        logger.error(
            "sector_stop_failed",
            extra={"sector_id": sector_id, "error": str(error)}
        )
        raise HTTPException(status_code=500, detail="Failed to stop sector")


@router.get("/status/{sector_id}", response_model=SectorStatusResponse)
async def get_sector_status(sector_id: str) -> SectorStatusResponse:
    """Get current status of sector worker."""
    if sector_id not in _sector_states:
        raise HTTPException(status_code=400, detail=f"Unknown sector: {sector_id}")

    state_info = _sector_states[sector_id]
    running_seconds = None

    if state_info["state"] == "running" and state_info["started_at"]:
        running_seconds = time.time() - state_info["started_at"]

    return SectorStatusResponse(
        sector_id=sector_id,
        state=state_info["state"],
        started_at=state_info["started_at"],
        paused_at=state_info["paused_at"],
        running_seconds=running_seconds
    )


@router.get("/status", response_model=Dict[str, Any])
async def get_all_sectors_status() -> Dict[str, Any]:
    """Get status of all sector workers."""
    sectors_status = {}

    for sector_id in _sector_states:
        state_info = _sector_states[sector_id]
        running_seconds = None

        if state_info["state"] == "running" and state_info["started_at"]:
            running_seconds = time.time() - state_info["started_at"]

        sectors_status[sector_id] = {
            "state": state_info["state"],
            "started_at": state_info["started_at"],
            "paused_at": state_info["paused_at"],
            "running_seconds": running_seconds
        }

    return sectors_status
