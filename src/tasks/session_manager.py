"""
Session management tasks for myMoment platform integration.

This module implements background tasks for managing myMoment login sessions,
including session initialization, health checks, cleanup, and concurrent session coordination.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from celery import current_task
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update, delete

from src.tasks.worker import celery_app, BaseTask
from src.models.mymoment_login import MyMomentLogin
from src.models.mymoment_session import MyMomentSession
from src.models.monitoring_process import MonitoringProcess
from src.services.mymoment_session_service import MyMomentSessionService
from src.services.scraper_service import ScraperService, SessionContext
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)


@dataclass
class SessionHealthResult:
    """Result of session health check operation."""
    total_sessions: int
    healthy_sessions: int
    expired_sessions: int
    failed_sessions: int
    cleaned_up_sessions: int
    errors: List[str]
    execution_time_seconds: float


class SessionManagementTask(BaseTask):
    """Base class for session management tasks."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = self.db_manager.get_async_sessionmaker()
        return sessionmaker()


@celery_app.task(
    bind=True,
    base=SessionManagementTask,
    name='src.tasks.session_manager.initialize_process_sessions',
    queue='sessions',
    max_retries=3,
    default_retry_delay=60
)
def initialize_process_sessions(self, process_id: str) -> Dict[str, Any]:
    """
    Initialize myMoment sessions for all logins associated with a monitoring process.

    Args:
        process_id: UUID of the monitoring process

    Returns:
        Dictionary with session initialization results
    """
    try:
        result = asyncio.run(self._initialize_process_sessions_async(uuid.UUID(process_id)))
        return result
    except Exception as exc:
        logger.error(f"Session initialization failed for process {process_id}: {exc}")
        self.retry(exc=exc, countdown=60)

    async def _initialize_process_sessions_async(self, process_id: uuid.UUID) -> Dict[str, Any]:
        """Async implementation of session initialization."""
        start_time = datetime.utcnow()
        initialized_sessions = 0
        failed_sessions = 0
        errors = []

        async with self.get_async_session() as session:
            try:
                # Get monitoring process
                result = await session.execute(
                    select(MonitoringProcess).where(MonitoringProcess.id == process_id)
                )
                process = result.scalar_one_or_none()

                if not process:
                    raise ValueError(f"Monitoring process {process_id} not found")

                # Get associated myMoment logins
                logins = await self._get_process_logins(session, process_id)
                if not logins:
                    raise ValueError(f"No active myMoment logins found for process {process_id}")

                logger.info(f"Initializing sessions for {len(logins)} logins in process {process.name}")

                # Initialize scraper service
                scraper_service = ScraperService(session)

                # Initialize sessions for each login
                for login in logins:
                    try:
                        # Check if session already exists and is valid
                        existing_session = await self._get_active_session(session, login.id)
                        if existing_session:
                            # Verify session is still valid
                            if await self._verify_session_health(scraper_service, existing_session):
                                logger.info(f"Session for login {login.username} is already active and healthy")
                                initialized_sessions += 1
                                continue

                        # Create new session
                        session_context = await scraper_service.create_session_for_login(login.id)
                        if session_context and session_context.is_authenticated:
                            initialized_sessions += 1
                            logger.info(f"Successfully initialized session for login {login.username}")
                        else:
                            failed_sessions += 1
                            error_msg = f"Failed to authenticate session for login {login.username}"
                            errors.append(error_msg)
                            logger.error(error_msg)

                    except Exception as e:
                        failed_sessions += 1
                        error_msg = f"Session initialization failed for login {login.username}: {str(e)}"
                        errors.append(error_msg)
                        logger.error(error_msg)

                execution_time = (datetime.utcnow() - start_time).total_seconds()

                logger.info(f"Session initialization completed for process {process.name}: "
                          f"{initialized_sessions} successful, {failed_sessions} failed")

                return {
                    'process_id': str(process_id),
                    'total_logins': len(logins),
                    'initialized_sessions': initialized_sessions,
                    'failed_sessions': failed_sessions,
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'status': 'success' if failed_sessions == 0 else 'partial'
                }

            except Exception as e:
                error_msg = f"Session initialization failed: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                return {
                    'process_id': str(process_id),
                    'total_logins': 0,
                    'initialized_sessions': 0,
                    'failed_sessions': 0,
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'status': 'failed'
                }

    async def _get_process_logins(self, session: AsyncSession, process_id: uuid.UUID) -> List[MyMomentLogin]:
        """Get active myMoment logins for a monitoring process."""
        result = await session.execute(
            select(MyMomentLogin)
            .join(MonitoringProcess.monitoring_process_logins)
            .where(
                and_(
                    MonitoringProcess.id == process_id,
                    MyMomentLogin.is_active == True
                )
            )
        )
        return result.scalars().all()

    async def _get_active_session(self, session: AsyncSession, login_id: uuid.UUID) -> Optional[MyMomentSession]:
        """Get active session for a login."""
        result = await session.execute(
            select(MyMomentSession)
            .where(
                and_(
                    MyMomentSession.mymoment_login_id == login_id,
                    MyMomentSession.is_active == True,
                    MyMomentSession.expires_at > datetime.utcnow()
                )
            )
            .order_by(MyMomentSession.created_at.desc())
        )
        return result.scalar_one_or_none()

    async def _verify_session_health(self, scraper_service: ScraperService,
                                   session_record: MyMomentSession) -> bool:
        """Verify that a session is still healthy and authenticated."""
        try:
            session_context = await scraper_service.get_session_context(session_record.mymoment_login_id)
            if session_context and session_context.is_authenticated:
                return await scraper_service.verify_authentication(session_context)
            return False
        except Exception as e:
            logger.warning(f"Session health check failed for session {session_record.id}: {e}")
            return False


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
    bind=True,
    base=SessionManagementTask,
    name='src.tasks.session_manager.health_check_sessions',
    queue='sessions'
)
def health_check_sessions(self, process_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Perform health check on myMoment sessions.

    Args:
        process_id: Optional UUID of specific process to check, or None for all sessions

    Returns:
        Dictionary with health check results
    """
    try:
        process_uuid = uuid.UUID(process_id) if process_id else None
        result = asyncio.run(self._health_check_sessions_async(process_uuid))
        return result
    except Exception as exc:
        logger.error(f"Session health check failed: {exc}")
        raise

    async def _health_check_sessions_async(self, process_id: Optional[uuid.UUID]) -> Dict[str, Any]:
        """Async implementation of session health check."""
        start_time = datetime.utcnow()
        healthy_sessions = 0
        unhealthy_sessions = 0
        refreshed_sessions = 0
        errors = []

        async with self.get_async_session() as session:
            try:
                # Get sessions to check
                if process_id:
                    # Check sessions for specific process
                    result = await session.execute(
                        select(MyMomentSession)
                        .join(MyMomentLogin)
                        .join(MonitoringProcess.monitoring_process_logins)
                        .where(
                            and_(
                                MonitoringProcess.id == process_id,
                                MyMomentSession.is_active == True
                            )
                        )
                    )
                else:
                    # Check all active sessions
                    result = await session.execute(
                        select(MyMomentSession)
                        .where(MyMomentSession.is_active == True)
                    )

                sessions_to_check = result.scalars().all()
                logger.info(f"Health checking {len(sessions_to_check)} sessions")

                scraper_service = ScraperService(session)

                # Check each session
                for session_record in sessions_to_check:
                    try:
                        if await self._verify_session_health(scraper_service, session_record):
                            healthy_sessions += 1
                            # Update last activity
                            session_record.last_activity_at = datetime.utcnow()
                        else:
                            unhealthy_sessions += 1
                            # Try to refresh the session
                            try:
                                new_context = await scraper_service.refresh_session(session_record.mymoment_login_id)
                                if new_context and new_context.is_authenticated:
                                    refreshed_sessions += 1
                                    logger.info(f"Successfully refreshed session for login {session_record.mymoment_login_id}")
                                else:
                                    # Mark session as inactive
                                    session_record.is_active = False
                                    session_record.ended_at = datetime.utcnow()
                                    logger.warning(f"Failed to refresh session for login {session_record.mymoment_login_id}")
                            except Exception as e:
                                error_msg = f"Session refresh failed for {session_record.id}: {str(e)}"
                                errors.append(error_msg)
                                logger.error(error_msg)

                    except Exception as e:
                        error_msg = f"Health check failed for session {session_record.id}: {str(e)}"
                        errors.append(error_msg)
                        logger.error(error_msg)

                await session.commit()

                execution_time = (datetime.utcnow() - start_time).total_seconds()

                logger.info(f"Session health check completed: {healthy_sessions} healthy, "
                          f"{unhealthy_sessions} unhealthy, {refreshed_sessions} refreshed")

                return {
                    'process_id': str(process_id) if process_id else None,
                    'total_sessions': len(sessions_to_check),
                    'healthy_sessions': healthy_sessions,
                    'unhealthy_sessions': unhealthy_sessions,
                    'refreshed_sessions': refreshed_sessions,
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'timestamp': datetime.utcnow().isoformat()
                }

            except Exception as e:
                error_msg = f"Session health check failed: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                return {
                    'process_id': str(process_id) if process_id else None,
                    'total_sessions': 0,
                    'healthy_sessions': 0,
                    'unhealthy_sessions': 0,
                    'refreshed_sessions': 0,
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'timestamp': datetime.utcnow().isoformat()
                }


@celery_app.task(
    bind=True,
    base=SessionManagementTask,
    name='src.tasks.session_manager.terminate_process_sessions',
    queue='sessions'
)
def terminate_process_sessions(self, process_id: str) -> Dict[str, Any]:
    """
    Terminate all sessions associated with a monitoring process.

    Args:
        process_id: UUID of the monitoring process

    Returns:
        Dictionary with termination results
    """
    try:
        result = asyncio.run(self._terminate_process_sessions_async(uuid.UUID(process_id)))
        return result
    except Exception as exc:
        logger.error(f"Session termination failed for process {process_id}: {exc}")
        raise

    async def _terminate_process_sessions_async(self, process_id: uuid.UUID) -> Dict[str, Any]:
        """Async implementation of session termination."""
        terminated_sessions = 0
        errors = []

        async with self.get_async_session() as session:
            try:
                # Get sessions for the process
                result = await session.execute(
                    select(MyMomentSession)
                    .join(MyMomentLogin)
                    .join(MonitoringProcess.monitoring_process_logins)
                    .where(
                        and_(
                            MonitoringProcess.id == process_id,
                            MyMomentSession.is_active == True
                        )
                    )
                )
                sessions_to_terminate = result.scalars().all()

                logger.info(f"Terminating {len(sessions_to_terminate)} sessions for process {process_id}")

                # Terminate each session
                for session_record in sessions_to_terminate:
                    try:
                        session_record.is_active = False
                        session_record.ended_at = datetime.utcnow()
                        terminated_sessions += 1
                    except Exception as e:
                        error_msg = f"Failed to terminate session {session_record.id}: {str(e)}"
                        errors.append(error_msg)
                        logger.error(error_msg)

                await session.commit()

                logger.info(f"Session termination completed: {terminated_sessions} sessions terminated")

                return {
                    'process_id': str(process_id),
                    'terminated_sessions': terminated_sessions,
                    'errors': errors,
                    'timestamp': datetime.utcnow().isoformat()
                }

            except Exception as e:
                error_msg = f"Session termination failed: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

                return {
                    'process_id': str(process_id),
                    'terminated_sessions': 0,
                    'errors': errors,
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