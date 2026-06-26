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
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta
from decimal import Decimal
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional, Any
from filelock import FileLock

import bcrypt
import jwt
from fastapi import FastAPI, Depends, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db_session, init_db, close_db
from backend.services import AuditService, MetricService, PipelineService, NotificationService
from backend.logging_config import setup_structured_logging, StructuredLoggerAdapter, set_request_id
from backend.health_check import get_health_check

# Context variable for storing request ID in async context
_request_id_context: ContextVar[Optional[str]] = ContextVar("request_id", default=None)

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

# Initialize logger early for import error handling
logging.basicConfig(level=logging.DEBUG)
_early_logger = logging.getLogger("butler_startup")

try:
    from .sektor_pilot import router as sektor_pilot_router
    SEKTOR_PILOT_AVAILABLE = True
except Exception as sektor_import_error:
    _early_logger.error("sektor_pilot_import_failed", extra={"error": str(sektor_import_error)}, exc_info=sektor_import_error)
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

try:
    JWT_SECRET = os.environ["AUTH_SECRET"]
    if len(JWT_SECRET) < 32:
        raise ValueError("AUTH_SECRET must be at least 32 characters")
except KeyError:
    raise RuntimeError(
        "AUTH_SECRET environment variable is required and must be at least 32 characters. "
        "Generate one with: openssl rand -hex 16"
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

# ─── Request ID Context Variable ───


def get_request_id() -> str:
    """Get current request ID from context."""
    return _request_id_context.get() or "unknown"


# ─── Logging Setup ───


class RequestIdFilter(logging.Filter):
    """Add request ID to log records."""

    def filter(self, record):
        record.request_id = get_request_id()
        return True


def setup_logging() -> None:
    """Configure rotating file and console logging."""
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(AUTH_DIR, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s  [%(request_id)s]  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if logger.handlers:
        return

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(RequestIdFilter())
    logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(RequestIdFilter())
    logger.addHandler(file_handler)


setup_logging()

# ─── FastAPI App ───

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Internal Transport Metrics API")
app.state.limiter = limiter

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


# ─── Request Correlation ID Middleware ───

class CorrelationIdMiddleware:
    """Add unique correlation ID to each request for tracing."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = None
        if scope.get("headers"):
            for header_name, header_value in scope["headers"]:
                if header_name.lower() == b"x-request-id":
                    request_id = header_value.decode()
                    break

        if not request_id:
            request_id = str(uuid.uuid4())

        scope["request_id"] = request_id
        _request_id_context.set(request_id)

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_request_id)


app.add_middleware(CorrelationIdMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Handle rate limit exceeded errors."""
    append_audit_entry(
        event_type="rate_limit_exceeded",
        actor="unknown",
        detail_message=f"Too many requests from {request.client.host if request.client else 'unknown'}",
        endpoint_path=str(request.url.path),
        operation_status="blocked",
    )
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Try again later."},
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
    """Read JSON file safely with file locking."""
    if not os.path.isfile(filepath):
        return default_value
    lock_path = f"{filepath}.lock"
    try:
        with FileLock(lock_path, timeout=5):
            with open(filepath, encoding="utf-8") as json_file:
                return json.load(json_file)
    except Exception as file_error:
        logger.error("failed_to_read_json", extra={"file": filepath, "error": str(file_error)})
        return default_value


def write_json_file(filepath: str, data: Any) -> None:
    """Write JSON file safely with file locking."""
    lock_path = f"{filepath}.lock"
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with FileLock(lock_path, timeout=5):
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


async def append_audit_entry_async(
    event_type: str,
    actor: str = "system",
    actor_role: str = "system",
    operation_status: str = "success",
    detail_message: str = "",
    endpoint_path: str = "",
    db: Optional[AsyncSession] = None,
) -> None:
    """Append entry to audit log with optional PostgreSQL persistence."""
    # Always write to JSON for backward compatibility
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
        "request_id": get_request_id(),
    })
    write_json_file(AUDIT_LOG_FILE, logs[-500:])

    # Also write to PostgreSQL if database connection available
    if db:
        try:
            audit_service = AuditService(db)
            await audit_service.log_event(
                event_type=event_type,
                actor=actor,
                actor_role=actor_role,
                operation_status=operation_status,
                detail_message=detail_message,
                endpoint_path=endpoint_path,
                request_id=get_request_id(),
            )
        except Exception as db_error:
            logger.warning("audit_log_database_write_failed", extra={"error": str(db_error)})


def append_audit_entry(
    event_type: str,
    actor: str = "system",
    actor_role: str = "system",
    operation_status: str = "success",
    detail_message: str = "",
    endpoint_path: str = ""
) -> None:
    """Append entry to audit log (JSON only, for sync contexts)."""
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
        "request_id": get_request_id(),
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


# ─── Background Metrics Refresh ───

