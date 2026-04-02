"""DB-backed tests for the current student-backup model behavior."""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.fixtures.factories import (
    create_article_version,
    create_mymoment_login,
    create_tracked_student,
    create_user,
)


pytestmark = pytest.mark.database


async def test_tracked_student_to_dict_and_lifecycle_helpers_are_safe(db_session):
    user = await create_user(db_session)
    admin_login = await create_mymoment_login(db_session, user=user, is_admin=True)
    tracked_student = await create_tracked_student(
        db_session,
        user=user,
        mymoment_login=admin_login,
    )

    payload = tracked_student.to_dict()
    assert payload["id"] == str(tracked_student.id)
    assert payload["user_id"] == str(user.id)
    assert payload["mymoment_login_id"] == str(admin_login.id)
    assert payload["last_backup_at"] is None
    assert payload["created_at"] is not None
    assert payload["updated_at"] is not None
    assert tracked_student.dashboard_url.endswith(f"/{tracked_student.mymoment_student_id}/")

    before_backup = datetime.utcnow()
    tracked_student.mark_backup_completed()
    assert tracked_student.last_backup_at is not None
    assert tracked_student.last_backup_at >= before_backup

    tracked_student.deactivate()
    assert tracked_student.is_active is False
    tracked_student.activate()
    assert tracked_student.is_active is True


async def test_tracked_student_counts_only_active_article_versions(db_session):
    user = await create_user(db_session)
    admin_login = await create_mymoment_login(db_session, user=user, is_admin=True)
    tracked_student = await create_tracked_student(
        db_session,
        user=user,
        mymoment_login=admin_login,
    )

    active_v1 = await create_article_version(
        db_session,
        user=user,
        tracked_student=tracked_student,
        mymoment_article_id=100,
        version_number=1,
    )
    inactive_v2 = await create_article_version(
        db_session,
        user=user,
        tracked_student=tracked_student,
        mymoment_article_id=100,
        version_number=2,
    )
    active_v3 = await create_article_version(
        db_session,
        user=user,
        tracked_student=tracked_student,
        mymoment_article_id=200,
        version_number=1,
    )
    inactive_v2.deactivate()

    await db_session.refresh(tracked_student, ["article_versions"])

    assert active_v1.is_active is True
    assert inactive_v2.is_active is False
    assert active_v3.is_active is True
    assert tracked_student.get_article_count() == 2
    assert tracked_student.get_total_versions_count() == 2


async def test_article_version_hash_urls_preview_and_dict_helpers_match_current_model(db_session):
    user = await create_user(db_session)
    admin_login = await create_mymoment_login(db_session, user=user, is_admin=True)
    tracked_student = await create_tracked_student(
        db_session,
        user=user,
        mymoment_login=admin_login,
    )
    content = "A" * 250
    raw_html = "<div><p>Preview body</p></div>"
    version = await create_article_version(
        db_session,
        user=user,
        tracked_student=tracked_student,
        content=content,
        raw_html=raw_html,
    )

    assert version.content_hash == version.compute_content_hash(content)
    assert version.has_content_changed(content) is False
    assert version.has_content_changed("changed body") is True
    assert version.view_url.endswith(f"/{version.mymoment_article_id}/")
    assert version.edit_url.endswith(f"/{version.mymoment_article_id}/")
    assert version.content_preview.endswith("...")
    assert len(version.content_preview) == 203

    payload = version.to_dict()
    assert payload["id"] == str(version.id)
    assert payload["user_id"] == str(user.id)
    assert payload["tracked_student_id"] == str(tracked_student.id)
    assert payload["content_hash"] == version.content_hash
    assert "article_content" not in payload
    assert "article_raw_html" not in payload

    with_content = version.to_dict(include_content=True)
    assert with_content["article_content"] == content
    assert with_content["article_raw_html"] == raw_html
    assert with_content["extra_metadata"] == {"source": "fixture"}
