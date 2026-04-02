import pytest
import uuid
from unittest.mock import patch, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.monitoring_service import (
    MonitoringService,
    ProcessStatus,
    ProcessValidationError,
    ProcessOperationError,
)
from tests.fixtures.factories.users import create_user
from tests.fixtures.factories.mymoment import create_mymoment_login
from tests.fixtures.factories.prompts import create_user_prompt_template, create_system_prompt_template
from tests.fixtures.factories.providers import create_llm_provider
from tests.fixtures.factories.monitoring import create_monitoring_process
from tests.fixtures.factories.comments import (
    create_discovered_ai_comment,
    create_prepared_ai_comment,
    create_generated_ai_comment,
    create_posted_ai_comment,
    create_failed_ai_comment,
)

from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from src.models.monitoring_process import MonitoringProcess
from src.models.monitoring_process_login import MonitoringProcessLogin

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
        login_ids=[login.id],
        prompt_template_ids=[prompt.id],
        llm_provider_id=provider.id
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
    
    with pytest.raises(ProcessValidationError, match="maximum concurrent process limit"):
        await service.create_process(user_id=user.id, name="Too Many")

@pytest.mark.asyncio
async def test_update_process(db_session: AsyncSession):
    """Test updating process fields and associations."""
    user = await create_user(db_session)
    login1 = await create_mymoment_login(db_session, user=user, name="Login 1")
    login2 = await create_mymoment_login(db_session, user=user, name="Login 2")
    process = await create_monitoring_process(db_session, user=user, mymoment_logins=[login1])
    
    service = MonitoringService(db_session)
    
    updated = await service.update_process(
        process.id,
        user_id=user.id,
        name="New Name",
        login_ids=[login2.id]
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
    active_logins = [l for l in updated.monitoring_process_logins if l.is_active]
    assert len(active_logins) == 1
    assert active_logins[0].mymoment_login_id == login2.id

@pytest.mark.asyncio
async def test_start_process(db_session: AsyncSession):
    """Test starting a process triggers scheduler."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    prompt = await create_user_prompt_template(db_session, user=user)
    provider = await create_llm_provider(db_session, user=user)
    process = await create_monitoring_process(
        db_session, 
        user=user, 
        mymoment_logins=[login], 
        prompt_templates=[prompt],
        llm_provider=provider
    )
    
    service = MonitoringService(db_session)
    
    with patch("src.tasks.scheduler.trigger_monitoring_pipeline.delay") as mock_delay:
        result = await service.start_process(process.id, user_id=user.id)
        
        assert result["status"] == "scheduled"
        await db_session.refresh(process)
        assert process.status == ProcessStatus.RUNNING
        mock_delay.assert_called_once_with(force_immediate=True)

@pytest.mark.asyncio
async def test_stop_process(db_session: AsyncSession):
    """Test stopping a running process."""
    user = await create_user(db_session)
    process = await create_monitoring_process(db_session, user=user, status=ProcessStatus.RUNNING)
    
    service = MonitoringService(db_session)
    
    with patch("src.tasks.worker.celery_app.control.revoke") as mock_revoke:
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
    await create_discovered_ai_comment(db_session, user=user, monitoring_process=process)
    await create_prepared_ai_comment(db_session, user=user, monitoring_process=process)
    await create_generated_ai_comment(db_session, user=user, monitoring_process=process)
    await create_posted_ai_comment(db_session, user=user, monitoring_process=process)
    await create_failed_ai_comment(db_session, user=user, monitoring_process=process)
    await create_failed_ai_comment(db_session, user=user, monitoring_process=process)
    
    service = MonitoringService(db_session)
    status = await service.get_pipeline_status(process.id, user_id=user.id)
    
    assert status["discovered"] == 1
    assert status["prepared"] == 1
    assert status["generated"] == 1
    assert status["posted"] == 1
    assert status["failed"] == 2
    assert status["total"] == 6
