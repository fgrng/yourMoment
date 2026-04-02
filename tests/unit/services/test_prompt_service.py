import pytest
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.prompt_service import (
    PromptService,
    TemplateValidationError,
    TemplateNotFoundError,
    TemplateAccessError,
)
from src.api.schemas import PromptTemplateCreate, PromptTemplateUpdate
from tests.fixtures.factories.users import create_user
from tests.fixtures.factories.prompts import (
    create_user_prompt_template,
    create_system_prompt_template,
)

@pytest.mark.asyncio
async def test_create_user_template(db_session: AsyncSession):
    """Test creating a user-owned template."""
    user = await create_user(db_session)
    service = PromptService(db_session)
    
    request = PromptTemplateCreate(
        name="My Test Template",
        description="Test description",
        system_prompt="You are a helpful assistant.",
        user_prompt_template="Read {article_title} and respond."
    )
    
    template = await service.create_template(request, user_id=user.id)
    
    assert template.name == "My Test Template"
    assert template.user_id == user.id
    assert template.category == "USER"
    assert template.is_active is True

@pytest.mark.asyncio
async def test_create_system_template(db_session: AsyncSession):
    """Test creating a system template (no user_id)."""
    service = PromptService(db_session)
    
    request = PromptTemplateCreate(
        name="System Template",
        system_prompt="System instructions here.",
        user_prompt_template="Analyze {article_content}."
    )
    
    template = await service.create_template(request, user_id=None)
    
    assert template.name == "System Template"
    assert template.user_id is None
    assert template.category == "SYSTEM"

@pytest.mark.asyncio
async def test_create_template_validation_error(db_session: AsyncSession):
    """Test validation failure during creation."""
    service = PromptService(db_session)
    
    # Valid Pydantic request but invalid placeholders for service
    request = PromptTemplateCreate(
        name="Invalid Placeholders",
        system_prompt="You are a helpful assistant.",
        user_prompt_template="Read {article_title} and use {invalid_placeholder}."
    )
    
    with pytest.raises(TemplateValidationError, match="Unsupported placeholders"):
        await service.create_template(request)

@pytest.mark.asyncio
async def test_get_template_access_control(db_session: AsyncSession):
    """Test access control in get_template."""
    user1 = await create_user(db_session)
    user2 = await create_user(db_session)
    
    service = PromptService(db_session)
    
    # User 1's template
    t1 = await create_user_prompt_template(db_session, user=user1)
    # System template
    ts = await create_system_prompt_template(db_session)
    
    # User 1 can get their own template
    fetched = await service.get_template(t1.id, user_id=user1.id)
    assert fetched.id == t1.id
    
    # User 1 can get system template
    fetched = await service.get_template(ts.id, user_id=user1.id)
    assert fetched.id == ts.id
    
    # User 2 cannot get User 1's template
    with pytest.raises(TemplateNotFoundError):
        await service.get_template(t1.id, user_id=user2.id)
    
    # Nobody can get User 1's template without a user_id (only SYSTEM allowed then)
    with pytest.raises(TemplateNotFoundError):
        await service.get_template(t1.id, user_id=None)

@pytest.mark.asyncio
async def test_list_templates(db_session: AsyncSession):
    """Test listing and filtering templates."""
    user = await create_user(db_session)
    other_user = await create_user(db_session)
    
    # Create 2 user templates
    await create_user_prompt_template(db_session, user=user, name="User T1")
    await create_user_prompt_template(db_session, user=user, name="User T2")
    # Create 1 system template
    await create_system_prompt_template(db_session, name="System T1")
    # Create 1 other user's template
    await create_user_prompt_template(db_session, user=other_user, name="Other User T1")
    
    service = PromptService(db_session)
    
    # List for user (should see theirs + system)
    templates = await service.list_templates(user_id=user.id)
    assert len(templates) == 3
    names = {t.name for t in templates}
    assert "User T1" in names
    assert "User T2" in names
    assert "System T1" in names
    assert "Other User T1" not in names
    
    # List only system templates
    templates = await service.list_templates(user_id=user.id, category="SYSTEM")
    assert len(templates) == 1
    assert templates[0].name == "System T1"

@pytest.mark.asyncio
async def test_update_template(db_session: AsyncSession):
    """Test updating a template."""
    user = await create_user(db_session)
    template = await create_user_prompt_template(db_session, user=user)
    
    service = PromptService(db_session)
    
    update_request = PromptTemplateUpdate(
        name="Updated Name",
        description="Updated Description"
    )
    
    updated = await service.update_template(template.id, update_request, user_id=user.id)
    assert updated.name == "Updated Name"
    assert updated.description == "Updated Description"

@pytest.mark.asyncio
async def test_update_system_template_denied(db_session: AsyncSession):
    """Test that system templates cannot be updated via service."""
    user = await create_user(db_session)
    template = await create_system_prompt_template(db_session)
    
    service = PromptService(db_session)
    
    update_request = PromptTemplateUpdate(name="Try Update")
    
    with pytest.raises(TemplateAccessError, match="Cannot modify system templates"):
        await service.update_template(template.id, update_request, user_id=user.id)

@pytest.mark.asyncio
async def test_delete_template(db_session: AsyncSession):
    """Test soft deleting a template."""
    user = await create_user(db_session)
    template = await create_user_prompt_template(db_session, user=user)
    
    service = PromptService(db_session)
    
    success = await service.delete_template(template.id, user_id=user.id)
    assert success is True
    
    # Verify it's inactive
    await db_session.refresh(template)
    assert template.is_active is False

@pytest.mark.asyncio
async def test_validate_template_placeholders(db_session: AsyncSession):
    """Test placeholder validation logic."""
    service = PromptService(db_session)
    
    # Valid
    result = await service.validate_template(
        system_prompt="Valid system prompt here.",
        user_prompt_template="Valid {article_title} template."
    )
    assert result.is_valid is True
    assert "article_title" in result.placeholders_used
    
    # Unsupported placeholder
    result = await service.validate_template(
        system_prompt="Valid system prompt here.",
        user_prompt_template="Invalid {non_existent} template."
    )
    assert result.is_valid is False
    assert any("Unsupported placeholders" in e for e in result.errors)

@pytest.mark.asyncio
async def test_render_template(db_session: AsyncSession):
    """Test template rendering with context."""
    user = await create_user(db_session)
    template = await create_user_prompt_template(
        db_session, 
        user=user,
        user_prompt_template="Hello {article_author}, I like {article_title}."
    )
    
    service = PromptService(db_session)
    
    context = {
        "article_author": "Alice",
        "article_title": "Wonderland"
    }
    
    result = await service.render_template(template.id, context, user_id=user.id)
    assert result.rendered_prompt == "Hello Alice, I like Wonderland."
    assert not result.render_errors

@pytest.mark.asyncio
async def test_get_default_system_template(db_session: AsyncSession):
    """Test getting or creating the default system template."""
    service = PromptService(db_session)
    
    # Should create it
    template = await service.get_default_system_template()
    assert template.category == "SYSTEM"
    assert template.name == "Default AI Comment Generator"
    
    # Should get existing one next time
    template2 = await service.get_default_system_template()
    assert template.id == template2.id
