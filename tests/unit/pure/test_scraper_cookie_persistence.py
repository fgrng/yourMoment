"""
Pure unit tests for scraper cookie persistence logic.

Tests cover cookie jar serialization/restoration plus the decision logic
around session initialization and authentication persistence.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services import scraper_service as scraper_service_module
from src.services.scraper_service import ScraperService, SessionContext
from tests.fixtures.stubs import AiohttpStubResponse


@pytest.fixture
def scraper():
    """Return a ScraperService instance with a mocked DB session."""
    return ScraperService(db_session=MagicMock())


def _build_cookie_morsel(
    *,
    name: str,
    value: str,
    domain: str | None = None,
    path: str | None = "/",
    expires: str | None = None,
):
    cookie = SimpleCookie()
    cookie[name] = value
    morsel = cookie[name]
    if domain is not None:
        morsel["domain"] = domain
    if path is not None:
        morsel["path"] = path
    if expires is not None:
        morsel["expires"] = expires
    return morsel


def _build_persisted_cookie(
    *,
    name: str = "sessionid",
    value: str = "abc123",
    domain: str | None = ".www.mymoment.ch",
    path: str = "/",
    expires: str | None = "2027-06-09T10:18:14+00:00",
):
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": path,
        "expires": expires,
    }


def _build_credentials(*, username: str = "user@example.com", password: str = "secret"):
    credentials = MagicMock()
    credentials.username = username
    credentials.get_credentials = MagicMock(return_value=(username, password))
    return credentials


def _build_session_record(*, session_data=None, session_id: uuid.UUID | None = None):
    session_record = MagicMock()
    session_record.id = session_id or uuid.uuid4()
    session_record.get_session_data = MagicMock(return_value=session_data)
    return session_record


def _build_http_session():
    http_session = MagicMock()
    http_session.cookie_jar = MagicMock()
    http_session.close = AsyncMock()
    return http_session


def _patch_aiohttp_client(monkeypatch, http_session):
    monkeypatch.setattr(
        scraper_service_module.aiohttp,
        "TCPConnector",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        scraper_service_module.aiohttp,
        "ClientTimeout",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr(
        scraper_service_module.aiohttp,
        "ClientSession",
        MagicMock(return_value=http_session),
    )


def _setup_initialize_single_session_mocks(
    scraper: ScraperService,
    monkeypatch,
    *,
    session_record,
    credentials,
    http_session,
    check_auth_return=False,
    restore_return=None,
    restore_side_effect=None,
):
    scraper._authenticate_session = AsyncMock(return_value=True)
    scraper._check_authentication_status = AsyncMock(return_value=check_auth_return)
    scraper._restore_cookies_to_session = MagicMock(
        return_value=restore_return,
        side_effect=restore_side_effect,
    )
    scraper.credentials_service.get_credentials_by_id = AsyncMock(return_value=credentials)
    scraper.session_service.get_or_create_session = AsyncMock(return_value=session_record)
    scraper.session_service.renew_session = AsyncMock(return_value=True)
    _patch_aiohttp_client(monkeypatch, http_session)


def _build_context(http_session):
    return SessionContext(
        login_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        username="auth-user",
        aiohttp_session=http_session,
        last_activity=datetime.utcnow(),
        is_authenticated=False,
    )


def test_serialize_cookie_jar_includes_all_cookie_fields(scraper):
    """Should serialize all cookie fields into a persistable dictionary."""
    cookie = _build_cookie_morsel(
        name="sessionid",
        value="abc123",
        domain=".www.mymoment.ch",
        path="/accounts",
        expires="Wed, 09 Jun 2027 10:18:14 GMT",
    )
    http_session = MagicMock()
    http_session.cookie_jar = [cookie]

    data = scraper._serialize_cookie_jar(http_session, csrf_token="csrf-token")

    assert data["cookies"] == [
        {
            "name": "sessionid",
            "value": "abc123",
            "domain": ".www.mymoment.ch",
            "path": "/accounts",
            "expires": "2027-06-09T10:18:14+00:00",
        }
    ]


def test_serialize_cookie_jar_sets_expires_none_when_missing(scraper):
    """Should serialize cookies without expiry as expires=None."""
    cookie = _build_cookie_morsel(
        name="csrftoken",
        value="csrf123",
        domain="www.mymoment.ch",
        path="/",
    )
    http_session = MagicMock()
    http_session.cookie_jar = [cookie]

    data = scraper._serialize_cookie_jar(http_session)

    assert data["cookies"][0]["expires"] is None


def test_serialize_cookie_jar_includes_csrf_and_saved_at(scraper):
    """Should include csrf_token and saved_at in the serialized output."""
    cookie = _build_cookie_morsel(name="sessionid", value="abc123")
    http_session = MagicMock()
    http_session.cookie_jar = [cookie]

    data = scraper._serialize_cookie_jar(http_session, csrf_token="csrf-token")

    assert data["csrf_token"] == "csrf-token"
    assert datetime.fromisoformat(data["saved_at"])


def test_serialize_cookie_jar_empty_jar_returns_empty_cookie_list(scraper):
    """Should return an empty cookies list when the jar is empty."""
    http_session = MagicMock()
    http_session.cookie_jar = []

    data = scraper._serialize_cookie_jar(http_session, csrf_token="csrf-token")

    assert data["cookies"] == []


def test_serialize_cookie_jar_sets_expires_none_for_unparseable_date(scraper):
    """Should store expires=None when the cookie's expires string cannot be parsed."""
    cookie = _build_cookie_morsel(
        name="sessionid",
        value="abc123",
        expires="not-a-valid-date",
    )
    http_session = MagicMock()
    http_session.cookie_jar = [cookie]

    data = scraper._serialize_cookie_jar(http_session)

    assert data["cookies"][0]["expires"] is None


