"""
Integration tests for ScraperService using static HTML fixtures.

These tests use cached HTML responses from examples/myMoment_html/ directory
to test scraper functionality without requiring live myMoment access.

No external API calls are made during these tests.
"""

import uuid
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock

import pytest
from bs4 import BeautifulSoup

from src.services.scraper_service import (
    ScraperService,
    ScrapingError,
    SessionContext,
)

# Test constants
VALID_USERNAME = "ArtificialArmadillo"
VALID_PASSWORD = "Valid!Password123"
AI_PREFIX = "[Dieser Kommentar stammt von einem KI-ChatBot.]"


class FakeCredentials:
    def __init__(self, username: str, password: str):
        self.username = username
        self._password = password

    def get_credentials(self):
        return self.username, self._password


class FakeResponse:
    def __init__(self, status: int, text: str = ""):
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):  # pragma: no cover - simple passthrough
        return False

    async def text(self):
        return self._text


class FakeSession:
    def __init__(self, html_dir: Path, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.closed = False
        self.logged_in = False
        self.last_comment_payload: Optional[dict] = None
        self.last_login_payload: Optional[dict] = None

        self.login_html = (html_dir / "accounts_login.html").read_text(encoding="utf-8")
        self.articles_html = (html_dir / "articles_index.html").read_text(encoding="utf-8")
        self.article_html = (html_dir / "articles_get.html").read_text(encoding="utf-8")

        login_soup = BeautifulSoup(self.login_html, "html.parser")
        self.login_csrf = login_soup.find("input", {"name": "csrfmiddlewaretoken"}).get("value")

        article_soup = BeautifulSoup(self.article_html, "html.parser")
        comment_form = article_soup.find("form", {"action": "/article/464/comment/"})
        self.article_csrf = comment_form.find("input", {"name": "csrfmiddlewaretoken"}).get("value")

    async def close(self):
        self.closed = True

    def _response(self, status: int, text: str = ""):
        return FakeResponse(status=status, text=text)

    def get(self, url: str, **_kwargs):
        if url == f"{self.base_url}/":
            html = self.articles_html if self.logged_in else self.login_html
            return self._response(200, html)

        if url == f"{self.base_url}/accounts/login/":
            return self._response(200, self.login_html)

        if url == f"{self.base_url}/articles/":
            if not self.logged_in:
                return self._response(403, "")
            return self._response(200, self.articles_html)

        if url.startswith(f"{self.base_url}/article/"):
            if not self.logged_in:
                return self._response(403, "")
            return self._response(200, self.article_html)

        return self._response(404, "")

    def post(self, url: str, data=None, headers=None):
        data = data or {}
        headers = headers or {}

        if url == f"{self.base_url}/accounts/login/":
            self.last_login_payload = {"url": url, "data": data.copy(), "headers": headers.copy()}
            is_valid = (
                data.get("username") == VALID_USERNAME
                and data.get("password") == VALID_PASSWORD
                and data.get("csrfmiddlewaretoken") == self.login_csrf
            )
            if is_valid:
                self.logged_in = True
                return self._response(302, "")
            return self._response(401, "Invalid credentials")

        if url.endswith("/comment/"):
            self.last_comment_payload = {
                "url": url,
                "data": data.copy(),
                "headers": headers.copy(),
            }
            if not self.logged_in:
                return self._response(403, "Auth required")
            if data.get("csrfmiddlewaretoken") != self.article_csrf:
                return self._response(400, "Invalid CSRF")
            return self._response(200, "Comment posted")

        return self._response(404, "")


@pytest.fixture
def fake_session(examples_dir: Path, test_env_override: dict):
    """Create a fake HTTP session using static HTML fixtures."""
    # Override base URL for testing
    base_url = test_env_override.get("MYMOMENT_BASE_URL", "https://new.mymoment.ch")
    html_dir = examples_dir / "myMoment_html"

    if not html_dir.exists():
        pytest.skip(f"HTML fixtures directory not found: {html_dir}")

    return FakeSession(html_dir, base_url)


@pytest.fixture
async def scraper_service():
    service = ScraperService(db_session=None)
    service.config.rate_limit_delay = 0.0
    service.session_service.touch_session = AsyncMock()
    service.credentials_service.get_credentials_by_id = AsyncMock(
        return_value=FakeCredentials(VALID_USERNAME, VALID_PASSWORD)
    )
    return service


def build_context(fake_session):
    return SessionContext(
        login_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        username=VALID_USERNAME,
        aiohttp_session=fake_session,
        csrf_token=None,
        last_activity=None,
        is_authenticated=False,
    )


@pytest.mark.asyncio
async def test_authenticate_session_with_cached_html(scraper_service, fake_session):
    context = build_context(fake_session)

    result = await scraper_service._authenticate_session(context)

    assert result is True
    assert context.is_authenticated is True
    assert context.csrf_token == fake_session.login_csrf
    assert fake_session.logged_in is True
    scraper_service.session_service.touch_session.assert_awaited_once_with(context.session_id)
    assert fake_session.last_login_payload["data"]["username"] == VALID_USERNAME


@pytest.mark.asyncio
async def test_discover_new_articles_uses_static_index(scraper_service, fake_session):
    context = build_context(fake_session)
    context.is_authenticated = True
    fake_session.logged_in = True

    articles = await scraper_service.discover_new_articles(context, tab="alle", limit=5)

    assert len(articles) == 5
    first = articles[0]
    assert first.id == "1078"
    assert first.title == "Windig"
    assert first.author == "RockstarCondor"
    assert first.status == "Publiziert"
    assert str(first.category_id) == "10"
    assert first.category_name == "Schreibaufgabe: Fiktionaler Dialog"
    assert first.visibility == "Alle"


@pytest.mark.asyncio
async def test_get_article_content_parses_cached_page(scraper_service, fake_session):
    context = build_context(fake_session)
    context.is_authenticated = True
    fake_session.logged_in = True

    content = await scraper_service.get_article_content(context, article_id="464")

    assert content["title"] == "Ein Arbeitsnachmittag an der PHSG"
    assert "Arbeitsnachmittag" in content["content"]
    assert content["csrf_token"] == fake_session.article_csrf
    assert content["url"].endswith("/article/464/")


@pytest.mark.asyncio
async def test_post_comment_enforces_ai_prefix(scraper_service, fake_session):
    context = build_context(fake_session)
    context.is_authenticated = True
    fake_session.logged_in = True

    await scraper_service.post_comment(context, article_id="464", comment_content="Das ist ein Test")

    payload = fake_session.last_comment_payload
    assert payload is not None
    assert payload["data"]["text"].startswith(AI_PREFIX)
    assert payload["data"]["csrfmiddlewaretoken"] == fake_session.article_csrf
    assert payload["headers"]["Referer"].endswith("/article/464/")


@pytest.mark.asyncio
async def test_discover_requires_authentication(scraper_service, fake_session):
    context = build_context(fake_session)
    with pytest.raises(ScrapingError):
        await scraper_service.discover_new_articles(context)


@pytest.mark.asyncio
async def test_post_comment_without_authentication(scraper_service, fake_session):
    context = build_context(fake_session)
    fake_session.logged_in = False
    with pytest.raises(ScrapingError):
        await scraper_service.post_comment(context, article_id="464", comment_content="Hallo")
