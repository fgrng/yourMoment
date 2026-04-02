import pytest
import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.services.student_backup_service import (
    StudentBackupService,
    StudentBackupValidationError,
    StudentBackupLimitError,
)
from src.models.article_version import ArticleVersion
from src.models.tracked_student import TrackedStudent
from tests.fixtures.factories.users import create_user
from tests.fixtures.factories.mymoment import create_mymoment_login
from tests.fixtures.factories.student_backup import (
    create_tracked_student,
    create_article_version,
)

@pytest.mark.asyncio
async def test_create_tracked_student(db_session: AsyncSession):
    """Test creating a tracked student with admin login validation."""
    user = await create_user(db_session)
    admin_login = await create_mymoment_login(db_session, user=user, is_admin=True)
    
    service = StudentBackupService(db_session)
    
    student = await service.create_tracked_student(
        user_id=user.id,
        mymoment_student_id=12345,
        mymoment_login_id=admin_login.id,
        display_name="John Doe"
    )
    
    assert student.mymoment_student_id == 12345
    assert student.display_name == "John Doe"
    assert student.user_id == user.id

@pytest.mark.asyncio
async def test_create_tracked_student_non_admin_denied(db_session: AsyncSession):
    """Test that non-admin logins are rejected for tracking."""
    user = await create_user(db_session)
    user_login = await create_mymoment_login(db_session, user=user, is_admin=False)
    
    service = StudentBackupService(db_session)
    
    with pytest.raises(StudentBackupValidationError, match="not an admin login"):
        await service.create_tracked_student(
            user_id=user.id,
            mymoment_student_id=12345,
            mymoment_login_id=user_login.id
        )

@pytest.mark.asyncio
async def test_create_article_version_changes_only(db_session: AsyncSession):
    """Test that duplicate versions are skipped when content is unchanged."""
    user = await create_user(db_session)
    admin_login = await create_mymoment_login(db_session, user=user, is_admin=True)
    student = await create_tracked_student(db_session, user=user, mymoment_login=admin_login)
    
    service = StudentBackupService(db_session)
    # Ensure setting is enabled for test
    service.settings.STUDENT_BACKUP_CONTENT_CHANGES_ONLY = True
    
    # First version
    v1 = await service.create_article_version(
        user_id=user.id,
        tracked_student_id=student.id,
        mymoment_article_id=999,
        article_content="Initial content",
        article_title="Original Title"
    )
    assert v1 is not None
    assert v1.version_number == 1
    
    # Identical version - should return None
    v2 = await service.create_article_version(
        user_id=user.id,
        tracked_student_id=student.id,
        mymoment_article_id=999,
        article_content="Initial content",
        article_title="Original Title"
    )
    assert v2 is None
    
    # Changed version - should create v2
    v3 = await service.create_article_version(
        user_id=user.id,
        tracked_student_id=student.id,
        mymoment_article_id=999,
        article_content="Changed content",
        article_title="Original Title"
    )
    assert v3 is not None
    assert v3.version_number == 2

@pytest.mark.asyncio
async def test_enforce_version_limit(db_session: AsyncSession):
    """Test soft-deleting old versions when limit is reached."""
    user = await create_user(db_session)
    admin_login = await create_mymoment_login(db_session, user=user, is_admin=True)
    student = await create_tracked_student(db_session, user=user, mymoment_login=admin_login)
    
    service = StudentBackupService(db_session)
    # Set a low limit for testing
    service.settings.STUDENT_BACKUP_MAX_VERSIONS_PER_ARTICLE = 2
    
    # Create 3 versions (with different content to bypass changes-only check)
    await service.create_article_version(user_id=user.id, tracked_student_id=student.id, mymoment_article_id=1, article_content="v1")
    await service.create_article_version(user_id=user.id, tracked_student_id=student.id, mymoment_article_id=1, article_content="v2")
    await service.create_article_version(user_id=user.id, tracked_student_id=student.id, mymoment_article_id=1, article_content="v3")
    
    # Verify version 1 is inactive
    stmt = select(ArticleVersion).where(
        ArticleVersion.tracked_student_id == student.id,
        ArticleVersion.version_number == 1
    )
    result = await db_session.execute(stmt)
    v1 = result.scalar_one()
    assert v1.is_active is False
    
    # Versions 2 and 3 should be active
    stmt = select(ArticleVersion).where(
        ArticleVersion.tracked_student_id == student.id,
        ArticleVersion.is_active == True
    )
    result = await db_session.execute(stmt)
    active = result.scalars().all()
    assert len(active) == 2
    version_numbers = {v.version_number for v in active}
    assert version_numbers == {2, 3}

@pytest.mark.asyncio
async def test_get_articles_summary(db_session: AsyncSession):
    """Test the summary aggregation per article."""
    user = await create_user(db_session)
    admin_login = await create_mymoment_login(db_session, user=user, is_admin=True)
    student = await create_tracked_student(db_session, user=user, mymoment_login=admin_login)
    
    # Article 1: 2 versions
    await create_article_version(db_session, user=user, tracked_student=student, mymoment_article_id=1, version_number=1, article_title="A1 V1")
    await create_article_version(db_session, user=user, tracked_student=student, mymoment_article_id=1, version_number=2, article_title="A1 V2")
    
    # Article 2: 1 version
    await create_article_version(db_session, user=user, tracked_student=student, mymoment_article_id=2, version_number=1, article_title="A2 V1")
    
    service = StudentBackupService(db_session)
    summary = await service.get_articles_summary(student.id, user.id)
    
    assert len(summary) == 2
    # Summary should be ordered by latest scraped_at desc, but IDs are 1 and 2
    s1 = next(s for s in summary if s["mymoment_article_id"] == 1)
    assert s1["version_count"] == 2
    assert s1["article_title"] == "A1 V2"  # Latest title
    
    s2 = next(s for s in summary if s["mymoment_article_id"] == 2)
    assert s2["version_count"] == 1
