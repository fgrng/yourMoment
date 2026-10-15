"""Scripts show times in the APP_TIMEZONE from the page, like the Jinja filter."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
UTILS_JS = REPO_ROOT / "static" / "js" / "utils.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")

# Gives utils.js a page whose meta tag names the time zone, then prints
# formatDateTime(...args) as JSON.
_PROBE = """
const [utilsPath, timezone, args] = process.argv.slice(1);
globalThis.document = {
    querySelector: () => (timezone ? { content: timezone } : null),
};
const { formatDateTime } = await import(new URL(`file://${utilsPath}`));
console.log(JSON.stringify(formatDateTime(...JSON.parse(args))));
"""


def _format_date_time(*args, timezone: str | None = "Europe/Zurich") -> str:
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            _PROBE,
            str(UTILS_JS),
            timezone or "",
            json.dumps(args),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_summer_time_is_shown_in_zurich_time():
    assert _format_date_time("2026-07-14T07:30:00+00:00") == "14.07.2026 09:30"


def test_winter_time_is_shown_in_zurich_time():
    assert _format_date_time("2026-01-14T08:30:00Z") == "14.01.2026 09:30"


def test_page_timezone_utc_shows_utc_time():
    assert (
        _format_date_time("2026-07-14T07:30:00Z", timezone="UTC") == "14.07.2026 07:30"
    )


def test_midnight_is_shown_as_hour_zero():
    assert _format_date_time("2026-07-13T22:05:00Z") == "14.07.2026 00:05"


def test_date_only_uses_local_date():
    assert (
        _format_date_time("2026-07-14T22:30:00Z", "-", {"dateOnly": True})
        == "15.07.2026"
    )


def test_missing_time_shows_fallback():
    assert _format_date_time(None, "Noch keins") == "Noch keins"


def test_invalid_time_shows_fallback():
    assert _format_date_time("kein Datum", "-") == "-"


def test_page_without_timezone_shows_zurich_time():
    assert (
        _format_date_time("2026-07-14T07:30:00Z", timezone=None) == "14.07.2026 09:30"
    )
