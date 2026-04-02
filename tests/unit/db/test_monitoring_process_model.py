"""DB-backed tests for the current `MonitoringProcess` model behavior."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tests.fixtures.factories import (
    create_llm_provider,
    create_monitoring_process,
    create_mymoment_login,
    create_system_prompt_template,
    create_user,
    create_user_prompt_template,
)


pytestmark = pytest.mark.database


async def _create_process_bundle(db_session):
    user = await create_user(db_session)
    provider = await create_llm_provider(db_session, user=user)
    login_primary = await create_mymoment_login(db_session, user=user)
    login_secondary = await create_mymoment_login(db_session, user=user)
    prompt_primary = await create_user_prompt_template(db_session, user=user)
    prompt_secondary = await create_system_prompt_template(db_session)
    process = await create_monitoring_process(
        db_session,
        user=user,
        llm_provider=provider,
        mymoment_logins=[login_primary, login_secondary],
        prompt_templates=[prompt_primary, prompt_secondary],
        prompt_weights={prompt_secondary.id: 2.5},
        category_filter=7,
        task_filter=13,
        search_filter="revision",
        tab_filter="class-a",
        sort_option="recent",
    )
    await db_session.refresh(process, ["monitoring_process_logins", "monitoring_process_prompts"])
    return {
        "user": user,
        "provider": provider,
        "logins": [login_primary, login_secondary],
        "prompts": [prompt_primary, prompt_secondary],
        "process": process,
    }


async def test_status_helpers_and_timestamps_reflect_current_process_state(db_session):
    user = await create_user(db_session)
    created_process = await create_monitoring_process(db_session, user=user, status="created")
    running_process = await create_monitoring_process(
        db_session,
        user=user,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    failed_process = await create_monitoring_process(db_session, user=user, status="failed")

    assert created_process.created_at is not None
    assert created_process.updated_at is not None
    assert created_process.last_activity_at is not None
    assert created_process.can_start is True
    assert created_process.is_running is False
    assert created_process.error_message is None
    assert created_process.expires_at is None

    assert running_process.is_running is True
    assert running_process.can_start is False

    assert failed_process.error_message == "Process failed"


async def test_duration_exceeded_and_expires_at_handle_running_datetimes(db_session):
    user = await create_user(db_session)
    aware_started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    aware_process = await create_monitoring_process(
        db_session,
        user=user,
        status="running",
        started_at=aware_started_at,
        max_duration_minutes=60,
    )
    naive_process = await create_monitoring_process(
        db_session,
        user=user,
        status="running",
        started_at=datetime.utcnow() - timedelta(minutes=90),
        max_duration_minutes=60,
    )

    assert aware_process.duration_exceeded is False
    assert aware_process.expires_at == aware_started_at + timedelta(minutes=60)
    assert naive_process.duration_exceeded is True


async def test_target_filters_and_association_helpers_only_expose_active_links(db_session):
    bundle = await _create_process_bundle(db_session)
    process = bundle["process"]
    login_primary, login_secondary = bundle["logins"]
    prompt_primary, prompt_secondary = bundle["prompts"]
    login_link_map = {l.mymoment_login_id: l for l in process.monitoring_process_logins}
    login_link_primary = login_link_map[login_primary.id]
    login_link_secondary = login_link_map[login_secondary.id]
    prompt_link_map = {p.prompt_template_id: p for p in process.monitoring_process_prompts}
    prompt_link_primary = prompt_link_map[prompt_primary.id]
    prompt_link_secondary = prompt_link_map[prompt_secondary.id]

    assert process.target_filters == {
        "category": 7,
        "task": 13,
        "search": "revision",
        "tab": "class-a",
        "sort": "recent",
    }
    assert login_link_primary.is_valid_association is True
    assert prompt_link_secondary.effective_weight == 2.5

    login_link_secondary.is_active = False
    prompt_link_secondary.is_active = False

    assert process.mymoment_login_ids == [login_primary.id]
    assert process.prompt_template_ids == [prompt_primary.id]
    assert process.get_associated_logins() == [login_primary]
    assert process.get_associated_prompts() == [prompt_primary]
    assert prompt_link_secondary.effective_weight == 0.0
