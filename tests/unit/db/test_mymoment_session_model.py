"""DB-backed tests for the current `MyMomentSession` model behavior."""

from __future__ import annotations

from datetime import datetime

import pytest

from tests.fixtures.assertions import assert_session_data_round_trip
from tests.fixtures.factories import (
    create_expired_mymoment_session,
    create_mymoment_login,
    create_mymoment_session,
    create_user,
)


pytestmark = pytest.mark.database


async def test_create_new_session_round_trip_and_safe_display_use_model_helpers(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    session_record = await create_mymoment_session(
        db_session,
        mymoment_login=login,
        session_data={"cookie": "abc123", "csrf": "token-1"},
        duration_hours=12,
    )

    assert_session_data_round_trip(
        session_record,
        expected_data={"cookie": "abc123", "csrf": "token-1"},
    )

    payload = session_record.to_dict()
    assert payload["id"] == str(session_record.id)
    assert payload["mymoment_login_id"] == str(login.id)
    assert payload["expires_at"] is not None
    assert payload["created_at"] is not None
    assert payload["updated_at"] is not None
    assert "session_data" not in payload
    assert "session_data_encrypted" not in payload

    with_session_data = session_record.to_dict(include_session_data=True)
    assert with_session_data["session_data"] == {"cookie": "abc123", "csrf": "token-1"}


async def test_expiry_usability_and_remaining_hours_reflect_session_state(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    active_session = await create_mymoment_session(db_session, mymoment_login=login, duration_hours=6)
    expired_session = await create_expired_mymoment_session(db_session, mymoment_login=login)

    assert active_session.is_expired() is False
    assert active_session.is_usable() is True
    assert active_session.get_remaining_hours() > 0

    assert expired_session.is_expired() is True
    assert expired_session.is_usable() is False
    assert expired_session.get_remaining_hours() == 0.0

    expired_session.is_active = False
    expired_session.activate()
    assert expired_session.is_active is False


async def test_touch_renew_update_and_deactivate_helpers_manage_lifecycle(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    session_record = await create_mymoment_session(
        db_session,
        mymoment_login=login,
        session_data={"cookie": "original"},
        duration_hours=1,
    )

    previous_expiry = session_record.expires_at

    before_touch = datetime.utcnow()
    session_record.touch()
    assert session_record.last_accessed >= before_touch

    session_record.update_session_data({"cookie": "rotated", "csrf": "new-token"})
    assert session_record.get_session_data() == {"cookie": "rotated", "csrf": "new-token"}

    session_record.deactivate()
    assert session_record.is_active is False

    session_record.renew_session(duration_hours=48)
    assert session_record.is_active is True
    assert session_record.expires_at > previous_expiry
