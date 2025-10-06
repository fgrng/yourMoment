"""
Session management service for yourMoment application.

Provides advanced session management capabilities including concurrent session
tracking, session cleanup, and security monitoring.
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy import select, delete, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user_session import UserSession


class SessionService:
    """
    Service for managing user sessions and security monitoring.

    Provides:
    - Session creation and validation
    - Concurrent session management
    - Security monitoring and alerting
    - Session cleanup and maintenance
    """

    def __init__(self, db_session: AsyncSession):
        """
        Initialize session service.

        Args:
            db_session: Database session for operations
        """
        self.db = db_session

    async def get_active_sessions(self, user_id: uuid.UUID) -> List[UserSession]:
        """
        Get all active sessions for a user.

        Args:
            user_id: User ID to get sessions for

        Returns:
            List of active UserSession objects
        """
        stmt = select(UserSession).where(
            and_(
                UserSession.user_id == user_id,
                UserSession.is_active == True,
                UserSession.expires_at > datetime.utcnow()
            )
        ).order_by(UserSession.last_activity.desc())

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_session_by_token_hash(self, token_hash: str) -> Optional[UserSession]:
        """
        Get session by token hash.

        Args:
            token_hash: Hashed token to lookup

        Returns:
            UserSession if found and valid, None otherwise
        """
        stmt = select(UserSession).where(
            and_(
                UserSession.token_hash == token_hash,
                UserSession.is_active == True,
                UserSession.expires_at > datetime.utcnow()
            )
        )

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke_session(self, session_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """
        Revoke a specific session.

        Args:
            session_id: Session ID to revoke
            user_id: User ID (for authorization check)

        Returns:
            True if session was revoked, False if not found
        """
        stmt = select(UserSession).where(
            and_(
                UserSession.id == session_id,
                UserSession.user_id == user_id,
                UserSession.is_active == True
            )
        )

        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if session:
            session.revoke()
            await self.db.commit()
            return True

        return False

    async def revoke_all_sessions(self, user_id: uuid.UUID, except_session_id: Optional[uuid.UUID] = None) -> int:
        """
        Revoke all sessions for a user.

        Args:
            user_id: User ID to revoke sessions for
            except_session_id: Optional session ID to keep active (current session)

        Returns:
            Number of sessions revoked
        """
        conditions = [
            UserSession.user_id == user_id,
            UserSession.is_active == True
        ]

        if except_session_id:
            conditions.append(UserSession.id != except_session_id)

        stmt = select(UserSession).where(and_(*conditions))
        result = await self.db.execute(stmt)
        sessions = result.scalars().all()

        count = 0
        for session in sessions:
            session.revoke()
            count += 1

        if count > 0:
            await self.db.commit()

        return count

    async def extend_session(
        self,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        additional_time: timedelta = timedelta(hours=1)
    ) -> bool:
        """
        Extend session expiry time.

        Args:
            session_id: Session ID to extend
            user_id: User ID (for authorization check)
            additional_time: Additional time to add to expiry

        Returns:
            True if session was extended, False if not found
        """
        stmt = select(UserSession).where(
            and_(
                UserSession.id == session_id,
                UserSession.user_id == user_id,
                UserSession.is_active == True
            )
        )

        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if session:
            session.extend_session(additional_time)
            await self.db.commit()
            return True

        return False

    async def cleanup_expired_sessions(self) -> int:
        """
        Remove expired sessions from database.

        Returns:
            Number of sessions cleaned up
        """
        stmt = delete(UserSession).where(
            UserSession.expires_at < datetime.utcnow()
        )

        result = await self.db.execute(stmt)
        await self.db.commit()

        return result.rowcount

    async def cleanup_inactive_sessions(self, inactive_threshold: timedelta = timedelta(days=7)) -> int:
        """
        Remove sessions that have been inactive for too long.

        Args:
            inactive_threshold: Time threshold for considering a session inactive

        Returns:
            Number of sessions cleaned up
        """
        cutoff_time = datetime.utcnow() - inactive_threshold

        stmt = delete(UserSession).where(
            UserSession.last_activity < cutoff_time
        )

        result = await self.db.execute(stmt)
        await self.db.commit()

        return result.rowcount

    async def get_session_statistics(self, user_id: Optional[uuid.UUID] = None) -> Dict[str, Any]:
        """
        Get session statistics.

        Args:
            user_id: Optional user ID to filter statistics for specific user

        Returns:
            Dictionary containing session statistics
        """
        base_conditions = []
        if user_id:
            base_conditions.append(UserSession.user_id == user_id)

        # Active sessions count
        active_stmt = select(func.count(UserSession.id)).where(
            and_(
                UserSession.is_active == True,
                UserSession.expires_at > datetime.utcnow(),
                *base_conditions
            )
        )
        active_result = await self.db.execute(active_stmt)
        active_count = active_result.scalar()

        # Expired sessions count
        expired_stmt = select(func.count(UserSession.id)).where(
            and_(
                UserSession.expires_at <= datetime.utcnow(),
                *base_conditions
            )
        )
        expired_result = await self.db.execute(expired_stmt)
        expired_count = expired_result.scalar()

        # Total sessions count
        total_stmt = select(func.count(UserSession.id))
        if base_conditions:
            total_stmt = total_stmt.where(and_(*base_conditions))
        total_result = await self.db.execute(total_stmt)
        total_count = total_result.scalar()

        return {
            "active_sessions": active_count,
            "expired_sessions": expired_count,
            "total_sessions": total_count,
            "user_id": str(user_id) if user_id else None
        }

    async def detect_concurrent_sessions(
        self,
        user_id: uuid.UUID,
        max_concurrent: int = 5
    ) -> Dict[str, Any]:
        """
        Detect if user has too many concurrent sessions.

        Args:
            user_id: User ID to check
            max_concurrent: Maximum allowed concurrent sessions

        Returns:
            Dictionary with detection results and session information
        """
        active_sessions = await self.get_active_sessions(user_id)
        session_count = len(active_sessions)

        return {
            "user_id": str(user_id),
            "active_session_count": session_count,
            "max_allowed": max_concurrent,
            "is_over_limit": session_count > max_concurrent,
            "sessions": [
                {
                    "id": str(session.id),
                    "last_activity": session.last_activity.isoformat(),
                    "expires_at": session.expires_at.isoformat()
                }
                for session in active_sessions
            ]
        }

    async def detect_rapid_session_creation(
        self,
        user_id: uuid.UUID,
        time_window: timedelta = timedelta(hours=1),
        max_sessions: int = 10
    ) -> Dict[str, Any]:
        """
        Detect rapid session creation which may indicate suspicious activity.

        Args:
            user_id: User ID to check
            time_window: Time window to analyze
            max_sessions: Maximum sessions allowed in time window

        Returns:
            Dictionary with rapid creation analysis
        """
        cutoff_time = datetime.utcnow() - time_window

        # Get recent sessions
        stmt = select(UserSession).where(
            and_(
                UserSession.user_id == user_id,
                UserSession.created_at >= cutoff_time
            )
        ).order_by(UserSession.created_at.desc())

        result = await self.db.execute(stmt)
        recent_sessions = result.scalars().all()

        rapid_creation = len(recent_sessions) > max_sessions

        return {
            "user_id": str(user_id),
            "time_window_hours": time_window.total_seconds() / 3600,
            "recent_session_count": len(recent_sessions),
            "max_allowed": max_sessions,
            "rapid_session_creation": rapid_creation,
            "is_suspicious": rapid_creation,
            "recent_sessions": [
                {
                    "id": str(session.id),
                    "created_at": session.created_at.isoformat(),
                    "is_active": session.is_active,
                    "expires_at": session.expires_at.isoformat()
                }
                for session in recent_sessions[:10]  # Limit to 10 most recent
            ]
        }

    async def get_session_history(
        self,
        user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Get session history for a user.

        Args:
            user_id: User ID to get history for
            limit: Maximum number of sessions to return
            offset: Number of sessions to skip

        Returns:
            List of session history records
        """
        stmt = select(UserSession).where(
            UserSession.user_id == user_id
        ).order_by(UserSession.created_at.desc()).limit(limit).offset(offset)

        result = await self.db.execute(stmt)
        sessions = result.scalars().all()

        return [
            {
                "id": str(session.id),
                "created_at": session.created_at.isoformat(),
                "expires_at": session.expires_at.isoformat(),
                "last_activity": session.last_activity.isoformat(),
                "is_active": session.is_active,
                "is_expired": session.is_expired
            }
            for session in sessions
        ]