"""Pytest configuration and fixtures for LUU Q-Console tests."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_auth_dir():
    """Create a temporary directory for test auth files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def temp_logs_dir():
    """Create a temporary directory for test log files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def jwt_secret():
    """Provide a test JWT secret."""
    return "test-jwt-secret-that-is-long-enough-32-chars-minimum"


@pytest.fixture
def test_user_credentials():
    """Provide test user credentials."""
    return {
        "username": "testuser",
        "password": "TestPassword123!",
        "role": "user",
    }


@pytest.fixture
def test_admin_credentials():
    """Provide test admin credentials."""
    return {
        "username": "admin",
        "password": "AdminPassword123!",
        "role": "admin",
    }
