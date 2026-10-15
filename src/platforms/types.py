"""Typed values that cross the platform interface (ADR-0001)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncContextManager, Mapping, Optional, Protocol


@dataclass(frozen=True)
class PlatformAccount:
    """A platform account with already decrypted credentials.

    Adapters receive this instead of the stored ORM model, so they depend
    neither on the database nor on encryption.
    """

    id: uuid.UUID
    base_url: str
    username: str
    password: str = field(repr=False)
    role: str  # "user" or "admin"; adapters ignore it, yourMoment selects accounts by it


@dataclass(frozen=True)
class ArticleRef:
    """Identity of an article on its platform: external ID and absolute URL."""

    id: str
    url: str


@dataclass(frozen=True)
class ArticleContent:
    """Full content of one article as read from its platform."""

    ref: ArticleRef
    title: str
    author: str
    body_html: str
    body_text: str
    published_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    category: Optional[str] = None
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ArticleSummary:
    """One entry of an article list: reference plus the metadata the list shows."""

    ref: ArticleRef
    title: str
    author: str
    category: Optional[str] = None
    extra: Mapping[str, str] = field(default_factory=dict)


class PlatformConnection(Protocol):
    """An authenticated connection to one platform account."""

    async def list_articles(self, target: Optional[Mapping[str, str]] = None) -> list[ArticleSummary]:
        """List the articles of a target; the adapter validates the target's keys and values."""
        ...

    async def fetch_article(self, ref: ArticleRef) -> ArticleContent: ...


class PlatformAdapter(Protocol):
    """Speaks to one platform type; `connect` opens and closes a connection."""

    def connect(self, account: PlatformAccount) -> AsyncContextManager[PlatformConnection]: ...
