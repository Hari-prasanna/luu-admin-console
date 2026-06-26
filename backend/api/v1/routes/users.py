"""User management endpoints."""

import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from backend.database import get_db_session
from backend.db_models import User
from backend.api.v1.schemas import (
    DataResponse, PaginatedResponse, ErrorResponse, PaginationMeta
)
from .auth import (
    require_admin_role,
    hash_password,
    append_audit_entry,
    ensure_bootstrap_users,
    normalize_panels,
    parse_panels_json,
    panels_to_json,
    snapshot_user_scd2,
)

logger = logging.getLogger("luu.api.users")
router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    """Create user request."""
    username: str
    password: str
    role: str = "user"
    panels: Optional[List[str]] = None


class UserUpdate(BaseModel):
    """Update user request."""
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    panels: Optional[List[str]] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """User response."""
    id: int
    username: str
    role: str
    panels: List[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: str


class UserListResponse(BaseModel):
    """User list response."""
    id: int
    username: str
    role: str
    panels: List[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: str


@router.get(
    "",
    response_model=PaginatedResponse[UserListResponse],
    responses={403: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="List users",
    description="Get paginated list of all users (admin only)"
)
async def list_users(
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
    admin: Dict[str, Any] = Depends(require_admin_role),
) -> PaginatedResponse[UserListResponse]:
    """List users (admin only)."""
    try:
        await ensure_bootstrap_users(session)

        total = await session.scalar(select(func.count()).select_from(User))
        users_page = (
            await session.execute(
                select(User).order_by(User.id.asc()).offset(offset).limit(limit)
            )
        ).scalars().all()

        users: List[UserListResponse] = [
            UserListResponse(
                id=user.id,
                username=user.username,
                role=user.role,
                panels=parse_panels_json(user.panels_json, role=user.role),
                is_active=bool(user.is_active),
                created_at=(user.created_at or datetime.utcnow()).isoformat(),
            )
            for user in users_page
        ]

        return PaginatedResponse(
            data=users,
            pagination=PaginationMeta(limit=limit, offset=offset, total=int(total or 0)),
            request_id=None
        )
    except Exception as e:
        logger.error("list_users_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to list users")


@router.post(
    "",
    response_model=DataResponse[UserResponse],
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Create user",
    description="Create a new user account (admin only)"
)
async def create_user(
    request: UserCreate,
    session: AsyncSession = Depends(get_db_session),
    admin: Dict[str, Any] = Depends(require_admin_role),
) -> DataResponse[UserResponse]:
    """Create a user (admin only)."""
    try:
        await ensure_bootstrap_users(session)

        if len(request.password) < 6:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 6 characters"
            )

        role = (request.role or "user").strip().lower()
        if role not in {"admin", "user"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Role must be either 'admin' or 'user'",
            )

        requested_username = request.username.strip()
        if not requested_username:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username is required")

        existing = (
            await session.execute(select(User).where(User.username.ilike(requested_username)))
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists",
            )

        panels = normalize_panels(request.panels, role=role)
        user = User(
            username=requested_username,
            password_hash=hash_password(request.password),
            role=role,
            panels_json=panels_to_json(panels),
            is_active=True,
        )
        session.add(user)
        await session.flush()

        await snapshot_user_scd2(
            session=session,
            user=user,
            operation_type="create",
            changed_by=str(admin.get("username", "admin")),
            change_reason="created via admin panel",
            is_current=True,
        )

        await session.commit()
        await session.refresh(user)

        append_audit_entry(
            event_type="user_created",
            actor=str(admin.get("username", "admin")),
            actor_role=str(admin.get("role", "admin")),
            operation_status="success",
            detail_message=f"Created user {requested_username}",
            endpoint_path="/users",
        )

        return DataResponse(
            data=UserResponse(
                id=user.id,
                username=user.username,
                role=user.role,
                panels=parse_panels_json(user.panels_json, role=user.role),
                is_active=bool(user.is_active),
                created_at=(user.created_at or datetime.utcnow()).isoformat(),
            ),
            request_id=None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("create_user_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to create user")


@router.put(
    "/{user_id}",
    response_model=DataResponse[UserResponse],
    responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Update user",
    description="Update username, password, role, panels, and active status (admin only)"
)
async def update_user(
    user_id: int,
    request: UserUpdate,
    session: AsyncSession = Depends(get_db_session),
    admin: Dict[str, Any] = Depends(require_admin_role),
) -> DataResponse[UserResponse]:
    """Update user profile and panel permissions."""
    try:
        await ensure_bootstrap_users(session)

        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        admin_username = str(admin.get("username", "")).strip().lower()
        if user.username.strip().lower() == admin_username and request.is_active is False:
            raise HTTPException(status_code=400, detail="You cannot disable your own account")

        if request.username is not None:
            new_username = request.username.strip()
            if not new_username:
                raise HTTPException(status_code=400, detail="Username cannot be empty")
            duplicate = (
                await session.execute(
                    select(User).where(User.username.ilike(new_username), User.id != user_id)
                )
            ).scalar_one_or_none()
            if duplicate:
                raise HTTPException(status_code=400, detail="Username already exists")
            user.username = new_username

        if request.password is not None and request.password != "":
            if len(request.password) < 6:
                raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
            user.password_hash = hash_password(request.password)

        if request.role is not None:
            new_role = request.role.strip().lower()
            if new_role not in {"admin", "user"}:
                raise HTTPException(status_code=400, detail="Role must be either 'admin' or 'user'")
            user.role = new_role

        if request.panels is not None:
            user.panels_json = panels_to_json(normalize_panels(request.panels, role=user.role))
        elif request.role is not None and not user.panels_json:
            user.panels_json = panels_to_json(normalize_panels(None, role=user.role))

        if request.is_active is not None:
            user.is_active = bool(request.is_active)

        await session.flush()

        await snapshot_user_scd2(
            session=session,
            user=user,
            operation_type="update",
            changed_by=str(admin.get("username", "admin")),
            change_reason="updated via admin panel",
            is_current=bool(user.is_active),
        )

        await session.commit()
        await session.refresh(user)

        append_audit_entry(
            event_type="user_modified",
            actor=str(admin.get("username", "admin")),
            actor_role=str(admin.get("role", "admin")),
            operation_status="success",
            detail_message=f"Updated user {user.username}",
            endpoint_path=f"/users/{user_id}",
        )

        return DataResponse(
            data=UserResponse(
                id=user.id,
                username=user.username,
                role=user.role,
                panels=parse_panels_json(user.panels_json, role=user.role),
                is_active=bool(user.is_active),
                created_at=(user.created_at or datetime.utcnow()).isoformat(),
            ),
            request_id=None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("update_user_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to update user")


@router.get(
    "/{user_id}",
    response_model=DataResponse[UserResponse],
    responses={404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Get user",
    description="Get user details by ID"
)
async def get_user(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
    admin: Dict[str, Any] = Depends(require_admin_role),
) -> DataResponse[UserResponse]:
    """Get user by ID."""
    try:
        await ensure_bootstrap_users(session)

        selected_user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if not selected_user:
            raise HTTPException(status_code=404, detail="User not found")

        return DataResponse(
            data=UserResponse(
                id=selected_user.id,
                username=selected_user.username,
                role=selected_user.role,
                panels=parse_panels_json(selected_user.panels_json, role=selected_user.role),
                is_active=bool(selected_user.is_active),
                created_at=(selected_user.created_at or datetime.utcnow()).isoformat(),
            ),
            request_id=None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_user_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to get user")


@router.delete(
    "/{user_id}",
    response_model=DataResponse[dict],
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Delete user",
    description="Deactivate a user account (admin only)"
)
async def delete_user(
    user_id: int,
    session: AsyncSession = Depends(get_db_session),
    admin: Dict[str, Any] = Depends(require_admin_role),
) -> DataResponse[dict]:
    """Deactivate user and persist SCD2 history."""
    try:
        await ensure_bootstrap_users(session)

        user_to_delete = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        if not user_to_delete:
            raise HTTPException(status_code=404, detail="User not found")

        if user_to_delete.username.strip().lower() == str(admin.get("username", "")).strip().lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot delete your own account",
            )

        user_to_delete.is_active = False
        await session.flush()

        await snapshot_user_scd2(
            session=session,
            user=user_to_delete,
            operation_type="delete",
            changed_by=str(admin.get("username", "admin")),
            change_reason="deactivated via admin panel",
            is_current=False,
        )

        await session.commit()

        append_audit_entry(
            event_type="user_deleted",
            actor=str(admin.get("username", "admin")),
            actor_role=str(admin.get("role", "admin")),
            operation_status="success",
            detail_message=f"Deactivated user {user_to_delete.username}",
            endpoint_path=f"/users/{user_id}",
        )

        return DataResponse(
            data={"message": f"User {user_id} deactivated successfully"},
            request_id=None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_user_failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Failed to delete user")
