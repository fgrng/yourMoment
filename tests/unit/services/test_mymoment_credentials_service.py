import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.mymoment_credentials_service import (
    MyMomentCredentialsService,
    MyMomentCredentialsValidationError,
)
from tests.fixtures.factories.users import create_user
from tests.fixtures.factories.mymoment import create_mymoment_login

@pytest.mark.asyncio
async def test_create_credentials(db_session: AsyncSession):
    """Test creating credentials with encryption."""
    user = await create_user(db_session)
    service = MyMomentCredentialsService(db_session)
    
    login = await service.create_credentials(
        user_id=user.id,
        username="testuser",
        password="testpassword",
        name="My Login"
    )
    
    assert login.name == "My Login"
    assert login.user_id == user.id
    assert login.is_active is True
    
    # Verify encryption/decryption works
    username, password = login.get_credentials()
    assert username == "testuser"
    assert password == "testpassword"

@pytest.mark.asyncio
async def test_create_credentials_duplicate_name(db_session: AsyncSession):
    """Test uniqueness of credential names per user."""
    user = await create_user(db_session)
    await create_mymoment_login(db_session, user=user, name="Duplicate")
    
    service = MyMomentCredentialsService(db_session)
    
    with pytest.raises(MyMomentCredentialsValidationError, match="already exist"):
        await service.create_credentials(
            user_id=user.id,
            username="other",
            password="pwd",
            name="Duplicate"
        )

@pytest.mark.asyncio
async def test_get_credentials_by_id_access_control(db_session: AsyncSession):
    """Test access control for credentials retrieval."""
    user1 = await create_user(db_session)
    user2 = await create_user(db_session)
    
    login1 = await create_mymoment_login(db_session, user=user1)
    
    service = MyMomentCredentialsService(db_session)
    
    # User 1 can get their own
    fetched = await service.get_credentials_by_id(login1.id, user_id=user1.id)
    assert fetched is not None
    assert fetched.id == login1.id
    
    # User 2 cannot get User 1's
    fetched = await service.get_credentials_by_id(login1.id, user_id=user2.id)
    assert fetched is None

@pytest.mark.asyncio
async def test_get_user_credentials_filtering(db_session: AsyncSession):
    """Test filtering by admin status."""
    user = await create_user(db_session)
    await create_mymoment_login(db_session, user=user, is_admin=True, name="Admin")
    await create_mymoment_login(db_session, user=user, is_admin=False, name="User")
    
    service = MyMomentCredentialsService(db_session)
    
    # All
    all_logins = await service.get_user_credentials(user.id)
    assert len(all_logins) == 2
    
    # Admin only
    admin_logins = await service.get_user_credentials(user.id, is_admin=True)
    assert len(admin_logins) == 1
    assert admin_logins[0].name == "Admin"

@pytest.mark.asyncio
async def test_update_credentials(db_session: AsyncSession):
    """Test updating credentials and re-encrypting."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user, username="old", password="old")
    
    service = MyMomentCredentialsService(db_session)
    
    updated = await service.update_credentials(
        login.id,
        user_id=user.id,
        username="new",
        password="new",
        name="Updated Name"
    )
    
    assert updated.name == "Updated Name"
    u, p = updated.get_credentials()
    assert u == "new"
    assert p == "new"

@pytest.mark.asyncio
async def test_delete_credentials(db_session: AsyncSession):
    """Test soft delete of credentials."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    
    service = MyMomentCredentialsService(db_session)
    
    success = await service.delete_credentials(login.id, user_id=user.id)
    assert success is True
    
    await db_session.refresh(login)
    assert login.is_active is False

@pytest.mark.asyncio
async def test_validate_credentials(db_session: AsyncSession):
    """Test credential validation (decryption check)."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user, username="u", password="p")
    
    service = MyMomentCredentialsService(db_session)
    
    is_valid, error = await service.validate_credentials(login.id, user_id=user.id)
    assert is_valid is True
    assert error is None
