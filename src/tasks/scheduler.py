"""
Task scheduling and coordination service for yourMoment application.

This module implements essential periodic tasks for system health checks
and basic maintenance operations.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from src.tasks.worker import celery_app, BaseTask
from src.models.monitoring_process import MonitoringProcess
from src.models.mymoment_session import MyMomentSession
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)


class SchedulingTask(BaseTask):
    """Base class for scheduling tasks."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = self.db_manager.get_async_sessionmaker()
        return sessionmaker()


@celery_app.task(
    bind=True,
    base=SchedulingTask,
    name='src.tasks.scheduler.health_check_monitoring_processes',
    queue='scheduler'
)
def health_check_monitoring_processes(self) -> Dict[str, Any]:
    """
    Perform basic health check on monitoring processes.

    Returns:
        Dictionary with basic health status
    """
    try:
        result = asyncio.run(self._health_check_async())
        return result
    except Exception as exc:
        logger.error(f"Health check failed: {exc}")
        raise

    async def _health_check_async(self) -> Dict[str, Any]:
        """Check for processes that need attention."""
        async with self.get_async_session() as session:
            try:
                # Count processes by status
                result = await session.execute(
                    select(
                        MonitoringProcess.status,
                        func.count(MonitoringProcess.id).label('count')
                    )
                    .where(MonitoringProcess.is_active == True)
                    .group_by(MonitoringProcess.status)
                )

                process_stats = {row.status: row.count for row in result}

                # Check for stale processes (inactive > 1 hour)
                stale_threshold = datetime.utcnow() - timedelta(hours=1)
                stale_result = await session.execute(
                    select(func.count(MonitoringProcess.id))
                    .where(
                        and_(
                            MonitoringProcess.status == "running",
                            MonitoringProcess.is_active == True,
                            MonitoringProcess.last_activity_at < stale_threshold
                        )
                    )
                )
                stale_count = stale_result.scalar()

                # Check active sessions
                session_result = await session.execute(
                    select(func.count(MyMomentSession.id))
                    .where(
                        and_(
                            MyMomentSession.is_active == True,
                            MyMomentSession.expires_at > datetime.utcnow()
                        )
                    )
                )
                active_sessions = session_result.scalar()

                return {
                    'process_stats': process_stats,
                    'stale_processes': stale_count,
                    'active_sessions': active_sessions,
                    'status': 'warning' if stale_count > 0 else 'healthy',
                    'timestamp': datetime.utcnow().isoformat()
                }

            except Exception as e:
                logger.error(f"Health check failed: {e}")
                return {
                    'status': 'error',
                    'error': str(e),
                    'timestamp': datetime.utcnow().isoformat()
                }


@celery_app.task(
    name='src.tasks.scheduler.system_maintenance',
    queue='scheduler'
)
def system_maintenance() -> Dict[str, Any]:
    """
    Schedule basic maintenance tasks.
    """
    try:
        maintenance_tasks = []

        # Schedule cleanup tasks
        cleanup_tasks = [
            ('cleanup_expired_sessions', 'sessions'),
            ('cleanup_old_articles', 'monitoring'),  # Cleans AIComment records (articles + comments)
            ('cleanup_old_session_records', 'sessions')
        ]

        for task_name, queue in cleanup_tasks:
            try:
                if task_name == 'cleanup_expired_sessions':
                    from src.tasks.session_manager import cleanup_expired_sessions
                    task_result = cleanup_expired_sessions.apply_async(queue=queue)
                elif task_name == 'cleanup_old_articles':
                    from src.tasks.article_monitor import cleanup_old_articles
                    task_result = cleanup_old_articles.apply_async(queue=queue)
                elif task_name == 'cleanup_old_session_records':
                    from src.tasks.session_manager import cleanup_old_session_records
                    task_result = cleanup_old_session_records.apply_async(queue=queue)

                maintenance_tasks.append({
                    'task': task_name,
                    'status': 'scheduled',
                    'task_id': task_result.id
                })

            except Exception as e:
                maintenance_tasks.append({
                    'task': task_name,
                    'status': 'error',
                    'error': str(e)
                })

        logger.info(f"Scheduled {len(maintenance_tasks)} maintenance tasks")

        return {
            'maintenance_tasks': maintenance_tasks,
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'success'
        }

    except Exception as exc:
        logger.error(f"System maintenance failed: {exc}")
        return {
            'status': 'failed',
            'error': str(exc),
            'timestamp': datetime.utcnow().isoformat()
        }