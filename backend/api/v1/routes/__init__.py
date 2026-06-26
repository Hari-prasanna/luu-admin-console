"""API v1 routes package."""

from fastapi import APIRouter

from .metrics import router as metrics_router
from .auth import router as auth_router
from .health import router as health_router
from .audit import router as audit_router
from .users import router as users_router
from .feedback import router as feedback_router

__all__ = [
    "metrics_router",
    "auth_router",
    "health_router",
    "audit_router",
    "users_router",
    "feedback_router",
]
