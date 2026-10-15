"""
Pure unit tests for URL sanitization logic.

Tests the URL sanitization utilities from src/utils/url_sanitizer.py.
"""

import pytest
from src.utils.url_sanitizer import (
    sanitize_url,
    is_url_malformed,
)


def test_sanitize_url():
    """Should replace backslashes with forward slashes in URLs."""
    # Malformed redirect URL (myMoment bug)
    url = r"https://www.mymoment.ch:443\accounts/login/"
    expected = "https://www.mymoment.ch:443/accounts/login/"
    assert sanitize_url(url) == expected

    # Multiple backslashes
    url = r"https://host:port\\\\path\to\somewhere/"
    expected = "https://host:port////path/to/somewhere/"
    assert sanitize_url(url) == expected


def test_sanitize_url_empty_raises_error():
    """Should raise ValueError for empty or None URL."""
    with pytest.raises(ValueError, match="URL cannot be empty or None"):
        sanitize_url("")
    with pytest.raises(ValueError, match="URL cannot be empty or None"):
        sanitize_url(None)


def test_is_url_malformed():
    """Should correctly identify malformed URLs with backslashes."""
    assert is_url_malformed("https://host\\path") is True
    assert is_url_malformed("https://host/path") is False
    assert is_url_malformed("") is False
    assert is_url_malformed(None) is False
