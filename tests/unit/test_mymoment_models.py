"""Unit tests for myMoment related models."""

import json
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import src.models.mymoment_login as login_module
import src.models.mymoment_session as session_module
from src.models.mymoment_login import MyMomentLogin
from src.models.mymoment_session import MyMomentSession
from src.models.monitoring_process_login import MonitoringProcessLogin


class TestMyMomentLogin:
    """Tests for credential storage helpers."""

    def test_set_and_get_credentials_roundtrip(self, monkeypatch):
        monkeypatch.setattr(
            login_module,
            "encrypt_mymoment_credentials",
            lambda username, password: (f"enc:{username}", f"enc:{password}"),
        )
        monkeypatch.setattr(
            login_module,
            "decrypt_mymoment_credentials",
            lambda enc_user, enc_pass: (
                enc_user.replace("enc:", "", 1),
                enc_pass.replace("enc:", "", 1),
            ),
        )

        login = MyMomentLogin(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            username_encrypted="enc:initial",
            password_encrypted="enc:initial",
            name="Account",
        )

        login.set_credentials("user", "pass")

        assert login.username_encrypted == "enc:user"
        assert login.password_encrypted == "enc:pass"
        assert login.get_credentials() == ("user", "pass")
        assert login.username == "user"

    def test_to_dict_excludes_credentials_by_default(self, monkeypatch):
        monkeypatch.setattr(
            login_module,
            "decrypt_mymoment_credentials",
            lambda enc_user, enc_pass: (
                enc_user.replace("enc:", "", 1),
                enc_pass.replace("enc:", "", 1),
            ),
        )

        login = MyMomentLogin(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            username_encrypted="enc:user",
            password_encrypted="enc:pass",
            name="Account",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        data = login.to_dict()

        assert data["username"] == "user"
        assert "credentials" not in data

    def test_to_dict_includes_credentials_when_requested(self, monkeypatch):
        monkeypatch.setattr(
            login_module,
            "decrypt_mymoment_credentials",
            lambda enc_user, enc_pass: ("user", "pass"),
        )

        login = MyMomentLogin(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            username_encrypted="enc:user",
            password_encrypted="enc:pass",
            name="Account",
        )

        data = login.to_dict(include_credentials=True)

        assert data["credentials"] == {"username": "user", "password": "pass"}

    def test_mark_as_used_updates_timestamp(self):
        login = MyMomentLogin(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            username_encrypted="enc:user",
            password_encrypted="enc:pass",
            name="Account",
        )
        login.last_used = None

        before = datetime.utcnow()
        login.mark_as_used()
        after = datetime.utcnow()

        assert login.last_used is not None
        assert before <= login.last_used <= after

    def test_activate_and_deactivate_toggle_state(self):
        login = MyMomentLogin(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            username_encrypted="enc:user",
            password_encrypted="enc:pass",
            name="Account",
            is_active=True,
        )

        login.deactivate()
        assert login.is_active is False

        login.activate()
        assert login.is_active is True

    def test_dependency_helpers(self):
        login = MyMomentLogin(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            username_encrypted="enc:user",
            password_encrypted="enc:pass",
            name="Account",
        )

        active_session = MyMomentSession(
            id=uuid.uuid4(),
            mymoment_login_id=login.id,
            session_data_encrypted="enc:data",
            expires_at=datetime.utcnow() + timedelta(hours=1),
            is_active=True,
            mymoment_login=login,
        )
        login.sessions = [active_session]
        login.monitoring_process_logins = []
        assert login.has_active_sessions() is True
        assert login.is_used_in_monitoring() is False
        assert login.can_be_deleted() is False

        inactive_session = MyMomentSession(
            id=uuid.uuid4(),
            mymoment_login_id=login.id,
            session_data_encrypted="enc:data",
            expires_at=datetime.utcnow() + timedelta(hours=1),
            is_active=False,
            mymoment_login=login,
        )
        login.sessions = [inactive_session]
        login.monitoring_process_logins = [
            MonitoringProcessLogin(
                id=uuid.uuid4(),
                monitoring_process_id=uuid.uuid4(),
                mymoment_login_id=login.id,
                is_active=True,
                mymoment_login=login,
            )
        ]
        assert login.is_used_in_monitoring() is True
        assert login.can_be_deleted() is False

        login.monitoring_process_logins = []
        assert login.can_be_deleted() is True


class TestMyMomentSession:
    """Tests for MyMomentSession lifecycle helpers."""

    def test_create_new_session_encrypts_data(self, monkeypatch):
        monkeypatch.setattr(session_module, "encrypt_session_data", lambda data: f"enc:{data}")

        session = MyMomentSession.create_new_session(uuid.uuid4(), {"token": "abc"}, duration_hours=2)

        assert session.session_data_encrypted == "enc:{'token': 'abc'}"
        assert session.is_active is True
        assert pytest_approx_hours(session.expires_at - datetime.utcnow(), 2)

    def test_set_and_get_session_data_roundtrip(self, monkeypatch):
        monkeypatch.setattr(session_module, "encrypt_session_data", lambda data: f"enc:{data}")
        monkeypatch.setattr(session_module, "decrypt_session_data", lambda data, as_dict=True: json.loads(data.split(":", 1)[1]))

        session = MyMomentSession(
            id=uuid.uuid4(),
            mymoment_login_id=uuid.uuid4(),
            session_data_encrypted="enc:{}",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )

        session.set_session_data(json.dumps({"token": "abc"}))

        assert session.session_data_encrypted == "enc:{\"token\": \"abc\"}"
        assert session.get_session_data() == {"token": "abc"}

    def test_update_session_data_calls_touch(self, monkeypatch):
        monkeypatch.setattr(session_module, "encrypt_session_data", lambda data: f"enc:{data}")

        def fake_touch(self):
            self.touched = True

        monkeypatch.setattr(MyMomentSession, "touch", fake_touch)

        session = MyMomentSession(
            id=uuid.uuid4(),
            mymoment_login_id=uuid.uuid4(),
            session_data_encrypted="enc:old",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )

        session.update_session_data("new-data")

        assert session.session_data_encrypted == "enc:new-data"
        assert getattr(session, "touched", False) is True

    def test_to_dict_optionally_includes_session_data(self, monkeypatch):
        monkeypatch.setattr(session_module, "decrypt_session_data", lambda data, as_dict=True: {"token": "abc"})

        now = datetime.utcnow()
        expires_at = now + timedelta(hours=1)
        session = MyMomentSession(
            id=uuid.uuid4(),
            mymoment_login_id=uuid.uuid4(),
            session_data_encrypted="enc:data",
            expires_at=expires_at,
            created_at=now,
            last_accessed=now,
            updated_at=now,
        )

        data = session.to_dict(include_session_data=True)

        assert data["session_data"] == {"token": "abc"}
        returned_expires_at = datetime.fromisoformat(data["expires_at"])
        assert abs((returned_expires_at - expires_at).total_seconds()) < 1

    def test_session_lifecycle_flags(self):
        session = MyMomentSession(
            id=uuid.uuid4(),
            mymoment_login_id=uuid.uuid4(),
            session_data_encrypted="enc:data",
            expires_at=datetime.utcnow() - timedelta(hours=1),
            is_active=True,
        )

        assert session.is_expired() is True
        assert session.is_usable() is False
        assert session.get_remaining_hours() == 0.0

        session.expires_at = datetime.utcnow() + timedelta(hours=2)
        assert session.is_expired() is False
        assert session.is_usable() is True
        assert session.get_remaining_hours() > 1.9

    def test_renew_deactivate_activate_and_touch(self):
        session = MyMomentSession(
            id=uuid.uuid4(),
            mymoment_login_id=uuid.uuid4(),
            session_data_encrypted="enc:data",
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            is_active=False,
            last_accessed=datetime.utcnow() - timedelta(hours=1),
        )

        session.renew_session(duration_hours=1)
        assert session.expires_at > datetime.utcnow()
        assert session.is_active is True

        previous_accessed = session.last_accessed
        session.touch()
        assert session.last_accessed >= previous_accessed

        session.deactivate()
        assert session.is_active is False

        session.activate()
        assert session.is_active is True

        session.expires_at = datetime.utcnow() - timedelta(minutes=1)
        session.is_active = False
        session.activate()
        assert session.is_active is False

    def test_cleanup_expired_sessions_updates_records(self, monkeypatch):
        query_mock = MagicMock()
        filter_mock = MagicMock()
        query_mock.filter.return_value = filter_mock
        filter_mock.count.return_value = 2

        session_mock = MagicMock()
        session_mock.query.return_value = query_mock

        result = MyMomentSession.cleanup_expired_sessions(session_mock)

        assert result == 2
        session_mock.query.assert_called_once_with(MyMomentSession)
        filter_mock.update.assert_called_once()
        update_args = filter_mock.update.call_args[0][0]
        assert update_args["is_active"] is False
        assert isinstance(update_args["updated_at"], datetime)
        session_mock.commit.assert_called_once()


def pytest_approx_hours(delta: timedelta, expected_hours: float) -> bool:
    """Helper asserting timedelta close to expected hours."""
    actual_hours = delta.total_seconds() / 3600.0
    return abs(actual_hours - expected_hours) < 0.05
