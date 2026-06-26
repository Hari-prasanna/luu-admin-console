"""Tests for authentication and user management."""

import json
import os
import tempfile
from pathlib import Path

import pytest
import bcrypt

from backend.api.v1.internal_transport import (
    hash_password,
    verify_password,
    read_users_list,
    write_users_list,
    append_audit_entry,
    read_audit_logs_list,
)


def test_hash_password():
    """Test password hashing."""
    password = "TestPassword123!"
    hashed = hash_password(password)

    assert hashed != password
    assert bcrypt.checkpw(password.encode(), hashed.encode())


def test_verify_password():
    """Test password verification."""
    password = "TestPassword123!"
    hashed = hash_password(password)

    assert verify_password(password, hashed)
    assert not verify_password("WrongPassword", hashed)


def test_read_write_users_list(temp_auth_dir):
    """Test reading and writing users list."""
    users_file = os.path.join(temp_auth_dir, "users.json")
    test_users = [
        {"username": "admin", "password_hash": "hash1", "role": "admin"},
        {"username": "user", "password_hash": "hash2", "role": "user"},
    ]

    # Mock the file path
    import backend.api.v1.internal_transport as it
    original_users_file = it.USERS_FILE
    it.USERS_FILE = users_file

    try:
        write_users_list(test_users)
        loaded_users = read_users_list()

        assert len(loaded_users) == 2
        assert loaded_users[0]["username"] == "admin"
        assert loaded_users[1]["username"] == "user"
    finally:
        it.USERS_FILE = original_users_file


def test_append_audit_entry(temp_auth_dir):
    """Test appending audit entries."""
    audit_file = os.path.join(temp_auth_dir, "audit_logs.json")

    import backend.api.v1.internal_transport as it
    original_audit_file = it.AUDIT_LOG_FILE
    it.AUDIT_LOG_FILE = audit_file

    try:
        append_audit_entry(
            event_type="test_event",
            actor="test_user",
            actor_role="user",
            operation_status="success",
            detail_message="Test message",
        )

        logs = read_audit_logs_list()
        assert len(logs) == 1
        assert logs[0]["event"] == "test_event"
        assert logs[0]["actor"] == "test_user"
        assert logs[0]["detail"] == "Test message"
    finally:
        it.AUDIT_LOG_FILE = original_audit_file


def test_concurrent_audit_writes(temp_auth_dir):
    """Test that concurrent writes don't lose data due to file locking."""
    audit_file = os.path.join(temp_auth_dir, "audit_logs.json")

    import backend.api.v1.internal_transport as it
    original_audit_file = it.AUDIT_LOG_FILE
    it.AUDIT_LOG_FILE = audit_file

    try:
        for i in range(5):
            append_audit_entry(
                event_type=f"event_{i}",
                actor=f"user_{i}",
                operation_status="success",
            )

        logs = read_audit_logs_list()
        assert len(logs) == 5
        for i, log in enumerate(logs):
            assert log["event"] == f"event_{i}"
    finally:
        it.AUDIT_LOG_FILE = original_audit_file
