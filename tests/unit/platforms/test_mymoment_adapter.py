"""myMoment adapter through its interface, with stubbed HTTP and real HTML fixtures."""

from __future__ import annotations

import uuid

import pytest

from src.platforms import ArticleRef, PlatformAccount, PlatformUnavailable
from src.platforms.mymoment.adapter import MyMomentAdapter
from tests.fixtures.stubs import AiohttpStubResponse, AiohttpStubSession
from tests.support.mymoment_http import (
    HOME_URL,
    LOGIN_URL,
    MYMOMENT_BASE_URL,
    logged_in_page,
    logged_out_page,
    queue_article,
    queue_login,
)
from tests.support.platform import InMemoryCookieStore


pytestmark = [pytest.mark.unit, pytest.mark.web_scraping]

ARTICLE_URL = f"{MYMOMENT_BASE_URL}/article/3170/"


@pytest.fixture
def account() -> PlatformAccount:
    return PlatformAccount(
        id=uuid.uuid4(),
        base_url=MYMOMENT_BASE_URL,
        username="teacher",
        password="secret",
        role="user",
    )


@pytest.fixture
def http() -> AiohttpStubSession:
    return AiohttpStubSession()


@pytest.fixture
def cookie_store() -> InMemoryCookieStore:
    return InMemoryCookieStore()


@pytest.fixture
def adapter(http, cookie_store) -> MyMomentAdapter:
    return MyMomentAdapter(cookie_store=cookie_store, http_session_factory=http.as_factory())


def _stored_session(value: str) -> dict:
    return {
        "cookies": [
            {"name": "sessionid", "value": value, "domain": "www.mymoment.ch", "path": "/", "expires": None}
        ],
        "csrf_token": "stored-csrf",
        "saved_at": "2026-10-14T08:00:00",
    }


def _stored_cookie_value(cookie_store, account) -> str:
    return {c["name"]: c["value"] for c in cookie_store.saved[account.id]["cookies"]}["sessionid"]


async def test_login_stores_session_cookie(adapter, http, cookie_store, account):
    queue_login(http, session_cookie="fresh-session")

    async with adapter.connect(account):
        pass

    assert _stored_cookie_value(cookie_store, account) == "fresh-session"


async def test_valid_stored_cookie_is_reused_without_login(adapter, http, cookie_store, account):
    cookie_store.saved[account.id] = _stored_session("stored-session")
    http.queue_response("GET", HOME_URL, logged_in_page())

    async with adapter.connect(account):
        pass

    assert [r["url"] for r in http.requests] == [HOME_URL]


async def test_invalid_stored_cookie_leads_to_new_login(adapter, http, cookie_store, account):
    cookie_store.saved[account.id] = _stored_session("expired-session")
    http.queue_response("GET", HOME_URL, logged_out_page())
    queue_login(http, session_cookie="fresh-session")

    async with adapter.connect(account):
        pass

    assert _stored_cookie_value(cookie_store, account) == "fresh-session"


async def test_login_sends_credentials_with_csrf_token(adapter, http, account):
    queue_login(http)

    async with adapter.connect(account):
        pass

    login_post = next(r for r in http.requests if r["method"] == "POST" and r["url"] == LOGIN_URL)
    assert {k: login_post["kwargs"]["data"][k] for k in ("csrfmiddlewaretoken", "username", "password")} == {
        "csrfmiddlewaretoken": "TEST_CSRF_TOKEN",
        "username": "teacher",
        "password": "secret",
    }


async def test_fetch_article_reads_category_and_arrangement(adapter, http, account):
    # articles_get.html: "Kategorie: Informieren" (7), "Aufgabe: Fiktionaler Dialog ..." (4)
    queue_login(http)
    queue_article(http, "3170")

    async with adapter.connect(account) as connection:
        content = await connection.fetch_article(ArticleRef(id="3170", url=ARTICLE_URL))

    assert (content.category, dict(content.extra)) == ("7", {"arrangement": "4"})


async def test_fetch_article_reads_author_and_html_body(adapter, http, account):
    queue_login(http)
    queue_article(http, "3170")

    async with adapter.connect(account) as connection:
        content = await connection.fetch_article(ArticleRef(id="3170", url=ARTICLE_URL))

    assert (content.author, content.body_html.startswith('<div class="article">')) == ("SampleAuthor01", True)


async def test_fetch_article_follows_malformed_redirect(adapter, http, account):
    """Regression: backslashes in Location are sanitized on non-login requests too."""
    queue_login(http)
    http.queue_response(
        "GET",
        ARTICLE_URL,
        AiohttpStubResponse(status=301, headers={"Location": "\\article\\3170\\detail\\"}),
    )
    queue_article(http, "3170/detail")

    async with adapter.connect(account) as connection:
        content = await connection.fetch_article(ArticleRef(id="3170", url=ARTICLE_URL))

    assert content.title == "Beispieldialog"


async def test_fetch_article_on_server_error_raises_unavailable(adapter, http, account):
    queue_login(http)
    http.queue_response("GET", ARTICLE_URL, AiohttpStubResponse(status=503))

    async with adapter.connect(account) as connection:
        with pytest.raises(PlatformUnavailable):
            await connection.fetch_article(ArticleRef(id="3170", url=ARTICLE_URL))
