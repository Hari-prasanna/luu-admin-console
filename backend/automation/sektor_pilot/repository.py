"""
Google Sheets audit ledger for Sektor Pilot operations.

Logs all user actions (start, pause, stop) and system events to a tracking spreadsheet.
Per Clean Code Chapter 2: intention-revealing names (not `log_start`, `log_pause`).
Per Clean Code Chapter 3: micro-functions (< 25 lines each, single responsibility).
Per Clean Code Chapter 7: specific typed exceptions — no bare except blocks.
"""

import logging
from datetime import datetime
from enum import Enum
from typing import List, Optional

from backend.exceptions import (
    GoogleSheetsAuthenticationError,
    GoogleSheetsNetworkError,
    GoogleSheetsDataError,
)
from backend.infrastructure.google_sheets import GoogleSheetsClient

logger = logging.getLogger(__name__)


# ─── Domain Models ───


class AuditActionType(str, Enum):
    """Enumeration of audit action types."""

    START_DOCKER = "START_DOCKER"
    PAUSE_DOCKER = "PAUSE_DOCKER"
    STOP_DOCKER = "STOP_DOCKER"
    IDLE_SHUTDOWN = "IDLE_SHUTDOWN"


class AuditOperationStatus(str, Enum):
    """Enumeration of operation statuses."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    PENDING = "PENDING"


# ─── Default Message Templates ───

AUDIT_ACTION_DEFAULT_MESSAGES: dict = {
    AuditActionType.START_DOCKER: {
        AuditOperationStatus.SUCCESS: "Worker started successfully",
        AuditOperationStatus.FAILURE: "Failed to start worker",
    },
    AuditActionType.PAUSE_DOCKER: {
        AuditOperationStatus.SUCCESS: "Worker paused successfully",
        AuditOperationStatus.FAILURE: "Failed to pause worker",
    },
    AuditActionType.STOP_DOCKER: {
        AuditOperationStatus.SUCCESS: "Worker stopped successfully",
        AuditOperationStatus.FAILURE: "Failed to stop worker",
    },
    AuditActionType.IDLE_SHUTDOWN: {
        AuditOperationStatus.SUCCESS: "Worker shut down due to 20-minute idle timeout",
        AuditOperationStatus.FAILURE: "",
    },
}

AUDIT_LOG_COLUMN_HEADERS = ["Timestamp", "User/Role", "Action", "Sector", "Status", "Message"]
AUDIT_LOG_RANGE_ALL_COLUMNS = "A:F"
AUDIT_LOG_START_CELL = "A1"


# ─── Entry Building ───


def _get_default_audit_message(
    action_type: AuditActionType,
    operation_status: AuditOperationStatus,
) -> str:
    """
    Look up default audit message for an action/status combination.

    Args:
        action_type: The audit action type
        operation_status: The operation result status

    Returns:
        Default message string, or empty string if no template found
    """
    return AUDIT_ACTION_DEFAULT_MESSAGES.get(action_type, {}).get(operation_status, "")


def _build_audit_entry_row(
    user_identifier: str,
    action_type: AuditActionType,
    sector_id: str,
    operation_status: AuditOperationStatus,
    audit_message: str,
) -> List[str]:
    """
    Build a single audit log row as a list of cell values.

    Args:
        user_identifier: User or role who triggered the action
        action_type: Type of action performed
        sector_id: Sector affected
        operation_status: Whether action succeeded or failed
        audit_message: Human-readable detail message

    Returns:
        List of 6 cell values: [timestamp, user, action, sector, status, message]
    """
    current_iso_timestamp = datetime.now().isoformat()
    return [
        current_iso_timestamp,
        user_identifier,
        action_type.value,
        sector_id,
        operation_status.value,
        audit_message,
    ]


def _ensure_headers_present(
    existing_audit_rows: List[List[str]],
) -> List[List[str]]:
    """
    Ensure audit log starts with correct column headers.

    Args:
        existing_audit_rows: Current rows from the audit sheet (may be empty)

    Returns:
        Rows list guaranteed to start with AUDIT_LOG_COLUMN_HEADERS
    """
    if not existing_audit_rows:
        return [AUDIT_LOG_COLUMN_HEADERS]

    if existing_audit_rows[0] != AUDIT_LOG_COLUMN_HEADERS:
        return [AUDIT_LOG_COLUMN_HEADERS] + existing_audit_rows

    return existing_audit_rows


# ─── Sheet I/O ───


def _read_existing_audit_rows(
    sheets_service: object,
    spreadsheet_id: str,
    audit_sheet_name: str,
) -> List[List[str]]:
    """
    Read all existing audit log rows from Google Sheets.

    Args:
        sheets_service: Google Sheets API service object
        spreadsheet_id: Google Sheets document ID
        audit_sheet_name: Sheet tab name for audit log

    Returns:
        List of row lists (empty list if sheet has no data)

    Raises:
        GoogleSheetsDataError: If API call fails
    """
    from googleapiclient.errors import HttpError
    from backend.infrastructure.google_sheets import _raise_typed_exception_for_http_error

    try:
        api_response = (
            sheets_service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"{audit_sheet_name}!{AUDIT_LOG_RANGE_ALL_COLUMNS}",
            )
            .execute()
        )
        return api_response.get("values", [])
    except HttpError as http_api_error:
        _raise_typed_exception_for_http_error(http_api_error, "read_audit_log")


def _write_audit_rows_to_sheet(
    sheets_service: object,
    spreadsheet_id: str,
    audit_sheet_name: str,
    all_audit_rows: List[List[str]],
) -> None:
    """
    Write all audit log rows back to Google Sheets (full overwrite).

    Args:
        sheets_service: Google Sheets API service object
        spreadsheet_id: Google Sheets document ID
        audit_sheet_name: Sheet tab name for audit log
        all_audit_rows: Complete list of rows to write (including headers)

    Raises:
        GoogleSheetsDataError: If API call fails
    """
    from googleapiclient.errors import HttpError
    from backend.infrastructure.google_sheets import _raise_typed_exception_for_http_error

    try:
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{audit_sheet_name}!{AUDIT_LOG_START_CELL}",
            valueInputOption="RAW",
            body={"values": all_audit_rows},
        ).execute()
    except HttpError as http_api_error:
        _raise_typed_exception_for_http_error(http_api_error, "write_audit_log")


# ─── Audit Ledger ───


class AuditLedger:
    """Manages audit logging to Google Sheets for all Sektor Pilot operations."""

    def __init__(
        self,
        credentials_file_path: Optional[str] = None,
        inline_credentials_json: Optional[str] = None,
    ) -> None:
        """
        Initialize audit ledger with Google Sheets credentials.

        Args:
            credentials_file_path: Path to service account JSON file
            inline_credentials_json: Inline service account JSON string

        Note:
            If initialization fails, ledger is silently disabled (sheets_client = None).
            Primary API actions are never blocked by audit ledger failures.
        """
        try:
            self._sheets_client = GoogleSheetsClient(
                credentials_file_path, inline_credentials_json
            )
            logger.info("audit_ledger_initialized")
        except GoogleSheetsAuthenticationError as auth_failure:
            logger.error(
                "audit_ledger_authentication_failed",
                extra={"error": str(auth_failure)},
            )
            self._sheets_client = None

    def _is_available(self) -> bool:
        """Check if audit ledger has a functioning Sheets client."""
        return self._sheets_client is not None

    def _load_audit_rows_with_fallback(
        self,
        spreadsheet_id: str,
        audit_sheet_name: str,
    ) -> List[List[str]]:
        """
        Load existing audit rows, returning empty list on any read failure.

        Args:
            spreadsheet_id: Google Sheets document ID
            audit_sheet_name: Sheet tab name

        Returns:
            Existing rows or empty list if read fails
        """
        try:
            return _read_existing_audit_rows(
                self._sheets_client.service,
                spreadsheet_id,
                audit_sheet_name,
            )
        except (GoogleSheetsDataError, GoogleSheetsNetworkError) as sheets_read_failure:
            logger.warning(
                "failed_to_read_existing_audit_log_starting_fresh",
                extra={"error": str(sheets_read_failure)},
            )
            return []

    def _append_entry_to_sheet(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        new_audit_entry_row: List[str],
    ) -> None:
        """
        Load existing audit rows, ensure headers, append entry, and write back.

        Args:
            spreadsheet_id: Google Sheets document ID
            sheet_name: Audit log sheet tab name
            new_audit_entry_row: New row to append

        Raises:
            GoogleSheetsDataError / GoogleSheetsNetworkError / GoogleSheetsAuthenticationError
        """
        existing_audit_rows = self._load_audit_rows_with_fallback(spreadsheet_id, sheet_name)
        audit_rows_with_headers = _ensure_headers_present(existing_audit_rows)
        audit_rows_with_headers.append(new_audit_entry_row)
        _write_audit_rows_to_sheet(
            self._sheets_client.service,
            spreadsheet_id,
            sheet_name,
            audit_rows_with_headers,
        )

    async def log_action(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        user: str,
        action: AuditActionType,
        sector_id: str,
        status: AuditOperationStatus,
        message: str = "",
    ) -> bool:
        """
        Append a single audit entry to the Google Sheets audit log.

        Non-blocking: returns False if audit service is unavailable rather than raising.
        Primary API action always completes regardless of audit logging outcome.

        Args:
            spreadsheet_id: Google Sheets document ID
            sheet_name: Audit log sheet tab name
            user: User identifier who triggered the action
            action: Action type enum
            sector_id: Sector affected by the action
            status: Operation result status enum
            message: Optional detail message (uses default template if empty)

        Returns:
            True if audit entry was written successfully, False otherwise
        """
        if not self._is_available():
            logger.warning("audit_ledger_unavailable_skipping_log")
            return False

        resolved_audit_message = message or _get_default_audit_message(action, status)
        new_audit_entry_row = _build_audit_entry_row(user, action, sector_id, status, resolved_audit_message)

        try:
            self._append_entry_to_sheet(spreadsheet_id, sheet_name, new_audit_entry_row)
            logger.info("audit_entry_logged", extra={"user": user, "action": action.value, "sector_id": sector_id, "status": status.value})
            return True
        except (GoogleSheetsDataError, GoogleSheetsNetworkError, GoogleSheetsAuthenticationError) as sheets_write_failure:
            logger.error("audit_entry_write_failed", extra={"sector_id": sector_id, "error": str(sheets_write_failure)})
            return False

    async def log_console_action(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        action_triggered: str,
        target_name: str,
    ) -> bool:
        """
        Append a console action entry to the console_logs sheet (flat row format).

        Row format: [Timestamp, "Hari Prasanna", Action_Triggered, Target_Name]

        Args:
            spreadsheet_id: Google Sheets document ID
            sheet_name: Console logs sheet tab name
            action_triggered: Action string (e.g., START_WORKER, PAUSE_WORKER, STOP_WORKER, AUTO_TIMEOUT)
            target_name: Target sector name

        Returns:
            True if entry was written successfully, False otherwise
        """
        if not self._is_available():
            logger.warning("audit_ledger_unavailable_skipping_console_log")
            return False

        console_entry_row = [
            datetime.now().isoformat(),
            "Hari Prasanna",
            action_triggered,
            target_name,
        ]

        try:
            self._append_entry_to_sheet(spreadsheet_id, sheet_name, console_entry_row)
            logger.info("console_action_logged", extra={"action": action_triggered, "target": target_name})
            return True
        except (GoogleSheetsDataError, GoogleSheetsNetworkError, GoogleSheetsAuthenticationError) as sheets_write_failure:
            logger.error("console_action_write_failed", extra={"action": action_triggered, "error": str(sheets_write_failure)})
            return False
