"""Authentication endpoints and shared auth/user helpers."""

import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional, List, Sequence
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import jwt
import os
import bcrypt
from filelock import FileLock

from backend.database import get_db_session
from backend.db_models import User, UserAccessSCD2
from backend.api.v1.schemas import (
    LoginRequest, TokenResponse, CurrentUserResponse, ErrorResponse, DataResponse
)

logger = logging.getLogger("luu.api.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

JWT_SECRET = os.environ.get("AUTH_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

AUTH_DIR = Path(__file__).resolve().parents[3] / "auth"
USERS_FILE = AUTH_DIR / "users.json"
AUDIT_LOG_FILE = AUTH_DIR / "audit_logs.json"

PANEL_IDENTIFIERS: List[str] = [
    "transit_theater",
    "monitor",
    "pipelines",
    "automation",
    "admin_panel",
]


def default_panels_for_role(role: str) -> List[str]:
    """Default panel grants by role."""
    normalized_role = (role or "user").strip().lower()
    if normalized_role == "admin":
        return PANEL_IDENTIFIERS.copy()
    return ["transit_theater"]


def normalize_panels(panels: Optional[Sequence[str]], role: str = "user") -> List[str]:
    """Normalize and validate panel identifiers."""
    if panels is None:
        return default_panels_for_role(role)

    seen = set()
    normalized: List[str] = []
    for panel in panels:
        panel_key = str(panel or "").strip().lower()
        if panel_key in PANEL_IDENTIFIERS and panel_key not in seen:
            normalized.append(panel_key)
            seen.add(panel_key)

    if not normalized:
        return default_panels_for_role(role)

    return normalized


def parse_panels_json(raw_value: Optional[str], role: str = "user") -> List[str]:
    """Parse user panel grants from JSON text."""
    if not raw_value:
        return default_panels_for_role(role)
    try:
        decoded = json.loads(raw_value)
        if isinstance(decoded, list):
            return normalize_panels(decoded, role=role)
    except Exception:
        pass
    return default_panels_for_role(role)


def panels_to_json(panels: Sequence[str]) -> str:
    """Serialize panel grants to JSON text."""
    return json.dumps(normalize_panels(panels), ensure_ascii=False)


def _read_json_file(filepath: Path, default_value: Any) -> Any:
    """Read JSON file safely with file lock."""
    if not filepath.exists():
        return default_value

    lock_path = f"{filepath}.lock"
    try:
        with FileLock(lock_path, timeout=5):
            with filepath.open(encoding="utf-8") as json_file:
                return json.load(json_file)
    except Exception as file_error:
        logger.error("failed_to_read_json", extra={"file": str(filepath), "error": str(file_error)})
        return default_value


def _write_json_file(filepath: Path, data: Any) -> None:
    """Write JSON file safely with file lock."""
    lock_path = f"{filepath}.lock"
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(lock_path, timeout=5):
            with filepath.open("w", encoding="utf-8") as json_file:
                json.dump(data, json_file, ensure_ascii=False, indent=2)
    except Exception as file_error:
        logger.error("failed_to_write_json", extra={"file": str(filepath), "error": str(file_error)})


def read_users_list() -> List[Dict[str, Any]]:
    """Load users from users.json (legacy migration source)."""
    users = _read_json_file(USERS_FILE, [])
    return users if isinstance(users, list) else []


def read_audit_logs_list() -> List[Dict[str, Any]]:
    """Load audit logs from audit_logs.json."""
    logs = _read_json_file(AUDIT_LOG_FILE, [])
    return logs if isinstance(logs, list) else []


def append_audit_entry(
    event_type: str,
    actor: str = "system",
    actor_role: str = "system",
    operation_status: str = "success",
    detail_message: str = "",
    endpoint_path: str = "",
    request_id: Optional[str] = None,
    ip_address: str = "local",
) -> None:
    """Append a JSON audit entry for admin panel consumption."""
    logs = read_audit_logs_list()
    logs.append(
        {
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "event": event_type,
            "actor": actor,
            "role": actor_role,
            "status": operation_status,
            "ip": ip_address,
            "detail": detail_message,
            "path": endpoint_path,
            "request_id": request_id,
        }
    )
    _write_json_file(AUDIT_LOG_FILE, logs[-1000:])


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify password using bcrypt."""
    try:
        return bcrypt.checkpw(password.encode(), hashed_password.encode())
    except Exception:
        return False


def verify_token(token: str) -> Dict[str, Any]:
    """Verify and decode JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def snapshot_user_scd2(
    session: AsyncSession,
    user: User,
    operation_type: str,
    changed_by: str,
    change_reason: Optional[str],
    is_current: bool,
) -> None:
    """Write a Type-2 history snapshot for a user record."""
    now = datetime.utcnow()

    await session.execute(
        update(UserAccessSCD2)
        .where(UserAccessSCD2.user_id == user.id, UserAccessSCD2.is_current.is_(True))
        .values(is_current=False, valid_to=now)
    )

    session.add(
        UserAccessSCD2(
            user_id=user.id,
            username=user.username,
            role=user.role,
            password_hash=user.password_hash,
            panels_json=user.panels_json or panels_to_json(default_panels_for_role(user.role)),
            is_active=bool(user.is_active),
            operation_type=operation_type,
            changed_by=changed_by,
            change_reason=change_reason,
            valid_from=now,
            valid_to=None if is_current else now,
            is_current=is_current,
        )
    )


async def ensure_bootstrap_users(session: AsyncSession) -> None:
    """Bootstrap SQL users from env or legacy JSON source when empty."""
    existing_users = (await session.execute(select(User))).scalars().all()
    if existing_users:
        return

    created: List[User] = []

    # Prefer migrating legacy JSON users first if available.
    legacy_users = read_users_list()
    for legacy_user in legacy_users:
        username = str(legacy_user.get("username", "")).strip()
        password_hash = str(legacy_user.get("password_hash", "")).strip()
        role = str(legacy_user.get("role", "user")).strip().lower()
        panels = normalize_panels(legacy_user.get("panels"), role=role)

        if not username or not password_hash:
            continue

        created.append(
            User(
                username=username,
                password_hash=password_hash,
                role="admin" if role == "admin" else "user",
                panels_json=panels_to_json(panels),
                is_active=True,
            )
        )

    if not created:
        bootstrap_admin_user = os.environ.get("AUTH_BOOTSTRAP_ADMIN_USER", "admin").strip() or "admin"
        bootstrap_admin_password = os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "admin123")
        bootstrap_user = os.environ.get("AUTH_BOOTSTRAP_USER", "operator").strip() or "operator"
        bootstrap_user_password = os.environ.get("AUTH_BOOTSTRAP_USER_PASSWORD", "operator123")

        created = [
            User(
                username=bootstrap_admin_user,
                password_hash=hash_password(bootstrap_admin_password),
                role="admin",
                panels_json=panels_to_json(default_panels_for_role("admin")),
                is_active=True,
            ),
            User(
                username=bootstrap_user,
                password_hash=hash_password(bootstrap_user_password),
                role="user",
                panels_json=panels_to_json(default_panels_for_role("user")),
                is_active=True,
            ),
        ]

    for user in created:
        session.add(user)

    await session.flush()

    for user in created:
        await snapshot_user_scd2(
            session=session,
            user=user,
            operation_type="migrate",
            changed_by="system",
            change_reason="initial bootstrap/migration",
            is_current=True,
        )

    await session.commit()


async def get_authenticated_user(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Dict[str, Any]:
    """Dependency: validate bearer token and return payload."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )

    token = authorization.split(" ", 1)[1]
    return verify_token(token)


async def require_admin_role(
    payload: Dict[str, Any] = Depends(get_authenticated_user),
) -> Dict[str, Any]:
    """Dependency: enforce admin role."""
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return payload


@router.post(
    "/login",
    response_model=DataResponse[TokenResponse],
    responses={401: {"model": ErrorResponse}},
    summary="Login",
    description="Authenticate with username and password"
)
async def login(
    request: LoginRequest,
    session: AsyncSession = Depends(get_db_session),
) -> DataResponse[TokenResponse]:
    """Authenticate user and return JWT token."""
    try:
        await ensure_bootstrap_users(session)

        username = request.username.strip()
        matched_user = (
            await session.execute(
                select(User).where(User.username.ilike(username), User.is_active.is_(True))
            )
        ).scalar_one_or_none()

        password_valid = bool(matched_user) and verify_password(request.password, str(matched_user.password_hash or ""))

        # Recovery fallback for local admin bootstrap credential.
        if not password_valid and matched_user:
            bootstrap_admin_user = os.environ.get("AUTH_BOOTSTRAP_ADMIN_USER", "admin").strip().lower()
            bootstrap_admin_password = os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "")
            if (
                matched_user.role == "admin"
                and matched_user.username.strip().lower() == bootstrap_admin_user
                and bootstrap_admin_password
                and request.password == bootstrap_admin_password
            ):
                matched_user.password_hash = hash_password(request.password)
                await session.commit()
                await session.refresh(matched_user)
                password_valid = True

        if not matched_user or not password_valid:
            append_audit_entry(
                event_type="login_failed",
                actor=username,
                actor_role="system",
                operation_status="failure",
                detail_message="Invalid credentials",
                endpoint_path="/auth/login",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials"
            )

        user_panels = parse_panels_json(matched_user.panels_json, role=matched_user.role)

        user = {
            "username": matched_user.username,
            "user_id": matched_user.id,
            "role": matched_user.role,
            "panels": user_panels,
        }

        token = create_access_token(user)
        expires_in = JWT_EXPIRY_HOURS * 3600

        append_audit_entry(
            event_type="login_success",
            actor=user["username"],
            actor_role=user["role"],
            operation_status="success",
            detail_message=f"User {user['username']} logged in",
            endpoint_path="/auth/login",
        )

        return DataResponse(
            data=TokenResponse(
                access_token=token,
                expires_in=expires_in,
                user={"username": user["username"], "role": user["role"], "panels": user_panels}
            ),
            request_id=None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("login_failed", extra={"error": str(e)})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )


@router.get(
    "/me",
    response_model=DataResponse[CurrentUserResponse],
    responses={401: {"model": ErrorResponse}},
    summary="Get current user",
    description="Get information about the currently authenticated user"
)
async def get_current_user(
    payload: Dict[str, Any] = Depends(get_authenticated_user),
) -> DataResponse[CurrentUserResponse]:
    """Get information about the authenticated user."""
    return DataResponse(
        data=CurrentUserResponse(
            id=payload.get("user_id", 0),
            username=payload.get("username", ""),
            role=payload.get("role", "user"),
            created_at=datetime.utcnow()
        ),
        request_id=None
    )


@router.post(
    "/logout",
    response_model=Dict[str, Any],
    summary="Logout",
    description="Logout current user (client-side token removal)"
)
async def logout() -> Dict[str, Any]:
    """Client-side logout endpoint."""
    return {
        "status": "success",
        "message": "Logged out successfully"
    }
