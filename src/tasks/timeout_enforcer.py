"""
Process timeout enforcement tasks for monitoring process management.

This module implements background tasks for enforcing maximum duration limits
on monitoring processes as required by FR-008 (maximum duration enforcement
with immediate stop).
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from src.tasks.worker import celery_app, BaseTask
from src.models.monitoring_process import MonitoringProcess
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)


class TimeoutEnforcementTask(BaseTask):
    """Base class for timeout enforcement tasks."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = self.db_manager.get_async_sessionmaker()
        return sessionmaker()


@celery_app.task(
    bind=True,
    base=TimeoutEnforcementTask,
    name='src.tasks.timeout_enforcer.check_process_timeouts',
    queue='timeouts'
)
def check_process_timeouts(self) -> Dict[str, Any]:
    """
    Check all running monitoring processes for timeout violations.

    This task enforces maximum duration limits as specified in FR-008.
    Processes that exceed their maximum duration are immediately stopped.

    Returns:
        Dictionary with timeout check results
    """
    try:
        result = asyncio.run(self._check_process_timeouts_async())
        return result
    except Exception as exc:
        logger.error(f"Process timeout check failed: {exc}")
        raise

    async def _check_process_timeouts_async(self) -> Dict[str, Any]:
        """Async implementation of process timeout checking."""
        start_time = datetime.utcnow()
        timeout_processes = 0
        stopped_processes = 0
        errors = []

        async with self.get_async_session() as session:
            try:
                # Find all running processes
                result = await session.execute(
                    select(MonitoringProcess)
                    .where(
                        and_(
                            MonitoringProcess.status == "running",
                            MonitoringProcess.is_active == True,
                            MonitoringProcess.started_at.isnot(None),
                            MonitoringProcess.max_duration_minutes.isnot(None)
                        )
                    )
                )
                running_processes = result.scalars().all()

                current_time = datetime.utcnow()

                # Check each process for timeout
                for process in running_processes:
                    try:
                        # Calculate how long the process has been running
                        running_duration = current_time - process.started_at
                        max_duration = timedelta(minutes=process.max_duration_minutes)

                        if running_duration > max_duration:
                            timeout_processes += 1

                            # Revoke all stage-specific Celery tasks if they exist
                            revoked_tasks = []
                            for task_field, task_label in [
                                ('celery_discovery_task_id', 'discovery'),
                                ('celery_preparation_task_id', 'preparation'),
                                ('celery_generation_task_id', 'generation'),
                                ('celery_posting_task_id', 'posting')
                            ]:
                                task_id = getattr(process, task_field, None)
                                if task_id:
                                    try:
                                        celery_app.control.revoke(
                                            task_id,
                                            terminate=True,
                                            signal='SIGTERM'
                                        )
                                        revoked_tasks.append(task_label)
                                        logger.info(f"Revoked {task_label} task {task_id} for process '{process.name}'")
                                    except Exception as e:
                                        logger.error(f"Failed to revoke {task_label} task {task_id}: {e}")

                            # Stop the process immediately
                            await session.execute(
                                update(MonitoringProcess)
                                .where(MonitoringProcess.id == process.id)
                                .values(
                                    status="stopped",
                                    stopped_at=current_time,
                                    last_activity_at=current_time,
                                    stop_reason="timeout",
                                    celery_discovery_task_id=None,
                                    celery_preparation_task_id=None,
                                    celery_generation_task_id=None,
                                    celery_posting_task_id=None
                                )
                            )

                            stopped_processes += 1
                            revoked_msg = f", revoked tasks: {', '.join(revoked_tasks)}" if revoked_tasks else ""
                            logger.warning(f"Stopped process '{process.name}' due to timeout "
                                         f"(max duration: {process.max_duration_minutes} minutes){revoked_msg}")

                    except Exception as e:
                        error_msg = f"Timeout check failed for process '{process.name}': {str(e)}"
                        errors.append(error_msg)
                        logger.error(error_msg)

                await session.commit()

                execution_time = (datetime.utcnow() - start_time).total_seconds()

                logger.info(f"Process timeout check completed: {timeout_processes} timed out, "
                          f"{stopped_processes} stopped successfully")

                return {
                    'total_processes': len(running_processes),
                    'timeout_processes': timeout_processes,
                    'stopped_processes': stopped_processes,
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'timestamp': datetime.utcnow().isoformat()
                }

            except Exception as e:
                error_msg = f"Process timeout check failed: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                return {
                    'total_processes': 0,
                    'timeout_processes': 0,
                    'stopped_processes': 0,
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'timestamp': datetime.utcnow().isoformat()
                }