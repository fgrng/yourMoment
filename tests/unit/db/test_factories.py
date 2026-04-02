"""Foundation checks for DB-backed fixture factories."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from src.models.monitoring_process_login import MonitoringProcessLogin
from src.models.monitoring_process_prompt import MonitoringProcessPrompt
from tests.fixtures.assertions import (
    assert_ai_comment_state,
    assert_api_key_round_trip,
    assert_mymoment_credentials_round_trip,
    assert_owned_by,
    assert_session_data_round_trip,
)
from tests.fixtures.factories import (
    create_article_version,
    create_discovered_ai_comment,
    create_failed_ai_comment,
    create_generated_ai_comment,
    create_llm_provider,
    create_monitoring_process,
    create_mymoment_login,
    create_mymoment_session,
    create_posted_ai_comment,
    create_prepared_ai_comment,
    create_tracked_student,
    create_user,
    create_user_prompt_template,
)


pytestmark = pytest.mark.database


async def test_encrypted_factories_persist_valid_defaults(db_session):
    user = await create_user(db_session)
    login = await create_mymoment_login(
        db_session,
        user=user,
        username="fixture-user",
        password="FixturePass-1!",
    )
    provider = await create_llm_provider(
        db_session,
        user=user,
        api_key="sk-fixture-provider",
    )
    session_record = await create_mymoment_session(
        db_session,
        mymoment_login=login,
        session_data={"csrftoken": "fixture-token"},
    )

    assert_owned_by(login, user)
    assert_owned_by(provider, user)
    assert_mymoment_credentials_round_trip(
        login,
        username="fixture-user",
        password="FixturePass-1!",
    )
    assert_api_key_round_trip(provider, api_key="sk-fixture-provider")
    assert_session_data_round_trip(
        session_record,
        expected_data={"csrftoken": "fixture-token"},
    )


async def test_monitoring_process_factory_uses_junction_rows(db_session):
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
    )

    login_links = (
        await db_session.execute(
            select(MonitoringProcessLogin).where(
                MonitoringProcessLogin.monitoring_process_id == process.id
            )
        )
    ).scalars().all()
    prompt_links = (
        await db_session.execute(
            select(MonitoringProcessPrompt).where(
                MonitoringProcessPrompt.monitoring_process_id == process.id
            )
        )
    ).scalars().all()

    assert len(login_links) == 1
    assert len(prompt_links) == 1
    assert login_links[0].mymoment_login_id == login.id
    assert prompt_links[0].prompt_template_id == prompt.id


async def test_ai_comment_factories_cover_pipeline_variants(db_session):
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
    )

    discovered = await create_discovered_ai_comment(
        db_session,
        user=user,
        monitoring_process=process,
    )
    prepared = await create_prepared_ai_comment(
        db_session,
        user=user,
        monitoring_process=process,
    )
    generated = await create_generated_ai_comment(
        db_session,
        user=user,
        monitoring_process=process,
        prompt_template=prompt,
        llm_provider=provider,
    )
    posted = await create_posted_ai_comment(
        db_session,
        user=user,
        monitoring_process=process,
        mymoment_login=login,
        prompt_template=prompt,
        llm_provider=provider,
    )
    failed = await create_failed_ai_comment(
        db_session,
        user=user,
        monitoring_process=process,
    )

    assert_ai_comment_state(discovered, "discovered")
    assert_ai_comment_state(prepared, "prepared")
    assert_ai_comment_state(generated, "generated")
    assert_ai_comment_state(posted, "posted")
    assert_ai_comment_state(failed, "failed")


async def test_student_backup_factories_build_versions_with_hashes(db_session):
    user = await create_user(db_session)
    admin_login = await create_mymoment_login(db_session, user=user, is_admin=True)
    tracked_student = await create_tracked_student(
        db_session,
        user=user,
        mymoment_login=admin_login,
    )
    version = await create_article_version(
        db_session,
        user=user,
        tracked_student=tracked_student,
        content="Versioned content for hashing.",
    )

    assert_owned_by(tracked_student, user)
    assert_owned_by(version, user)
    assert version.content_hash == version.compute_content_hash("Versioned content for hashing.")
