"""
Oracle database client for Sektor Pilot ZAL_BESTAND queries.

Per Clean Code Chapter 2: intention-revealing names (no `log`, `f`, `val`, `creds`).
Per Clean Code Chapter 3: micro-functions (< 25 lines each, single responsibility).
Per Clean Code Chapter 7: specific typed exceptions — no bare except blocks.
"""

import os
import stat
import logging
from typing import List, Dict, Any, Optional

try:
    import oracledb
except ImportError:
    raise ImportError("oracledb is not installed. Run: pip install oracledb")

from backend.exceptions import OracleConnectionError, OracleQueryError, ConfigurationError

logger = logging.getLogger("sektor_db")


# ─── Constants ───

ORACLE_ENV_FILE_ENV_VAR = "ORA_ENV_FILE"
ORACLE_QUERY_FILENAME = "zal_bestand.sql"
ORACLE_REQUIRED_CREDENTIAL_KEYS = ("user", "password", "host", "service")
ORACLE_DEFAULT_PORT = "1521"
ORACLE_POOL_MIN_SIZE = 2
ORACLE_POOL_MAX_SIZE = 10
ORACLE_POOL_INCREMENT = 1

# Global connection pool (singleton)
_oracle_connection_pool: Optional["oracledb.ConnectionPool"] = None


# ─── Credential File Loading ───


def _resolve_oracle_env_file_path() -> str:
    """
    Resolve path to oracle.env credential file.

    Priority: ORA_ENV_FILE environment variable, then default relative path.

    Returns:
        Absolute path to the oracle.env file
    """
    default_oracle_env_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "oracle.env")
    )
    return os.environ.get(ORACLE_ENV_FILE_ENV_VAR, default_oracle_env_path)


def _warn_if_file_permissions_are_insecure(oracle_env_file_path: str) -> None:
    """
    Emit warning if oracle.env is readable by group or others.

    Args:
        oracle_env_file_path: Path to oracle.env file
    """
    file_mode = os.stat(oracle_env_file_path).st_mode
    if file_mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.warning(
            "secure_file_readable_by_others",
            extra={"path": oracle_env_file_path, "hint": f"chmod 600 {oracle_env_file_path}"},
        )


def _parse_env_file_into_dict(oracle_env_file_path: str) -> Dict[str, str]:
    """
    Parse key=value pairs from an .env file into a dictionary.

    Skips blank lines and comment lines. Strips surrounding quotes from values.

    Args:
        oracle_env_file_path: Path to the .env file

    Returns:
        Dictionary of key-value credential pairs
    """
    parsed_credential_values: Dict[str, str] = {}
    with open(oracle_env_file_path, encoding="utf-8") as env_file_stream:
        for raw_line in env_file_stream:
            stripped_line = raw_line.strip()
            if stripped_line and not stripped_line.startswith("#") and "=" in stripped_line:
                credential_key, _, raw_credential_value = stripped_line.partition("=")
                parsed_credential_values[credential_key.strip()] = (
                    raw_credential_value.strip().strip('"').strip("'")
                )
    return parsed_credential_values


def load_oracle_credentials_from_env_file() -> Dict[str, str]:
    """
    Load Oracle credentials from oracle.env file.

    Falls back to empty dict if file not found (caller then relies on OS env vars).

    Returns:
        Dictionary of credential key-value pairs (may be empty if file missing)
    """
    oracle_env_file_path = _resolve_oracle_env_file_path()

    if not os.path.isfile(oracle_env_file_path):
        logger.warning(
            "oracle_env_file_not_found_using_environment_variables",
            extra={"path": oracle_env_file_path},
        )
        return {}

    _warn_if_file_permissions_are_insecure(oracle_env_file_path)
    return _parse_env_file_into_dict(oracle_env_file_path)


# ─── Credential Resolution ───


def _resolve_single_credential(
    credential_file_values: Dict[str, str],
    credential_name: str,
    default_value: Optional[str] = None,
) -> Optional[str]:
    """
    Resolve one credential from OS environment or credential file, with optional default.

    Priority: OS environment variable > credential file > default.

    Args:
        credential_file_values: Parsed values from oracle.env
        credential_name: Environment variable / key name (e.g., "ORA_USER")
        default_value: Fallback if neither env nor file has the key

    Returns:
        Resolved credential string, or None if absent and no default
    """
    return os.environ.get(credential_name) or credential_file_values.get(credential_name) or default_value


