"""
MyMoment session management service for yourMoment application.

Implements secure session management for myMoment platform connections with
multi-login support, session isolation, and encrypted session data storage.
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any, Union

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.mymoment_session import MyMomentSession
from src.models.mymoment_login import MyMomentLogin
from src.services.base_service import BaseService


class MyMomentSessionServiceError(Exception):
    """Base exception for myMoment session service operations."""
    pass


class MyMomentSessionValidationError(MyMomentSessionServiceError):
    """Raised when session validation fails."""
    pass


class MyMomentSessionNotFoundError(MyMomentSessionServiceError):
    """Raised when session is not found."""
    pass


class MyMomentSessionService(BaseService):
    """
    Service for managing myMoment platform sessions.

    Implements:
    - Multi-login session management with isolation
    - Encrypted session data storage (cookies, tokens)
    - Session lifecycle management and cleanup
    - Concurrent session coordination for monitoring processes
    - One active session per myMoment login constraint
    """

    def __init__(self, db_session: AsyncSession):
        """
        Initialize myMoment session service.

        Args:
            db_session: Database session for operations
        """
        super().__init__(db_session)

    async def create_session(
        self,
        mymoment_login_id: uuid.UUID,
        session_data: Union[str, Dict[str, Any]],
        duration_hours: int = 24,
        deactivate_existing: bool = True
    ) -> MyMomentSession:
        """
        Create a new myMoment session.

        Args:
            mymoment_login_id: ID of the myMoment login
            session_data: Session data (cookies, tokens, etc.)
            duration_hours: Session duration in hours
            deactivate_existing: Whether to deactivate existing sessions for this login

        Returns:
            Created MyMomentSession object

        Raises:
            MyMomentSessionValidationError: If session creation fails
        """
        # Verify the myMoment login exists
        login_stmt = select(MyMomentLogin).where(
            and_(
                MyMomentLogin.id == mymoment_login_id,
                MyMomentLogin.is_active == True
            )
        )
        login_result = await self.db_session.execute(login_stmt)
        login = login_result.scalar_one_or_none()

        if not login:
            raise MyMomentSessionNotFoundError("MyMoment login not found or inactive")

        # Deactivate existing sessions if requested (default behavior)
        if deactivate_existing:
            await self._deactivate_login_sessions(mymoment_login_id)

        # Create new session
        try:
            session = MyMomentSession.create_new_session(
                mymoment_login_id=mymoment_login_id,
                session_data=session_data,
                duration_hours=duration_hours
            )

            self.db_session.add(session)
            await self.db_session.commit()
            await self.db_session.refresh(session)

            return session

        except Exception as e:
            await self.db_session.rollback()
            raise MyMomentSessionValidationError(f"Failed to create session: {str(e)}")

    async def get_session_by_id(self, session_id: uuid.UUID) -> Optional[MyMomentSession]:
        """
        Get session by ID.

        Args:
            session_id: Session ID to retrieve

        Returns:
            MyMomentSession if found, None otherwise
        """
        stmt = select(MyMomentSession).where(MyMomentSession.id == session_id)
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_session_for_login(
        self,
        mymoment_login_id: uuid.UUID
    ) -> Optional[MyMomentSession]:
        """
        Get active session for a myMoment login.

        Args:
            mymoment_login_id: MyMoment login ID

        Returns:
            Active MyMomentSession if found, None otherwise
        """
        stmt = select(MyMomentSession).where(
            and_(
                MyMomentSession.mymoment_login_id == mymoment_login_id,
                MyMomentSession.is_active == True,
                MyMomentSession.expires_at > datetime.utcnow()
            )
        ).order_by(MyMomentSession.created_at.desc())

        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create_session(
        self,
        login_id: uuid.UUID,
        user_id: uuid.UUID,
        duration_hours: int = 24,
        session_data: Optional[Union[str, Dict[str, Any]]] = None
    ) -> MyMomentSession:
        """
        Get existing active session or create a new one for a myMoment login.

        Args:
            login_id: MyMoment login ID
            user_id: User ID for validation
            duration_hours: Session duration in hours (used if creating new session)
            session_data: Optional session data (used if creating new session)

        Returns:
            Existing or newly created MyMomentSession

        Raises:
            MyMomentSessionNotFoundError: If login not found or doesn't belong to user
            MyMomentSessionValidationError: If session creation fails
        """
        # Verify the login exists and belongs to the user
        login_stmt = select(MyMomentLogin).where(
            and_(
                MyMomentLogin.id == login_id,
                MyMomentLogin.user_id == user_id,
                MyMomentLogin.is_active == True
            )
        )
        login_result = await self.db_session.execute(login_stmt)
        login = login_result.scalar_one_or_none()

        if not login:
            raise MyMomentSessionNotFoundError(
                f"MyMoment login {login_id} not found or doesn't belong to user {user_id}"
            )

        # Check for existing active session
        existing_session = await self.get_active_session_for_login(login_id)

        if existing_session and existing_session.is_usable():
            # Return existing session if it's still usable
            return existing_session

        # Create new session with placeholder data if not provided
        if session_data is None:
            session_data = {"status": "initializing"}

        return await self.create_session(
            mymoment_login_id=login_id,
            session_data=session_data,
            duration_hours=duration_hours,
            deactivate_existing=True
        )

    async def _update_session_with_operation(
        self,
        session_id: uuid.UUID,
        operation: callable,
        check_usable: bool = True
    ) -> bool:
        """
        Generic helper to update a session with a given operation.

        Args:
            session_id: Session ID to update
            operation: Callable that takes a session and performs the update (can be sync or async)
            check_usable: Whether to check if session is usable before updating

        Returns:
            True if update was successful, False if session not found
        """
        session = await self.get_session_by_id(session_id)
        if not session or (check_usable and not session.is_usable()):
            return False

        try:
            # Support both sync and async operation callables
            import inspect
            if inspect.iscoroutinefunction(operation):
                await operation(session)
            else:
                operation(session)
            await self.db_session.commit()
            return True
        except Exception:
            await self.db_session.rollback()
            return False

    async def update_session_data(
        self,
        session_id: uuid.UUID,
        session_data: Union[str, Dict[str, Any]]
    ) -> bool:
        """
        Update session data for an existing session.

        Args:
            session_id: Session ID to update
            session_data: New session data

        Returns:
            True if update was successful, False if session not found
        """
        async def operation(session):
            session.update_session_data(session_data)

        return await self._update_session_with_operation(session_id, operation, check_usable=True)

    async def touch_session(self, session_id: uuid.UUID) -> bool:
        """
        Update session's last accessed time to mark it as recently used.

        Args:
            session_id: Session ID to touch

        Returns:
            True if session was touched, False if not found
        """
        async def operation(session):
            session.touch()

        return await self._update_session_with_operation(session_id, operation, check_usable=True)

    async def renew_session(
        self,
        session_id: uuid.UUID,
        duration_hours: int = 24
    ) -> bool:
        """
        Renew session with new expiration time.

        Args:
            session_id: Session ID to renew
            duration_hours: New duration in hours

        Returns:
            True if session was renewed, False if not found
        """
        async def operation(session):
            session.renew_session(duration_hours)

        return await self._update_session_with_operation(session_id, operation, check_usable=False)

    async def deactivate_session(self, session_id: uuid.UUID) -> bool:
        """
        Deactivate a specific session.

        Args:
            session_id: Session ID to deactivate

        Returns:
            True if session was deactivated, False if not found
        """
        async def operation(session):
            session.deactivate()

        return await self._update_session_with_operation(session_id, operation, check_usable=False)

    async def _deactivate_login_sessions(self, mymoment_login_id: uuid.UUID) -> int:
        """
        Internal method to deactivate all sessions for a login.

        Args:
            mymoment_login_id: MyMoment login ID

        Returns:
            Number of sessions deactivated
        """
        stmt = select(MyMomentSession).where(
            and_(
                MyMomentSession.mymoment_login_id == mymoment_login_id,
                MyMomentSession.is_active == True
            )
        )

        result = await self.db_session.execute(stmt)
        sessions = list(result.scalars().all())

        count = 0
        for session in sessions:
            session.deactivate()
            count += 1

        if count > 0:
            await self.db_session.commit()

        return count
