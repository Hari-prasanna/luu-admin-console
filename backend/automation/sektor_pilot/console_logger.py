"""
Simple console logging utility for Sektor Pilot.

Appends action logs to a Google Sheet "console_logs" tab.
Non-blocking: failures are logged locally, do not block API response.
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger("butler")


def log_to_console(
    action: str,
    sector_id: str,
    user: str = "system",
    status: str = "SUCCESS",
    details: str = ""
) -> None:
    """
    Log action to console (Google Sheets or local fallback).

    Args:
        action: Action name (START, PAUSE, STOP, etc)
        sector_id: Sector affected
        user: User who triggered action
        status: SUCCESS or FAILURE
        details: Additional details
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_entry = {
        "timestamp": timestamp,
        "action": action,
        "sector_id": sector_id,
        "user": user,
        "status": status,
        "details": details
    }

    logger.info(
        "console_log",
        extra=log_entry
    )

    # TODO: Implement Google Sheets append when sheets auth is ready
    # For now, logs go to butler.log via structured logging


def log_sector_start(sector_id: str, user: str = "system") -> None:
    """Log sector start action."""
    log_to_console("START", sector_id, user, "SUCCESS", "Worker started")


def log_sector_pause(sector_id: str, user: str = "system") -> None:
    """Log sector pause action."""
    log_to_console("PAUSE", sector_id, user, "SUCCESS", "Worker paused")


def log_sector_stop(sector_id: str, user: str = "system") -> None:
    """Log sector stop action."""
    log_to_console("STOP", sector_id, user, "SUCCESS", "Worker stopped")


def log_sector_error(
    action: str,
    sector_id: str,
    error_message: str,
    user: str = "system"
) -> None:
    """Log sector error."""
    log_to_console(action, sector_id, user, "FAILURE", error_message)
