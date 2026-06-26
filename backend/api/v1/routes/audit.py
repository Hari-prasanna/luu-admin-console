"""Audit log endpoints."""

import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query, Path, Depends

from .auth import require_admin_role, read_audit_logs_list

logger = logging.getLogger("luu.api.audit")
router = APIRouter(prefix="/audit", tags=["audit"])


@router.get(
    "/logs",
    summary="Get audit logs",
    description="Retrieve paginated audit log entries"
)
async def get_audit_logs(
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    event: Optional[str] = Query(default=None),
    actor: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    admin: Dict[str, Any] = Depends(require_admin_role),
) -> Dict[str, Any]:
    """
    Get audit logs.

    Retrieve paginated audit log entries with optional filtering.
    """
    try:
        logs = _filter_audit_logs(
            logs=read_audit_logs_list(),
            event=event,
            actor=actor,
            status=status,
            query=None,
        )
        return _format_audit_response(logs=logs, limit=limit, offset=offset)
    except Exception as e:
        logger.error("get_audit_logs_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to retrieve audit logs")


def _filter_audit_logs(
    logs: List[Dict[str, Any]],
    event: Optional[str],
    actor: Optional[str],
    status: Optional[str],
    query: Optional[str],
) -> List[Dict[str, Any]]:
    """Filter audit logs by known criteria."""
    filtered = logs

    if event:
        event_lower = event.lower()
        filtered = [log for log in filtered if str(log.get("event", "")).lower() == event_lower]

    if actor:
        actor_lower = actor.lower()
        filtered = [log for log in filtered if str(log.get("actor", "")).lower() == actor_lower]

    if status:
        status_lower = status.lower()
        status_aliases = {
            "failed": "failure",
            "failure": "failure",
            "success": "success",
            "blocked": "blocked",
        }
        normalized = status_aliases.get(status_lower, status_lower)
        filtered = [
            log
            for log in filtered
            if status_aliases.get(str(log.get("status", "")).lower(), str(log.get("status", "")).lower()) == normalized
        ]

    if query:
        query_lower = query.lower()
        filtered = [
            log
            for log in filtered
            if (
                query_lower in str(log.get("detail", "")).lower()
                or query_lower in str(log.get("path", "")).lower()
                or query_lower in str(log.get("event", "")).lower()
                or query_lower in str(log.get("actor", "")).lower()
            )
        ]

    return filtered


def _format_audit_response(logs: List[Dict[str, Any]], limit: int, offset: int) -> Dict[str, Any]:
    """Return paginated response in frontend-compatible shape."""
    total = len(logs)
    ordered = list(reversed(logs))
    page_items = ordered[offset: offset + limit]

    return {
        "status": "ok",
        "logs": page_items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get(
    "/search",
    summary="Search audit logs",
    description="Search audit logs with multiple filters"
)
async def search_audit_logs(
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    event: Optional[str] = Query(default=None),
    actor: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    query: Optional[str] = Query(default=None),
    admin: Dict[str, Any] = Depends(require_admin_role),
) -> Dict[str, Any]:
    """
    Search audit logs with advanced filtering.
    """
    try:
        logs = _filter_audit_logs(
            logs=read_audit_logs_list(),
            event=event,
            actor=actor,
            status=status,
            query=query,
        )
        return _format_audit_response(logs=logs, limit=limit, offset=offset)
    except Exception as e:
        logger.error("audit_search_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to search audit logs")


@router.get(
    "/trace/{request_id}",
    summary="Trace request",
    description="Get all audit events for a specific request"
)
async def trace_request(
    request_id: str = Path(..., min_length=1),
    admin: Dict[str, Any] = Depends(require_admin_role),
) -> Dict[str, Any]:
    """
    Trace request - retrieve all audit events for a specific request ID.
    """
    try:
        matching = [
            log
            for log in read_audit_logs_list()
            if str(log.get("request_id", "")).strip() == request_id
        ]

        return {
            "status": "ok",
            "request_id": request_id,
            "logs": matching,
            "total": len(matching),
        }
    except Exception as e:
        logger.error("request_trace_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to trace request")
