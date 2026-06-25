#!/usr/bin/env python3

"""
Internal Transport Metrics API — FastAPI backend for LUU Q-Console dashboard.

Exposes endpoints for live Oracle metrics collection, caching, authentication, and audit logging.
Per Clean Code principles: type hints on all functions, specific exception handling, micro-functions < 25 lines.
"""

import json
import logging
import os
import stat
import sys
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional, Any

import bcrypt
import jwt
from fastapi import FastAPI, Depends, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Imports from backend infrastructure
try:
    from backend.config import Constants, Settings
    from backend.exceptions import (
        OracleConnectionError,
        OracleQueryError,
        ValidationError,
        ConfigurationError,
    )
    from backend.models import TileConfig, MetricsResponse, ConfigResponse
except ImportError as import_error:
    sys.exit(f"Failed to import backend infrastructure: {import_error}")

# Setup path for shared utilities
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", ".."))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
_COMMON_DIR = os.path.join(_PROJECT_ROOT, "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

from common import notify

try:
    from .sektor_pilot import router as sektor_pilot_router
    SEKTOR_PILOT_AVAILABLE = True
except Exception as sektor_import_error:
    logger.error("sektor_pilot_import_failed", extra={"error": str(sektor_import_error)}, exc_info=sektor_import_error)
    SEKTOR_PILOT_AVAILABLE = False

try:
    import oracledb
except ImportError:
    sys.exit("oracledb is not installed. Activate venv and run: pip install oracledb")

try:
    from zoneinfo import ZoneInfo
    BERLIN_TZ = ZoneInfo("Europe/Berlin")
except Exception:
    BERLIN_TZ = None

# ─── Authentication Constants ───

JWT_SECRET = os.environ.get(
    "AUTH_SECRET",
    "change-me-in-production-use-a-strong-secret-key-at-least-32-chars"
)
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

# ─── Directory & File Paths ───

BASE_DIR = os.path.join(_BACKEND_DIR, "internal-transport")
AUTH_DIR = os.path.join(_BACKEND_DIR, "auth")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
QUERIES_DIR = os.path.join(BASE_DIR, "queries")
LOG_DIR = os.path.join(BASE_DIR, "logs")
STATUS_FILE = os.path.join(LOG_DIR, "last_status")
USERS_FILE = os.path.join(AUTH_DIR, "users.json")
AUDIT_LOG_FILE = os.path.join(AUTH_DIR, "audit_logs.json")
DEFAULT_SECRETS_FILE = os.path.normpath(os.path.join(_BACKEND_DIR, "..", "oracle.env"))
DASHBOARD_LABEL = os.path.basename(BASE_DIR)
LOG_FILE = os.path.join(LOG_DIR, "butler.log")

logger = logging.getLogger("butler")

# ─── Logging Setup ───


def setup_logging() -> None:
    """Configure rotating file and console logging."""
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(AUTH_DIR, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if logger.handlers:
        return

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)


setup_logging()

# ─── FastAPI App ───

app = FastAPI(title="Internal Transport Metrics API")

if SEKTOR_PILOT_AVAILABLE:
    app.include_router(sektor_pilot_router)
    logger.info("sektor_pilot_router_registered")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Utility Functions ───


def get_current_timestamp() -> str:
    """Get formatted timestamp in Berlin timezone."""
    now = datetime.now(BERLIN_TZ) if BERLIN_TZ else datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


def normalize_numeric_value(value: Any) -> Any:
    """Convert Decimal values to int or float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def load_secure_credentials_file() -> Dict[str, str]:
    """Load credentials from oracle.env file."""
    path = os.environ.get("ORA_ENV_FILE", DEFAULT_SECRETS_FILE)
    credentials = {}

    if os.path.isfile(path):
        file_permissions = os.stat(path).st_mode
        if file_permissions & (stat.S_IRWXG | stat.S_IRWXO):
            logger.warning(
                "secure_file_readable_by_others",
                extra={"path": path}
            )
        try:
            with open(path, encoding="utf-8") as cred_file:
                for line in cred_file:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        credentials[key.strip()] = value.strip().strip('"').strip("'")
        except Exception as file_error:
            logger.error(
                "failed_to_load_credentials_file",
                extra={"error": str(file_error)}
            )
    else:
        logger.warning(
            "secure_credentials_file_not_found",
            extra={"path": path}
        )

    return credentials


def get_credential_value(
    credentials: Dict[str, str],
    environment_key: str,
    default_value: Optional[str] = None
) -> Optional[str]:
    """Get credential from environment or credentials dict."""
    return os.environ.get(environment_key) or credentials.get(environment_key) or default_value


# ─── Authentication Functions ───


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode(), hashed_password.encode())
    except Exception:
        return False


def create_access_token(username: str, user_role: str) -> str:
    """Create JWT access token."""
    payload = {
        "username": username,
        "role": user_role,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token_from_header(authorization_header: Optional[str] = Header(None)) -> Dict[str, str]:
    """Verify and decode JWT from Authorization header."""
    if not authorization_header:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    parts = authorization_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = parts[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("username")
        user_role = payload.get("role")
        if not username or not user_role:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"username": username, "role": user_role}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    authorization: str = Header(None)
) -> Dict[str, str]:
    """Dependency: Get current authenticated user."""
    return verify_token_from_header(authorization)


async def require_admin_role(
    authorization: str = Header(None)
) -> Dict[str, str]:
    """Dependency: Require admin role."""
    user = verify_token_from_header(authorization)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ─── Oracle Connection Functions ───


def build_oracle_credentials(credentials: Dict[str, str]) -> Dict[str, str]:
    """Build and validate Oracle connection credentials."""
    oracle_creds = {
        "user": get_credential_value(credentials, "ORA_USER"),
        "password": get_credential_value(credentials, "ORA_PASSWORD"),
        "host": get_credential_value(credentials, "ORA_HOST"),
        "port": get_credential_value(credentials, "ORA_PORT", "1521"),
        "service": get_credential_value(credentials, "ORA_SERVICE"),
    }
    missing_keys = [
        key for key in ("user", "password", "host", "service")
        if not oracle_creds[key]
    ]
    if missing_keys:
        raise ConfigurationError(
            f"Missing Oracle credentials: {', '.join(missing_keys)}",
            context={"missing_keys": missing_keys}
        )
    return oracle_creds


def connect_to_oracle(oracle_creds: Dict[str, str]) -> oracledb.Connection:
    """Connect to Oracle database."""
    dsn = f"{oracle_creds['host']}:{oracle_creds['port']}/{oracle_creds['service']}"
    try:
        logger.info(
            "oracle_connection_attempt",
            extra={"dsn": dsn, "user": oracle_creds["user"]}
        )
        connection = oracledb.connect(
            user=oracle_creds["user"],
            password=oracle_creds["password"],
            dsn=dsn
        )
        logger.info("oracle_connection_success")
        return connection
    except oracledb.Error as oracle_error:
        raise OracleConnectionError(
            f"Failed to connect to Oracle: {oracle_error}",
            context={"dsn": dsn}
        ) from oracle_error


def execute_query_file(cursor: oracledb.Cursor, query_filename: str) -> Any:
    """Execute SQL query from file and return first column value."""
    query_path = os.path.join(QUERIES_DIR, query_filename)
    try:
        with open(query_path, encoding="utf-8") as query_file:
            sql = query_file.read().strip().rstrip(";")
        cursor.execute(sql)
        query_result = cursor.fetchone()
        return normalize_numeric_value(query_result[0]) if query_result else None
    except FileNotFoundError:
        logger.error("query_file_not_found", extra={"file": query_path})
        return "ERROR"
    except oracledb.Error as oracle_error:
        logger.error(
            "oracle_query_failed",
            extra={"file": query_filename, "error": str(oracle_error)}
        )
        return "ERROR"


def fetch_all_metric_values(
    oracle_connection: oracledb.Connection,
    tiles: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Fetch metric values for all tiles from Oracle."""
    metric_values = {}
    with oracle_connection.cursor() as cursor:
        for tile in tiles:
            tile_key = tile.get("key")
            query_file = tile.get("query")
            if not tile_key or not query_file:
                continue
            metric_value = execute_query_file(cursor, query_file)
            metric_values[tile_key] = metric_value
            logger.info(
                "metric_fetched",
                extra={"key": tile_key, "value": metric_value}
            )
    return metric_values


def load_dashboard_config() -> Dict[str, Any]:
    """Load dashboard configuration from config.json."""
    if not os.path.isfile(CONFIG_FILE):
        raise ConfigurationError(
            f"Config file not found: {CONFIG_FILE}"
        )
    try:
        with open(CONFIG_FILE, encoding="utf-8") as config_file:
            config = json.load(config_file)
        if "tiles" not in config:
            raise ValidationError(
                "config.json missing 'tiles' section"
            )
        return config
    except json.JSONDecodeError as json_error:
        raise ConfigurationError(
            f"Invalid config.json: {json_error}"
        ) from json_error


# ─── JSON File Operations ───


def read_json_file(filepath: str, default_value: Any) -> Any:
    """Read JSON file safely."""
    if not os.path.isfile(filepath):
        return default_value
    try:
        with open(filepath, encoding="utf-8") as json_file:
            return json.load(json_file)
    except Exception as file_error:
        logger.error("failed_to_read_json", extra={"file": filepath, "error": str(file_error)})
        return default_value


def write_json_file(filepath: str, data: Any) -> None:
    """Write JSON file safely."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=2)
    except Exception as file_error:
        logger.error("failed_to_write_json", extra={"file": filepath, "error": str(file_error)})


# ─── User Management ───


def read_users_list() -> List[Dict[str, Any]]:
    """Load users from users.json."""
    users = read_json_file(USERS_FILE, [])
    return users if isinstance(users, list) else []


def write_users_list(users: List[Dict[str, Any]]) -> None:
    """Save users to users.json."""
    write_json_file(USERS_FILE, users)


# ─── Audit Logging ───


def read_audit_logs_list() -> List[Dict[str, Any]]:
    """Load audit logs from file."""
    logs = read_json_file(AUDIT_LOG_FILE, [])
    return logs if isinstance(logs, list) else []


def append_audit_entry(
    event_type: str,
    actor: str = "system",
    actor_role: str = "system",
    operation_status: str = "success",
    detail_message: str = "",
    endpoint_path: str = ""
) -> None:
    """Append entry to audit log."""
    logs = read_audit_logs_list()
    logs.append({
        "timestamp": get_current_timestamp(),
        "event": event_type,
        "actor": actor,
        "role": actor_role,
        "status": operation_status,
        "ip": "local",
        "detail": detail_message,
        "path": endpoint_path,
    })
    write_json_file(AUDIT_LOG_FILE, logs[-500:])


# ─── Metrics Caching ───

_METRICS_CACHE_LOCK = threading.Lock()
_METRICS_REFRESH_LOCK = threading.Lock()
_METRICS_CACHE_PAYLOAD: Optional[Dict[str, Any]] = None
_METRICS_CACHE_TIMESTAMP: Optional[datetime] = None


def get_cache_age_seconds() -> Optional[float]:
    """Get age of cached metrics in seconds."""
    if _METRICS_CACHE_TIMESTAMP is None:
        return None
    current_time = datetime.now(BERLIN_TZ) if BERLIN_TZ else datetime.now()
    return (current_time - _METRICS_CACHE_TIMESTAMP).total_seconds()


def get_cached_metrics_if_valid(max_age_seconds: int) -> Optional[Dict[str, Any]]:
    """Get cached metrics if still valid."""
    with _METRICS_CACHE_LOCK:
        if _METRICS_CACHE_PAYLOAD is None:
            return None
        cache_age = get_cache_age_seconds()
        if cache_age is None or cache_age > max_age_seconds:
            return None
        payload = dict(_METRICS_CACHE_PAYLOAD)
        payload["cached"] = True
        payload["cache_age_seconds"] = int(cache_age)
        return payload


def set_cached_metrics(payload: Dict[str, Any]) -> None:
    """Store metrics in cache."""
    global _METRICS_CACHE_PAYLOAD, _METRICS_CACHE_TIMESTAMP
    with _METRICS_CACHE_LOCK:
        _METRICS_CACHE_PAYLOAD = dict(payload)
        _METRICS_CACHE_TIMESTAMP = (
            datetime.now(BERLIN_TZ) if BERLIN_TZ else datetime.now()
        )


# ─── Startup Event ───


@app.on_event("startup")
async def bootstrap_initial_users() -> None:
    """Initialize admin and user accounts if not already configured."""
    existing_users = read_users_list()
    if existing_users:
        logger.info("users_already_initialized")
        return

    admin_username = os.environ.get("AUTH_BOOTSTRAP_ADMIN_USER", "").strip()
    admin_password = os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    user_username = os.environ.get("AUTH_BOOTSTRAP_USER", "").strip()
    user_password = os.environ.get("AUTH_BOOTSTRAP_USER_PASSWORD", "").strip()

    new_users = []
    if admin_username and admin_password:
        new_users.append({
            "username": admin_username,
            "password_hash": hash_password(admin_password),
            "role": "admin",
            "created_at": get_current_timestamp(),
        })
        logger.info("bootstrap_admin_user_created", extra={"username": admin_username})

    if user_username and user_password:
        new_users.append({
            "username": user_username,
            "password_hash": hash_password(user_password),
            "role": "user",
            "created_at": get_current_timestamp(),
        })
        logger.info("bootstrap_user_user_created", extra={"username": user_username})

    if new_users:
        write_users_list(new_users)
        append_audit_entry(
            event_type="bootstrap",
            actor="system",
            detail_message=f"Bootstrapped {len(new_users)} users",
            endpoint_path="/startup",
        )


# ─── Routes: Health ───


@app.get("/health")
def health_check() -> Dict[str, str]:
    """Simple health check endpoint for load balancers and Docker."""
    return {"status": "ok", "service": "internal-transport-api"}


# ─── Routes: Metrics ───


@app.get("/api/config")
def get_dashboard_config() -> Dict[str, Any]:
    """Get dashboard configuration and tile definitions."""
    try:
        config = load_dashboard_config()
        return {
            "refresh_interval_milliseconds": config.get("refresh_interval_milliseconds", 5000),
            "tiles": config["tiles"],
        }
    except (ConfigurationError, ValidationError) as config_error:
        logger.error("config_endpoint_failed", extra={"error": str(config_error)})
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to load config"}
        )


@app.get("/api/metrics")
def get_live_metrics() -> Dict[str, Any]:
    """Get live metrics from Oracle (with caching)."""
    try:
        config = load_dashboard_config()
        refresh_ms = int(config.get("refresh_interval_milliseconds", 5000) or 5000)
        refresh_seconds = max(1, refresh_ms // 1000)

        cached_payload = get_cached_metrics_if_valid(refresh_seconds)
        if cached_payload is not None:
            return cached_payload

        with _METRICS_REFRESH_LOCK:
            cached_payload = get_cached_metrics_if_valid(refresh_seconds)
            if cached_payload is not None:
                return cached_payload

            credentials = load_secure_credentials_file()
            if "CHAT_WEBHOOK_URL" in credentials:
                os.environ["CHAT_WEBHOOK_URL"] = credentials["CHAT_WEBHOOK_URL"]

            oracle_creds = build_oracle_credentials(credentials)
            connection = connect_to_oracle(oracle_creds)
            try:
                metric_values = fetch_all_metric_values(connection, config["tiles"])
            finally:
                connection.close()

            payload = {
                "last_updated": get_current_timestamp(),
                "values": metric_values,
                "cached": False,
                "cache_age_seconds": 0,
            }
            set_cached_metrics(payload)

        notify.report_dashboard_outcome(DASHBOARD_LABEL, STATUS_FILE, True, "")
        return payload

    except Exception as error:
        logger.exception("metrics_endpoint_failed", extra={"error": str(error)})
        notify.report_dashboard_outcome(DASHBOARD_LABEL, STATUS_FILE, False, str(error))
        with _METRICS_CACHE_LOCK:
            if _METRICS_CACHE_PAYLOAD is not None:
                stale_payload = dict(_METRICS_CACHE_PAYLOAD)
                stale_payload["stale"] = True
                stale_payload["cached"] = True
                stale_payload["cache_age_seconds"] = int(get_cache_age_seconds() or 0)
                return stale_payload
        return JSONResponse(
            status_code=500,
            content={
                "error": "Failed to fetch metrics",
                "last_updated": get_current_timestamp(),
            },
        )


# ─── Routes: Authentication ───


@app.post("/auth/login")
async def login_user(request: Request) -> Dict[str, Any]:
    """Authenticate user and return JWT token."""
    try:
        request_body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    username_input = str(request_body.get("username", "")).strip()
    password_input = str(request_body.get("password", ""))

    if not username_input or not password_input:
        append_audit_entry(
            event_type="login_failed",
            actor=username_input or "unknown",
            detail_message="Missing credentials",
            endpoint_path="/auth/login",
            operation_status="failure",
        )
        raise HTTPException(status_code=400, detail="Username and password required")

    users = read_users_list()
    found_user = next(
        (u for u in users if u.get("username", "").lower() == username_input.lower()),
        None
    )

    if not found_user or not verify_password(password_input, found_user.get("password_hash", "")):
        append_audit_entry(
            event_type="login_failed",
            actor=username_input,
            detail_message="Invalid credentials",
            endpoint_path="/auth/login",
            operation_status="failure",
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(found_user["username"], found_user["role"])
    append_audit_entry(
        event_type="login_success",
        actor=found_user["username"],
        actor_role=found_user["role"],
        detail_message=f"User {found_user['username']} logged in",
        endpoint_path="/auth/login",
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": found_user["role"]
    }


@app.get("/auth/me")
async def get_current_user_info(
    user: Dict[str, str] = Depends(get_current_user)
) -> Dict[str, str]:
    """Get current authenticated user info."""
    return {"username": user["username"], "role": user["role"]}


# ─── Routes: User Management ───


@app.get("/auth/users")
async def list_all_users(
    admin: Dict[str, str] = Depends(require_admin_role)
) -> List[Dict[str, str]]:
    """List all users (admin only)."""
    users = read_users_list()
    return [{"username": u["username"], "role": u["role"]} for u in users]


@app.post("/auth/users")
async def create_new_user(
    request: Request,
    admin: Dict[str, str] = Depends(require_admin_role)
) -> Dict[str, str]:
    """Create new user (admin only)."""
    try:
        request_body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")

    username_input = str(request_body.get("username", "")).strip()
    password_input = str(request_body.get("password", ""))
    role_input = str(request_body.get("role", "user")).strip() or "user"

    if not username_input or not password_input:
        raise HTTPException(status_code=400, detail="Username and password required")
    if len(password_input) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if role_input not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid role")

    users = read_users_list()
    if any(u.get("username", "").lower() == username_input.lower() for u in users):
        raise HTTPException(status_code=409, detail="User already exists")

    new_user = {
        "username": username_input,
        "password_hash": hash_password(password_input),
        "role": role_input,
        "created_at": get_current_timestamp(),
    }
    users.append(new_user)
    write_users_list(users)
    append_audit_entry(
        event_type="user_created",
        actor=admin["username"],
        actor_role=admin["role"],
        detail_message=f"Created user {username_input} with role {role_input}",
        endpoint_path="/auth/users",
    )
    return JSONResponse(
        status_code=201,
        content={"username": new_user["username"], "role": new_user["role"]}
    )


# ─── Routes: Audit Logs ───


@app.get("/audit/health")
async def get_audit_system_health(
    admin: Dict[str, str] = Depends(require_admin_role)
) -> Dict[str, Any]:
    """Get audit system health (admin only)."""
    return {
        "status": "ok",
        "total_logs": len(read_audit_logs_list()),
        "last_updated": get_current_timestamp(),
    }


def filter_audit_logs_by_criteria(
    logs: List[Dict[str, Any]],
    event_type: Optional[str] = None,
    actor_name: Optional[str] = None,
    status_filter: Optional[str] = None,
    search_query: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Filter audit logs by criteria."""
    filtered = logs
    if event_type:
        filtered = [
            log for log in filtered
            if str(log.get("event", "")).lower() == str(event_type).lower()
        ]
    if actor_name:
        filtered = [
            log for log in filtered
            if str(actor_name).lower() in str(log.get("actor", "")).lower()
        ]
    if status_filter:
        filtered = [
            log for log in filtered
            if str(log.get("status", "")).lower() == str(status_filter).lower()
        ]
    if search_query:
        search_lower = str(search_query).lower()
        filtered = [
            log for log in filtered
            if (search_lower in str(log.get("detail", "")).lower()
                or search_lower in str(log.get("path", "")).lower()
                or search_lower in str(log.get("event", "")).lower()
                or search_lower in str(log.get("actor", "")).lower())
        ]
    return filtered


def format_audit_response(
    logs: List[Dict[str, Any]],
    page_limit: int,
    page_offset: int
) -> Dict[str, Any]:
    """Format audit logs for API response."""
    total_count = len(logs)
    paginated_items = list(reversed(logs))[page_offset:page_offset + page_limit]
    return {
        "logs": paginated_items,
        "total": total_count,
        "limit": page_limit,
        "offset": page_offset,
    }


@app.get("/audit/logs")
async def get_audit_logs(
    limit: int = 50,
    offset: int = 0,
    admin: Dict[str, str] = Depends(require_admin_role)
) -> Dict[str, Any]:
    """Get audit logs (admin only)."""
    logs = read_audit_logs_list()
    valid_limit = max(1, min(limit, 200))
    valid_offset = max(0, offset)
    return format_audit_response(logs, valid_limit, valid_offset)


@app.get("/audit/search")
async def search_audit_logs(
    limit: int = 50,
    offset: int = 0,
    event: str = "",
    actor: str = "",
    status: str = "",
    query: str = "",
    admin: Dict[str, str] = Depends(require_admin_role)
) -> Dict[str, Any]:
    """Search audit logs (admin only)."""
    logs = filter_audit_logs_by_criteria(
        read_audit_logs_list(),
        event_type=event or None,
        actor_name=actor or None,
        status_filter=status or None,
        search_query=query or None,
    )
    valid_limit = max(1, min(limit, 200))
    valid_offset = max(0, offset)
    return format_audit_response(logs, valid_limit, valid_offset)
