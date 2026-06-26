"""Base service class with common patterns.

All services inherit from BaseService to ensure consistent:
- Error handling
- Logging
- Validation
- Operation timing

Usage:
    class MetricService(BaseService[MetricRepository]):
        def __init__(self, db: AsyncSession):
            repo = MetricRepository(db)
            logger = logging.getLogger("luu.services.metrics")
            super().__init__(db, repo, logger)

        async def record_metric(self, **kwargs):
            validated = await self.validate_input(**kwargs)
            result = await self.repo.create(**validated)
            await self.log_operation("record_metric")
            return result
"""

import logging
import time
from typing import Any, Optional, TypeVar, Generic

from sqlalchemy.ext.asyncio import AsyncSession

from backend.exceptions import AppError

T = TypeVar('T')


class BaseService(Generic[T]):
    """Generic base service with common patterns."""

    def __init__(
        self,
        db: AsyncSession,
        repo: Any,
        logger: logging.Logger,
    ):
        """Initialize service.

        Args:
            db: AsyncSession for database operations
            repo: Repository instance for data access
            logger: Logger instance for this service
        """
        self.db = db
        self.repo = repo
        self.logger = logger
        self._operation_start_time: Optional[float] = None

    async def validate_input(self, **kwargs) -> dict:
        """Validate input before processing.

        Override in subclass for specific validation.

        Args:
            **kwargs: Input fields to validate

        Returns:
            Validated input dict

        Raises:
            ValidationError: If validation fails
        """
        return kwargs

    def _start_timer(self) -> None:
        """Start operation timer."""
        self._operation_start_time = time.time()

    def _get_duration_ms(self) -> int:
        """Get operation duration in milliseconds."""
        if self._operation_start_time is None:
            return 0
        return int((time.time() - self._operation_start_time) * 1000)

    async def log_operation(
        self,
        operation: str,
        details: Optional[dict] = None,
        duration_ms: Optional[int] = None,
        status: str = "success",
    ) -> None:
        """Log service operation.

        Args:
            operation: Operation name (e.g., "record_metric")
            details: Optional details dict
            duration_ms: Optional operation duration
            status: Operation status (success, failure, etc.)
        """
        if duration_ms is None:
            duration_ms = self._get_duration_ms()

        self.logger.info(
            event=f"service_{operation}",
            extra={
                "service": self.__class__.__name__,
                "operation": operation,
                "status": status,
                "details": details,
                "duration_ms": duration_ms,
            },
        )

    async def handle_error(
        self,
        error: Exception,
        operation: str,
        details: Optional[dict] = None,
    ) -> None:
        """Centralized error handling.

        Args:
            error: Exception to handle
            operation: Operation name that failed
            details: Optional context details

        Raises:
            AppError: Re-raised as standardized error
        """
        duration_ms = self._get_duration_ms()

        self.logger.error(
            event=f"service_{operation}_failed",
            extra={
                "service": self.__class__.__name__,
                "operation": operation,
                "error": str(error),
                "error_type": type(error).__name__,
                "details": details,
                "duration_ms": duration_ms,
            },
            exc_info=error,
        )

        await self.log_operation(
            operation,
            details=details,
            status="error",
        )

        raise AppError(f"Failed to {operation}") from error

    async def safe_operation(
        self,
        operation_name: str,
        operation_func,
        *args,
        **kwargs,
    ) -> Any:
        """Execute operation with automatic error handling and logging.

        Args:
            operation_name: Name of operation for logging
            operation_func: Async function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function

        Returns:
            Operation result

        Example:
            result = await self.safe_operation(
                "record_metric",
                self.repo.create,
                metric_key="we_bgl",
                metric_value=100,
            )
        """
        self._start_timer()

        try:
            result = await operation_func(*args, **kwargs)
            await self.log_operation(operation_name)
            return result

        except Exception as error:
            await self.handle_error(error, operation_name)
            # handle_error raises, so this never executes
            return None
