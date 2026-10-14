"""myMoment adapter through its interface, with stubbed HTTP and real HTML fixtures."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from src.platforms import ArticleRef, PlatformAccount, PlatformRejected, PlatformUnavailable
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


async def test_login_is_confirmed_on_home_page_wherever_it_lands(adapter, http, account):
    http.queue_response("GET", LOGIN_URL, logged_out_page())
    http.queue_response(
        "POST",
        LOGIN_URL,
        AiohttpStubResponse(status=302, headers={"Location": "/accounts/profile/"}),
    )
    http.queue_response(
        "GET",
        f"{MYMOMENT_BASE_URL}/accounts/profile/",
        AiohttpStubResponse(status=200, body="<html><body><h1>Profil</h1></body></html>"),
    )
    http.queue_response("GET", HOME_URL, logged_in_page())

    async with adapter.connect(account) as connection:
        assert connection is not None


class _TimedStubSession(AiohttpStubSession):
    """Records when each request reached the network."""

    def __init__(self) -> None:
        super().__init__()
        self.sent_at: list[float] = []

    def request(self, method, url, **kwargs):
        self.sent_at.append(asyncio.get_running_loop().time())
        return super().request(method, url, **kwargs)


async def test_concurrent_requests_on_one_connection_keep_the_rate_limit(cookie_store, account):
    http = _TimedStubSession()
    adapter = MyMomentAdapter(cookie_store=cookie_store, rate_limit_delay=0.05, http_session_factory=http.as_factory())
    cookie_store.saved[account.id] = _stored_session("stored-session")
    http.queue_response("GET", HOME_URL, logged_in_page())
    queue_article(http, "3170")
    queue_article(http, "3171")

    async with adapter.connect(account) as connection:
        await asyncio.gather(
            connection.fetch_article(ArticleRef(id="3170", url=ARTICLE_URL)),
            connection.fetch_article(ArticleRef(id="3171", url=f"{MYMOMENT_BASE_URL}/article/3171/")),
        )

    gaps = [later - earlier for earlier, later in zip(http.sent_at, http.sent_at[1:])]
    assert min(gaps) >= 0.045


async def test_corrupt_stored_cookies_lead_to_new_login(adapter, http, cookie_store, account):
    cookie_store.saved[account.id] = {"cookies": [{"value": "no-name"}], "csrf_token": None}
    queue_login(http, session_cookie="fresh-session")

    async with adapter.connect(account):
        pass

    assert _stored_cookie_value(cookie_store, account) == "fresh-session"


class _FailingSaveCookieStore(InMemoryCookieStore):
    async def save(self, account_id, data):
        raise RuntimeError("database is locked")


async def test_failed_cookie_save_keeps_the_connection_usable(http, account):
    adapter = MyMomentAdapter(cookie_store=_FailingSaveCookieStore(), http_session_factory=http.as_factory())
    queue_login(http)
    queue_article(http, "3170")

    async with adapter.connect(account) as connection:
        content = await connection.fetch_article(ArticleRef(id="3170", url=ARTICLE_URL))

    assert content.title == "Beispieldialog"


async def test_login_page_without_csrf_token_raises_unavailable(adapter, http, account):
    http.queue_response("GET", LOGIN_URL, AiohttpStubResponse(status=200, body="<html><body>Wartung</body></html>"))

    with pytest.raises(PlatformUnavailable):
        async with adapter.connect(account):
            pass


async def test_fetch_missing_article_raises_rejected(adapter, http, account):
    queue_login(http)
    http.queue_response("GET", ARTICLE_URL, AiohttpStubResponse(status=404))

    async with adapter.connect(account) as connection:
        with pytest.raises(PlatformRejected):
            await connection.fetch_article(ArticleRef(id="3170", url=ARTICLE_URL))


async def test_redirect_without_location_raises_unavailable(adapter, http, account):
    queue_login(http)
    http.queue_response("GET", ARTICLE_URL, AiohttpStubResponse(status=302))

    async with adapter.connect(account) as connection:
        with pytest.raises(PlatformUnavailable):
            await connection.fetch_article(ArticleRef(id="3170", url=ARTICLE_URL))
