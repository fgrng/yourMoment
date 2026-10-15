"""Building the decrypted platform account from the stored one."""

from __future__ import annotations

import pytest

from src.platforms import PlatformAccount
from src.platforms.accounts import load_platform_account
from tests.fixtures.factories.mymoment import create_mymoment_login
from tests.fixtures.factories.users import create_user


pytestmark = [pytest.mark.unit, pytest.mark.database]


async def test_load_platform_account_decrypts_credentials(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user, username="teacher", password="Secret-1!", is_admin=True)

    account = await load_platform_account(db_session, login.id, user.id)

    assert account == PlatformAccount(
        id=login.id,
        base_url="https://www.mymoment.ch",
        username="teacher",
        password="Secret-1!",
        role="admin",
    )


async def test_load_platform_account_of_other_user_returns_none(db_session):
    owner = await create_user(db_session)
    other = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=owner)

    assert await load_platform_account(db_session, login.id, other.id) is None


async def test_load_inactive_platform_account_returns_none(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user, is_active=False)

    assert await load_platform_account(db_session, login.id, user.id) is None
