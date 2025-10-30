"""
URL sanitization utilities to handle malformed redirect URLs.

Workaround for myMoment server bug that returns Location headers with backslashes
instead of forward slashes (e.g., "https://www.mymoment.ch:443\accounts/login/").

This module provides utilities to detect and fix these malformed URLs so they
can be used by HTTP clients that expect RFC 3986-compliant URLs.
"""

import re
import logging
from typing import Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)


def sanitize_url(url: str) -> str:
    """
    Sanitize a URL by fixing common malformations.

    Specifically handles the myMoment server bug where backslashes appear
    instead of forward slashes in redirect Location headers.

    Examples:
        - "https://www.mymoment.ch:443\\" -> "https://www.mymoment.ch:443/"
        - "https://www.mymoment.ch:443\\accounts/login/" -> "https://www.mymoment.ch:443/accounts/login/"

    Args:
        url: The URL string to sanitize

    Returns:
        Sanitized URL string

    Raises:
        ValueError: If URL is empty or None
    """
    if not url:
        raise ValueError("URL cannot be empty or None")

    original_url = url

    # Fix 1: Replace backslashes with forward slashes in the path component
    # This handles cases like "https://host:port\path" -> "https://host:port/path"
    url = url.replace('\\', '/')

    if url != original_url:
        logger.warning(
            f"Sanitized malformed URL: {repr(original_url)} -> {repr(url)}"
        )

    return url


def is_url_malformed(url: str) -> bool:
    """
    Check if a URL contains obvious malformations (backslashes).

    Args:
        url: The URL string to check

    Returns:
        True if the URL appears malformed, False otherwise
    """
    if not url:
        return False

    # Check for backslashes in the URL
    return '\\' in url


def safe_parse_url(url: str) -> Optional[tuple]:
    """
    Safely parse a URL, attempting to fix malformations first.

    Args:
        url: The URL string to parse

    Returns:
        Tuple of (scheme, netloc, path, params, query, fragment) or None if unparseable

    Raises:
        ValueError: If URL cannot be parsed even after sanitization
    """
    if not url:
        raise ValueError("URL cannot be empty or None")

    try:
        # Try to parse as-is first
        parsed = urlparse(url)
        return parsed
    except Exception:
        pass

    # Try sanitizing and parsing again
    try:
        sanitized = sanitize_url(url)
        parsed = urlparse(sanitized)
        return parsed
    except Exception as e:
        logger.error(f"Failed to parse URL even after sanitization: {url}")
        raise ValueError(f"Unable to parse URL: {url}") from e


def reconstruct_url_from_parts(scheme: str, netloc: str, path: str,
                               params: str = '', query: str = '',
                               fragment: str = '') -> str:
    """
    Reconstruct a URL from its components.

    Args:
        scheme: URL scheme (e.g., 'https')
        netloc: Network location (e.g., 'example.com:443')
        path: URL path (e.g., '/accounts/login/')
        params: URL parameters
        query: Query string
        fragment: URL fragment

    Returns:
        Reconstructed URL string
    """
    return urlunparse((scheme, netloc, path, params, query, fragment))


def join_url_with_path(base_url: str, path: str) -> str:
    """
    Join a base URL with a path, handling malformations.

    Useful for constructing URLs from redirected base URLs.

    Args:
        base_url: Base URL (may be malformed)
        path: Path to append

    Returns:
        Properly formatted joined URL

    Examples:
        - join_url_with_path("https://www.mymoment.ch:443\\", "/accounts/login/")
          -> "https://www.mymoment.ch:443/accounts/login/"
    """
    if not base_url:
        raise ValueError("base_url cannot be empty")

    # Sanitize both parts
    base_url = sanitize_url(base_url)

    # Ensure path starts with /
    if not path.startswith('/'):
        path = '/' + path

    # Ensure base_url doesn't end with /
    base_url = base_url.rstrip('/')

    return base_url + path
