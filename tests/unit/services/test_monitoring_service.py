import pytest
from datetime import datetime
from unittest.mock import patch
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.monitoring_service import (
    MonitoringService,
    ProcessStatus,
    ProcessValidationError,
)
from src.platforms import InvalidTarget, PlatformUnavailable
from tests.fixtures.factories.users import create_user
from tests.fixtures.factories.mymoment import create_mymoment_login
from tests.fixtures.factories.prompts import create_user_prompt_template
from tests.fixtures.factories.providers import create_llm_provider
from tests.fixtures.factories.monitoring import create_monitoring_process
from tests.fixtures.factories.comments import (
    create_discovered_ai_comment,
    create_prepared_ai_comment,
    create_generated_ai_comment,
    create_posting_ai_comment,
    create_posted_ai_comment,
    create_failed_ai_comment,
)

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.models.monitoring_process import MonitoringProcess


@pytest.mark.asyncio
async def test_create_process(db_session: AsyncSession):
    """Test creating a monitoring process with associations."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    prompt = await create_user_prompt_template(db_session, user=user)
    provider = await create_llm_provider(db_session, user=user)

    service = MonitoringService(db_session)

    process = await service.create_process(
        user_id=user.id,
        name="Test Process",
        target={"classroom": "4711"},
        login_ids=[login.id],
        prompt_template_ids=[prompt.id],
        llm_provider_id=provider.id,
    )

    assert process.name == "Test Process"
    assert process.status == ProcessStatus.CREATED
    assert len(process.monitoring_process_logins) == 1
    assert process.monitoring_process_logins[0].mymoment_login_id == login.id
    assert len(process.monitoring_process_prompts) == 1
    assert process.monitoring_process_prompts[0].prompt_template_id == prompt.id
    assert process.llm_provider_id == provider.id


@pytest.mark.asyncio
async def test_create_process_limit_exceeded(db_session: AsyncSession):
    """Test concurrent process limit enforcement."""
    user = await create_user(db_session)
    service = MonitoringService(db_session, max_concurrent_processes_per_user=1)

    # Create one running process
    await create_monitoring_process(db_session, user=user, status=ProcessStatus.RUNNING)

    with pytest.raises(
        ProcessValidationError, match="maximum concurrent process limit"
    ):
        await service.create_process(
            user_id=user.id, name="Too Many", target={"classroom": "4711"}
        )


@pytest.mark.asyncio
async def test_update_process(db_session: AsyncSession):
    """Test updating process fields and associations."""
    user = await create_user(db_session)
    login1 = await create_mymoment_login(db_session, user=user, name="Login 1")
    login2 = await create_mymoment_login(db_session, user=user, name="Login 2")
    process = await create_monitoring_process(
        db_session, user=user, mymoment_logins=[login1]
    )

    service = MonitoringService(db_session)

    updated = await service.update_process(
        process.id, user_id=user.id, name="New Name", login_ids=[login2.id]
    )

    # Ensure all changes are flushed to DB
    await db_session.flush()

    # Store ID and expire the object to force a reload of its relationships
    pid = updated.id
    db_session.expire(updated)

    # Reload from DB with associations to avoid MissingGreenlet (lazy loading)
    stmt = (
        select(MonitoringProcess)
        .options(selectinload(MonitoringProcess.monitoring_process_logins))
        .where(MonitoringProcess.id == pid)
    )
    result = await db_session.execute(stmt)
    updated = result.scalar_one()

    assert updated.name == "New Name"
    active_logins = [
        link for link in updated.monitoring_process_logins if link.is_active
    ]
    assert len(active_logins) == 1
    assert active_logins[0].mymoment_login_id == login2.id


@pytest.mark.asyncio
async def test_start_process_triggers_process_scoped_scheduler_delay(
    db_session: AsyncSession,
):
    """Test starting a process dispatches the scheduler in process-scoped mode."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    prompt = await create_user_prompt_template(db_session, user=user)
    provider = await create_llm_provider(db_session, user=user)
    process = await create_monitoring_process(
        db_session,
        user=user,
        mymoment_logins=[login],
        prompt_templates=[prompt],
        llm_provider=provider,
    )

    service = MonitoringService(db_session)

    with patch("src.tasks.scheduler.trigger_monitoring_pipeline.delay") as mock_delay:
        result = await service.start_process(process.id, user_id=user.id)

        assert result["process_id"] == str(process.id)
        assert result["status"] == "scheduled"
        assert result["message"].startswith("Process marked as running.")
        assert result["associated_logins"] == 1
        assert result["associated_prompts"] == 1
        assert result["max_duration_minutes"] == process.max_duration_minutes
        assert result["generate_only"] is process.generate_only
        await db_session.refresh(process)
        assert process.status == ProcessStatus.RUNNING
        assert process.started_at is not None
        assert process.last_activity_at is not None
        assert datetime.fromisoformat(result["started_at"]) == process.started_at
        mock_delay.assert_called_once_with(process_ids=[str(process.id)])
        assert mock_delay.call_args.args == ()


