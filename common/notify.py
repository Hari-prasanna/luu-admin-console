#!/usr/bin/env python3

"""
notify.py — Shared Google Chat notification service for dashboard monitoring.

Sends state-change alerts (failure/recovery) to Google Chat via webhook.
Implements non-blocking, idempotent notification logic with structured logging.
Per Clean Code principles: type hints, defensive error handling, micro-functions < 25 lines.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional, Dict, Any

# Reuse caller's logger so notifications land in the same butler.log
logger = logging.getLogger("butler")

WEBHOOK_ENV_VAR = "CHAT_WEBHOOK_URL"
WEBHOOK_TIMEOUT_SECONDS = 10


def get_formatted_timestamp() -> str:
    """Get current timestamp formatted as YYYY-MM-DD HH:MM:SS."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def send_google_chat_payload(
    payload: Dict[str, Any],
    log_summary: str
) -> bool:
    """
    Post structured JSON card payload to Google Chat.

    Returns True if sent successfully, False otherwise.
    Never raises — network errors are logged and swallowed.

    Args:
        payload: CardsV2 JSON payload
        log_summary: Summary string for logging

    Returns:
        True if sent, False if webhook unavailable or error
    """
    webhook_url = os.environ.get(WEBHOOK_ENV_VAR)
    if not webhook_url:
        logger.warning(
            "google_chat_webhook_not_configured",
            extra={
                "env_var": WEBHOOK_ENV_VAR,
                "summary": log_summary
            }
        )
        return False

    try:
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers = {
            "Content-Type": "application/json; charset=UTF-8"
        }

        http_request = urllib.request.Request(
            webhook_url,
            data=payload_bytes,
            headers=request_headers,
            method="POST"
        )

        with urllib.request.urlopen(
            http_request,
            timeout=WEBHOOK_TIMEOUT_SECONDS
        ) as http_response:
            response_status = http_response.status
            if 200 <= response_status < 300:
                logger.info(
                    "google_chat_notification_sent",
                    extra={"summary": log_summary, "status": response_status}
                )
                return True

            logger.warning(
                "google_chat_webhook_error",
                extra={"status": response_status, "summary": log_summary}
            )
            return False

    except urllib.error.URLError as url_error:
        logger.warning(
            "google_chat_webhook_unreachable",
            extra={"error": str(url_error), "summary": log_summary}
        )
        return False
    except Exception as unexpected_error:
        logger.warning(
            "google_chat_notification_failed",
            extra={"error": str(unexpected_error), "summary": log_summary}
        )
        return False


def create_failure_notification_payload(
    dashboard_name: str,
    error_message: str
) -> Dict[str, Any]:
    """
    Create CardsV2 payload for failure notification.

    Args:
        dashboard_name: Name of the dashboard that failed
        error_message: Error details to display

    Returns:
        CardsV2 JSON payload structure
    """
    failure_color = "#D93025"  # Red
    failure_status = "Update Failed"
    failure_icon = "cancel"
    error_display_text = error_message or "Unknown operational failure"

    widgets = [
        {
            "decoratedText": {
                "startIcon": {"materialIcon": {"name": failure_icon}},
                "text": f'<font color="{failure_color}"><b>{failure_status}</b></font>',
            }
        },
        {
            "decoratedText": {
                "startIcon": {"materialIcon": {"name": "calendar_month"}},
                "topLabel": "Timestamp",
                "text": get_formatted_timestamp(),
            }
        },
        {
            "decoratedText": {
                "startIcon": {"materialIcon": {"name": "error"}},
                "topLabel": "Error Details",
                "text": error_display_text,
                "wrapText": True,
            }
        },
        {
            "decoratedText": {
                "startIcon": {"materialIcon": {"name": "build"}},
                "text": "Automated data retrieval is blocked. Metrics remain frozen.",
                "wrapText": True,
            }
        }
    ]

    return {
        "cardsV2": [
            {
                "cardId": "pipeline_failure_card",
                "card": {
                    "header": {
                        "title": f"Dashboard Monitor: {dashboard_name}",
                        "subtitle": "Automation Monitoring System",
                    },
                    "sections": [{"widgets": widgets}],
                },
            }
        ]
    }


