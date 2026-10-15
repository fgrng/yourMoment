"""Platform IDs arrive as strings; the schema still stores some as integers."""

from typing import Optional


def is_number(value: str) -> bool:
    """ASCII digits only: str.isdigit() also accepts e.g. '²', which int() rejects."""
    return value.isascii() and value.isdigit()


def as_int(value: Optional[str]) -> Optional[int]:
    """Convert a platform ID string to the integer column, None if not numeric."""
    if value is None or not is_number(value):
        return None
    return int(value)
