"""
Session management tasks for myMoment platform integration.

This module implements background tasks for managing myMoment login sessions,
specifically for cleaning up expired sessions and old session records.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any

from sqlalchemy import select, and_

from src.tasks.worker import celery_app, BaseTask
from src.models.mymoment_session import MyMomentSession
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)


class SessionManagementTask(BaseTask):
    """Base class for session management tasks."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self):
        """Get async database session."""
        sessionmaker = self.db_manager.get_async_sessionmaker()
        return sessionmaker()


@celery_app.task(
    bind=True,
    base=SessionManagementTask,
    name='src.tasks.session_manager.cleanup_expired_sessions',
    queue='sessions'
)
def cleanup_expired_sessions(self) -> Dict[str, Any]:
    """
    Clean up expired myMoment sessions.

    This task removes sessions that have expired or are no longer valid.
    """
    try:
        result = asyncio.run(self._cleanup_expired_sessions_async())
        return result
    except Exception as exc:
        logger.error(f"Session cleanup failed: {exc}")
        raise

    async def _cleanup_expired_sessions_async(self) -> Dict[str, Any]:
        """Async implementation of session cleanup."""
        start_time = datetime.utcnow()
        cleaned_up_count = 0
        errors = []

        async with self.get_async_session() as session:
            try:
                # Find expired sessions
                result = await session.execute(
                    select(MyMomentSession)
                    .where(
                        and_(
                            MyMomentSession.is_active == True,
                            MyMomentSession.expires_at < datetime.utcnow()
                        )
                    )
                )
                expired_sessions = result.scalars().all()

                logger.info(f"Found {len(expired_sessions)} expired sessions to clean up")

                # Mark expired sessions as inactive
                for session_record in expired_sessions:
                    try:
                        session_record.is_active = False
                        session_record.ended_at = datetime.utcnow()
                        cleaned_up_count += 1
                    except Exception as e:
                        error_msg = f"Failed to cleanup session {session_record.id}: {str(e)}"
                        errors.append(error_msg)
                        logger.error(error_msg)

                await session.commit()

                execution_time = (datetime.utcnow() - start_time).total_seconds()

                logger.info(f"Session cleanup completed: {cleaned_up_count} sessions cleaned up")

                return {
                    'cleaned_up_sessions': cleaned_up_count,
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'timestamp': datetime.utcnow().isoformat()
                }

            except Exception as e:
                error_msg = f"Session cleanup failed: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                return {
                    'cleaned_up_sessions': 0,
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'timestamp': datetime.utcnow().isoformat()
                }


@celery_app.task(
    name='src.tasks.session_manager.cleanup_old_session_records',
    queue='sessions'
)
def cleanup_old_session_records() -> Dict[str, Any]:
    """
    Clean up old session records based on retention policy.

    This task removes session records that are older than the configured retention period.
    """
    try:
        result = asyncio.run(_cleanup_old_session_records_async())
        return result
    except Exception as exc:
        logger.error(f"Session record cleanup failed: {exc}")
        raise

async def _cleanup_old_session_records_async() -> Dict[str, Any]:
    """Async implementation of session record cleanup."""
    db_manager = get_database_manager()
    sessionmaker = db_manager.get_async_sessionmaker()

    # Default retention: 30 days for session records
    retention_days = 30
    cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

    deleted_records = 0

    async with sessionmaker() as session:
        # Find old session records
        result = await session.execute(
            select(MyMomentSession).where(
                and_(
                    MyMomentSession.created_at < cutoff_date,
                    MyMomentSession.is_active == False
                )
            )
        )
        old_sessions = result.scalars().all()

        for session_record in old_sessions:
            try:
                await session.delete(session_record)
                deleted_records += 1
            except Exception as e:
                logger.error(f"Failed to delete session record {session_record.id}: {e}")
                continue

        await session.commit()

    logger.info(f"Session record cleanup completed: {deleted_records} records deleted")

    return {
        'deleted_records': deleted_records,
        'cutoff_date': cutoff_date.isoformat(),
        'timestamp': datetime.utcnow().isoformat()
    }