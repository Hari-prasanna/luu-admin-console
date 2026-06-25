"""
Sektor Pilot sector configuration mapping.
Defines three distinct sector instances with their own spreadsheet IDs and monitoring targets.
"""

from typing import Dict, Any

SECTOR_INSTANCES: Dict[str, Dict[str, Any]] = {
    "bsf_halle1": {
        "name": "Sektor Audit",
        "description": "BSF storage hall 1 inventory monitoring",
        "spreadsheet_id": "1Y8uTxDDc4yyajduTEKha4V-FD1-98eVPyqHx0A8oyis",
        "test_sheet_name": "Inventur",
        "trigger_cell": "A2",
        "sektor_sheet_name": "sektor",
        "audit_sheet_name": "audit_log",
        "console_logs_sheet_name": "console_logs",
    },
    "bsf_bestand": {
        "name": "Sektor Audit - BSF Bestand",
        "description": "BSF inventory stock master monitoring",
        "spreadsheet_id": "1Db0VNaphDZsWqp3K8Zs8LBHWPAjvgWerHti-VeNsF7w",
        "test_sheet_name": "Inventur",
        "trigger_cell": "A3",
        "sektor_sheet_name": "sektor",
        "audit_sheet_name": "audit_log",
        "console_logs_sheet_name": "console_logs",
    },
    "akl_bestand": {
        "name": "Sektor Audit - AKL Bestand",
        "description": "Automated Small Parts Storage inventory monitoring",
        "spreadsheet_id": "1Db0VNaphDZsWqp3K8Zs8LBHWPAjvgWerHti-VeNsF7w",
        "test_sheet_name": "Inventur",
        "trigger_cell": "A4",
        "sektor_sheet_name": "sektor",
        "audit_sheet_name": "audit_log",
        "console_logs_sheet_name": "console_logs",
    },
}


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
    if sector_id not in SECTOR_INSTANCES:
        raise ValueError(f"Unknown sector_id: {sector_id}. Valid options: {', '.join(SECTOR_INSTANCES.keys())}")
    return SECTOR_INSTANCES[sector_id]


def list_sectors() -> list:
    """Return list of all available sector instances."""
    return [
        {
            "sector_id": sector_id,
            "name": config["name"],
            "description": config["description"],
        }
        for sector_id, config in SECTOR_INSTANCES.items()
    ]
