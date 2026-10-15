"""The one check of a target against its platform's target description (ADR-0002)."""

from __future__ import annotations

from typing import Any, Mapping

from src.platforms.errors import InvalidTarget
from src.platforms.types import PlatformAdapter, TargetEntry


def validate_target(adapter: PlatformAdapter, target: Mapping[str, Any]) -> dict[str, str]:
    """Check `target` without a connection and return it as a plain dict; raise InvalidTarget.

    Only keys of the description, every required key present, every value a
    non-empty string; then the adapter's own rules. Whether a value exists on
    the platform shows only when its articles are listed.
    """
    description = adapter.describe_target()
    labels = {dimension.key: dimension.label for dimension in description}

    unknown = sorted(str(key) for key in set(target) - set(labels))
    if unknown:
        raise InvalidTarget(f"Unbekannte Angaben im Ziel: {', '.join(unknown)}")
    for dimension in description:
        if dimension.required and dimension.key not in target:
            raise InvalidTarget(f"Pflichtangabe „{dimension.label}“ ({dimension.key}) fehlt")
    for key, value in target.items():
        if not isinstance(value, str) or not value.strip():
            raise InvalidTarget(f"„{labels[key]}“ ({key}) braucht einen nicht-leeren Text als Wert")

    adapter.check_target(target)
    return dict(target)


def label_target(adapter: PlatformAdapter, target: Mapping[str, str]) -> tuple[TargetEntry, ...]:
    """The set dimensions of `target` with their labels, without a connection.

    Description order first; unset dimensions are left out. A key the
    description does not know follows with its raw key as label.
    """
    description = adapter.describe_target()
    known = {dimension.key for dimension in description}
    entries = [
        TargetEntry(key=dimension.key, label=dimension.label, value=target[dimension.key])
        for dimension in description
        if dimension.key in target
    ]
    entries += [TargetEntry(key=key, label=key, value=target[key]) for key in target if key not in known]
    return tuple(entries)
