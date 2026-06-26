"""FastAPI application factory for v1 API."""

import logging
import os
from typing import Optional
from contextvars import ContextVar

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uuid

from backend.database import init_db, close_db
from backend.logging_config import setup_structured_logging
from .schemas import ErrorResponse, StatusEnum

# Import route modules
from .routes import (
    metrics_router,
    auth_router,
    health_router,
    audit_router,
    users_router,
)
from .routes import feedback_router
from .sektor_pilot import router as sektor_pilot_router

logger = logging.getLogger("luu.api.factory")

# Request ID context
_request_id_context: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def get_request_id() -> Optional[str]:
    """Get current request ID from context."""
    return _request_id_context.get()


def set_request_id(request_id: Optional[str]) -> None:
    """Set request ID in context."""
    _request_id_context.set(request_id)


def create_app() -> FastAPI:
    """
    Create and configure FastAPI application.

    Returns:
        Configured FastAPI instance
    """
    app = FastAPI(
        title="LUU Q-Console API",
        version="1.0.0",
        description="Real-time logistics monitoring platform",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        redoc_url="/api/v1/redoc",
    )

    # ─── Configuration ───

    # Rate limiting
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter

    # CORS
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

    # ─── Middleware ───

    class CorrelationIdMiddleware(BaseHTTPMiddleware):
        """Inject request ID into every request for tracing."""

        async def dispatch(self, request: Request, call_next):
            # Extract or create request ID
            request_id = request.headers.get("x-request-id")
            if not request_id:
                request_id = str(uuid.uuid4())

            # Store in context
            set_request_id(request_id)

            # Process request
            response = await call_next(request)

            # Add to response headers
            response.headers["x-request-id"] = request_id
            return response

    app.add_middleware(CorrelationIdMiddleware)

    # ─── Exception Handlers ───

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        """Handle rate limit exceeded errors."""
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=ErrorResponse(
                status=StatusEnum.ERROR,
                error_code="RATE_LIMIT_EXCEEDED",
                message="Too many requests. Please try again later.",
                request_id=get_request_id(),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        """Handle HTTP exceptions."""
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                status=StatusEnum.ERROR,
                error_code="HTTP_ERROR",
                message=exc.detail or "Internal server error",
                request_id=get_request_id(),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle unexpected exceptions."""
        logger.error("unhandled_exception", extra={"error": str(exc)}, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                status=StatusEnum.ERROR,
                error_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred. Please try again later.",
                request_id=get_request_id(),
            ).model_dump(mode="json"),
        )

    # ─── Lifespan Events ───

    @app.on_event("startup")
    async def startup():
        """Initialize on startup."""
        try:
            await init_db()
            logger.info("database_initialized")
        except Exception as e:
            logger.error("database_initialization_failed", extra={"error": str(e)})
            raise

    @app.on_event("shutdown")
    async def shutdown():
        """Cleanup on shutdown."""
        try:
            await close_db()
            logger.info("database_connection_closed")
        except Exception as e:
            logger.error("database_shutdown_failed", extra={"error": str(e)})

    # ─── Register Routes ───

    # Include all routers with v1 prefix
    app.include_router(metrics_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")
    app.include_router(users_router, prefix="/api/v1")
    app.include_router(feedback_router, prefix="/api/v1")

    # Include sektor_pilot router (already includes full path prefix)
    app.include_router(sektor_pilot_router)

    # Health endpoints at root for load balancers
    @app.get(
        "/health",
        tags=["health"],
        summary="Liveness probe",
        description="Root-level health check for load balancers"
    )
    async def root_health() -> dict:
        """Root health check endpoint."""
        return {"status": "ok"}

    return app


# Create application instance
app = create_app()
