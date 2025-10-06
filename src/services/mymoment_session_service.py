"""
MyMoment session management service for yourMoment application.

Implements secure session management for myMoment platform connections with
multi-login support, session isolation, and encrypted session data storage.
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Union, Tuple

from sqlalchemy import select, and_, or_, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

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

    async def get_active_sessions_for_user(
        self,
        user_id: uuid.UUID
    ) -> List[MyMomentSession]:
        """
        Get all active sessions for a user across all their myMoment logins.

        Args:
            user_id: User ID

        Returns:
            List of active MyMomentSession objects
        """
        stmt = select(MyMomentSession).join(MyMomentLogin).where(
            and_(
                MyMomentLogin.user_id == user_id,
                MyMomentLogin.is_active == True,
                MyMomentSession.is_active == True,
                MyMomentSession.expires_at > datetime.utcnow()
            )
        ).order_by(MyMomentSession.last_accessed.desc())

        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_sessions_for_monitoring_process(
        self,
        process_id: uuid.UUID
    ) -> List[MyMomentSession]:
        """
        Get all active sessions for logins associated with a monitoring process.

        Args:
            process_id: Monitoring process ID

        Returns:
            List of active MyMomentSession objects for the process
        """
        from src.models.monitoring_process_login import MonitoringProcessLogin

        stmt = select(MyMomentSession).join(MyMomentLogin).join(
            MonitoringProcessLogin,
            MonitoringProcessLogin.mymoment_login_id == MyMomentLogin.id
        ).where(
            and_(
                MonitoringProcessLogin.monitoring_process_id == process_id,
                MyMomentLogin.is_active == True,
                MyMomentSession.is_active == True,
                MyMomentSession.expires_at > datetime.utcnow()
            )
        ).order_by(MyMomentSession.last_accessed.desc())

        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

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

    async def deactivate_all_sessions_for_user(
        self,
        user_id: uuid.UUID
    ) -> int:
        """
        Deactivate all sessions for a user across all their myMoment logins.

        Args:
            user_id: User ID

        Returns:
            Number of sessions deactivated
        """
        stmt = select(MyMomentSession).join(MyMomentLogin).where(
            and_(
                MyMomentLogin.user_id == user_id,
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

    async def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions by deactivating them.

        Returns:
            Number of sessions cleaned up
        """
        stmt = select(MyMomentSession).where(
            and_(
                MyMomentSession.is_active == True,
                MyMomentSession.expires_at < datetime.utcnow()
            )
        )

        result = await self.db_session.execute(stmt)
        expired_sessions = list(result.scalars().all())

        count = 0
        for session in expired_sessions:
            session.deactivate()
            count += 1

        if count > 0:
            await self.db_session.commit()

        return count

    async def cleanup_old_inactive_sessions(
        self,
        older_than_days: int = 30
    ) -> int:
        """
        Delete old inactive sessions from database.

        Args:
            older_than_days: Delete sessions inactive for more than this many days

        Returns:
            Number of sessions deleted
        """
        cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)

        stmt = delete(MyMomentSession).where(
            and_(
                MyMomentSession.is_active == False,
                MyMomentSession.updated_at < cutoff_date
            )
        )

        result = await self.db_session.execute(stmt)
        await self.db_session.commit()

        return result.rowcount

    async def get_session_statistics(
        self,
        user_id: Optional[uuid.UUID] = None
    ) -> Dict[str, Any]:
        """
        Get session statistics.

        Args:
            user_id: Optional user ID to filter statistics

        Returns:
            Dictionary containing session statistics
        """
        base_conditions = []
        if user_id:
            # Join with MyMomentLogin to filter by user
            query_with_join = True
            base_conditions.append(MyMomentLogin.user_id == user_id)
        else:
            query_with_join = False

        # Active sessions count
        if query_with_join:
            active_stmt = select(func.count(MyMomentSession.id)).join(MyMomentLogin).where(
                and_(
                    MyMomentSession.is_active == True,
                    MyMomentSession.expires_at > datetime.utcnow(),
                    *base_conditions
                )
            )
        else:
            active_stmt = select(func.count(MyMomentSession.id)).where(
                and_(
                    MyMomentSession.is_active == True,
                    MyMomentSession.expires_at > datetime.utcnow()
                )
            )

        active_result = await self.db_session.execute(active_stmt)
        active_count = active_result.scalar()

        # Expired sessions count
        if query_with_join:
            expired_stmt = select(func.count(MyMomentSession.id)).join(MyMomentLogin).where(
                and_(
                    MyMomentSession.expires_at <= datetime.utcnow(),
                    *base_conditions
                )
            )
        else:
            expired_stmt = select(func.count(MyMomentSession.id)).where(
                MyMomentSession.expires_at <= datetime.utcnow()
            )

        expired_result = await self.db_session.execute(expired_stmt)
        expired_count = expired_result.scalar()

        # Total sessions count
        if query_with_join:
            total_stmt = select(func.count(MyMomentSession.id)).join(MyMomentLogin).where(
                and_(*base_conditions) if base_conditions else True
            )
        else:
            total_stmt = select(func.count(MyMomentSession.id))

        total_result = await self.db_session.execute(total_stmt)
        total_count = total_result.scalar()

        return {
            "active_sessions": active_count,
            "expired_sessions": expired_count,
            "total_sessions": total_count,
            "user_id": str(user_id) if user_id else None
        }

    async def validate_session_for_monitoring(
        self,
        session_id: uuid.UUID
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate if a session is suitable for monitoring operations.

        Args:
            session_id: Session ID to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        session = await self.get_session_by_id(session_id)

        if not session:
            return False, "Session not found"

        if not session.is_active:
            return False, "Session is inactive"

        if session.is_expired():
            return False, "Session has expired"

        # Check if session will expire soon (within 1 hour)
        remaining_hours = session.get_remaining_hours()
        if remaining_hours < 1.0:
            return False, f"Session expires too soon ({remaining_hours:.1f} hours remaining)"

        return True, None

    async def get_usable_sessions_for_process(
        self,
        process_id: uuid.UUID
    ) -> List[MyMomentSession]:
        """
        Get all usable sessions for a monitoring process.

        Args:
            process_id: Monitoring process ID

        Returns:
            List of usable MyMomentSession objects
        """
        sessions = await self.get_active_sessions_for_monitoring_process(process_id)
        usable_sessions = []

        for session in sessions:
            is_valid, _ = await self.validate_session_for_monitoring(session.id)
            if is_valid:
                usable_sessions.append(session)

        return usable_sessions

    async def ensure_sessions_for_process(
        self,
        process_id: uuid.UUID,
        required_session_hours: int = 2
    ) -> List[Tuple[MyMomentSession, bool]]:
        """
        Ensure all logins for a monitoring process have usable sessions.

        Args:
            process_id: Monitoring process ID
            required_session_hours: Minimum hours of session life required

        Returns:
            List of tuples (session, needs_refresh) for each login
        """
        from src.models.monitoring_process_login import MonitoringProcessLogin

        # Get all logins for the process
        logins_stmt = select(MyMomentLogin).join(
            MonitoringProcessLogin,
            MonitoringProcessLogin.mymoment_login_id == MyMomentLogin.id
        ).where(
            and_(
                MonitoringProcessLogin.monitoring_process_id == process_id,
                MyMomentLogin.is_active == True
            )
        )

        logins_result = await self.db_session.execute(logins_stmt)
        logins = list(logins_result.scalars().all())

        session_status = []

        for login in logins:
            session = await self.get_active_session_for_login(login.id)

            if not session or not session.is_usable():
                # No usable session - needs to be created
                session_status.append((None, True))
            else:
                # Check if session has enough time remaining
                remaining_hours = session.get_remaining_hours()
                needs_refresh = remaining_hours < required_session_hours
                session_status.append((session, needs_refresh))

        return session_status

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