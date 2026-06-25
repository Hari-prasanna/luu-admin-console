"""
Typed exception hierarchy for LUU Q-Console backend.

Provides specific exception types for all error scenarios per Clean Code Chapter 7:
- Exceptions over error codes
- No bare `except` blocks
- Defensive logging boundaries
"""


class AppError(Exception):
    """Base exception for all LUU Q-Console application errors."""

    def __init__(self, message: str, context: dict | None = None) -> None:
        """Initialize AppError with message and optional context.

        Args:
            message: Human-readable error description (safe for client)
            context: Optional dict with debug details (logged server-side only)
        """
        super().__init__(message)
        self.message = message
        self.context = context or {}


class OracleConnectionError(AppError):
    """Raised when Oracle database connection fails."""

    pass


class OracleQueryError(AppError):
    """Raised when Oracle query execution fails."""

    pass


class GoogleSheetsAuthenticationError(AppError):
    """Raised when Google Sheets API authentication fails."""

    pass


class GoogleSheetsNetworkError(AppError):
    """Raised when Google Sheets API network call fails."""

    pass


class GoogleSheetsDataError(AppError):
    """Raised when Google Sheets data operation fails (read/write)."""

    pass


class DockerExecutionError(AppError):
    """Raised when Docker command execution fails."""

    pass


class ValidationError(AppError):
    """Raised when input validation fails."""

    pass


class ConfigurationError(AppError):
    """Raised when configuration is missing or invalid."""

    pass
