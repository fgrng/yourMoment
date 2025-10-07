"""Unit tests for User model helper behavior."""

import uuid
from datetime import datetime, timedelta

import pytest

from src.models.user import User
from src.models.user_session import UserSession


class TestUserModel:
    """Tests covering user-specific helpers."""

    def test_to_dict_excludes_sensitive_by_default(self):
        now = datetime.utcnow()
        user = User(
            id=uuid.uuid4(),
            email="person@example.com",
            password_hash="hashed",
            is_active=True,
            is_verified=False,
            created_at=now,
            updated_at=now,
        )

        user_dict = user.to_dict()

        assert user_dict["id"] == str(user.id)
        assert user_dict["email"] == "person@example.com"
        assert user_dict["is_active"] is True
        assert user_dict["is_verified"] is False
        assert user_dict["created_at"] == now.isoformat()
        assert "password_hash" not in user_dict

    def test_to_dict_can_include_sensitive_fields(self):
        user = User(
            id=uuid.uuid4(),
            email="person@example.com",
            password_hash="hashed",
        )

        user_dict = user.to_dict(include_sensitive=True)

        assert user_dict["password_hash"] == "hashed"

    @pytest.mark.parametrize(
        "candidate, expected",
        [
            ("valid@example.com", True),
            ("missing-at", False),
            ("also@invalid", False),
            ("", False),
        ],
    )
    def test_validate_email(self, candidate, expected):
        assert User.validate_email(candidate) is expected

    def test_is_password_valid_matches_hash(self):
        user = User(password_hash="stored")

        assert user.is_password_valid("stored") is True
        assert user.is_password_valid("other") is False


class TestUserSessionModel:
    """Tests for user session lifecycle helpers."""

    def test_create_session_sets_defaults(self):
        user_id = uuid.uuid4()
        session = UserSession.create_session(user_id, "hash", session_duration=timedelta(hours=2))

        assert session.user_id == user_id
        assert session.token_hash == "hash"
        assert session.is_active is True
        assert session.is_valid is True
        assert session.expires_at > datetime.utcnow()

    def test_expiry_and_activity_properties(self):
        now = datetime.utcnow()
        session = UserSession(
            user_id=uuid.uuid4(),
            token_hash="hash",
            expires_at=now + timedelta(minutes=10),
            last_activity=now - timedelta(minutes=5),
            is_active=True,
        )

        assert session.is_expired is False
        assert session.is_valid is True
        assert session.time_until_expiry.total_seconds() > 0
        assert 240 <= session.time_since_last_activity.total_seconds() <= 360

        session.expires_at = datetime.utcnow() - timedelta(seconds=1)
        assert session.is_expired is True
        assert session.is_valid is False
        assert session.time_until_expiry == timedelta(0)

    def test_update_last_activity_and_extend_session(self):
        session = UserSession.create_session(uuid.uuid4(), "hash", session_duration=timedelta(hours=1))
        before_expiry = session.expires_at

        session.last_activity = datetime.utcnow() - timedelta(minutes=5)
        session.update_last_activity()
        assert session.time_since_last_activity.total_seconds() < 1

        session.extend_session(timedelta(hours=1))
        assert session.expires_at >= before_expiry + timedelta(hours=1)
        assert session.is_valid is True

    def test_revoke_marks_inactive(self):
        session = UserSession.create_session(uuid.uuid4(), "hash")
        session.revoke()

        assert session.is_active is False
        assert session.is_valid is False
