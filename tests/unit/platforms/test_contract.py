"""Contract suite: every platform adapter behaves the same behind the interface."""

from __future__ import annotations

import uuid

import aiohttp
import pytest

from urllib.parse import urlparse

from src.platforms import (
    ArticleRef,
    PlatformAccount,
    PlatformAuthError,
    PlatformUnavailable,
)
from src.platforms.mymoment.adapter import MyMomentAdapter
from tests.fixtures.stubs import AiohttpStubSession
from tests.support.mymoment_http import LOGIN_URL, MYMOMENT_BASE_URL, queue_article, queue_login
from tests.support.platform import FakePlatform, InMemoryCookieStore


pytestmark = [pytest.mark.unit]


def _account() -> PlatformAccount:
    return PlatformAccount(
        id=uuid.uuid4(),
        base_url=MYMOMENT_BASE_URL,
        username="teacher",
        password="secret",
        role="user",
    )


class FakeHarness:
    def __init__(self) -> None:
        self.adapter = FakePlatform()
        self.account = _account()

    def given_valid_login(self) -> None:
        pass

    def given_wrong_password(self) -> None:
        self.adapter.fail("connect", PlatformAuthError("wrong password"))

    def given_unreachable(self) -> None:
        self.adapter.fail("connect", PlatformUnavailable("connection refused"))

    def given_article(self) -> tuple[ArticleRef, str]:
        ref = self.adapter.add_article("3170", title="Beispieldialog", body_text="Hallo.")
        return ref, "Beispieldialog"


class MyMomentHarness:
    def __init__(self) -> None:
        self.http = AiohttpStubSession()
        self.adapter = MyMomentAdapter(
            cookie_store=InMemoryCookieStore(),
            http_session_factory=self.http.as_factory(),
        )
        self.account = _account()

    def given_valid_login(self) -> None:
        queue_login(self.http)

    def given_wrong_password(self) -> None:
        queue_login(self.http, succeed=False)

    def given_unreachable(self) -> None:
        self.http.queue_response("GET", LOGIN_URL, aiohttp.ClientConnectionError("connection refused"))

    def given_article(self) -> tuple[ArticleRef, str]:
        queue_article(self.http, "3170")
        return ArticleRef(id="3170", url=f"{MYMOMENT_BASE_URL}/article/3170/"), "Beispieldialog"


@pytest.fixture(params=["fake", "mymoment"])
def harness(request):
    return {"fake": FakeHarness, "mymoment": MyMomentHarness}[request.param]()


async def test_connect_with_valid_account_yields_connection(harness):
    harness.given_valid_login()

    async with harness.adapter.connect(harness.account) as connection:
        assert connection is not None


async def test_connect_with_wrong_password_raises_auth_error(harness):
    harness.given_wrong_password()

    with pytest.raises(PlatformAuthError):
        async with harness.adapter.connect(harness.account):
            pass


async def test_connect_to_unreachable_platform_raises_unavailable(harness):
    harness.given_unreachable()

    with pytest.raises(PlatformUnavailable):
        async with harness.adapter.connect(harness.account):
            pass


async def test_fetch_article_returns_its_content(harness):
    harness.given_valid_login()
    ref, expected_title = harness.given_article()

    async with harness.adapter.connect(harness.account) as connection:
        content = await connection.fetch_article(ref)

    assert (content.ref.id, content.title, bool(content.body_text)) == (ref.id, expected_title, True)


async def test_fetched_article_url_is_absolute(harness):
    harness.given_valid_login()
    ref, _ = harness.given_article()

    async with harness.adapter.connect(harness.account) as connection:
        content = await connection.fetch_article(ref)

    parsed = urlparse(content.ref.url)
    assert parsed.scheme in {"http", "https"} and parsed.netloc
