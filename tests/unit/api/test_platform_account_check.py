"""Checking a platform account through the credentials router, against the fake platform."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.mymoment_credentials import test_credentials as check_platform_account
from src.platforms import PlatformAuthError, PlatformUnavailable
from src.services.mymoment_credentials_service import MyMomentCredentialsService
from tests.fixtures.factories.mymoment import create_mymoment_login
from tests.fixtures.factories.users import create_user


pytestmark = [pytest.mark.unit, pytest.mark.database]


async def _stored_login(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user, username="teacher")
    await db_session.commit()
    return user, login


async def _check(db_session, user, login):
    return await check_platform_account(
        credentials_id=login.id,
        current_user=user,
        service=MyMomentCredentialsService(db_session),
    )


async def test_check_connects_with_the_decrypted_account(db_session, fake_platform):
    user, login = await _stored_login(db_session)

    response = await _check(db_session, user, login)

    [account] = fake_platform.connected_accounts
    assert (response["username"], account.id, account.username) == ("teacher", login.id, "teacher")


async def test_check_logs_in_instead_of_reusing_a_stored_session(db_session, fake_platform):
    user, login = await _stored_login(db_session)

    await _check(db_session, user, login)

    assert [account.id for account in fake_platform.fresh_logins] == [login.id]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PlatformAuthError("wrong password"), (401, "mymoment_credentials_authentication_failed")),
        (PlatformUnavailable("timeout"), (503, "mymoment_credentials_platform_unavailable")),
    ],
    ids=["wrong-credentials", "unavailable"],
)
async def test_check_tells_wrong_credentials_apart_from_unavailable_platform(
    db_session, fake_platform, error, expected
):
    user, login = await _stored_login(db_session)
    fake_platform.fail("connect", error)

    with pytest.raises(HTTPException) as raised:
        await _check(db_session, user, login)

    assert (raised.value.status_code, raised.value.detail["error"]) == expected


async def test_check_of_another_users_account_is_not_found(db_session, fake_platform):
    _, login = await _stored_login(db_session)
    stranger = await create_user(db_session)

    with pytest.raises(HTTPException) as raised:
        await _check(db_session, stranger, login)

    assert (raised.value.status_code, fake_platform.connected_accounts) == (404, [])
