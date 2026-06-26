"""
Centralized configuration for LUU Q-Console backend.

Loads environment variables and defines application-wide constants.
Follows Clean Code principle: one place for settings.
"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration from environment variables."""

    # Oracle Database
    oracle_user: str = os.getenv("ORA_USER", "")
    oracle_password: str = os.getenv("ORA_PASSWORD", "")
    oracle_host: str = os.getenv("ORA_HOST", "")
    oracle_port: int = int(os.getenv("ORA_PORT", "1521"))
    oracle_service: str = os.getenv("ORA_SERVICE", "")
    oracle_query_timeout_seconds: int = 30

    # Google Sheets
    google_sheets_credentials_json: str = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "")
    google_sheets_credentials_file: str = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
    google_sheets_spreadsheet_id: str = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")

    # Webhooks & Notifications
    chat_webhook_url: str = os.getenv("CHAT_WEBHOOK_URL", "")

    # Server
    server_host: str = os.getenv("SERVER_HOST", "0.0.0.0")
    server_port: int = int(os.getenv("SERVER_PORT", "8000"))
    server_reload: bool = os.getenv("SERVER_RELOAD", "false").lower() == "true"

    # Sektor Pilot
    sektor_docker_image: str = os.getenv("SEKTOR_DOCKER_IMAGE", "")
    sektor_docker_timeout_seconds: int = 10
    sektor_docker_stop_grace_period_seconds: int = 15
    sektor_poll_interval_seconds: int = 3
    sektor_idle_timeout_seconds: int = 1200  # 20 minutes

    class Config:
        """Pydantic config."""

        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()


# Application-wide constants
class Constants:
    """Application constants per Clean Code principle: searchable, intention-revealing."""

    # Retries
    MAX_ORACLE_RETRY_ATTEMPTS: int = 3
    MAX_GOOGLE_SHEETS_RETRY_ATTEMPTS: int = 2
    MAX_DOCKER_RETRY_ATTEMPTS: int = 2

    # Timeouts
    ORACLE_QUERY_TIMEOUT_SECONDS: int = settings.oracle_query_timeout_seconds
    DOCKER_COMMAND_TIMEOUT_SECONDS: int = settings.sektor_docker_timeout_seconds
    HTTP_REQUEST_TIMEOUT_SECONDS: int = 30

    # Paths
    PROJECT_ROOT: Path = Path(__file__).parent.parent.parent
    BACKEND_DIR: Path = PROJECT_ROOT / "backend"
    LOG_DIR: Path = BACKEND_DIR / "logs"
    STATE_DIR: Path = BACKEND_DIR / "state"

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE_NAME: str = "butler.log"
    LOG_MAX_BYTES: int = 1_000_000
    LOG_BACKUP_COUNT: int = 3

    # Error messages (normalized for client)
    ERROR_ORACLE_CONNECTION_FAILED: str = "Database connection failed. Please check the configuration."
    ERROR_ORACLE_QUERY_FAILED: str = "Database query failed. Please try again later."
    ERROR_GOOGLE_SHEETS_AUTH_FAILED: str = "Authentication service unavailable. Please verify credentials."
    ERROR_GOOGLE_SHEETS_NETWORK_FAILED: str = "Network error with external service. Please try again."
    ERROR_DOCKER_EXECUTION_FAILED: str = "Container orchestration failed. Please check system status."
    ERROR_VALIDATION_FAILED: str = "Invalid input. Please review and try again."
    ERROR_CONFIGURATION_INVALID: str = "System configuration error. Please contact support."


def validate_required_settings() -> None:
    """Validate that all required settings are configured.

    Raises:
        ConfigurationError: If any required setting is missing.
    """
    from exceptions import ConfigurationError

    missing_settings: list[str] = []

    if not settings.oracle_user:
        missing_settings.append("ORA_USER")
    if not settings.oracle_password:
        missing_settings.append("ORA_PASSWORD")
    if not settings.oracle_host:
        missing_settings.append("ORA_HOST")
    if not settings.oracle_service:
        missing_settings.append("ORA_SERVICE")

    if missing_settings:
        raise ConfigurationError(
            f"Missing required configuration: {', '.join(missing_settings)}",
            context={"missing_settings": missing_settings},
        )
