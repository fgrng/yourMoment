"""Manual posting of one AI comment through the comments router, against the fake platform."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.comments import post_comment_to_mymoment
from src.platforms import PlatformAuthError, PlatformUnavailable
from tests.fixtures.builders import build_scenario


pytestmark = [pytest.mark.unit, pytest.mark.database]


async def _generated_comment_on_platform(db_session, fake_platform, **ai_comment):
    scenario = await build_scenario("generated_not_posted", db_session, overrides={"ai_comment": ai_comment})
    await db_session.commit()
    fake_platform.add_article(scenario["ai_comment"].mymoment_article_id)
    return scenario


async def _post(scenario, db_session):
    return await post_comment_to_mymoment(
        comment_id=scenario["ai_comment"].id,
        current_user=scenario["user"],
        session=db_session,
    )


async def test_manual_posting_marks_the_comment_posted(db_session, fake_platform):
    scenario = await _generated_comment_on_platform(db_session, fake_platform)

    response = await _post(scenario, db_session)

    assert (response.status, response.mymoment_comment_id.startswith(f"{scenario['ai_comment'].mymoment_article_id}-")) == (
        "posted",
        True,
    )


async def test_manual_posting_publishes_the_text_with_ai_prefix_and_hide_flag(db_session, fake_platform):
    scenario = await _generated_comment_on_platform(
        db_session, fake_platform, comment_content="<p>Gut gemacht.</p>", is_hidden=True
    )

    await _post(scenario, db_session)

    [posted] = fake_platform.posted_comments
    assert (posted.ref.id, posted.text, posted.hidden, posted.account.id) == (
        scenario["ai_comment"].mymoment_article_id,
        "<p>[Dieser Kommentar stammt von einem KI-ChatBot.]</p><p>Gut gemacht.</p>",
        True,
        scenario["login"].id,
    )


@pytest.mark.parametrize(
    ("given", "expected_status"),
    [
        (lambda platform, article_id: platform.reject_comments(article_id), 422),
        (lambda platform, _: platform.fail("connect", PlatformAuthError("wrong password")), 502),
        (lambda platform, _: platform.fail("post_comment", PlatformUnavailable("timeout")), 503),
    ],
    ids=["rejected", "wrong-credentials", "unavailable"],
)
async def test_manual_posting_reports_platform_errors_and_keeps_the_comment_generated(
    db_session, fake_platform, given, expected_status
):
    scenario = await _generated_comment_on_platform(db_session, fake_platform)
    given(fake_platform, scenario["ai_comment"].mymoment_article_id)

    with pytest.raises(HTTPException) as raised:
        await _post(scenario, db_session)

    await db_session.refresh(scenario["ai_comment"])
    assert (raised.value.status_code, scenario["ai_comment"].status) == (expected_status, "generated")
