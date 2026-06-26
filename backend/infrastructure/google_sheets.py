"""
Google Sheets API client for Sektor Pilot operations.

Per Clean Code Chapter 2: intention-revealing names (no `e`, `f`, `values`).
Per Clean Code Chapter 3: micro-functions (< 25 lines each, single responsibility).
Per Clean Code Chapter 7: specific typed exceptions from backend.exceptions.
"""

import json
import os
from pathlib import Path
from typing import List, Optional

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.exceptions import (
    GoogleSheetsAuthenticationError,
    GoogleSheetsNetworkError,
    GoogleSheetsDataError,
)


# ─── Constants ───

GOOGLE_SHEETS_API_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
GOOGLE_SHEETS_CREDENTIALS_ENV_VAR = "GOOGLE_SHEETS_CREDENTIALS"
GOOGLE_SHEETS_CREDENTIALS_FILE_ENV_VAR = "GOOGLE_SHEETS_CREDENTIALS_JSON"


# ─── Credential Resolution ───


def _resolve_credentials_json_string(
    inline_credentials_json: Optional[str],
) -> Optional[str]:
    """
    Resolve Google Sheets credentials from inline JSON string or environment.

    Args:
        inline_credentials_json: Inline JSON string (optional, overrides env)

    Returns:
        Stripped credentials JSON string, or None if not provided
    """
    raw_credentials_json = inline_credentials_json or os.getenv(
        GOOGLE_SHEETS_CREDENTIALS_ENV_VAR, ""
    )
    return raw_credentials_json.strip() or None


def _resolve_credentials_file_path(
    credentials_file_path: Optional[str],
) -> Optional[str]:
    """
    Resolve Google Sheets credentials file path from argument or environment.

    Args:
        credentials_file_path: Explicit file path (optional, overrides env)

    Returns:
        Stripped file path string, or None if not provided
    """
    raw_file_path = credentials_file_path or os.getenv(
        GOOGLE_SHEETS_CREDENTIALS_FILE_ENV_VAR, ""
    )
    return raw_file_path.strip() or None


# ─── Credential Loading ───


def _load_credentials_from_json_string(
    credentials_json_string: str,
) -> Credentials:
    """
    Parse and validate Google service account credentials from JSON string.

    Args:
        credentials_json_string: Raw JSON string with service account data

    Returns:
        Authenticated Google Credentials object

    Raises:
        GoogleSheetsAuthenticationError: If JSON is invalid or credentials fail
    """
    try:
        service_account_dict = json.loads(credentials_json_string)
    except json.JSONDecodeError as json_parse_failure:
        raise GoogleSheetsAuthenticationError(
            "Invalid JSON in Google Sheets credentials string",
            context={
                "env_var": GOOGLE_SHEETS_CREDENTIALS_ENV_VAR,
                "char_count": len(credentials_json_string),
                "error": str(json_parse_failure),
            },
        ) from json_parse_failure

    try:
        return Credentials.from_service_account_info(
            service_account_dict, scopes=GOOGLE_SHEETS_API_SCOPES
        )
    except Exception as credential_creation_failure:
        raise GoogleSheetsAuthenticationError(
            "Failed to create Google credentials from JSON string",
            context={"error": str(credential_creation_failure)},
        ) from credential_creation_failure


def _load_credentials_from_file(
    credentials_file_path: str,
) -> Credentials:
    """
    Load Google service account credentials from a JSON file on disk.

    Args:
        credentials_file_path: Path to the service account JSON file

    Returns:
        Authenticated Google Credentials object

    Raises:
        GoogleSheetsAuthenticationError: If file is missing or credentials fail
    """
    if not Path(credentials_file_path).exists():
        raise GoogleSheetsAuthenticationError(
            f"Google Sheets credentials file not found: {credentials_file_path}",
            context={"path": credentials_file_path},
        )
    try:
        return Credentials.from_service_account_file(
            credentials_file_path, scopes=GOOGLE_SHEETS_API_SCOPES
        )
    except Exception as file_load_failure:
        raise GoogleSheetsAuthenticationError(
            f"Failed to load Google credentials from file: {credentials_file_path}",
            context={"path": credentials_file_path, "error": str(file_load_failure)},
        ) from file_load_failure


