"""
Domain-specific exceptions for Sektor Pilot.

Keeping exceptions in their own module avoids circular imports and makes
error-handling contracts explicit across routes, container manager, and worker.
"""


class SektorError(Exception):
    """Base class for all Sektor Pilot errors."""


class UnknownSectorError(SektorError):
    """Raised when a sector_id is not found in the configured SECTOR_INSTANCES registry."""


class DockerExecutionError(SektorError):
    """Raised when a Docker subprocess command fails or times out."""


class AuditLoggingError(SektorError):
    """Raised when writing an audit entry to Google Sheets fails unrecoverably."""
