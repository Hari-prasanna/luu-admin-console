"""Tests for configuration loading."""

import os
import pytest

from backend.config import Settings, Constants


def test_settings_from_env():
    """Test that Settings correctly reads from environment variables."""
    os.environ["ORA_USER"] = "test_user"
    os.environ["ORA_PASSWORD"] = "test_password"
    os.environ["ORA_HOST"] = "test_host"
    os.environ["ORA_SERVICE"] = "test_service"

    settings = Settings()

    assert settings.oracle_user == "test_user"
    assert settings.oracle_password == "test_password"
    assert settings.oracle_host == "test_host"
    assert settings.oracle_service == "test_service"
    assert settings.oracle_port == 1521  # Default


def test_constants_defined():
    """Test that all required constants are defined."""
    assert Constants.MAX_ORACLE_RETRY_ATTEMPTS == 3
    assert Constants.MAX_GOOGLE_SHEETS_RETRY_ATTEMPTS == 2
    assert Constants.MAX_DOCKER_RETRY_ATTEMPTS == 2
    assert Constants.ORACLE_QUERY_TIMEOUT_SECONDS > 0
    assert Constants.LOG_LEVEL in ["INFO", "DEBUG", "WARNING", "ERROR"]
