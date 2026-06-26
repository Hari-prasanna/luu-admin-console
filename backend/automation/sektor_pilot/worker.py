#!/usr/bin/env python3

"""
Sektor Pilot worker: continuously polls Google Sheets for LHM ID trigger.

When detected, fetches ZAL_BESTAND data from Oracle and writes to sektor sheet.
Worker auto-exits after 20 minutes of idle (no valid LHM received).

Per Clean Code Chapter 2: meaningful names (no `current_time`, use `current_unix_timestamp`).
Per Clean Code Chapter 3: micro-functions (< 25 lines each).
Per Clean Code Chapter 7: specific typed exceptions — no bare except blocks.
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional

from backend.exceptions import (
    OracleConnectionError,
    OracleQueryError,
    GoogleSheetsAuthenticationError,
    GoogleSheetsNetworkError,
    GoogleSheetsDataError,
    ConfigurationError,
)
from backend.infrastructure.google_sheets import GoogleSheetsClient
from backend.infrastructure import oracle_pool as db_client
from backend.repositories import AuditRepository
from backend.database import AsyncSessionLocal
from backend.automation.sektor_pilot.sector_config import get_sector_config


# ─── Logging Setup ───


def _configure_rotating_logger(logger_name: str) -> logging.Logger:
    """
    Configure logger with console and rotating file handlers.

    Args:
        logger_name: Identifier for this logger instance

    Returns:
        Configured Logger instance
    """
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    worker_logger = logging.getLogger(logger_name)
    worker_logger.setLevel(logging.INFO)
    worker_logger.propagate = False

    if worker_logger.handlers:
        worker_logger.handlers.clear()

    log_formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    worker_logger.addHandler(console_handler)

    rotating_file_handler = RotatingFileHandler(
        log_dir / "worker.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    rotating_file_handler.setFormatter(log_formatter)
    worker_logger.addHandler(rotating_file_handler)

    return worker_logger


logger = _configure_rotating_logger("sektor_worker")


# ─── Configuration Loading ───


def _build_default_worker_config() -> dict:
    """
    Return default worker configuration dict with sensible operational defaults.

    Returns:
        Dict with poll_interval_seconds, idle_timeout_seconds, google_sheets, oracle sections
    """
    return {
        "poll_interval_seconds": 3,
        "idle_timeout_seconds": 1200,  # 20 minutes
        "google_sheets": {
            "spreadsheet_id": "",
            "trigger_sheet_name": "Inventur",
            "test_sheet_name": "Inventur",
            "trigger_cell": "A1",
            "target_sheet_name": "sektor",
            "sektor_sheet_name": "sektor",
        },
        "oracle": {
            "query_timeout_seconds": 30,
        },
    }


def _merge_user_config_into_defaults(
    default_worker_config: dict,
    user_supplied_config: dict,
) -> dict:
    """
    Merge user-supplied config values into the default config dict.

    Merges top-level keys and nested google_sheets / oracle sections independently.

    Args:
        default_worker_config: Base config with all defaults pre-populated
        user_supplied_config: User config loaded from config.json

    Returns:
        Merged config dict
    """
    merged_config = dict(default_worker_config)

    for top_level_key in user_supplied_config:
        if top_level_key not in ("google_sheets", "oracle"):
            merged_config[top_level_key] = user_supplied_config[top_level_key]

    if "google_sheets" in user_supplied_config:
        merged_config["google_sheets"].update(user_supplied_config["google_sheets"])

    if "oracle" in user_supplied_config:
        merged_config["oracle"].update(user_supplied_config["oracle"])

    return merged_config


def _resolve_spreadsheet_id(merged_worker_config: dict) -> str:
    """
    Resolve spreadsheet ID from config or environment variable fallback chain.

    Priority: config.json google_sheets.spreadsheet_id → top-level key → OS env var.

    Args:
        merged_worker_config: Fully merged worker configuration dict

    Returns:
        Resolved spreadsheet ID string (may be empty string if unconfigured)
    """
    return (
        merged_worker_config["google_sheets"].get("spreadsheet_id", "")
        or merged_worker_config.get("GOOGLE_SHEETS_SPREADSHEET_ID", "")
        or os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    )


def _load_config_json_file(config_file_path: Path) -> Optional[dict]:
    """
    Load and parse config.json from disk.

    Args:
        config_file_path: Path to the config.json file

    Returns:
        Parsed dict if file exists and is valid JSON, None otherwise
    """
    if not config_file_path.exists():
        logger.info(
            "config_file_not_found_using_defaults",
            extra={"config_path": str(config_file_path)},
        )
        return None

    try:
        with open(config_file_path, encoding="utf-8") as config_file_stream:
            parsed_config = json.load(config_file_stream)
        logger.info("loaded_configuration", extra={"config_path": str(config_file_path)})
        return parsed_config
    except (json.JSONDecodeError, OSError) as config_load_failure:
        logger.warning(
            "failed_to_load_config_using_defaults",
            extra={
                "config_path": str(config_file_path),
                "error": str(config_load_failure),
            },
        )
        return None


def load_worker_config() -> dict:
    """
    Load worker configuration from config.json with fallback to defaults.

    Spreadsheet ID resolution order:
    1. config.json google_sheets.spreadsheet_id
    2. config.json top-level GOOGLE_SHEETS_SPREADSHEET_ID
    3. OS environment variable GOOGLE_SHEETS_SPREADSHEET_ID

    Returns:
        Merged config dict with all required sections
    """
    config_file_path = Path(__file__).parent / "config.json"
    default_worker_config = _build_default_worker_config()
    user_supplied_config = _load_config_json_file(config_file_path)

    if user_supplied_config is None:
        return default_worker_config

    merged_worker_config = _merge_user_config_into_defaults(
        default_worker_config, user_supplied_config
    )
    merged_worker_config["google_sheets"]["spreadsheet_id"] = _resolve_spreadsheet_id(
        merged_worker_config
    )
    return merged_worker_config


# ─── Trigger Reading ───


async def read_trigger_lhm_id(
    sheets_client: GoogleSheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    trigger_cell: str,
) -> Optional[str]:
    """
    Read the LHM ID trigger from Google Sheets trigger cell.

    Args:
        sheets_client: Authenticated Google Sheets client
        spreadsheet_id: Google Sheets document ID
        sheet_name: Sheet tab name containing trigger cell
        trigger_cell: Cell reference (e.g., 'A1')

    Returns:
        LHM ID string or None if cell is empty or read fails
    """
    try:
        return await sheets_client.read_trigger_cell(
            spreadsheet_id, sheet_name, trigger_cell
        )
    except (GoogleSheetsAuthenticationError, GoogleSheetsNetworkError, GoogleSheetsDataError) as sheets_read_failure:
        logger.error(
            "failed_to_read_trigger_cell",
            extra={"trigger_cell": trigger_cell, "error": str(sheets_read_failure)},
        )
        return None


# ─── Data Writing ───


def _build_sheet_header_row() -> list:
    """
    Build header row for sektor sheet (columns A through M).

    Returns:
        List containing a single header row (as list of lists for Sheets API)
    """
    return [[
        "MainLhm", "", "", "ARTNR", "", "Qualität",
        "ANZ", "", "", "", "", "Sortierziel ID", "SortKriterium",
    ]]


SEKTOR_COLUMN_LETTER_MAP = {
    "MainLhm": "A",
    "ARTNR": "D",
    "Qualität": "F",
    "ANZ": "G",
    "Sortierziel ID": "L",
    "SortKriterium": "M",
}

SEKTOR_COLUMN_INDEX_MAP = {
    column_name: ord(column_letter) - ord("A")
    for column_name, column_letter in SEKTOR_COLUMN_LETTER_MAP.items()
}

SEKTOR_TOTAL_COLUMN_COUNT = 13  # Columns A through M


def _normalize_anz_value(raw_anz_value: object) -> object:
    """
    Normalize the ANZ (quantity) column value to integer if possible.

    Args:
        raw_anz_value: Raw value from Oracle cursor (may be Decimal, str, int)

    Returns:
        Integer if conversion succeeds, original value otherwise
    """
    try:
        return int(float(raw_anz_value))
    except (ValueError, TypeError):
        return raw_anz_value


def _map_oracle_row_to_sheet_row(
    oracle_row_dict: dict,
) -> list:
    """
    Map a single Oracle row dict to a 13-column Google Sheet row list.

    Args:
        oracle_row_dict: Dict with Oracle column names as keys

    Returns:
        List of 13 string values (empty string for unmapped columns)
    """
    sheet_row_values = [""] * SEKTOR_TOTAL_COLUMN_COUNT

    for oracle_column_name, column_index in SEKTOR_COLUMN_INDEX_MAP.items():
        raw_cell_value = oracle_row_dict.get(oracle_column_name, "")

        if oracle_column_name == "ANZ" and raw_cell_value:
            raw_cell_value = _normalize_anz_value(raw_cell_value)

        sheet_row_values[column_index] = str(raw_cell_value) if raw_cell_value != "" else ""

    return sheet_row_values


def _build_sektor_data_matrix(oracle_rows: list) -> list:
    """
    Build complete sektor sheet data matrix from Oracle rows (header + data rows).

    Args:
        oracle_rows: List of Oracle row dicts from ZAL_BESTAND query

    Returns:
        2D list ready to write to Google Sheets (header row + mapped data rows)
    """
    data_matrix = _build_sheet_header_row()
    for oracle_row_dict in oracle_rows:
        data_matrix.append(_map_oracle_row_to_sheet_row(oracle_row_dict))
    return data_matrix


async def _fetch_oracle_rows_for_lhm(detected_lhm_id: str) -> Optional[list]:
    """
    Fetch ZAL_BESTAND rows from Oracle for the given LHM ID.

    Args:
        detected_lhm_id: LHM identifier to query

    Returns:
        List of row dicts, or None if Oracle call failed
    """
    try:
        return await db_client.fetch_lhm_data(detected_lhm_id)
    except (OracleConnectionError, OracleQueryError, ConfigurationError) as oracle_fetch_failure:
        logger.error(
            "failed_to_fetch_lhm_data_from_oracle",
            extra={"lhm_id": detected_lhm_id, "error": str(oracle_fetch_failure)},
        )
        return None


async def _write_oracle_rows_to_sektor_sheet(
    sheets_client: GoogleSheetsClient,
    spreadsheet_id: str,
    detected_lhm_id: str,
    oracle_rows: list,
    target_sheet_name: str,
) -> bool:
    """
    Build sektor data matrix from Oracle rows and write to Google Sheets.

    Args:
        sheets_client: Authenticated Google Sheets client
        spreadsheet_id: Google Sheets document ID
        detected_lhm_id: LHM ID (used for logging context)
        oracle_rows: List of Oracle row dicts to write

    Returns:
        True if write succeeded, False otherwise
    """
    sektor_data_matrix = _build_sektor_data_matrix(oracle_rows)
    logger.info(
        "writing_lhm_data_to_sektor_sheet",
        extra={"lhm_id": detected_lhm_id, "row_count": len(oracle_rows)},
    )
    try:
        await sheets_client.write_sektor_data(
            spreadsheet_id,
            sektor_data_matrix,
            target_sheet_name=target_sheet_name,
        )
        return True
    except (GoogleSheetsAuthenticationError, GoogleSheetsNetworkError, GoogleSheetsDataError) as sheets_write_failure:
        logger.error(
            "failed_to_write_lhm_data_to_sheets",
            extra={"lhm_id": detected_lhm_id, "error": str(sheets_write_failure)},
        )
        return False


async def fetch_and_write_lhm_data(
    sheets_client: GoogleSheetsClient,
    spreadsheet_id: str,
    detected_lhm_id: str,
    target_sheet_name: str,
) -> bool:
    """
    Fetch ZAL_BESTAND data from Oracle and write to sektor sheet.

    Args:
        sheets_client: Authenticated Google Sheets client
        spreadsheet_id: Google Sheets document ID
        detected_lhm_id: LHM ID to query in Oracle

    Returns:
        True if fetch and write succeeded, False otherwise
    """
    logger.info("fetching_lhm_data", extra={"lhm_id": detected_lhm_id})
    oracle_rows = await _fetch_oracle_rows_for_lhm(detected_lhm_id)

    if oracle_rows is None:
        return False

    if not oracle_rows:
        logger.warning("no_data_found_for_lhm_id", extra={"lhm_id": detected_lhm_id})
        await sheets_client.write_sektor_data(
            spreadsheet_id,
            [],
            target_sheet_name=target_sheet_name,
        )
        return True

    return await _write_oracle_rows_to_sektor_sheet(
        sheets_client,
        spreadsheet_id,
        detected_lhm_id,
        oracle_rows,
        target_sheet_name,
    )


# ─── Trigger Clearing ───


async def clear_trigger_cell(
    sheets_client: GoogleSheetsClient,
    spreadsheet_id: str,
    sheet_name: str,
    trigger_cell: str,
) -> bool:
    """
    Skip clearing the trigger cell to preserve history for search functionality.

    The trigger cell is kept intact to allow users to search and view the
    complete history of processed LHM entries.

    Args:
        sheets_client: Authenticated Google Sheets client
        spreadsheet_id: Google Sheets document ID
        sheet_name: Sheet tab name containing trigger cell
        trigger_cell: Cell reference (kept intact, not cleared)

    Returns:
        Always True (no-op operation succeeds)
    """
    logger.info(
        "trigger_cell_kept_intact_for_history",
        extra={"trigger_cell": trigger_cell},
    )
    return True


# ─── Trigger Processing ───


async def process_detected_lhm_trigger(
    sheets_client: GoogleSheetsClient,
    spreadsheet_id: str,
    detected_lhm_id: str,
    prior_lhm_id: Optional[str],
    test_sheet_name: str,
    trigger_cell: str,
    target_sheet_name: str,
) -> bool:
    """
    Process a detected LHM trigger: fetch from Oracle, write to sheet, clear trigger.

    Args:
        sheets_client: Authenticated Google Sheets client
        spreadsheet_id: Google Sheets document ID
        detected_lhm_id: New LHM ID from trigger cell
        prior_lhm_id: Previously processed LHM (for logging context only)
        test_sheet_name: Sheet name containing the trigger cell
        trigger_cell: Trigger cell reference

    Returns:
        True if all three steps succeeded, False otherwise
    """
    logger.info(
        "state_transition_new_trigger_detected",
        extra={"new_lhm_id": detected_lhm_id, "prior_lhm_id": prior_lhm_id},
    )

    if not await fetch_and_write_lhm_data(
        sheets_client,
        spreadsheet_id,
        detected_lhm_id,
        target_sheet_name,
    ):
        logger.error("fetch_write_failed_skipping_trigger_clear")
        return False

    if not await clear_trigger_cell(sheets_client, spreadsheet_id, test_sheet_name, trigger_cell):
        logger.error("trigger_clear_failed_will_retry_next_cycle")
        return False

    logger.info(
        "state_transition_processing_complete",
        extra={"processed_lhm_id": detected_lhm_id},
    )
    return True


# ─── Idle Timeout Detection ───


def detect_idle_timeout_exceeded(
    last_active_unix_timestamp: float,
    idle_threshold_seconds: int,
) -> bool:
    """
    Check whether the worker has exceeded the idle timeout threshold.

    Worker exits to free resources when idle for the configured period.

    Args:
        last_active_unix_timestamp: Unix timestamp of last successful trigger
        idle_threshold_seconds: Idle threshold in seconds (typically 1200 = 20 min)

    Returns:
        True if elapsed idle time exceeds threshold, False otherwise
    """
    current_unix_timestamp = time.time()
    elapsed_idle_seconds = current_unix_timestamp - last_active_unix_timestamp
    return elapsed_idle_seconds > idle_threshold_seconds


# ─── Pause State Detection ───


def detect_pause_signal_file() -> bool:
    """
    Check if the pause signal file exists in the worker directory.

    When present, worker suspends polling without terminating the process.

    Returns:
        True if .pause file exists, False otherwise
    """
    pause_signal_file = Path(__file__).parent / ".pause"
    return pause_signal_file.exists()


# ─── Poll Cycle Handlers ───


async def _handle_pause_cycle(
    is_currently_paused: bool,
    poll_interval_seconds: int,
) -> bool:
    """
    Handle a polling cycle where pause signal is active.

    Logs transition to paused state on first detection only.

    Args:
        is_currently_paused: Whether worker was already paused last cycle
        poll_interval_seconds: Duration to sleep before next cycle

    Returns:
        True (new paused state to persist in caller)
    """
    if not is_currently_paused:
        logger.info("pause_signal_detected_entering_idle_state")
    await asyncio.sleep(poll_interval_seconds)
    return True


def _handle_resume_from_pause(is_currently_paused: bool) -> bool:
    """
    Handle resumption when pause signal file is no longer present.

    Args:
        is_currently_paused: Whether worker was paused last cycle

    Returns:
        False (new unpaused state to persist in caller)
    """
    if is_currently_paused:
        logger.info("pause_signal_cleared_resuming_polling")
    return False


def _should_skip_duplicate_trigger(
    detected_lhm_id: str,
    last_processed_lhm_id: Optional[str],
    poll_cycle_count: int,
) -> bool:
    """
    Check if the detected trigger is unchanged since last processing.

    Logs at debug level every 20 cycles to avoid log noise.

    Args:
        detected_lhm_id: LHM ID read from trigger cell this cycle
        last_processed_lhm_id: LHM ID from the last successfully processed cycle
        poll_cycle_count: Running count of poll cycles (for periodic logging)

    Returns:
        True if trigger is a duplicate and should be skipped
    """
    if detected_lhm_id != last_processed_lhm_id:
        return False

    if poll_cycle_count % 20 == 0:
        logger.debug(
            "poll_cycle_unchanged_trigger",
            extra={"poll_count": poll_cycle_count, "lhm_id": detected_lhm_id},
        )
    return True


# ─── Worker Initialization ───


def _extract_worker_settings_from_config(
    worker_config: dict,
) -> tuple:
    """
    Extract and return individual worker settings from merged config dict.

    Args:
        worker_config: Merged config from load_worker_config()

    Returns:
        Tuple of (poll_interval_seconds, idle_timeout_seconds,
                  spreadsheet_id, trigger_sheet_name, trigger_cell, target_sheet_name)
    """
    poll_interval_seconds = worker_config.get("poll_interval_seconds", 3)
    idle_timeout_seconds = worker_config.get("idle_timeout_seconds", 1200)
    spreadsheet_id = worker_config["google_sheets"].get("spreadsheet_id", "")
    trigger_sheet_name = (
        worker_config["google_sheets"].get("trigger_sheet_name")
        or worker_config["google_sheets"].get("test_sheet_name")
        or "Inventur"
    )
    trigger_cell = worker_config["google_sheets"].get("trigger_cell", "A1")
    target_sheet_name = (
        worker_config["google_sheets"].get("target_sheet_name")
        or worker_config["google_sheets"].get("sektor_sheet_name")
        or "sektor"
    )
    return (
        poll_interval_seconds,
        idle_timeout_seconds,
        spreadsheet_id,
        trigger_sheet_name,
        trigger_cell,
        target_sheet_name,
    )


def _apply_sector_overrides(worker_config: dict, sector_id: str) -> dict:
    """
    Apply sector-specific Google Sheets routing from sector_config.py.

    Args:
        worker_config: Base worker config from config file/defaults
        sector_id: Sector identifier passed via SECTOR_ID environment variable

    Returns:
        Updated worker config with sector-specific spreadsheet and sheet names
    """
    if not sector_id or sector_id == "unknown":
        return worker_config

    sector_config = get_sector_config(sector_id)
    merged_config = dict(worker_config)
    merged_config["google_sheets"] = dict(worker_config["google_sheets"])
    merged_config["google_sheets"]["spreadsheet_id"] = sector_config.get(
        "spreadsheet_id", ""
    )
    merged_config["google_sheets"]["trigger_sheet_name"] = sector_config.get(
        "trigger_sheet_name", "Inventur"
    )
    merged_config["google_sheets"]["test_sheet_name"] = sector_config.get(
        "trigger_sheet_name", "Inventur"
    )
    merged_config["google_sheets"]["trigger_cell"] = sector_config.get(
        "trigger_cell", "A1"
    )
    merged_config["google_sheets"]["target_sheet_name"] = sector_config.get(
        "target_sheet_name", "sektor"
    )
    merged_config["google_sheets"]["sektor_sheet_name"] = sector_config.get(
        "target_sheet_name", "sektor"
    )

    logger.info(
        "sector_configuration_applied",
        extra={
            "sector_id": sector_id,
            "trigger_sheet_name": merged_config["google_sheets"]["trigger_sheet_name"],
            "trigger_cell": merged_config["google_sheets"]["trigger_cell"],
            "target_sheet_name": merged_config["google_sheets"]["target_sheet_name"],
        },
    )
    return merged_config


def _initialize_sheets_client_or_exit() -> GoogleSheetsClient:
    """
    Initialize Google Sheets client, exiting process on authentication failure.

    Returns:
        Authenticated GoogleSheetsClient instance

    Side effect:
        Calls sys.exit(1) if authentication fails (unrecoverable at startup)
    """
    try:
        sheets_client = GoogleSheetsClient()
        logger.info("google_sheets_client_initialized")
        return sheets_client
    except GoogleSheetsAuthenticationError as auth_failure:
        logger.error(
            "failed_to_initialize_sheets_client",
            extra={"error": str(auth_failure)},
        )
        sys.exit(1)


# ─── Poll Cycle State ───


class _PollCycleState:
    """Mutable state carried across poll cycles in the worker loop."""

    def __init__(self) -> None:
        self.last_processed_lhm_id: Optional[str] = None
        self.last_active_unix_timestamp: float = time.time()
        self.poll_cycle_count: int = 0
        self.is_paused: bool = False


# ─── Single Poll Cycle ───


async def _check_and_apply_idle_shutdown(
    cycle_state: "_PollCycleState",
    idle_timeout_seconds: int,
    sector_id: str,
) -> None:
    """
    Check idle timeout and exit if exceeded (only when not paused).

    Args:
        cycle_state: Mutable poll cycle state
        idle_timeout_seconds: Threshold in seconds for idle auto-shutdown
        sector_id: Sector identifier for logging
    """
    if detect_idle_timeout_exceeded(cycle_state.last_active_unix_timestamp, idle_timeout_seconds) and not cycle_state.is_paused:
        elapsed_idle_seconds = time.time() - cycle_state.last_active_unix_timestamp
        logger.info("idle_timeout_threshold_exceeded_shutting_down", extra={"sector_id": sector_id, "elapsed_seconds": elapsed_idle_seconds, "threshold_seconds": idle_timeout_seconds})

        try:
            async with AsyncSessionLocal() as session:
                audit_repo = AuditRepository(session)
                await audit_repo.create({
                    "actor": "sektor-worker-auto",
                    "event_type": "IDLE_SHUTDOWN",
                    "status": "success",
                    "description": f"Worker auto-terminated after {idle_timeout_seconds}s idle timeout",
                    "metadata": {"sector_id": sector_id, "elapsed_seconds": int(elapsed_idle_seconds)},
                })
                await session.commit()
        except Exception as audit_error:
            logger.warning("failed_to_log_idle_shutdown", extra={"error": str(audit_error)})

        sys.exit(0)


async def _handle_trigger_read_and_dispatch(
    cycle_state: "_PollCycleState",
    sheets_client: GoogleSheetsClient,
    spreadsheet_id: str,
    trigger_sheet_name: str,
    trigger_cell: str,
    target_sheet_name: str,
    poll_interval_seconds: int,
) -> None:
    """
    Read trigger cell and dispatch to processing if a new LHM is detected.

    Args:
        cycle_state: Mutable poll cycle state
        sheets_client: Authenticated Google Sheets client
        spreadsheet_id: Google Sheets document ID
        trigger_sheet_name: Sheet containing trigger cell
        trigger_cell: Cell reference to read
        poll_interval_seconds: Sleep duration if no new trigger
    """
    detected_lhm_id = await read_trigger_lhm_id(sheets_client, spreadsheet_id, trigger_sheet_name, trigger_cell)

    if not detected_lhm_id:
        if cycle_state.poll_cycle_count % 20 == 0:
            logger.debug("poll_cycle_empty_trigger", extra={"poll_count": cycle_state.poll_cycle_count})
        await asyncio.sleep(poll_interval_seconds)
        return

    if _should_skip_duplicate_trigger(detected_lhm_id, cycle_state.last_processed_lhm_id, cycle_state.poll_cycle_count):
        await asyncio.sleep(poll_interval_seconds)
        return

    await _process_new_lhm_trigger_in_cycle(
        cycle_state,
        sheets_client,
        spreadsheet_id,
        detected_lhm_id,
        trigger_sheet_name,
        trigger_cell,
        target_sheet_name,
        poll_interval_seconds,
    )


async def _run_single_poll_cycle(
    cycle_state: "_PollCycleState",
    sheets_client: GoogleSheetsClient,
    spreadsheet_id: str,
    trigger_sheet_name: str,
    trigger_cell: str,
    target_sheet_name: str,
    poll_interval_seconds: int,
    idle_timeout_seconds: int,
    sector_id: str,
) -> None:
    """
    Execute one poll cycle: idle check, pause check, trigger read, process if new.

    Args:
        cycle_state: Mutable poll cycle state object
        sheets_client: Authenticated Google Sheets client
        spreadsheet_id: Target Google Sheets document ID
        trigger_sheet_name: Sheet name containing trigger cell
        trigger_cell: Cell reference to read for trigger
        poll_interval_seconds: Sleep duration between cycles
        idle_timeout_seconds: Idle threshold before auto-shutdown
        sector_id: Sector identifier for logging
    """
    cycle_state.poll_cycle_count += 1
    await _check_and_apply_idle_shutdown(cycle_state, idle_timeout_seconds, sector_id)

    if detect_pause_signal_file():
        cycle_state.is_paused = await _handle_pause_cycle(cycle_state.is_paused, poll_interval_seconds)
        return

    cycle_state.is_paused = _handle_resume_from_pause(cycle_state.is_paused)
    await _handle_trigger_read_and_dispatch(
        cycle_state,
        sheets_client,
        spreadsheet_id,
        trigger_sheet_name,
        trigger_cell,
        target_sheet_name,
        poll_interval_seconds,
    )


async def _process_new_lhm_trigger_in_cycle(
    cycle_state: "_PollCycleState",
    sheets_client: GoogleSheetsClient,
    spreadsheet_id: str,
    detected_lhm_id: str,
    trigger_sheet_name: str,
    trigger_cell: str,
    target_sheet_name: str,
    poll_interval_seconds: int,
) -> None:
    """
    Process a new LHM trigger detected in the current poll cycle.

    Updates cycle_state on success. Logs and sleeps regardless of outcome.

    Args:
        cycle_state: Mutable poll cycle state (updated on success)
        sheets_client: Authenticated Google Sheets client
        spreadsheet_id: Google Sheets document ID
        detected_lhm_id: New LHM trigger value from sheet
        trigger_sheet_name: Sheet containing trigger cell
        trigger_cell: Trigger cell reference
        poll_interval_seconds: Sleep duration after cycle
    """
    logger.info(
        "poll_cycle_new_trigger_detected",
        extra={"poll_count": cycle_state.poll_cycle_count, "lhm_id": detected_lhm_id},
    )
    trigger_processing_succeeded = await process_detected_lhm_trigger(
        sheets_client, spreadsheet_id, detected_lhm_id,
        cycle_state.last_processed_lhm_id,
        trigger_sheet_name,
        trigger_cell,
        target_sheet_name,
    )
    if trigger_processing_succeeded:
        cycle_state.last_processed_lhm_id = detected_lhm_id
        cycle_state.last_active_unix_timestamp = time.time()
        logger.info(
            "poll_cycle_trigger_processing_succeeded",
            extra={"poll_count": cycle_state.poll_cycle_count, "processed_lhm_id": detected_lhm_id},
        )
    else:
        logger.warning(
            "poll_cycle_trigger_processing_failed_will_retry",
            extra={"poll_count": cycle_state.poll_cycle_count},
        )
    await asyncio.sleep(poll_interval_seconds)


# ─── Main Polling Loop ───


def _load_and_validate_worker_config() -> tuple:
    """
    Load worker config, validate spreadsheet_id is present, and log settings.

    Returns:
        Tuple of (poll_interval_seconds, idle_timeout_seconds,
                  spreadsheet_id, trigger_sheet_name, trigger_cell, target_sheet_name)

    Side effect:
        Calls sys.exit(1) if spreadsheet_id is not configured
    """
    sector_id = os.environ.get("SECTOR_ID", "unknown")
    worker_config = load_worker_config()

    try:
        worker_config = _apply_sector_overrides(worker_config, sector_id)
    except ValueError as sector_config_error:
        logger.warning(
            "failed_to_apply_sector_config_falling_back_to_default_worker_config",
            extra={"sector_id": sector_id, "error": str(sector_config_error)},
        )

    (
        poll_interval_seconds,
        idle_timeout_seconds,
        spreadsheet_id,
        trigger_sheet_name,
        trigger_cell,
        target_sheet_name,
    ) = _extract_worker_settings_from_config(worker_config)
    if not spreadsheet_id:
        logger.error("google_sheets_spreadsheet_id_not_configured")
        sys.exit(1)
    logger.info(
        "worker_configuration_loaded",
        extra={
            "sector_id": sector_id,
            "poll_interval_seconds": poll_interval_seconds,
            "idle_timeout_seconds": idle_timeout_seconds,
            "spreadsheet_id_prefix": spreadsheet_id[:20] + "...",
            "trigger_sheet_name": trigger_sheet_name,
            "trigger_cell": trigger_cell,
            "target_sheet_name": target_sheet_name,
        },
    )
    return (
        poll_interval_seconds,
        idle_timeout_seconds,
        spreadsheet_id,
        trigger_sheet_name,
        trigger_cell,
        target_sheet_name,
    )


async def _run_poll_loop(
    sheets_client: GoogleSheetsClient,
    spreadsheet_id: str,
    trigger_sheet_name: str,
    trigger_cell: str,
    target_sheet_name: str,
    poll_interval_seconds: int,
    idle_timeout_seconds: int,
    sector_id: str,
) -> None:
    """
    Run the main polling loop until idle timeout or KeyboardInterrupt.

    Args:
        sheets_client: Authenticated Google Sheets client
        spreadsheet_id: Google Sheets document ID
        trigger_sheet_name: Sheet containing trigger cell
        trigger_cell: Cell reference for LHM trigger
        poll_interval_seconds: Sleep duration between poll cycles
        idle_timeout_seconds: Idle threshold for auto-shutdown
        sector_id: Sector identifier for logging
    """
    cycle_state = _PollCycleState()
    try:
        while True:
            await _run_single_poll_cycle(
                cycle_state,
                sheets_client,
                spreadsheet_id,
                trigger_sheet_name,
                trigger_cell,
                target_sheet_name,
                poll_interval_seconds,
                idle_timeout_seconds,
                sector_id,
            )
    except KeyboardInterrupt:
        logger.info("worker_interrupted_by_user")
        sys.exit(0)


async def run_worker_loop() -> None:
    """
    Main worker entry point: load config, initialize client, run poll loop.

    Exits via sys.exit(0) on idle timeout or KeyboardInterrupt.
    Exits via sys.exit(1) on missing configuration or authentication failure.
    """
    logger.info("sektor_worker_starting")
    sector_id = os.environ.get("SECTOR_ID", "unknown")
    (
        poll_interval_seconds,
        idle_timeout_seconds,
        spreadsheet_id,
        trigger_sheet_name,
        trigger_cell,
        target_sheet_name,
    ) = (
        _load_and_validate_worker_config()
    )
    sheets_client = _initialize_sheets_client_or_exit()
    await _run_poll_loop(
        sheets_client,
        spreadsheet_id,
        trigger_sheet_name,
        trigger_cell,
        target_sheet_name,
        poll_interval_seconds,
        idle_timeout_seconds,
        sector_id,
    )


# ─── Entry Point ───


if __name__ == "__main__":
    asyncio.run(run_worker_loop())