def create_recovery_notification_payload(dashboard_name: str) -> Dict[str, Any]:
    """
    Create CardsV2 payload for recovery notification.

    Args:
        dashboard_name: Name of the dashboard that recovered

    Returns:
        CardsV2 JSON payload structure
    """
    recovery_color = "#188038"  # Green
    recovery_status = "Update Successful (Recovered)"
    recovery_icon = "check_circle"

    widgets = [
        {
            "decoratedText": {
                "startIcon": {"materialIcon": {"name": recovery_icon}},
                "text": f'<font color="{recovery_color}"><b>{recovery_status}</b></font>',
            }
        },
        {
            "decoratedText": {
                "startIcon": {"materialIcon": {"name": "calendar_month"}},
                "topLabel": "Timestamp",
                "text": get_formatted_timestamp(),
            }
        },
        {
            "decoratedText": {
                "startIcon": {"materialIcon": {"name": "speed"}},
                "text": "Communication channel restored. Live data stream processing normally.",
                "wrapText": True,
            }
        }
    ]

    return {
        "cardsV2": [
            {
                "cardId": "pipeline_recovery_card",
                "card": {
                    "header": {
                        "title": f"Dashboard Monitor: {dashboard_name}",
                        "subtitle": "Automation Monitoring System",
                    },
                    "sections": [{"widgets": widgets}],
                },
            }
        ]
    }


def send_failure_notification(dashboard_name: str, error_message: str) -> bool:
    """
    Send failure alert to Google Chat.

    Args:
        dashboard_name: Name of failing dashboard
        error_message: Error details

    Returns:
        True if sent, False if webhook unavailable
    """
    payload = create_failure_notification_payload(dashboard_name, error_message)
    return send_google_chat_payload(payload, f"Failure Alert - {error_message}")


def send_recovery_notification(dashboard_name: str) -> bool:
    """
    Send recovery alert to Google Chat.

    Args:
        dashboard_name: Name of recovered dashboard

    Returns:
        True if sent, False if webhook unavailable
    """
    payload = create_recovery_notification_payload(dashboard_name)
    return send_google_chat_payload(payload, "Recovery Alert - System Restored")


def read_last_known_state(state_file: str) -> str:
    """
    Read last known status from state file.

    Returns 'ok' if file missing or any error occurs.

    Args:
        state_file: Path to state file

    Returns:
        'ok' or 'fail'
    """
    try:
        if os.path.isfile(state_file):
            with open(state_file, encoding="utf-8") as state_stream:
                saved_state = state_stream.read().strip()
                if saved_state:
                    logger.debug(
                        "last_state_loaded",
                        extra={"state": saved_state}
                    )
                    return saved_state
    except Exception as read_error:
        logger.warning(
            "failed_to_read_state_file",
            extra={"file": state_file, "error": str(read_error)}
        )
    return "ok"


def write_current_state(state_file: str, current_status: str) -> None:
    """
    Persist current status to state file.

    Args:
        state_file: Path to state file
        current_status: 'ok' or 'fail'
    """
    try:
        state_dir = os.path.dirname(state_file)
        if state_dir:
            os.makedirs(state_dir, exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as state_stream:
            state_stream.write(current_status)
        logger.debug("state_persisted", extra={"state": current_status})
    except Exception as write_error:
        logger.warning(
            "failed_to_write_state_file",
            extra={"file": state_file, "error": str(write_error)}
        )


def report_dashboard_outcome(
    dashboard_name: str,
    state_file: str,
    operation_succeeded: bool,
    error_message: str = ""
) -> None:
    """
    Report dashboard operation outcome (success/failure).

    Sends notification ONLY on state change (failure→recovery or recovery→failure).
    Avoids spam by staying silent when status is unchanged.

    Args:
        dashboard_name: Name of dashboard
        state_file: Path to persistent state file
        operation_succeeded: True if operation succeeded, False if failed
        error_message: Error details (if failed)
    """
    prior_status = read_last_known_state(state_file)
    current_status = "ok" if operation_succeeded else "fail"

    # State transition: was_ok, now_failing → send failure alert
    if current_status == "fail" and prior_status != "fail":
        logger.info(
            "state_transition_to_failure",
            extra={"dashboard": dashboard_name}
        )
        send_failure_notification(dashboard_name, error_message)

    # State transition: was_failing, now_ok → send recovery alert
    elif current_status == "ok" and prior_status == "fail":
        logger.info(
            "state_transition_to_recovery",
            extra={"dashboard": dashboard_name}
        )
        send_recovery_notification(dashboard_name)

    # No state change → stay silent
    else:
        logger.debug(
            "status_unchanged_no_notification",
            extra={"dashboard": dashboard_name, "status": current_status}
        )

    # Persist new state
    write_current_state(state_file, current_status)
