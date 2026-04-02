"""
Process timeout enforcement tasks for monitoring process management.

This module implements background tasks for enforcing maximum duration limits
on monitoring processes as required by FR-008 (maximum duration enforcement
with immediate stop).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from src.tasks.worker import celery_app, BaseTask
from src.models.monitoring_process import MonitoringProcess
from src.services.monitoring_service import MonitoringService
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)


class TimeoutEnforcementTask(BaseTask):
    """Base class for timeout enforcement tasks."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()

    async def _check_process_timeouts_async(self) -> Dict[str, Any]:
        """Async implementation of process timeout checking."""
        start_time = datetime.now(timezone.utc)
        timeout_processes = 0
        stopped_processes = 0
        errors = []

        async with await self.get_async_session() as session:
            try:
                monitoring_service = MonitoringService(session)

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

                current_time = datetime.now(timezone.utc)

                # Check each process for timeout
                for process in running_processes:
                    try:
                        # Calculate how long the process has been running
                        started_at = MonitoringProcess._normalize_utc(process.started_at)
                        running_duration = current_time - started_at
                        max_duration = timedelta(minutes=process.max_duration_minutes)

                        if running_duration > max_duration:
                            timeout_processes += 1

                            stop_result = await monitoring_service._stop_process_instance(
                                process,
                                reason="timeout",
                                commit=False,
                            )

                            stopped_processes += 1
                            revoked_msg = ""
                            if stop_result["revoked_tasks"]:
                                revoked_msg = (
                                    ", revoked tasks: "
                                    + ", ".join(stop_result["revoked_tasks"].keys())
                                )
                            logger.warning(
                                "Stopped process '%s' due to timeout "
                                "(max duration: %s minutes)%s",
                                process.name,
                                process.max_duration_minutes,
                                revoked_msg,
                            )

                    except Exception as e:
                        error_msg = f"Timeout check failed for process '{process.name}': {str(e)}"
                        errors.append(error_msg)
                        logger.error(error_msg)

                await session.commit()

                execution_time = (datetime.now(timezone.utc) - start_time).total_seconds()

                logger.info(f"Process timeout check completed: {timeout_processes} timed out, "
                          f"{stopped_processes} stopped successfully")

                return {
                    'total_processes': len(running_processes),
                    'timeout_processes': timeout_processes,
                    'stopped_processes': stopped_processes,
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }

            except Exception as e:
                error_msg = f"Process timeout check failed: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

                execution_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                return {
                    'total_processes': 0,
                    'timeout_processes': 0,
                    'stopped_processes': 0,
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }


# Register the task as a Celery task
@celery_app.task(
    name='src.tasks.timeout_enforcer.check_process_timeouts',
    queue='timeouts'
)
def check_process_timeouts() -> Dict[str, Any]:
    """
    Check all running monitoring processes for timeout violations.

    This task enforces maximum duration limits as specified in FR-008.
    Processes that exceed their maximum duration are immediately stopped.

    Returns:
        Dictionary with timeout check results
    """
    try:
        task = TimeoutEnforcementTask()
        result = asyncio.run(task._check_process_timeouts_async())
        return result
    except Exception as exc:
        logger.error(f"Process timeout check failed: {exc}")
        raise
