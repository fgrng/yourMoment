"""Times shown in templates use APP_TIMEZONE; the stored value stays UTC."""

from datetime import UTC, datetime

import pytest
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.web import router, templates
from src.config.settings import AppSettings


def _render(source: str, **context) -> str:
    return templates.env.from_string(source).render(**context)


def _page_app_timezone(path: str) -> str:
    app = FastAPI()
    app.include_router(router)
    app.mount("/static", StaticFiles(directory="static"), name="static")
    html = TestClient(app).get(path).text
    return BeautifulSoup(html, "html.parser").find(
        "meta", attrs={"name": "app-timezone"}
    )["content"]


def test_summer_time_is_shown_in_zurich_time():
    value = datetime(2026, 7, 14, 7, 30, tzinfo=UTC)

    assert _render("{{ value | format_datetime }}", value=value) == "14.07.2026 09:30"


def test_winter_time_is_shown_in_zurich_time():
    value = datetime(2026, 1, 14, 8, 30, tzinfo=UTC)

    assert _render("{{ value | format_datetime }}", value=value) == "14.01.2026 09:30"


def test_app_timezone_utc_shows_utc_time(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "UTC")
    value = datetime(2026, 7, 14, 7, 30, tzinfo=UTC)

    assert _render("{{ value | format_datetime }}", value=value) == "14.07.2026 07:30"


def test_missing_time_shows_placeholder_chosen_by_template():
    assert _render("{{ value | format_datetime(fallback='–') }}", value=None) == "–"


def test_date_only_format_uses_local_date():
    value = datetime(2026, 7, 14, 22, 30, tzinfo=UTC)

    assert (
        _render("{{ value | format_datetime('%d.%m.%Y') }}", value=value)
        == "15.07.2026"
    )


def test_unknown_app_timezone_is_rejected_when_settings_load(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "Europe/Atlantis")

    with pytest.raises(ValidationError, match="APP_TIMEZONE"):
        AppSettings()


def test_pages_tell_scripts_the_app_timezone():
    assert _page_app_timezone("/login") == "Europe/Zurich"


def test_pages_tell_scripts_a_configured_app_timezone(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "UTC")

    assert _page_app_timezone("/login") == "UTC"
