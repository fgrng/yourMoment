"""
URL sanitization utilities to handle malformed redirect URLs.

Workaround for myMoment server bug that returns Location headers with backslashes
instead of forward slashes (e.g., "https://www.mymoment.ch:443\accounts/login/").

This module provides utilities to detect and fix these malformed URLs so they
can be used by HTTP clients that expect RFC 3986-compliant URLs.
"""

import logging

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
