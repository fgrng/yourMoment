"""
Pure unit tests for logging configuration helpers.

Tests the logging configuration utilities from src/config/logging.py.
"""

import pytest
import logging
from src.config.logging import (
    _resolve_log_level,
    _build_formatter,
    format_log_context,
    _ServiceNameFilter
)


def test_resolve_log_level_from_int():
    """Should return the integer as-is if it's already an int."""
    assert _resolve_log_level(logging.DEBUG, "INFO") == logging.DEBUG


def test_resolve_log_level_from_string():
    """Should correctly resolve log levels from string names."""
    assert _resolve_log_level("DEBUG", "INFO") == logging.DEBUG
    assert _resolve_log_level("warning", "INFO") == logging.WARNING
    assert _resolve_log_level("ERROR", "INFO") == logging.ERROR


def test_resolve_log_level_invalid_fallback():
    """Should fallback to the specified default level if name is invalid."""
    assert _resolve_log_level("BOGUS_LEVEL", "DEBUG") == logging.DEBUG


def test_build_formatter_development():
    """Should return the dev-specific formatter."""
    formatter = _build_formatter("development")
    # Development formatter has a specific pattern, we just check it exists
    assert isinstance(formatter, logging.Formatter)


def test_build_formatter_production():
    """Should return the production-specific formatter."""
    formatter = _build_formatter("production")
    assert isinstance(formatter, logging.Formatter)


def test_format_log_context():
    """Should correctly format a dict into a key=value string."""
    context = {
        "user_id": 123,
        "action": "login",
        "empty": "",
        "none": None
    }
    # Should skip empty and None values
    formatted = format_log_context(**context)
    
    # Check parts (order may vary in some Python versions, but fragments list handles it)
    assert "user_id=123" in formatted
    assert "action=login" in formatted
    assert "empty=" not in formatted
    assert "none=" not in formatted


def test_service_name_filter():
    """Should add the service name to log records."""
    name_filter = _ServiceNameFilter("test-service")
    record = MagicMock()
    # Mock hasattr to return False for "service"
    del record.service
    
    name_filter.filter(record)
    assert record.service == "test-service"


# We need MagicMock for the last test
from unittest.mock import MagicMock
