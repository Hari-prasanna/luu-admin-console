"""
Sektor Pilot sector configuration mapping.
Defines three distinct sector instances with their own spreadsheet IDs and monitoring targets.
Spreadsheet IDs loaded from environment variables (never hardcoded in source).

For container and collies audits: trigger cell in Inventur sheet → results in sektor sheet
For outlet audit: supports 3 audit sheets (Audit 1/2/3) mapping to sektor sheets (Sektor 1/2/3)
"""

import os
import re
from typing import Dict, Any

SECTOR_DEFINITIONS = {
    "stock_audit_containers": {
        "name": "Stock Audit - Containers",
        "description": "Container inventory stock monitoring",
        "env_var": "SEKTOR_SPREADSHEET_CONTAINERS",
        "trigger_sheet_name": "Inventur",
        "trigger_cell": "A1",
        "target_sheet_name": "sektor",
        "audit_sheet_name": "audit_log",
        "console_logs_sheet_name": "console_logs",
    },
    "stock_audit_collies": {
        "name": "Stock Audit - Collies",
        "description": "Collies inventory stock monitoring",
        "env_var": "SEKTOR_SPREADSHEET_COLLIES",
        "trigger_sheet_name": "Inventur",
        "trigger_cell": "A1",
        "target_sheet_name": "sektor",
        "audit_sheet_name": "audit_log",
        "console_logs_sheet_name": "console_logs",
    },
    "outlet_audit_1": {
        "name": "Outlet Audit 1",
        "description": "Outlet audit - batch 1",
        "env_var": "SEKTOR_SPREADSHEET_OUTLET",
        "trigger_sheet_name": "Audit 1",
        "trigger_cell": "A1",
        "target_sheet_name": "Sektor 1",
        "audit_sheet_name": "audit_log",
        "console_logs_sheet_name": "console_logs",
    },
    "outlet_audit_2": {
        "name": "Outlet Audit 2",
        "description": "Outlet audit - batch 2",
        "env_var": "SEKTOR_SPREADSHEET_OUTLET",
        "trigger_sheet_name": "Audit 2",
        "trigger_cell": "A1",
        "target_sheet_name": "Sektor 2",
        "audit_sheet_name": "audit_log",
        "console_logs_sheet_name": "console_logs",
    },
    "outlet_audit_3": {
        "name": "Outlet Audit 3",
        "description": "Outlet audit - batch 3",
        "env_var": "SEKTOR_SPREADSHEET_OUTLET",
        "trigger_sheet_name": "Audit 3",
        "trigger_cell": "A1",
        "target_sheet_name": "Sektor 3",
        "audit_sheet_name": "audit_log",
        "console_logs_sheet_name": "console_logs",
    },
}


def _build_sector_override_env_key(sector_id: str, config_key: str) -> str:
    """Build normalized env key for sector-specific config overrides."""
    normalized_sector_id = re.sub(r"[^A-Za-z0-9]", "_", sector_id).upper()
    normalized_config_key = re.sub(r"[^A-Za-z0-9]", "_", config_key).upper()
    return f"SEKTOR_{normalized_sector_id}_{normalized_config_key}"


def _build_sector_instances() -> Dict[str, Dict[str, Any]]:
    """
    Build sector instances with environment variables evaluated at call time.

    Returns:
        Dictionary of sector_id -> config with current env vars
    """
    instances = {}
    for sector_id, config_template in SECTOR_DEFINITIONS.items():
        config = dict(config_template)
        env_var = config.pop("env_var")

        spreadsheet_id = os.environ.get(env_var, "").strip()
        if not spreadsheet_id:
            spreadsheet_id = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip()
        config["spreadsheet_id"] = spreadsheet_id

        for config_key in (
            "trigger_sheet_name",
            "trigger_cell",
            "target_sheet_name",
            "audit_sheet_name",
            "console_logs_sheet_name",
        ):
            override_env_key = _build_sector_override_env_key(sector_id, config_key)
            override_env_value = os.environ.get(override_env_key, "").strip()
            if override_env_value:
                config[config_key] = override_env_value

        instances[sector_id] = config
    return instances


# Lazy-evaluated sector instances (env vars checked at first access)
SECTOR_INSTANCES: Dict[str, Dict[str, Any]] | None = None


def _get_sector_instances() -> Dict[str, Dict[str, Any]]:
    """Get sector instances, building if needed."""
    global SECTOR_INSTANCES
    if SECTOR_INSTANCES is None:
        SECTOR_INSTANCES = _build_sector_instances()
    return SECTOR_INSTANCES


def get_sector_config(sector_id: str) -> Dict[str, Any]:
    """
    Retrieve configuration for a specific sector instance.

    Args:
        sector_id: Sector identifier (e.g., "bsf_halle1", "bsf_bestand", "akl_bestand")

    Returns:
        Dictionary containing sector configuration

    Raises:
        ValueError: If sector_id is not recognized
    """
    instances = _get_sector_instances()
    if sector_id not in instances:
        raise ValueError(f"Unknown sector_id: {sector_id}. Valid options: {', '.join(instances.keys())}")
    return instances[sector_id]


def list_sectors() -> list:
    """Return list of all available sector instances."""
    instances = _get_sector_instances()
    return [
        {
            "sector_id": sector_id,
            "name": config["name"],
            "description": config["description"],
        }
        for sector_id, config in instances.items()
    ]
