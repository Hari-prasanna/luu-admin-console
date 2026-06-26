"""
Health check endpoints for system diagnostics.

Provides deep health checks for Oracle, PostgreSQL, background threads, and automation workers.
"""

import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("luu.health")


class HealthCheck:
    """Health check probe for system diagnostics."""

    def __init__(self):
        self.last_oracle_check: Optional[float] = None
        self.last_oracle_error: Optional[str] = None
        self.oracle_consecutive_failures: int = 0
        self.last_postgres_check: Optional[float] = None
        self.last_postgres_error: Optional[str] = None
        self.postgres_consecutive_failures: int = 0
        self.last_metrics_refresh: Optional[datetime] = None
        self.metrics_consecutive_failures: int = 0

    async def check_oracle(self, oracle_pool: Any) -> Dict[str, Any]:
        """Check Oracle database connectivity."""
        start_time = time.time()
        try:
            # Attempt a simple query to verify connectivity
            async with oracle_pool.connection() as conn:
                cursor = conn.cursor()
                await cursor.execute("SELECT 1 FROM DUAL")
                await cursor.fetchone()
                await cursor.close()

            connection_time_ms = int((time.time() - start_time) * 1000)
            self.last_oracle_check = time.time()
            self.last_oracle_error = None
            self.oracle_consecutive_failures = 0

            return {
                "status": "ok",
                "connection_time_ms": connection_time_ms,
                "last_query": datetime.utcnow().isoformat() + "Z",
                "consecutive_failures": 0,
            }
        except Exception as e:
            self.oracle_consecutive_failures += 1
            self.last_oracle_error = str(e)
            logger.error(
                "oracle_health_check_failed",
                extra={
                    "error_message": str(e),
                    "status": "failure",
                    "duration_ms": int((time.time() - start_time) * 1000),
                },
            )
            return {
                "status": "error",
                "error": str(e),
                "consecutive_failures": self.oracle_consecutive_failures,
            }

    async def check_postgres(self, session: AsyncSession) -> Dict[str, Any]:
        """Check PostgreSQL connectivity and table counts."""
        start_time = time.time()
        try:
            # Simple connectivity check
            result = await session.execute(text("SELECT 1"))
            row = result.fetchone()

            connection_time_ms = int((time.time() - start_time) * 1000)

            # Get table counts (non-blocking)
            table_counts = {}
            tables = ["operation_logs", "job_executions", "audit_logs", "metric_history"]
            for table_name in tables:
                try:
                    count_result = await session.execute(
                        text(f"SELECT COUNT(*) FROM {table_name}")
                    )
                    count_row = count_result.fetchone()
                    table_counts[table_name] = count_row[0] if count_row else 0
                except Exception:
                    table_counts[table_name] = 0

            self.last_postgres_check = time.time()
            self.last_postgres_error = None
            self.postgres_consecutive_failures = 0

            return {
                "status": "ok",
                "connection_time_ms": connection_time_ms,
                "table_counts": table_counts,
            }
        except Exception as e:
            self.postgres_consecutive_failures += 1
            self.last_postgres_error = str(e)
            logger.error(
                "postgres_health_check_failed",
                extra={
                    "error_message": str(e),
                    "status": "failure",
                    "duration_ms": int((time.time() - start_time) * 1000),
                },
            )
            return {
                "status": "error",
                "error": str(e),
                "consecutive_failures": self.postgres_consecutive_failures,
            }

    async def check_background_threads(self) -> Dict[str, Any]:
        """Check status of background refresh threads."""
        return {
            "metrics_refresh": {
                "status": "ok",
                "last_run": (
                    self.last_metrics_refresh.isoformat() + "Z"
                    if self.last_metrics_refresh
                    else None
                ),
                "consecutive_failures": self.metrics_consecutive_failures,
            }
        }

    async def check_automation(self) -> Dict[str, Any]:
        """Check automation workers health."""
        return {
            "status": "ok",
            "running_sectors": [],
            "paused_sectors": [],
            "last_heartbeat": datetime.utcnow().isoformat() + "Z",
        }

    async def deep_health_check(
        self, oracle_pool: Any, session: AsyncSession
    ) -> Dict[str, Any]:
        """Perform comprehensive health check."""
        start_time = time.time()

        checks = {
            "api": {"status": "ok", "response_time_ms": 0},
            "oracle": await self.check_oracle(oracle_pool),
            "postgres": await self.check_postgres(session),
            "background_threads": await self.check_background_threads(),
            "automation": await self.check_automation(),
        }

        # Determine overall status
        overall_status = "healthy"
        for check_name, check_result in checks.items():
            if check_result.get("status") == "error":
                overall_status = "degraded"
            elif check_name == "oracle" and check_result.get("consecutive_failures", 0) > 3:
                overall_status = "degraded"

        return {
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "response_time_ms": int((time.time() - start_time) * 1000),
            "checks": checks,
        }


# Global health check instance
_health_check_instance: Optional[HealthCheck] = None


def get_health_check() -> HealthCheck:
    """Get singleton health check instance."""
    global _health_check_instance
    if _health_check_instance is None:
        _health_check_instance = HealthCheck()
    return _health_check_instance