_metrics_refresh_thread: Optional[threading.Thread] = None
_metrics_refresh_running = False


def _refresh_metrics_background() -> None:
    """Background worker: continuously refresh metrics on schedule."""
    global _metrics_refresh_running
    _metrics_refresh_running = True

    while _metrics_refresh_running:
        try:
            config = load_dashboard_config()
            refresh_ms = int(config.get("refresh_interval_milliseconds", 5000) or 5000)
            refresh_seconds = max(1, refresh_ms // 1000)

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
            logger.debug("background_metrics_refreshed", extra={"metric_count": len(metric_values)})

        except Exception as refresh_error:
            logger.error("background_metrics_refresh_failed", extra={"error": str(refresh_error)})
            notify.report_dashboard_outcome(DASHBOARD_LABEL, STATUS_FILE, False, str(refresh_error))

        try:
            threading.Event().wait(refresh_seconds)
        except KeyboardInterrupt:
            break


def start_background_metrics_refresh() -> None:
    """Start the background metrics refresh thread (daemon mode)."""
    global _metrics_refresh_thread, _metrics_refresh_running
    if _metrics_refresh_thread is not None and _metrics_refresh_thread.is_alive():
        logger.warning("background_metrics_refresh_already_running")
        return

    _metrics_refresh_running = True
    _metrics_refresh_thread = threading.Thread(
        target=_refresh_metrics_background,
        daemon=True,
        name="MetricsRefreshWorker",
    )
    _metrics_refresh_thread.start()
    logger.info("background_metrics_refresh_started")


def stop_background_metrics_refresh() -> None:
    """Stop the background metrics refresh thread."""
    global _metrics_refresh_running
    _metrics_refresh_running = False
    if _metrics_refresh_thread is not None:
        _metrics_refresh_thread.join(timeout=5)
        logger.info("background_metrics_refresh_stopped")


# ─── Startup Event ───


@app.on_event("startup")
async def startup_database() -> None:
    """Initialize database and run migrations."""
    try:
        await init_db()
        logger.info("database_tables_created_or_verified")
    except Exception as db_init_error:
        logger.error("database_initialization_failed", extra={"error": str(db_init_error)})
        raise


@app.on_event("startup")
async def bootstrap_initial_users() -> None:
    """Initialize admin and user accounts if not already configured."""
    existing_users = read_users_list()
    if existing_users:
        logger.info("users_already_initialized")
    else:
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

    start_background_metrics_refresh()


@app.on_event("shutdown")
async def shutdown_database() -> None:
    """Close database connections."""
    await close_db()
    logger.info("database_connections_closed")


@app.on_event("shutdown")
async def shutdown_background_tasks() -> None:
    """Clean up background threads on shutdown."""
    stop_background_metrics_refresh()


# ─── Routes: Metrics ───


@app.get("/api/config")
async def get_dashboard_config(request: Request) -> Dict[str, Any]:
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
async def get_live_metrics(request: Request) -> Dict[str, Any]:
    """Get cached metrics (refreshed by background thread)."""
    with _METRICS_CACHE_LOCK:
        if _METRICS_CACHE_PAYLOAD is not None:
            payload = dict(_METRICS_CACHE_PAYLOAD)
            payload["cached"] = True
            payload["cache_age_seconds"] = int(get_cache_age_seconds() or 0)
            return payload

        return JSONResponse(
            status_code=503,
            content={
                "error": "Metrics cache not ready",
                "last_updated": get_current_timestamp(),
            },
        )


# ─── Routes: Authentication ───


@app.post("/auth/login")
@limiter.limit("5/minute")
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


# ─── Routes: Historical Analytics ───


@app.get("/api/analytics/metrics/{metric_key}")
async def get_metric_history(
    metric_key: str,
    days: int = 7,
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Get historical metric data for analytics."""
    try:
        from datetime import timedelta
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        service = MetricService(db)
        records = await service.get_metric_history(
            metric_key=metric_key,
            start_date=start_date,
            end_date=end_date,
        )

        return {
            "metric_key": metric_key,
            "period_days": days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total_records": len(records),
            "values": [
                {
                    "timestamp": r.timestamp.isoformat(),
                    "value": r.metric_value,
                    "status": r.metric_status,
                }
                for r in records
            ],
        }
    except Exception as error:
        logger.exception("metrics_history_failed", extra={"metric_key": metric_key, "error": str(error)})
        raise HTTPException(status_code=500, detail="Failed to fetch metrics history")


@app.get("/api/analytics/audit-logs")
async def get_audit_logs(
    days: int = 7,
    event_type: Optional[str] = None,
    actor: Optional[str] = None,
    user: Dict[str, str] = Depends(require_admin_role),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Get audit logs for reporting (admin only)."""
    try:
        from datetime import timedelta
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        service = AuditService(db)
        records = await service.get_logs_for_period(
            start_date=start_date,
            end_date=end_date,
            event_type=event_type,
            actor=actor,
        )

        return {
            "period_days": days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total_records": len(records),
            "logs": [
                {
                    "timestamp": r.timestamp.isoformat(),
                    "event_type": r.event_type,
                    "actor": r.actor,
                    "status": r.operation_status,
                    "detail": r.detail_message,
                    "request_id": r.request_id,
                }
                for r in records
            ],
        }
    except Exception as error:
        logger.exception("audit_logs_failed", extra={"error": str(error)})
        raise HTTPException(status_code=500, detail="Failed to fetch audit logs")


@app.get("/api/analytics/trace/{request_id}")
async def trace_request(
    request_id: str,
    user: Dict[str, str] = Depends(require_admin_role),
    db: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Trace all events for a single request (admin only)."""
    try:
        service = AuditService(db)
        events = await service.get_request_trace(request_id=request_id)

        return {
            "request_id": request_id,
            "total_events": len(events),
            "events": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "event_type": e.event_type,
                    "actor": e.actor,
                    "status": e.operation_status,
                    "detail": e.detail_message,
                    "endpoint": e.endpoint_path,
                }
                for e in events
            ],
        }
    except Exception as error:
        logger.exception("request_trace_failed", extra={"request_id": request_id, "error": str(error)})
        raise HTTPException(status_code=500, detail="Failed to trace request")


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


# ─── Health Check Endpoints ───


@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Basic liveness probe."""
    return {"status": "ok"}


@app.get("/health/deep")
async def deep_health_check(
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Comprehensive health check for all subsystems."""
    try:
        health_checker = get_health_check()

        # Get oracle pool from environment
        # Note: oracle_pool is created lazily, this is a placeholder check
        result = await health_checker.deep_health_check(None, session)
        return result
    except Exception as error:
        logger.error(
            "deep_health_check_failed",
            extra={
                "error_message": str(error),
                "status": "failure",
            }
        )
        return {
            "status": "unhealthy",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "error": str(error),
        }


@app.get("/health/oracle")
async def oracle_health() -> Dict[str, Any]:
    """Check Oracle connectivity."""
    health_checker = get_health_check()
    return {
        "status": "ok",
        "service": "oracle",
        "consecutive_failures": health_checker.oracle_consecutive_failures,
        "last_error": health_checker.last_oracle_error,
    }


@app.get("/health/postgres")
async def postgres_health(
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Check PostgreSQL connectivity."""
    health_checker = get_health_check()
    postgres_check = await health_checker.check_postgres(session)
    return postgres_check


@app.get("/health/automation")
async def automation_health() -> Dict[str, Any]:
    """Check automation workers health."""
    health_checker = get_health_check()
    return await health_checker.check_automation()


@app.get("/metrics/dashboard")
async def metrics_dashboard(
    days: int = 7,
    session: AsyncSession = Depends(get_db_session),
) -> Dict[str, Any]:
    """Get operational dashboard metrics."""
    try:
        from sqlalchemy import text

        valid_days = max(1, min(days, 90))

        # Query job_executions for statistics
        result = await session.execute(
            text(f"""
                SELECT
                    COUNT(*) as total_jobs,
                    COUNT(*) FILTER (WHERE status = 'success') as successful_jobs,
                    COUNT(*) FILTER (WHERE status = 'failure') as failed_jobs,
                    COUNT(*) FILTER (WHERE status = 'timeout') as timeout_jobs,
                    COALESCE(CAST(100.0 * COUNT(*) FILTER (WHERE status = 'success') / NULLIF(COUNT(*), 0) AS NUMERIC), 0)::FLOAT8 as success_rate_percent,
                    COALESCE(AVG(CAST(duration_seconds AS FLOAT8)), 0) as avg_duration_seconds
                FROM job_executions
                WHERE started_at >= NOW() - INTERVAL '{valid_days} days'
            """)
        )

        row = result.fetchone()
        if not row:
            return {
                "period": f"last_{valid_days}_days",
                "summary": {
                    "total_jobs_executed": 0,
                    "successful_jobs": 0,
                    "failed_jobs": 0,
                    "success_rate_percent": 0,
                    "avg_job_duration_seconds": 0,
                }
            }

        return {
            "period": f"last_{valid_days}_days",
            "summary": {
                "total_jobs_executed": row[0] or 0,
                "successful_jobs": row[1] or 0,
                "failed_jobs": row[2] or 0,
                "timeout_jobs": row[3] or 0,
                "success_rate_percent": float(row[4] or 0),
                "avg_job_duration_seconds": float(row[5] or 0),
            }
        }
    except Exception as error:
        logger.error(
            "metrics_dashboard_failed",
            extra={
                "error_message": str(error),
                "status": "failure",
            }
        )
        return {
            "error": str(error),
            "period": f"last_{days}_days",
        }