@pytest.mark.asyncio
async def test_stop_process(db_session: AsyncSession):
    """Test stopping a running process."""
    user = await create_user(db_session)
    process = await create_monitoring_process(
        db_session, user=user, status=ProcessStatus.RUNNING
    )

    service = MonitoringService(db_session)

    with patch("src.tasks.worker.celery_app.control.revoke"):
        result = await service.stop_process(process.id, user_id=user.id)

        assert result["status"] == "stopped"
        await db_session.refresh(process)
        assert process.status == ProcessStatus.STOPPED


@pytest.mark.asyncio
async def test_get_pipeline_status(db_session: AsyncSession):
    """Test counting AIComments by status for a process."""
    user = await create_user(db_session)
    process = await create_monitoring_process(db_session, user=user)

    # Create comments in various states
    await create_discovered_ai_comment(
        db_session, user=user, monitoring_process=process
    )
    await create_prepared_ai_comment(db_session, user=user, monitoring_process=process)
    await create_generated_ai_comment(db_session, user=user, monitoring_process=process)
    await create_posting_ai_comment(db_session, user=user, monitoring_process=process)
    await create_posted_ai_comment(db_session, user=user, monitoring_process=process)
    await create_failed_ai_comment(db_session, user=user, monitoring_process=process)
    await create_failed_ai_comment(db_session, user=user, monitoring_process=process)

    service = MonitoringService(db_session)
    status = await service.get_pipeline_status(process.id, user_id=user.id)

    assert status["discovered"] == 1
    assert status["prepared"] == 1
    assert status["generated"] == 1
    assert status["posting"] == 1
    assert status["posted"] == 1
    assert status["failed"] == 2
    assert status["total"] == 7


# --- Target (ADR-0002): checked against the myMoment description, no connection ---

CLASSROOM_ONLY = {"classroom": "4711"}


async def _create_with_target(db_session, target, **kwargs):
    user = await create_user(db_session)
    service = MonitoringService(db_session)
    process = await service.create_process(
        user_id=user.id, name="Ziel", target=target, **kwargs
    )
    return service, user, process


@pytest.mark.asyncio
async def test_create_process_stores_target_and_search(db_session: AsyncSession):
    target = {"classroom": "4711", "category": "7", "arrangement": "12"}

    _, _, process = await _create_with_target(
        db_session, target, search_filter="Rotpanda"
    )

    assert (process.target, process.search_filter) == (target, "Rotpanda")


@pytest.mark.asyncio
async def test_create_process_stores_an_empty_search_term_as_none(
    db_session: AsyncSession,
):
    _, _, process = await _create_with_target(
        db_session, CLASSROOM_ONLY, search_filter=""
    )

    assert process.search_filter is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("target", "message"),
    [
        ({"classroom": "4711", "tab": "4711"}, "Unbekannte Angaben im Ziel: tab"),
        ({"category": "7"}, "classroom"),
        ({"classroom": "alle"}, "alle"),
        ({"classroom": "4711", "category": ""}, "category"),
    ],
    ids=["unknown-key", "missing-classroom", "classroom-alle", "empty-value"],
)
async def test_create_process_rejects_an_invalid_target(
    db_session: AsyncSession, target, message
):
    user = await create_user(db_session)

    with pytest.raises(InvalidTarget, match=message):
        await MonitoringService(db_session).create_process(
            user_id=user.id, name="Ziel", target=target
        )


@pytest.mark.asyncio
async def test_create_process_saves_without_a_platform_connection(
    db_session: AsyncSession, fake_platform
):
    fake_platform.fail("connect", PlatformUnavailable("myMoment down"))

    _, _, process = await _create_with_target(db_session, CLASSROOM_ONLY)

    assert (process.target, fake_platform.connected_accounts) == (CLASSROOM_ONLY, [])


@pytest.mark.asyncio
async def test_update_process_replaces_the_target_as_a_whole(db_session: AsyncSession):
    service, user, process = await _create_with_target(
        db_session, {"classroom": "4711", "category": "7", "arrangement": "12"}
    )

    updated = await service.update_process(
        process.id, user_id=user.id, target={"classroom": "82"}
    )

    assert updated.target == {"classroom": "82"}


@pytest.mark.asyncio
async def test_update_process_without_target_keeps_it(db_session: AsyncSession):
    service, user, process = await _create_with_target(
        db_session, {"classroom": "4711", "category": "7"}
    )

    updated = await service.update_process(process.id, user_id=user.id, name="Neu")

    assert updated.target == {"classroom": "4711", "category": "7"}


@pytest.mark.asyncio
async def test_update_process_rejects_an_invalid_target_and_keeps_the_stored_one(
    db_session: AsyncSession,
):
    service, user, process = await _create_with_target(db_session, CLASSROOM_ONLY)

    with pytest.raises(InvalidTarget, match="alle"):
        await service.update_process(
            process.id, user_id=user.id, target={"classroom": "alle"}
        )

    status = await service.get_process_status(process.id, user.id)
    assert status["target"] == CLASSROOM_ONLY


@pytest.mark.asyncio
async def test_update_process_clears_the_search_term(db_session: AsyncSession):
    service, user, process = await _create_with_target(
        db_session, CLASSROOM_ONLY, search_filter="Rotpanda"
    )

    updated = await service.update_process(
        process.id, user_id=user.id, search_filter=""
    )

    assert updated.search_filter is None
