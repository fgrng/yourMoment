"""DB-backed tests for the current `MyMomentLogin` model behavior."""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.fixtures.assertions import assert_mymoment_credentials_round_trip
from tests.fixtures.factories import (
    create_monitoring_process,
    create_mymoment_login,
    create_mymoment_session,
    create_user,
)


pytestmark = pytest.mark.database


async def test_credentials_round_trip_and_safe_display_use_model_helpers(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(
        db_session,
        user=user,
        username="teacher.one",
        password="S3cure-Pass!",
    )

    assert_mymoment_credentials_round_trip(
        login,
        username="teacher.one",
        password="S3cure-Pass!",
    )
    assert login.get_username() == "teacher.one"
    assert login.get_password() == "S3cure-Pass!"
    assert login.username == "teacher.one"

    payload = login.to_dict()
    assert payload["id"] == str(login.id)
    assert payload["user_id"] == str(user.id)
    assert payload["username"] == "teacher.one"
    assert payload["created_at"] is not None
    assert payload["updated_at"] is not None
    assert "credentials" not in payload
    assert "username_encrypted" not in payload
    assert "password_encrypted" not in payload

    with_credentials = login.to_dict(include_credentials=True)
    assert with_credentials["credentials"] == {
        "username": "teacher.one",
        "password": "S3cure-Pass!",
    }


async def test_lifecycle_helpers_update_timestamps_and_usage_flags(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)

    before_used = datetime.utcnow()
    login.mark_as_used()
    assert login.last_used is not None
    assert login.last_used >= before_used

    before_deactivate = datetime.utcnow()
    login.deactivate()
    assert login.is_active is False
    assert login.updated_at >= before_deactivate

    before_activate = datetime.utcnow()
    login.activate()
    assert login.is_active is True
    assert login.updated_at >= before_activate


async def test_association_and_role_helpers_reflect_current_state(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user, is_admin=False)
    admin_login = await create_mymoment_login(db_session, user=user, is_admin=True)

    await create_mymoment_session(
        db_session,
        mymoment_login=login,
        session_data={"cookie": "active-session"},
    )
    await create_monitoring_process(
        db_session,
        user=user,
        mymoment_logins=[login],
    )

    await db_session.refresh(login, ["sessions", "monitoring_process_logins"])

    assert login.has_active_sessions() is True
    assert login.is_used_in_monitoring() is True
    assert login.can_be_deleted() is False
    assert login.can_be_used_for_monitoring() is True
    assert login.can_be_used_for_student_backup() is False

    assert admin_login.can_be_used_for_monitoring() is False
    assert admin_login.can_be_used_for_student_backup() is True

    admin_login.deactivate()
    assert admin_login.can_be_used_for_student_backup() is False
