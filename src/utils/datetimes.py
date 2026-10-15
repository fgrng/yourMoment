"""Every datetime in application code is UTC with tzinfo set."""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """The current time as an aware UTC datetime."""
    return datetime.now(UTC)
