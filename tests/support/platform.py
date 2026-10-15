"""Stateful fake platform adapter and the fixture that installs it via the registry."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
import uuid
from typing import Any, AsyncIterator, Callable, Mapping, Optional

import pytest

from src.platforms import (
    ArticleContent,
    ArticleRef,
    ArticleSummary,
    PlatformAccount,
    PlatformRejected,
    PostedComment,
    StudentRef,
    use_adapter,
)


class InMemoryCookieStore:
    """Cookie store for the myMoment adapter that keeps saved data in a dict."""

    def __init__(self) -> None:
        self.saved: dict[uuid.UUID, dict[str, Any]] = {}

    async def load(self, account_id: uuid.UUID) -> Optional[dict[str, Any]]:
        return self.saved.get(account_id)

    async def save(self, account_id: uuid.UUID, data: dict[str, Any]) -> None:
        self.saved[account_id] = data

    async def discard(self, account_id: uuid.UUID) -> None:
        self.saved.pop(account_id, None)


_TARGET_KEYS = {"category", "arrangement", "classroom"}


def _target_value(article: ArticleContent, key: str) -> Optional[str]:
    """Category is a field; arrangement and classroom live in `extra`."""
    return article.category if key == "category" else article.extra.get(key)


@dataclass(frozen=True)
class FakePostedComment:
    account: PlatformAccount
    ref: ArticleRef
    text: str
    hidden: bool


class FakeConnection:
    def __init__(self, platform: "FakePlatform", account: PlatformAccount) -> None:
        self._platform = platform
        self.account = account

    async def list_articles(self, target: Optional[Mapping[str, str]] = None) -> list[ArticleSummary]:
        self._platform._raise_injected("list_articles")
        target = dict(target or {})
        unknown = set(target) - _TARGET_KEYS
        if unknown:
            raise PlatformRejected(f"unknown target keys: {sorted(unknown)}")
        return [
            ArticleSummary(
                ref=article.ref,
                title=article.title,
                author=article.author,
                category=article.category,
                extra=article.extra,
            )
            for article in self._platform.articles.values()
            if all(_target_value(article, key) == value for key, value in target.items())
        ]

    async def fetch_article(self, ref: ArticleRef) -> ArticleContent:
        self._platform._raise_injected("fetch_article")
        try:
            return self._platform.articles[ref.id]
        except KeyError:
            raise PlatformRejected(f"article {ref.id} not found") from None

    async def post_comment(self, ref: ArticleRef, text: str, *, hidden: bool = False) -> PostedComment:
        self._platform._raise_injected("post_comment")
        if ref.id not in self._platform.articles:
            raise PlatformRejected(f"article {ref.id} not found")
        if ref.id in self._platform.closed_articles:
            raise PlatformRejected(f"article {ref.id} does not accept comments")
        self._platform.posted_comments.append(FakePostedComment(self.account, ref, text, hidden))
        return PostedComment()

    async def list_student_articles(self, student: StudentRef) -> list[ArticleSummary]:
        self._platform._raise_injected("list_student_articles")
        return [
            ArticleSummary(
                ref=article.ref,
                title=article.title,
                author=article.author,
                category=article.category,
                edited_at=article.edited_at,
                extra=article.extra,
            )
            for article_id, article in self._platform.articles.items()
            if self._platform.article_students.get(article_id) == student.id
        ]


class FakePlatform:
    """In-memory platform: articles can be added, posted comments read back, errors injected per operation."""

    def __init__(self, base_url: str = "https://fake.example") -> None:
        self.base_url = base_url
        self.articles: dict[str, ArticleContent] = {}
        self.connected_accounts: list[PlatformAccount] = []
        self.posted_comments: list[FakePostedComment] = []
        self.closed_articles: set[str] = set()
        self.article_students: dict[str, str] = {}
        self.on_call: Optional[Callable[[str], None]] = None  # observes every operation before it runs
        self._errors: dict[str, Exception] = {}

    def fail(self, operation: str, error: Exception) -> None:
        """Raise `error` on every call of `operation`: "connect" or a connection method's name."""
        self._errors[operation] = error

    def reject_comments(self, article_id: str) -> None:
        """Let the platform refuse comments on this article, like a closed or deleted one."""
        self.closed_articles.add(article_id)

    def add_article(
        self,
        article_id: str,
        *,
        title: str = "Fake Title",
        author: str = "Fake Author",
        body_text: str = "Fake body.",
        body_html: Optional[str] = None,
        category: Optional[str] = None,
        extra: Optional[Mapping[str, str]] = None,
        edited_at: Optional[datetime] = None,
        student: Optional[str] = None,
    ) -> ArticleRef:
        """Add or replace an article; `student` is the external ID of its author for `list_student_articles`."""
        ref = ArticleRef(id=article_id, url=f"{self.base_url}/articles/{article_id}")
        if student is not None:
            self.article_students[article_id] = student
        self.articles[article_id] = ArticleContent(
            ref=ref,
            title=title,
            author=author,
            body_html=body_html if body_html is not None else f"<p>{body_text}</p>",
            body_text=body_text,
            edited_at=edited_at,
            category=category,
            extra=dict(extra or {}),
        )
        return ref

    @asynccontextmanager
    async def connect(self, account: PlatformAccount) -> AsyncIterator[FakeConnection]:
        self._raise_injected("connect")
        self.connected_accounts.append(account)
        yield FakeConnection(self, account)

    def _raise_injected(self, operation: str) -> None:
        if self.on_call is not None:
            self.on_call(operation)
        error = self._errors.get(operation)
        if error is not None:
            raise error


@pytest.fixture
def fake_platform():
    """Install a FakePlatform behind `connect` for the duration of a test."""
    platform = FakePlatform()
    use_adapter(platform)
    yield platform
    use_adapter(None)
