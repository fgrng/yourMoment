"""
Shared loader API for static test fixture assets.

All tests should load fixture data through these functions instead of
constructing file paths inline. Path knowledge stays here; callers work
by name only.
"""

import json
from pathlib import Path

_FIXTURES_DIR = Path(__file__).parent
_HTML_DIR = _FIXTURES_DIR / "myMoment_html"
_MANIFEST_PATH = _HTML_DIR / "manifest.json"


class FixtureNotFoundError(FileNotFoundError):
    """Raised when a requested fixture name does not exist on disk."""


def load_html_fixture(name: str) -> str:
    """Return the contents of an HTML fixture file.

    Args:
        name: Bare filename, with or without the ``.html`` extension.

    Returns:
        The full HTML source as a string.

    Raises:
        FixtureNotFoundError: If no matching file exists under
            ``tests/fixtures/myMoment_html/``.
    """
    if not name.endswith(".html"):
        name = f"{name}.html"
    path = _HTML_DIR / name
    if not path.is_file():
        raise FixtureNotFoundError(
            f"HTML fixture {name!r} not found in {_HTML_DIR}. "
            f"Available fixtures: {_available_html_names()}"
        )
    return path.read_text(encoding="utf-8")


def load_json_fixture(name: str) -> dict:
    """Return the parsed contents of a JSON fixture file.

    Searches ``tests/fixtures/myMoment_html/`` first, then
    ``tests/fixtures/`` itself, so both HTML-companion JSON files and
    standalone JSON fixtures are reachable.

    Args:
        name: Bare filename, with or without the ``.json`` extension.

    Returns:
        The parsed JSON content as a dict.

    Raises:
        FixtureNotFoundError: If no matching file exists.
    """
    if not name.endswith(".json"):
        name = f"{name}.json"
    for directory in (_HTML_DIR, _FIXTURES_DIR):
        path = directory / name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FixtureNotFoundError(
        f"JSON fixture {name!r} not found in {_HTML_DIR} or {_FIXTURES_DIR}."
    )


def load_manifest() -> dict:
    """Return the parsed myMoment HTML fixture manifest.

    Returns:
        The full manifest dict as parsed from
        ``tests/fixtures/myMoment_html/manifest.json``.

    Raises:
        FixtureNotFoundError: If the manifest file is missing.
    """
    if not _MANIFEST_PATH.is_file():
        raise FixtureNotFoundError(
            f"Fixture manifest not found at {_MANIFEST_PATH}."
        )
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _available_html_names() -> list[str]:
    """Return sorted list of available HTML fixture filenames."""
    return sorted(p.name for p in _HTML_DIR.glob("*.html"))
