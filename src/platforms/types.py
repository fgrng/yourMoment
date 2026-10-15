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
class StudentRef:
    """Identity of a student on its platform: the external ID."""

    id: str


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
    edited_at: Optional[datetime] = None
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TargetValue:
    """One value a target dimension can take, with the label the platform shows."""

    value: str
    label: str


@dataclass(frozen=True)
class TargetOption:
    """One selectable target dimension: its key in the target mapping, a label and its values."""

    key: str
    label: str
    values: list[TargetValue] = field(default_factory=list)


@dataclass(frozen=True)
class PostedComment:
    """A published comment; platforms that do not report an ID return None."""

    external_id: Optional[str] = None


class PlatformConnection(Protocol):
    """An authenticated connection to one platform account."""

    async def list_targets(self) -> list[TargetOption]:
        """Describe the target dimensions this account can choose from, with their values."""
        ...

    async def list_articles(self, target: Optional[Mapping[str, str]] = None) -> list[ArticleSummary]:
        """List the articles of a target; the adapter validates the target's keys and values."""
        ...

    async def fetch_article(self, ref: ArticleRef) -> ArticleContent: ...

    async def post_comment(self, ref: ArticleRef, text: str, *, hidden: bool = False) -> PostedComment:
        """Publish `text` under the article; `hidden` hides it from other readers."""
        ...

    async def list_student_articles(self, student: StudentRef) -> list[ArticleSummary]:
        """List every article of a student, drafts included; the contents come from `fetch_article`."""
        ...


class PlatformAdapter(Protocol):
    """Speaks to one platform type; `connect` opens and closes a connection."""

    def connect(self, account: PlatformAccount) -> AsyncContextManager[PlatformConnection]: ...
