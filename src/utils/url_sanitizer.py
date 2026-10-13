"""Workaround for myMoment redirects whose Location header contains backslashes."""

import logging

logger = logging.getLogger(__name__)


def sanitize_url(url: str) -> str:
    """Replace backslashes with forward slashes; raise ValueError for an empty URL."""
    if not url:
        raise ValueError("URL cannot be empty or None")
    sanitized = url.replace("\\", "/")
    if sanitized != url:
        logger.warning(f"Sanitized malformed URL: {url!r} -> {sanitized!r}")
    return sanitized


def is_url_malformed(url: str) -> bool:
    """Return True if the URL contains backslashes."""
    return bool(url) and "\\" in url