def test_restore_returns_none_without_cookies_key_and_does_not_update(scraper):
    """Should no-op when session_data only contains placeholder initialization state."""
    http_session = _build_http_session()

    result = scraper._restore_cookies_to_session(
        http_session,
        {"status": "initializing"},
    )

    assert result is None
    http_session.cookie_jar.update_cookies.assert_not_called()


def test_restore_returns_none_for_empty_cookies_list_and_does_not_update(scraper):
    """Should no-op when cookies list is present but empty."""
    http_session = _build_http_session()

    result = scraper._restore_cookies_to_session(
        http_session,
        {"cookies": []},
    )

    assert result is None
    http_session.cookie_jar.update_cookies.assert_not_called()


def test_restore_returns_csrf_token_when_cookies_present(scraper):
    """Should return csrf_token when at least one cookie is restored."""
    http_session = _build_http_session()
    session_data = {
        "cookies": [_build_persisted_cookie()],
        "csrf_token": "csrf-123",
    }

    result = scraper._restore_cookies_to_session(http_session, session_data)

    assert result == "csrf-123"


def test_restore_calls_update_cookies_for_each_cookie(scraper):
    """Should call update_cookies once per persisted cookie."""
    http_session = _build_http_session()
    session_data = {
        "cookies": [
            _build_persisted_cookie(name="sessionid"),
            _build_persisted_cookie(name="csrftoken", value="csrf123"),
        ]
    }

    scraper._restore_cookies_to_session(http_session, session_data)

    assert http_session.cookie_jar.update_cookies.call_count == 2


@pytest.mark.parametrize(
    ("session_data", "update_side_effect"),
    [
        (
            {
                "cookies": [
                    {
                        "value": "abc123",
                        "domain": ".www.mymoment.ch",
                        "path": "/",
                        "expires": "2027-06-09T10:18:14+00:00",
                    }
                ]
            },
            None,
        ),
        (
            {"cookies": [_build_persisted_cookie()]},
            RuntimeError("cookie update failed"),
        ),
    ],
)
def test_restore_returns_none_on_malformed_data_or_update_failure(
    scraper,
    session_data,
    update_side_effect,
):
    """Should swallow restore failures and return None."""
    http_session = _build_http_session()
    if update_side_effect is not None:
        http_session.cookie_jar.update_cookies.side_effect = update_side_effect

    result = scraper._restore_cookies_to_session(http_session, session_data)

    assert result is None


async def test_initialize_single_session_uses_restored_cookies_when_valid(scraper, monkeypatch):
    """Should skip full authentication when restored cookies are still valid."""
    login_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_data = {
        "cookies": [_build_persisted_cookie()],
        "csrf_token": "csrf-123",
    }
    session_record = _build_session_record(session_data=session_data)
    credentials = _build_credentials(username="restored-user")
    http_session = _build_http_session()
    _setup_initialize_single_session_mocks(
        scraper,
        monkeypatch,
        session_record=session_record,
        credentials=credentials,
        http_session=http_session,
        check_auth_return=True,
        restore_return="csrf-123",
    )

    context = await scraper._initialize_single_session(login_id, user_id)

    scraper._authenticate_session.assert_not_awaited()
    scraper.session_service.renew_session.assert_awaited_once_with(session_record.id)
    assert context.is_authenticated is True


async def test_initialize_single_session_falls_back_to_auth_when_restored_cookies_invalid(
    scraper,
    monkeypatch,
):
    """Should re-authenticate when restored cookies fail validation."""
    login_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_data = {
        "cookies": [_build_persisted_cookie()],
        "csrf_token": "csrf-123",
    }
    session_record = _build_session_record(session_data=session_data)
    credentials = _build_credentials(username="fallback-user")
    http_session = _build_http_session()
    _setup_initialize_single_session_mocks(
        scraper,
        monkeypatch,
        session_record=session_record,
        credentials=credentials,
        http_session=http_session,
        check_auth_return=False,
        restore_return="csrf-123",
    )

    await scraper._initialize_single_session(login_id, user_id)

    scraper._authenticate_session.assert_awaited_once()
    scraper.session_service.renew_session.assert_not_awaited()


