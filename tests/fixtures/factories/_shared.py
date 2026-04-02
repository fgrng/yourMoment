"""Internal helpers shared by DB-backed test factories."""

from __future__ import annotations

from collections.abc import Mapping
from itertools import count
from typing import Any


_SEQUENCES: dict[str, count] = {}


def next_sequence(name: str) -> int:
    """Return a monotonically increasing sequence per logical factory name."""
    if name not in _SEQUENCES:
        _SEQUENCES[name] = count(1)
    return next(_SEQUENCES[name])


def require_owner(*, user: Any = None, user_id: Any = None) -> dict[str, Any]:
    """Resolve an explicit owner for a user-scoped record."""
    if user is None and user_id is None:
        raise ValueError("user-owned fixtures require either user or user_id")

    if user is not None:
        resolved_user_id = getattr(user, "id", None)
        if resolved_user_id is None:
            raise ValueError("user must be flushed before being used as an owner")
        if user_id is not None and user_id != resolved_user_id:
            raise ValueError("user and user_id point to different owners")
        return {"user": user, "user_id": resolved_user_id}

    return {"user": None, "user_id": user_id}


def ensure_same_user(*records: Any) -> None:
    """Ensure every supplied record with a user_id belongs to the same owner."""
    seen_user_ids = {
        getattr(record, "user_id")
        for record in records
        if record is not None and hasattr(record, "user_id")
    }
    if len(seen_user_ids) > 1:
        raise ValueError("fixture records must belong to the same user")


def merge_kwargs(defaults: dict[str, Any], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return defaults updated by a shallow overrides mapping."""
    merged = dict(defaults)
    if overrides:
        merged.update(dict(overrides))
    return merged
