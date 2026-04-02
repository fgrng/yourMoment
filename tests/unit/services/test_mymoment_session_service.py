import pytest
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.mymoment_session_service import (
    MyMomentSessionService,
    MyMomentSessionValidationError,
    MyMomentSessionNotFoundError,
)
from tests.fixtures.factories.users import create_user
from tests.fixtures.factories.mymoment import (
    create_mymoment_login,
    create_mymoment_session,
    create_expired_mymoment_session,
)

@pytest.mark.asyncio
async def test_create_session(db_session: AsyncSession):
    """Test creating a new session for a login."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    
    service = MyMomentSessionService(db_session)
    
    session = await service.create_session(
        mymoment_login_id=login.id,
        session_data={"cookie": "abc-123"}
    )
    
    assert session.mymoment_login_id == login.id
    assert session.is_active is True
    assert session.expires_at > datetime.utcnow()
    assert session.get_session_data() == {"cookie": "abc-123"}

@pytest.mark.asyncio
async def test_create_session_deactivates_existing(db_session: AsyncSession):
    """Test that creating a new session deactivates old ones for the same login."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    old_session = await create_mymoment_session(db_session, mymoment_login=login)
    
    service = MyMomentSessionService(db_session)
    
    await service.create_session(
        mymoment_login_id=login.id,
        session_data={"cookie": "new"}
    )
    
    await db_session.refresh(old_session)
    assert old_session.is_active is False

@pytest.mark.asyncio
async def test_get_active_session_for_login(db_session: AsyncSession):
    """Test retrieving active session."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    active = await create_mymoment_session(db_session, mymoment_login=login)
    await create_expired_mymoment_session(db_session, mymoment_login=login)
    
    service = MyMomentSessionService(db_session)
    
    fetched = await service.get_active_session_for_login(login.id)
    assert fetched is not None
    assert fetched.id == active.id

@pytest.mark.asyncio
async def test_get_or_create_session_existing(db_session: AsyncSession):
    """Test get_or_create returns existing usable session."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    active = await create_mymoment_session(db_session, mymoment_login=login)
    
    service = MyMomentSessionService(db_session)
    
    session = await service.get_or_create_session(login.id, user.id)
    assert session.id == active.id

@pytest.mark.asyncio
async def test_get_or_create_session_new(db_session: AsyncSession):
    """Test get_or_create creates new session if none exists or expired."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    # No session yet
    
    service = MyMomentSessionService(db_session)
    
    session = await service.get_or_create_session(login.id, user.id)
    assert session is not None
    assert session.mymoment_login_id == login.id

@pytest.mark.asyncio
async def test_update_session_data(db_session: AsyncSession):
    """Test updating encrypted session data."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    session = await create_mymoment_session(db_session, mymoment_login=login)
    
    service = MyMomentSessionService(db_session)
    
    success = await service.update_session_data(session.id, {"new": "data"})
    assert success is True
    
    await db_session.refresh(session)
    assert session.get_session_data() == {"new": "data"}

@pytest.mark.asyncio
async def test_cleanup_expired_sessions(db_session: AsyncSession):
    """Test bulk deactivation of expired sessions."""
    user = await create_user(db_session)
    login = await create_mymoment_login(db_session, user=user)
    expired = await create_expired_mymoment_session(db_session, mymoment_login=login)
    active = await create_mymoment_session(db_session, mymoment_login=login)
    
    service = MyMomentSessionService(db_session)
    
    count = await service.cleanup_expired_sessions()
    assert count == 1
    
    await db_session.refresh(expired)
    assert expired.is_active is False
    
    await db_session.refresh(active)
    assert active.is_active is True
