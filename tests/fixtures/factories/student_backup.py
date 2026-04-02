"""Factories for student-backup records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.article_version import ArticleVersion
from src.models.tracked_student import TrackedStudent

from tests.fixtures.factories._shared import ensure_same_user, next_sequence, require_owner


async def create_tracked_student(
    session: AsyncSession,
    *,
    user: Any = None,
    user_id: Any = None,
    mymoment_login: Any = None,
    mymoment_login_id: Any = None,
    **overrides: Any,
) -> TrackedStudent:
    """Persist a valid `TrackedStudent`."""
    owner = require_owner(user=user, user_id=user_id)
    if mymoment_login is not None:
        ensure_same_user(owner["user"] or type("Owner", (), {"user_id": owner["user_id"]})(), mymoment_login)
        if not mymoment_login.is_admin:
            raise ValueError("tracked_student fixtures require an admin myMoment login")

    index = next_sequence("tracked_student")
    student = TrackedStudent(
        user=owner["user"],
        user_id=owner["user_id"],
        mymoment_login=mymoment_login,
        mymoment_login_id=mymoment_login.id if mymoment_login is not None else mymoment_login_id,
        mymoment_student_id=overrides.pop("mymoment_student_id", 1000 + index),
        display_name=overrides.pop("display_name", f"Tracked Student {index}"),
        notes=overrides.pop("notes", "Fixture student for backup tests."),
        is_active=overrides.pop("is_active", True),
        last_backup_at=overrides.pop("last_backup_at", None),
        **overrides,
    )
    session.add(student)
    await session.flush()
    return student


async def create_article_version(
    session: AsyncSession,
    *,
    user: Any = None,
    user_id: Any = None,
    tracked_student: TrackedStudent | None = None,
    tracked_student_id: Any = None,
    content: str | None = None,
    raw_html: str | None = None,
    **overrides: Any,
) -> ArticleVersion:
    """Persist a valid `ArticleVersion` with a computed content hash."""
    owner = require_owner(user=user, user_id=user_id)
    if tracked_student is None and tracked_student_id is None:
        raise ValueError("article_version fixtures require tracked_student or tracked_student_id")
    if tracked_student is not None:
        ensure_same_user(owner["user"] or type("Owner", (), {"user_id": owner["user_id"]})(), tracked_student)

    index = next_sequence("article_version")
    version = ArticleVersion(
        user=owner["user"],
        user_id=owner["user_id"],
        tracked_student=tracked_student,
        tracked_student_id=tracked_student.id if tracked_student is not None else tracked_student_id,
        mymoment_article_id=overrides.pop("mymoment_article_id", 2000 + index),
        version_number=overrides.pop("version_number", 1),
        article_title=overrides.pop("article_title", f"Backed Up Article {index}"),
        article_url=overrides.pop("article_url", f"/article/{2000 + index}/"),
        article_status=overrides.pop("article_status", "Publiziert"),
        article_visibility=overrides.pop("article_visibility", "Beispielklasse A (Testschule)"),
        article_category=overrides.pop("article_category", "Informieren"),
        article_task=overrides.pop("article_task", "Fixture task"),
        article_last_modified=overrides.pop("article_last_modified", datetime.utcnow()),
        scraped_at=overrides.pop("scraped_at", datetime.utcnow()),
        extra_metadata=overrides.pop("extra_metadata", {"source": "fixture"}),
        is_active=overrides.pop("is_active", True),
        **overrides,
    )
    version.set_content(
        content or f"Versioned article content {index}.",
        raw_html or f"<div><p>Versioned article content {index}.</p></div>",
    )
    session.add(version)
    await session.flush()
    return version