def _resolve_google_credentials(
    credentials_file_path: Optional[str],
    inline_credentials_json: Optional[str],
) -> Credentials:
    """
    Resolve Google Sheets credentials from either inline JSON or file.

    Inline JSON takes precedence over file path.

    Args:
        credentials_file_path: Path to service account JSON file (optional)
        inline_credentials_json: Inline JSON string (optional, higher priority)

    Returns:
        Authenticated Google Credentials object

    Raises:
        GoogleSheetsAuthenticationError: If neither source is provided or fails
    """
    resolved_json_string = _resolve_credentials_json_string(inline_credentials_json)
    resolved_file_path = _resolve_credentials_file_path(credentials_file_path)

    if not resolved_json_string and not resolved_file_path:
        raise GoogleSheetsAuthenticationError(
            "No Google Sheets credentials provided.",
            context={
                "hint_inline": f"Set {GOOGLE_SHEETS_CREDENTIALS_ENV_VAR} env var",
                "hint_file": f"Set {GOOGLE_SHEETS_CREDENTIALS_FILE_ENV_VAR} env var",
            },
        )

    if resolved_json_string:
        return _load_credentials_from_json_string(resolved_json_string)

    return _load_credentials_from_file(resolved_file_path)


# ─── Service Initialization ───


def _build_sheets_api_service(
    google_credentials: Credentials,
) -> object:
    """
    Build the Google Sheets API v4 service object.

    Args:
        google_credentials: Authenticated Google Credentials

    Returns:
        Google Sheets API service resource

    Raises:
        GoogleSheetsAuthenticationError: If service initialization fails
    """
    try:
        return build("sheets", "v4", credentials=google_credentials)
    except Exception as service_build_failure:
        raise GoogleSheetsAuthenticationError(
            "Failed to initialize Google Sheets API service",
            context={"error": str(service_build_failure)},
        ) from service_build_failure


# ─── HTTP Error Mapping ───


def _raise_typed_exception_for_http_error(
    http_error: HttpError,
    operation_description: str,
) -> None:
    """
    Map a Google API HttpError to a typed application exception.

    Args:
        http_error: The raw HttpError from Google API
        operation_description: Short description of the failed operation

    Raises:
        GoogleSheetsAuthenticationError: For 401/403 permission errors
        GoogleSheetsNetworkError: For 5xx server / connection errors
        GoogleSheetsDataError: For 400/404 data / range errors
    """
    http_status_code = http_error.resp.status
    error_context = {"operation": operation_description, "http_status": http_status_code}

    if http_status_code in (401, 403):
        raise GoogleSheetsAuthenticationError(
            f"Google Sheets permission denied during {operation_description}",
            context=error_context,
        ) from http_error

    if http_status_code >= 500:
        raise GoogleSheetsNetworkError(
            f"Google Sheets server error during {operation_description}",
            context=error_context,
        ) from http_error

    raise GoogleSheetsDataError(
        f"Google Sheets data error during {operation_description}",
        context=error_context,
    ) from http_error


# ─── Client ───