def build_oracle_connection_credentials(
    credential_file_values: Dict[str, str],
) -> Dict[str, str]:
    """
    Build and validate Oracle connection credential dictionary.

    Args:
        credential_file_values: Parsed values from oracle.env

    Returns:
        Validated credential dict with keys: user, password, host, port, service

    Raises:
        ConfigurationError: If any required credential is missing
    """
    oracle_connection_credentials = {
        "user": _resolve_single_credential(credential_file_values, "ORA_USER"),
        "password": _resolve_single_credential(credential_file_values, "ORA_PASSWORD"),
        "host": _resolve_single_credential(credential_file_values, "ORA_HOST"),
        "port": _resolve_single_credential(credential_file_values, "ORA_PORT", ORACLE_DEFAULT_PORT),
        "service": _resolve_single_credential(credential_file_values, "ORA_SERVICE"),
    }
    missing_credential_keys = [
        key for key in ORACLE_REQUIRED_CREDENTIAL_KEYS
        if not oracle_connection_credentials[key]
    ]
    if missing_credential_keys:
        raise ConfigurationError(
            f"Missing Oracle credential(s): {', '.join(missing_credential_keys)}",
            context={"missing_keys": missing_credential_keys},
        )
    return oracle_connection_credentials


# ─── Connection Pool ───


def _get_or_create_connection_pool(
    oracle_connection_credentials: Dict[str, str],
) -> "oracledb.ConnectionPool":
    """
    Get or create a shared Oracle connection pool.

    Uses lazy initialization on first call. Subsequent calls return the cached pool.

    Args:
        oracle_connection_credentials: Dict with user, password, host, port, service

    Returns:
        Active oracledb.ConnectionPool

    Raises:
        OracleConnectionError: If pool creation fails
    """
    global _oracle_connection_pool

    if _oracle_connection_pool is not None:
        return _oracle_connection_pool

    oracle_dsn = (
        f"{oracle_connection_credentials['host']}"
        f":{oracle_connection_credentials['port']}"
        f"/{oracle_connection_credentials['service']}"
    )
    logger.info(
        "oracle_connection_pool_creating",
        extra={
            "dsn": oracle_dsn,
            "min_size": ORACLE_POOL_MIN_SIZE,
            "max_size": ORACLE_POOL_MAX_SIZE,
        },
    )
    try:
        _oracle_connection_pool = oracledb.create_pool(
            user=oracle_connection_credentials["user"],
            password=oracle_connection_credentials["password"],
            dsn=oracle_dsn,
            min=ORACLE_POOL_MIN_SIZE,
            max=ORACLE_POOL_MAX_SIZE,
            increment=ORACLE_POOL_INCREMENT,
        )
        logger.info("oracle_connection_pool_created", extra={"dsn": oracle_dsn})
        return _oracle_connection_pool
    except oracledb.Error as pool_creation_failure:
        raise OracleConnectionError(
            f"Failed to create Oracle connection pool for {oracle_dsn}",
            context={"dsn": oracle_dsn, "error": str(pool_creation_failure)},
        ) from pool_creation_failure


def open_oracle_connection(
    oracle_connection_credentials: Dict[str, str],
) -> "oracledb.Connection":
    """
    Acquire a connection from the pool or create a new one if pool unavailable.

    Args:
        oracle_connection_credentials: Dict with user, password, host, port, service

    Returns:
        Active oracledb.Connection (from pool if available, fresh otherwise)

    Raises:
        OracleConnectionError: If connection acquisition fails
    """
    try:
        pool = _get_or_create_connection_pool(oracle_connection_credentials)
        connection = pool.acquire()
        logger.debug("oracle_connection_acquired_from_pool")
        return connection
    except OracleConnectionError:
        raise
    except oracledb.Error as connection_failure:
        raise OracleConnectionError(
            "Failed to acquire connection from Oracle pool",
            context={"error": str(connection_failure)},
        ) from connection_failure


# ─── Query File Loading ───