async def test_initialize_single_session_auths_when_no_cookies_in_placeholder_session(
    scraper,
    monkeypatch,
):
    """Should authenticate when persisted session data has no cookies."""
    login_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_record = _build_session_record(session_data={"status": "initializing"})
    credentials = _build_credentials(username="placeholder-user")
    http_session = _build_http_session()
    _setup_initialize_single_session_mocks(
        scraper,
        monkeypatch,
        session_record=session_record,
        credentials=credentials,
        http_session=http_session,
        check_auth_return=False,
        restore_return=None,
    )

    await scraper._initialize_single_session(login_id, user_id)

    scraper._authenticate_session.assert_awaited_once()
    scraper.session_service.renew_session.assert_not_awaited()


async def test_initialize_single_session_auths_when_get_session_data_raises(
    scraper,
    monkeypatch,
):
    """Should fall back to authentication when session data cannot be loaded."""
    login_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_record = _build_session_record(session_data=None)
    session_record.get_session_data.side_effect = RuntimeError("session load failed")
    credentials = _build_credentials(username="load-failure-user")
    http_session = _build_http_session()
    _setup_initialize_single_session_mocks(
        scraper,
        monkeypatch,
        session_record=session_record,
        credentials=credentials,
        http_session=http_session,
        check_auth_return=False,
        restore_return=None,
    )

    await scraper._initialize_single_session(login_id, user_id)

    scraper._authenticate_session.assert_awaited_once()


async def test_initialize_single_session_auths_once_when_restore_raises(scraper, monkeypatch):
    """Should fall back to one authentication attempt when cookie restore fails."""
    login_id = uuid.uuid4()
    user_id = uuid.uuid4()
    session_data = {
        "cookies": [_build_persisted_cookie()],
        "csrf_token": "csrf-123",
    }
    session_record = _build_session_record(session_data=session_data)
    credentials = _build_credentials(username="restore-error-user")
    http_session = _build_http_session()
    _setup_initialize_single_session_mocks(
        scraper,
        monkeypatch,
        session_record=session_record,
        credentials=credentials,
        http_session=http_session,
        check_auth_return=False,
        restore_side_effect=RuntimeError("restore failed"),
    )

    await scraper._initialize_single_session(login_id, user_id)

    assert scraper._authenticate_session.await_count == 1
    scraper.session_service.renew_session.assert_not_awaited()


async def test_authenticate_persists_cookie_data_after_successful_auth(scraper):
    """Should persist serialized cookies after successful login flow."""
    http_session = _build_http_session()
    context = _build_context(http_session)
    credentials = _build_credentials(username="auth-user", password="topsecret")
    persisted_data = {
        "cookies": [_build_persisted_cookie()],
        "csrf_token": "csrf-123",
        "saved_at": "2026-04-14T10:00:00",
    }

    scraper._check_authentication_status = AsyncMock(side_effect=[False, True])
    scraper.credentials_service.get_credentials_by_id = AsyncMock(return_value=credentials)
    scraper._get_with_redirect_handling = AsyncMock(
        return_value=AiohttpStubResponse(
            body='<form><input name="csrfmiddlewaretoken" value="csrf-123" /></form>'
        )
    )
    scraper._request_with_redirect_handling = AsyncMock(
        return_value=AiohttpStubResponse(status=302)
    )
    scraper._serialize_cookie_jar = MagicMock(return_value=persisted_data)
    scraper.session_service.touch_session = AsyncMock(return_value=True)
    scraper.session_service.update_session_data = AsyncMock(return_value=True)

    result = await scraper._authenticate_session(context)

    assert result is True
    scraper.session_service.update_session_data.assert_awaited_once()
    session_id, data = scraper.session_service.update_session_data.await_args.args
    assert session_id == context.session_id
    assert "cookies" in data


async def test_authenticate_returns_true_when_update_session_data_raises(scraper):
    """Should not fail authentication if session persistence raises."""
    http_session = _build_http_session()
    context = _build_context(http_session)
    credentials = _build_credentials(username="auth-user", password="topsecret")
    persisted_data = {
        "cookies": [_build_persisted_cookie()],
        "csrf_token": "csrf-123",
        "saved_at": "2026-04-14T10:00:00",
    }

    scraper._check_authentication_status = AsyncMock(side_effect=[False, True])
    scraper.credentials_service.get_credentials_by_id = AsyncMock(return_value=credentials)
    scraper._get_with_redirect_handling = AsyncMock(
        return_value=AiohttpStubResponse(
            body='<form><input name="csrfmiddlewaretoken" value="csrf-123" /></form>'
        )
    )
    scraper._request_with_redirect_handling = AsyncMock(
        return_value=AiohttpStubResponse(status=302)
    )
    scraper._serialize_cookie_jar = MagicMock(return_value=persisted_data)
    scraper.session_service.touch_session = AsyncMock(return_value=True)
    scraper.session_service.update_session_data = AsyncMock(
        side_effect=RuntimeError("persist failed")
    )

    result = await scraper._authenticate_session(context)

    assert result is True

