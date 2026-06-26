"""Tests for Oracle connection pooling."""

import pytest

from backend.infrastructure.oracle_pool import (
    _parse_env_file_into_dict,
    build_oracle_connection_credentials,
)
from backend.exceptions import ConfigurationError


def test_parse_env_file_into_dict(temp_logs_dir):
    """Test parsing of .env file format."""
    env_content = """
# This is a comment
ORA_USER=test_user
ORA_PASSWORD=test_password
ORA_HOST=test_host
ORA_PORT=1521
ORA_SERVICE=test_service
# Another comment
UNKNOWN_VAR=value
"""
    env_file = temp_logs_dir + "/test.env"
    with open(env_file, "w") as f:
        f.write(env_content)

    parsed = _parse_env_file_into_dict(env_file)

    assert parsed["ORA_USER"] == "test_user"
    assert parsed["ORA_PASSWORD"] == "test_password"
    assert parsed["ORA_HOST"] == "test_host"
    assert parsed["ORA_PORT"] == "1521"
    assert parsed["ORA_SERVICE"] == "test_service"
    assert parsed["UNKNOWN_VAR"] == "value"


def test_build_oracle_connection_credentials():
    """Test building Oracle connection credentials."""
    credentials_dict = {
        "ORA_USER": "test_user",
        "ORA_PASSWORD": "test_password",
        "ORA_HOST": "test_host",
        "ORA_PORT": "1521",
        "ORA_SERVICE": "test_service",
    }

    result = build_oracle_connection_credentials(credentials_dict)

    assert result["user"] == "test_user"
    assert result["password"] == "test_password"
    assert result["host"] == "test_host"
    assert result["port"] == "1521"
    assert result["service"] == "test_service"


def test_build_oracle_connection_credentials_missing_required():
    """Test that missing required credentials raise ConfigurationError."""
    credentials_dict = {
        "ORA_USER": "test_user",
        # Missing password, host, and service
    }

    with pytest.raises(ConfigurationError) as exc_info:
        build_oracle_connection_credentials(credentials_dict)

    assert "Missing Oracle credential(s)" in str(exc_info.value)
