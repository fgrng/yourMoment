"""Every datetime in application code is UTC with tzinfo set."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

DISPLAY_FORMAT = "%d.%m.%Y %H:%M"


def utcnow() -> datetime:
    """The current time as an aware UTC datetime."""
    return datetime.now(UTC)


def format_local(
    value: datetime | None, timezone: str, fmt: str = DISPLAY_FORMAT, fallback: str = ""
) -> str:
    """Format an aware datetime as wall-clock time in ``timezone`` for display.

    ``None`` gives ``fallback``. Only for display: stored and API values stay UTC.
    """
    if value is None:
        return fallback
    return value.astimezone(ZoneInfo(timezone)).strftime(fmt)
