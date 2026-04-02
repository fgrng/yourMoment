import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.comment_service import (
    ensure_html_paragraphs,
    validate_comment,
    CommentService,
)
from src.config.settings import get_settings
from tests.fixtures.factories.users import create_user
from tests.fixtures.factories.comments import (
    create_generated_ai_comment,
    create_posted_ai_comment,
    create_failed_ai_comment,
)

def test_ensure_html_paragraphs():
    """Test HTML paragraph normalization."""
    # Plain text
    assert ensure_html_paragraphs("Hello world") == "<p>Hello world</p>"
    
    # Already HTML
    assert ensure_html_paragraphs("<p>Already HTML</p>") == "<p>Already HTML</p>"
    
    # Multiple lines
    text = "Line 1\n\nLine 2"
    assert ensure_html_paragraphs(text) == "<p>Line 1</p><p>Line 2</p>"
    
    # Single newline
    assert ensure_html_paragraphs("Line 1\nLine 2") == "<p>Line 1</p><p>Line 2</p>"

def test_validate_comment():
    """Test comment validation logic."""
    settings = get_settings()
    prefix = settings.monitoring.AI_COMMENT_PREFIX
    
    # Valid comment
    valid_content = f"<p>{prefix}</p><p>This is a valid and constructive comment for the article.</p>"
    result = validate_comment(valid_content)
    assert result["is_valid"] is True
    
    # Missing prefix
    invalid_content = "<p>Nice article!</p>"
    result = validate_comment(invalid_content)
    assert result["is_valid"] is False
    assert "Missing required German AI prefix" in result["errors"]
    
    # Too short
    short_content = f"{prefix} short"
    result = validate_comment(short_content, min_length=50)
    assert result["is_valid"] is False
    assert any("Comment too short" in e for e in result["errors"])

@pytest.mark.asyncio
async def test_get_user_comment_statistics(db_session: AsyncSession):
    """Test statistics aggregation for a user."""
    user = await create_user(db_session)
    
    # Create 1 posted, 1 generated, 1 failed
    await create_posted_ai_comment(db_session, user=user, generation_time_ms=1000)
    await create_generated_ai_comment(db_session, user=user, generation_time_ms=2000)
    await create_failed_ai_comment(db_session, user=user)
    
    service = CommentService(db_session)
    stats = await service.get_user_comment_statistics(user.id)
    
    assert stats["total_comments"] == 3
    assert stats["posted_comments"] == 1
    assert stats["generated_comments"] == 1
    assert stats["failed_comments"] == 1
    assert stats["avg_generation_time_ms"] == 1500.0
    assert stats["success_rate"] == pytest.approx(33.33, 0.01)
