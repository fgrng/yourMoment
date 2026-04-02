"""DB-backed tests for the current `AIComment` model behavior."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from src.models.ai_comment import AIComment
from src.config.settings import get_settings
from tests.fixtures.assertions import assert_ai_comment_state
from tests.fixtures.factories import (
    create_discovered_ai_comment,
    create_failed_ai_comment,
    create_generated_ai_comment,
    create_llm_provider,
    create_monitoring_process,
    create_mymoment_login,
    create_posted_ai_comment,
    create_prepared_ai_comment,
    create_user,
    create_user_prompt_template,
)


pytestmark = pytest.mark.database


async def _create_comment_bundle(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    prompt = await create_user_prompt_template(db_session, user=user)
    provider = await create_llm_provider(db_session, user=user)
    process = await create_monitoring_process(
        db_session,
        user=user,
        llm_provider=provider,
        mymoment_logins=[login],
        prompt_templates=[prompt],
        status="running",
        started_at=datetime.utcnow(),
    )
    return {
        "user": user,
        "login": login,
        "prompt": prompt,
        "provider": provider,
        "process": process,
    }


async def test_pipeline_state_factories_cover_current_status_helpers(db_session):
    bundle = await _create_comment_bundle(db_session)

    discovered = await create_discovered_ai_comment(
        db_session,
        user=bundle["user"],
        monitoring_process=bundle["process"],
    )
    prepared = await create_prepared_ai_comment(
        db_session,
        user=bundle["user"],
        monitoring_process=bundle["process"],
    )
    generated = await create_generated_ai_comment(
        db_session,
        user=bundle["user"],
        monitoring_process=bundle["process"],
        prompt_template=bundle["prompt"],
        llm_provider=bundle["provider"],
        article_title="X" * 150,
    )
    posted = await create_posted_ai_comment(
        db_session,
        user=bundle["user"],
        monitoring_process=bundle["process"],
        mymoment_login=bundle["login"],
        prompt_template=bundle["prompt"],
        llm_provider=bundle["provider"],
    )
    failed = await create_failed_ai_comment(
        db_session,
        user=bundle["user"],
        monitoring_process=bundle["process"],
    )

    assert_ai_comment_state(discovered, "discovered")
    assert_ai_comment_state(prepared, "prepared")
    assert_ai_comment_state(generated, "generated")
    assert_ai_comment_state(posted, "posted")
    assert_ai_comment_state(failed, "failed")

    assert discovered.is_discovered is True
    assert prepared.is_prepared is True
    assert generated.is_generated is True
    assert posted.is_posted is True
    assert failed.is_failed is True
    assert discovered.short_content == "(Comment not yet generated)"
    assert generated.short_title.endswith("...")
    assert len(generated.short_title) == 100
    assert posted.posting_status_display == "Posted to myMoment"
    assert failed.posting_status_display == "Posting failed"


async def test_ai_prefix_helpers_and_requirement_validation_use_current_rules(db_session):
    bundle = await _create_comment_bundle(db_session)
    prefix = get_settings().monitoring.AI_COMMENT_PREFIX

    posted = await create_posted_ai_comment(
        db_session,
        user=bundle["user"],
        monitoring_process=bundle["process"],
        mymoment_login=bundle["login"],
        prompt_template=bundle["prompt"],
        llm_provider=bundle["provider"],
    )
    invalid_prefix = await create_posted_ai_comment(
        db_session,
        user=bundle["user"],
        monitoring_process=bundle["process"],
        mymoment_login=bundle["login"],
        prompt_template=bundle["prompt"],
        llm_provider=bundle["provider"],
        mymoment_article_id="invalid-prefix-article",
        comment_content="<p>No prefix here.</p>",
    )

    assert posted.has_valid_ai_prefix is True
    assert posted.validate_requirements()["is_valid"] is True
    assert invalid_prefix.has_valid_ai_prefix is False
    assert invalid_prefix.validate_requirements()["has_required_prefix"] is False
    assert invalid_prefix.validate_requirements()["is_valid"] is False

    plain_text = AIComment.apply_ai_prefix("Hello world.")
    html_text = AIComment.apply_ai_prefix("<p>Hello world.</p>")
    assert plain_text.startswith(prefix)
    assert html_text.startswith(f"<p>{prefix}</p>")
    assert AIComment.apply_ai_prefix(plain_text) == plain_text


async def test_mark_as_posted_and_failed_update_comment_state_and_timestamps(db_session):
    bundle = await _create_comment_bundle(db_session)
    comment = await create_generated_ai_comment(
        db_session,
        user=bundle["user"],
        monitoring_process=bundle["process"],
        mymoment_login=bundle["login"],
        prompt_template=bundle["prompt"],
        llm_provider=bundle["provider"],
    )

    comment.error_message = "old error"

    before_post = datetime.utcnow()
    comment.mark_as_posted("comment-123")
    assert comment.status == "posted"
    assert comment.mymoment_comment_id == "comment-123"
    assert comment.posted_at is not None
    assert comment.posted_at >= before_post
    assert comment.error_message is None

    before_failure = datetime.utcnow()
    comment.mark_as_failed("network timeout")
    assert comment.status == "failed"
    assert comment.error_message == "network timeout"
    assert comment.retry_count == 1
    assert comment.failed_at is not None
    assert comment.failed_at >= before_failure


async def test_snapshot_dicts_and_uniqueness_constraint_follow_current_schema(db_session):
    bundle = await _create_comment_bundle(db_session)
    generated = await create_generated_ai_comment(
        db_session,
        user=bundle["user"],
        monitoring_process=bundle["process"],
        mymoment_login=bundle["login"],
        prompt_template=bundle["prompt"],
        llm_provider=bundle["provider"],
        mymoment_article_id="article-unique-shape",
    )

    snapshot = generated.to_article_snapshot_dict()
    assert snapshot["mymoment_article_id"] == "article-unique-shape"
    assert snapshot["title"] == generated.article_title
    assert snapshot["content"] == generated.article_content
    assert snapshot["scraped_at"] == generated.article_scraped_at

    comment_dict = generated.to_comment_dict()
    assert comment_dict["id"] == generated.id
    assert comment_dict["content"] == generated.comment_content
    assert comment_dict["status"] == "generated"
    assert comment_dict["is_posted"] is False
    assert comment_dict["ai_model_name"] == generated.ai_model_name

    await create_discovered_ai_comment(
        db_session,
        user=bundle["user"],
        monitoring_process=bundle["process"],
        mymoment_login=bundle["login"],
        prompt_template=bundle["prompt"],
        mymoment_article_id="duplicate-article",
    )
    with pytest.raises(IntegrityError):
        await create_discovered_ai_comment(
            db_session,
            user=bundle["user"],
            monitoring_process=bundle["process"],
            mymoment_login=bundle["login"],
            prompt_template=bundle["prompt"],
            mymoment_article_id="duplicate-article",
        )
