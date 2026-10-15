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
    PlatformRejected,
    PlatformUnavailable,
    PostedComment,
    StudentRef,
    TargetOption,
    TargetValue,
)
from src.platforms.mymoment.adapter import MyMomentAdapter
from tests.fixtures.stubs import AiohttpStubResponse, AiohttpStubSession
from tests.support.mymoment_http import (
    LOGIN_URL,
    MYMOMENT_BASE_URL,
    queue_article,
    queue_article_list,
    queue_comment_post,
    queue_login,
    queue_student_dashboard,
    queue_targets,
)
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


# The classroom tabs of articles_index.html
CLASSROOMS = (
    TargetValue(value="home", label="Meine"),
    TargetValue(value="82", label="Beispielklasse A (Testschule)"),
    TargetValue(value="91", label="Beispielklasse B (Testschule)"),
    TargetValue(value="alle", label="Alle"),
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

    def given_classrooms(self) -> None:
        self.adapter.targets = [TargetOption(key="classroom", label="Classroom", values=list(CLASSROOMS))]

    def given_listed_articles(self, target=None) -> None:
        # Mirrors the "alle" classroom of articles_index.html: two Unterhalten (9), one Informieren (7)
        self.adapter.add_article("4801", category="9", extra={"classroom": "alle"})
        self.adapter.add_article("4802", category="9", extra={"classroom": "alle"})
        self.adapter.add_article("4803", category="7", extra={"classroom": "alle"})

    def given_article_open_for_comments(self) -> ArticleRef:
        return self.adapter.add_article("3170")

    def given_article_refusing_comments(self) -> ArticleRef:
        ref = self.adapter.add_article("3170")
        self.adapter.reject_comments(ref.id)
        return ref

    def given_student_articles(self) -> StudentRef:
        # Mirrors student_dashboard.html: three articles of student 1042
        for article_id in ("2695", "2711", "2730"):
            self.adapter.add_article(article_id, student="1042")
        self.adapter.add_article("3170", student="1043")
        return StudentRef(id="1042")

    def posted_texts(self) -> list[str]:
        return [comment.text for comment in self.adapter.posted_comments]


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

    def given_classrooms(self) -> None:
        queue_targets(self.http)

    def given_listed_articles(self, target=None) -> None:
        queue_article_list(self.http, target)

    def given_article_open_for_comments(self) -> ArticleRef:
        queue_article(self.http, "3170")
        queue_comment_post(self.http, "3170")
        return ArticleRef(id="3170", url=f"{MYMOMENT_BASE_URL}/article/3170/")

    def given_article_refusing_comments(self) -> ArticleRef:
        # A deleted article: myMoment answers 404 for its page
        self.http.queue_response("GET", f"{MYMOMENT_BASE_URL}/article/3170/", AiohttpStubResponse(status=404))
        return ArticleRef(id="3170", url=f"{MYMOMENT_BASE_URL}/article/3170/")

    def given_student_articles(self) -> StudentRef:
        queue_student_dashboard(self.http, "1042")
        return StudentRef(id="1042")

    def posted_texts(self) -> list[str]:
        return [r["kwargs"]["data"]["text"] for r in self.http.requests if r["method"] == "POST" and "/comment/" in r["url"]]


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


async def test_list_targets_offers_the_classrooms(harness):
    harness.given_valid_login()
    harness.given_classrooms()

    async with harness.adapter.connect(harness.account) as connection:
        targets = await connection.list_targets()

    assert [(t.key, t.values) for t in targets] == [("classroom", list(CLASSROOMS))]


async def test_list_articles_without_target_lists_all_articles(harness):
    harness.given_valid_login()
    harness.given_listed_articles()

    async with harness.adapter.connect(harness.account) as connection:
        articles = await connection.list_articles()

    assert [a.ref.id for a in articles] == ["4801", "4802", "4803"]


async def test_list_articles_with_category_target_lists_only_that_category(harness):
    target = {"classroom": "alle", "category": "7"}
    harness.given_valid_login()
    harness.given_listed_articles(target)

    async with harness.adapter.connect(harness.account) as connection:
        articles = await connection.list_articles(target)

    assert [(a.ref.id, a.category) for a in articles] == [("4803", "7")]


async def test_listed_article_urls_are_absolute(harness):
    harness.given_valid_login()
    harness.given_listed_articles()

    async with harness.adapter.connect(harness.account) as connection:
        articles = await connection.list_articles()

    parsed = [urlparse(a.ref.url) for a in articles]
    assert parsed and all(p.scheme in {"http", "https"} and p.netloc for p in parsed)


async def test_list_articles_with_unknown_target_key_is_rejected(harness):
    harness.given_valid_login()

    async with harness.adapter.connect(harness.account) as connection:
        with pytest.raises(PlatformRejected):
            await connection.list_articles({"classroom": "alle", "colour": "blue"})


async def test_post_comment_publishes_the_text(harness):
    harness.given_valid_login()
    ref = harness.given_article_open_for_comments()

    async with harness.adapter.connect(harness.account) as connection:
        await connection.post_comment(ref, "<p>Schöner Text!</p>")

    assert harness.posted_texts() == ["<p>Schöner Text!</p>"]


async def test_post_comment_returns_the_posted_comment(harness):
    harness.given_valid_login()
    ref = harness.given_article_open_for_comments()

    async with harness.adapter.connect(harness.account) as connection:
        posted = await connection.post_comment(ref, "<p>Schöner Text!</p>")

    assert isinstance(posted, PostedComment)


async def test_post_comment_to_article_refusing_comments_is_rejected(harness):
    harness.given_valid_login()
    ref = harness.given_article_refusing_comments()

    async with harness.adapter.connect(harness.account) as connection:
        with pytest.raises(PlatformRejected):
            await connection.post_comment(ref, "<p>Schöner Text!</p>")

    assert harness.posted_texts() == []


async def test_list_student_articles_lists_the_students_articles(harness):
    harness.given_valid_login()
    student = harness.given_student_articles()

    async with harness.adapter.connect(harness.account) as connection:
        articles = await connection.list_student_articles(student)

    assert [a.ref.id for a in articles] == ["2695", "2711", "2730"]


async def test_listed_student_article_urls_are_absolute(harness):
    harness.given_valid_login()
    student = harness.given_student_articles()

    async with harness.adapter.connect(harness.account) as connection:
        articles = await connection.list_student_articles(student)

    parsed = [urlparse(a.ref.url) for a in articles]
    assert parsed and all(p.scheme in {"http", "https"} and p.netloc for p in parsed)