def _resolve_zal_bestand_query_file_path() -> str:
    """
    Resolve path to zal_bestand.sql query file.

    Checks sektor_pilot query directory first, then Docker container path.

    Returns:
        Path to the SQL query file

    Raises:
        OracleQueryError: If query file cannot be found at either location
    """
    project_root_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    local_query_path = os.path.join(
        project_root_path,
        "backend",
        "automation",
        "sektor_pilot",
        "queries",
        ORACLE_QUERY_FILENAME,
    )
    docker_query_path = os.path.join(
        "/app",
        "backend",
        "automation",
        "sektor_pilot",
        "queries",
        ORACLE_QUERY_FILENAME,
    )

    if os.path.exists(local_query_path):
        return local_query_path
    if os.path.exists(docker_query_path):
        return docker_query_path

    raise OracleQueryError(
        f"Query file '{ORACLE_QUERY_FILENAME}' not found",
        context={"local_path": local_query_path, "docker_path": docker_query_path},
    )


def _load_zal_bestand_sql_query() -> str:
    """
    Load ZAL_BESTAND SQL query text from file.

    Returns:
        SQL query string (stripped)

    Raises:
        OracleQueryError: If file is missing or unreadable
    """
    query_file_path = _resolve_zal_bestand_query_file_path()
    with open(query_file_path, "r", encoding="utf-8") as sql_file_stream:
        return sql_file_stream.read().strip()


# ─── Row Mapping ───


def _map_cursor_rows_to_dicts(
    cursor_rows: List[tuple],
    cursor_column_names: List[str],
) -> List[Dict[str, Any]]:
    """
    Convert raw cursor rows into list of column-named dictionaries.

    Args:
        cursor_rows: List of row tuples from cursor.fetchall()
        cursor_column_names: Column names from cursor.description

    Returns:
        List of row dictionaries with column names as keys
    """
    return [
        dict(zip(cursor_column_names, single_row))
        for single_row in cursor_rows
    ]


def _extract_column_names_from_cursor(
    cursor: "oracledb.Cursor",
) -> List[str]:
    """
    Extract column name strings from Oracle cursor description.

    Args:
        cursor: Active Oracle cursor after query execution

    Returns:
        List of column name strings
    """
    return [column_descriptor[0] for column_descriptor in cursor.description]


# ─── Query Execution ───


def _execute_lhm_query_on_cursor(
    oracle_cursor: "oracledb.Cursor",
    lhm_id: str,
) -> List[Dict[str, Any]]:
    """
    Execute the ZAL_BESTAND query and return rows as dicts.

    Args:
        oracle_cursor: Open Oracle cursor
        lhm_id: LHM identifier to filter by

    Returns:
        List of row dictionaries (empty list if no matching rows)

    Raises:
        OracleQueryError: If SQL execution fails
    """
    zal_bestand_sql_query = _load_zal_bestand_sql_query()
    try:
        oracle_cursor.execute(zal_bestand_sql_query, {"lhm_num": lhm_id})
    except oracledb.Error as query_execution_failure:
        raise OracleQueryError(
            f"ZAL_BESTAND query failed for LHM ID: {lhm_id}",
            context={"lhm_id": lhm_id, "error": str(query_execution_failure)},
        ) from query_execution_failure

    fetched_rows = oracle_cursor.fetchall()
    if not fetched_rows:
        logger.info("no_rows_found_for_lhm_id", extra={"lhm_id": lhm_id})
        return []

    cursor_column_names = _extract_column_names_from_cursor(oracle_cursor)
    row_dicts = _map_cursor_rows_to_dicts(fetched_rows, cursor_column_names)
    logger.info(
        "zal_bestand_rows_fetched",
        extra={"lhm_id": lhm_id, "row_count": len(row_dicts)},
    )
    return row_dicts


# ─── Public API ───


async def fetch_lhm_data(lhm_id: str) -> List[Dict[str, Any]]:
    """
    Query ZAL_BESTAND for all inventory rows matching the given LHM ID.

    Args:
        lhm_id: The MainLhm identifier to filter by (e.g., "001", "002")

    Returns:
        List of row dicts with keys: MainLhm, ARTNR, Qualität, ANZ, Sortierziel ID, SortKriterium
        Returns empty list if no rows found.

    Raises:
        ConfigurationError: If Oracle credentials are missing
        OracleConnectionError: If database connection fails
        OracleQueryError: If query file is missing or SQL execution fails
    """
    credential_file_values = load_oracle_credentials_from_env_file()
    oracle_connection_credentials = build_oracle_connection_credentials(credential_file_values)
    oracle_connection = open_oracle_connection(oracle_connection_credentials)

    try:
        oracle_cursor = oracle_connection.cursor()
        try:
            return _execute_lhm_query_on_cursor(oracle_cursor, lhm_id)
        finally:
            oracle_cursor.close()
    finally:
        oracle_connection.close()