class GoogleSheetsClient:
    """
    Google Sheets client for Sektor Pilot sheet reads, writes, and clears.

    Raises typed exceptions (GoogleSheetsAuthenticationError, GoogleSheetsNetworkError,
    GoogleSheetsDataError) instead of raw HttpError, per Clean Code Chapter 7.
    """

    def __init__(
        self,
        credentials_file_path: Optional[str] = None,
        inline_credentials_json: Optional[str] = None,
    ) -> None:
        """
        Initialize with Google service account credentials.

        Inline JSON takes precedence over file path.

        Args:
            credentials_file_path: Path to service account JSON file
            inline_credentials_json: Inline service account JSON string

        Raises:
            GoogleSheetsAuthenticationError: If no credentials provided or authentication fails
        """
        google_credentials = _resolve_google_credentials(
            credentials_file_path, inline_credentials_json
        )
        self.service = _build_sheets_api_service(google_credentials)

    async def read_trigger_cell(
        self,
        spreadsheet_id: str,
        sheet_name: str = "test",
        trigger_cell: str = "A1",
    ) -> Optional[str]:
        """
        Read the LHM trigger cell value from Google Sheets.

        Args:
            spreadsheet_id: Google Sheets document ID
            sheet_name: Sheet tab name (default: "test")
            trigger_cell: Cell reference to read (default: "A1")

        Returns:
            String cell value, or None if cell is empty

        Raises:
            GoogleSheetsAuthenticationError: On permission errors
            GoogleSheetsNetworkError: On server/connection errors
            GoogleSheetsDataError: On invalid range or data errors
        """
        cell_range_reference = f"{sheet_name}!{trigger_cell}"
        try:
            api_response = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=cell_range_reference)
                .execute()
            )
        except HttpError as http_api_error:
            _raise_typed_exception_for_http_error(http_api_error, "read_trigger_cell")

        cell_value_matrix = api_response.get("values", [])
        if cell_value_matrix and cell_value_matrix[0]:
            return str(cell_value_matrix[0][0]).strip()
        return None

    async def write_sektor_data(
        self,
        spreadsheet_id: str,
        data_matrix: List[List],
        target_sheet_name: str = "sektor",
    ) -> None:
        """
        Clear the target sektor sheet and overwrite with a new data matrix.

        Args:
            spreadsheet_id: Google Sheets document ID
            data_matrix: 2D list of rows to write (header + data rows)
            target_sheet_name: Destination sheet tab name (default: "sektor")

        Raises:
            GoogleSheetsAuthenticationError: On permission errors
            GoogleSheetsNetworkError: On server/connection errors
            GoogleSheetsDataError: On invalid range or data errors
        """
        self._clear_sheet_range(spreadsheet_id, target_sheet_name)

        if data_matrix:
            self._write_values_to_range(
                spreadsheet_id,
                f"{target_sheet_name}!A1",
                data_matrix,
            )

    async def clear_trigger_cell(
        self,
        spreadsheet_id: str,
        sheet_name: str = "test",
        trigger_cell: str = "A1",
    ) -> None:
        """
        Clear the LHM trigger cell after successful processing.

        Args:
            spreadsheet_id: Google Sheets document ID
            sheet_name: Sheet tab name (default: "test")
            trigger_cell: Cell reference to clear (default: "A1")

        Raises:
            GoogleSheetsAuthenticationError: On permission errors
            GoogleSheetsNetworkError: On server/connection errors
            GoogleSheetsDataError: On invalid range or data errors
        """
        cell_range_reference = f"{sheet_name}!{trigger_cell}"
        self._clear_sheet_range(spreadsheet_id, cell_range_reference)

    def _clear_sheet_range(
        self,
        spreadsheet_id: str,
        range_reference: str,
    ) -> None:
        """
        Clear a named range in Google Sheets.

        Args:
            spreadsheet_id: Google Sheets document ID
            range_reference: Range notation (e.g., "sektor", "test!A1")

        Raises:
            GoogleSheetsAuthenticationError / GoogleSheetsNetworkError / GoogleSheetsDataError
        """
        try:
            self.service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=range_reference,
            ).execute()
        except HttpError as http_api_error:
            _raise_typed_exception_for_http_error(http_api_error, f"clear_range:{range_reference}")

    def _write_values_to_range(
        self,
        spreadsheet_id: str,
        range_reference: str,
        data_matrix: List[List],
    ) -> None:
        """
        Write a 2D data matrix to a named range in Google Sheets.

        Args:
            spreadsheet_id: Google Sheets document ID
            range_reference: Starting range notation (e.g., "sektor!A1")
            data_matrix: 2D list of rows to write

        Raises:
            GoogleSheetsAuthenticationError / GoogleSheetsNetworkError / GoogleSheetsDataError
        """
        try:
            self.service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_reference,
                valueInputOption="RAW",
                body={"values": data_matrix},
            ).execute()
        except HttpError as http_api_error:
            _raise_typed_exception_for_http_error(http_api_error, f"write_range:{range_reference}")
