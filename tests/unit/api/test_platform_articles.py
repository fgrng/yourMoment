"""Listing targets, listing articles and previewing an article through the articles router, against the fake platform."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.mymoment_articles import get_article_detail, get_articles, get_targets
from src.platforms import PlatformAuthError, PlatformRejected, PlatformUnavailable, TargetValue
from tests.fixtures.factories.mymoment import create_mymoment_login
from tests.fixtures.factories.users import create_user


pytestmark = [pytest.mark.unit, pytest.mark.database]


async def _stored_login(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user, username="teacher")
    await db_session.commit()
    return user, login


async def _list(db_session, user, login, *, category=None, tab="alle", limit=20):
    return await get_articles(
        mymoment_login_id=login.id,
        category=category,
        tab=tab,
        limit=limit,
        current_user=user,
        session=db_session,
    )


async def _preview(db_session, user, login, article_id="3170"):
    return await get_article_detail(
        mymoment_login_id=login.id,
        mymoment_article_id=article_id,
        current_user=user,
        session=db_session,
    )


PLATFORM_ERRORS = pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (PlatformRejected("unknown classroom"), 422),
        (PlatformAuthError("wrong password"), 502),
        (PlatformUnavailable("timeout"), 503),
    ],
    ids=["rejected", "wrong-credentials", "unavailable"],
)


async def test_targets_describe_every_dimension_of_the_platform_account(db_session, fake_platform):
    user, login = await _stored_login(db_session)

    response = await get_targets(mymoment_login_id=login.id, current_user=user, session=db_session)

    assert [(o.key, o.label, o.required) for o in response.items] == [
        ("category", "Category", False),
        ("arrangement", "Arrangement", False),
        ("classroom", "Classroom", True),
    ]


async def test_targets_offer_the_values_of_each_dimension(db_session, fake_platform):
    user, login = await _stored_login(db_session)
    fake_platform.target_values = {
        "arrangement": [TargetValue(value="12", label="Storymap")],
        "classroom": [TargetValue(value="home", label="Meine"), TargetValue(value="82", label="Klasse A")],
    }

    response = await get_targets(mymoment_login_id=login.id, current_user=user, session=db_session)

    assert {o.key: [(v.value, v.label) for v in o.values] for o in response.items} == {
        "category": [],
        "arrangement": [("12", "Storymap")],
        "classroom": [("home", "Meine"), ("82", "Klasse A")],
    }


async def test_targets_are_read_through_the_chosen_platform_account(db_session, fake_platform):
    user, login = await _stored_login(db_session)

    await get_targets(mymoment_login_id=login.id, current_user=user, session=db_session)

    assert [account.id for account in fake_platform.connected_accounts] == [login.id]


@PLATFORM_ERRORS
async def test_platform_errors_while_listing_targets_map_to_http_status(db_session, fake_platform, error, expected_status):
    user, login = await _stored_login(db_session)
    fake_platform.fail("list_targets", error)

    with pytest.raises(HTTPException) as raised:
        await get_targets(mymoment_login_id=login.id, current_user=user, session=db_session)

    assert raised.value.status_code == expected_status


async def test_articles_are_listed_for_the_classroom_and_category_target(db_session, fake_platform):
    user, login = await _stored_login(db_session)
    fake_platform.add_article("4801", category="9", extra={"classroom": "82"})
    fake_platform.add_article("4802", category="7", extra={"classroom": "82"})
    fake_platform.add_article("4803", category="7", extra={"classroom": "alle"})

    response = await _list(db_session, user, login, category=7, tab="82")

    assert [(a.id, a.mymoment_url) for a in response.items] == [("4802", "https://fake.example/articles/4802")]


async def test_article_list_is_cut_to_the_limit(db_session, fake_platform):
    user, login = await _stored_login(db_session)
    for article_id in ("1", "2", "3"):
        fake_platform.add_article(article_id, extra={"classroom": "alle"})

    response = await _list(db_session, user, login, limit=2)

    assert ([a.id for a in response.items], response.total) == (["1", "2"], 2)


async def test_article_preview_shows_the_fetched_content(db_session, fake_platform):
    user, login = await _stored_login(db_session)
    fake_platform.add_article("3170", title="Beispieldialog", author="Sam", body_text="Hallo.", body_html="<p>Hallo.</p>")

    response = await _preview(db_session, user, login)

    assert (response.title, response.author, response.content, response.raw_html, response.mymoment_url) == (
        "Beispieldialog",
        "Sam",
        "Hallo.",
        "<p>Hallo.</p>",
        "https://fake.example/articles/3170",
    )


async def test_preview_of_an_unknown_article_is_not_found(db_session, fake_platform):
    user, login = await _stored_login(db_session)

    with pytest.raises(HTTPException) as raised:
        await _preview(db_session, user, login, article_id="9999")

    assert raised.value.status_code == 404


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [(PlatformAuthError("wrong password"), 502), (PlatformUnavailable("timeout"), 503)],
    ids=["wrong-credentials", "unavailable"],
)
async def test_platform_errors_while_previewing_map_to_http_status(db_session, fake_platform, error, expected_status):
    user, login = await _stored_login(db_session)
    fake_platform.add_article("3170")
    fake_platform.fail("fetch_article", error)

    with pytest.raises(HTTPException) as raised:
        await _preview(db_session, user, login)

    assert raised.value.status_code == expected_status


@PLATFORM_ERRORS
async def test_platform_errors_while_listing_articles_map_to_http_status(db_session, fake_platform, error, expected_status):
    user, login = await _stored_login(db_session)
    fake_platform.fail("list_articles", error)

    with pytest.raises(HTTPException) as raised:
        await _list(db_session, user, login)

    assert raised.value.status_code == expected_status


async def test_another_users_account_is_not_found(db_session, fake_platform):
    _, login = await _stored_login(db_session)
    stranger = await create_user(db_session)

    with pytest.raises(HTTPException) as raised:
        await get_targets(mymoment_login_id=login.id, current_user=stranger, session=db_session)

    assert raised.value.status_code == 404


async def test_another_users_account_is_never_connected(db_session, fake_platform):
    _, login = await _stored_login(db_session)
    stranger = await create_user(db_session)

    with pytest.raises(HTTPException):
        await get_targets(mymoment_login_id=login.id, current_user=stranger, session=db_session)

    assert fake_platform.connected_accounts == []
