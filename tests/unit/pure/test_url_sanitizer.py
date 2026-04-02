"""
Pure unit tests for URL sanitization logic.

Tests the URL sanitization utilities from src/utils/url_sanitizer.py.
"""

import pytest
from src.utils.url_sanitizer import (
    sanitize_url,
    is_url_malformed,
    safe_parse_url,
    join_url_with_path,
    reconstruct_url_from_parts
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


def test_safe_parse_url():
    """Should correctly parse both valid and malformed URLs."""
    # Valid URL
    parsed = safe_parse_url("https://example.com/path?query=1#frag")
    assert parsed.scheme == "https"
    assert parsed.netloc == "example.com"
    assert parsed.path == "/path"
    assert parsed.query == "query=1"
    assert parsed.fragment == "frag"

    # Malformed URL
    parsed = safe_parse_url("https://example.com\\path")
    assert parsed.scheme == "https"
    assert parsed.netloc == "example.com"
    assert parsed.path == "/path"


def test_reconstruct_url_from_parts():
    """Should correctly reconstruct a URL from its components."""
    url = reconstruct_url_from_parts(
        "https", "example.com", "/path", query="q=1"
    )
    assert url == "https://example.com/path?q=1"


def test_join_url_with_path():
    """Should correctly join base URL and path, handling malformations."""
    # Base URL with backslash
    base = "https://www.mymoment.ch:443\\"
    path = "/accounts/login/"
    expected = "https://www.mymoment.ch:443/accounts/login/"
    assert join_url_with_path(base, path) == expected

    # Relative path without leading slash
    base = "https://host/app"
    path = "api/v1"
    expected = "https://host/app/api/v1"
    assert join_url_with_path(base, path) == expected

    # Base URL with trailing slash, path with leading slash
    base = "https://host/app/"
    path = "/api/v1/"
    expected = "https://host/app/api/v1/"
    assert join_url_with_path(base, path) == expected
