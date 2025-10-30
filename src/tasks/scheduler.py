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
from celery.result import AsyncResult

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
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()

    async def _trigger_pipeline_async(self, force_immediate: bool = False) -> Dict[str, Any]:
        """
        Async implementation of pipeline triggering.

        Args:
            force_immediate: If True, spawn tasks for ALL running processes immediately.
                            If False (default), only spawn if no task is currently running.
        """
        start_time = datetime.utcnow()

        # Import stage tasks
        from src.tasks.article_discovery import discover_articles
        from src.tasks.article_preparation import prepare_content_of_articles
        from src.tasks.comment_generation import generate_comments_for_articles
        from src.tasks.comment_posting import post_comments_for_articles

        spawned_tasks = []
        skipped_tasks = []
        errors = []

        async with await self.get_async_session() as session:
            try:
                # Find all running monitoring processes
                result = await session.execute(
                    select(MonitoringProcess)
                    .where(
                        and_(
                            MonitoringProcess.status == "running",
                            MonitoringProcess.is_active == True
                        )
                    )
                )
                running_processes = result.scalars().all()

                logger.info(f"Found {len(running_processes)} running monitoring processes")

                # For each process, check and spawn stage tasks
                for process in running_processes:
                    try:
                        process_spawned = await self._spawn_stage_tasks_for_process(
                            process,
                            discover_articles,
                            prepare_content_of_articles,
                            generate_comments_for_articles,
                            post_comments_for_articles,
                            force_immediate=force_immediate
                        )

                        spawned_tasks.extend(process_spawned['spawned'])
                        skipped_tasks.extend(process_spawned['skipped'])

                    except Exception as e:
                        error_msg = f"Failed to trigger tasks for process {process.id}: {str(e)}"
                        errors.append(error_msg)
                        logger.error(error_msg)

                # Commit any task ID updates
                await session.commit()

                execution_time = (datetime.utcnow() - start_time).total_seconds()

                logger.info(
                    f"Pipeline trigger completed: "
                    f"{len(spawned_tasks)} tasks spawned, "
                    f"{len(skipped_tasks)} tasks skipped (already running), "
                    f"{len(errors)} errors"
                )

                return {
                    'processes_checked': len(running_processes),
                    'tasks_spawned': len(spawned_tasks),
                    'tasks_skipped': len(skipped_tasks),
                    'spawned_details': spawned_tasks,
                    'skipped_details': skipped_tasks,
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'timestamp': datetime.utcnow().isoformat()
                }

            except Exception as e:
                error_msg = f"Pipeline trigger failed: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                return {
                    'processes_checked': 0,
                    'tasks_spawned': 0,
                    'tasks_skipped': 0,
                    'spawned_details': [],
                    'skipped_details': [],
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'timestamp': datetime.utcnow().isoformat()
                }

    async def _spawn_stage_tasks_for_process(
        self,
        process: MonitoringProcess,
        discover_articles_task,
        prepare_content_task,
        generate_comments_task,
        post_comments_task,
        force_immediate: bool = False
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        Spawn stage tasks for a single process, checking if tasks are already running.

        Args:
            process: MonitoringProcess instance
            discover_articles_task: Discovery task callable
            prepare_content_task: Preparation task callable
            generate_comments_task: Generation task callable
            post_comments_task: Posting task callable
            force_immediate: If True, spawn all tasks regardless of previous state.
                            Useful for initial process start.

        Returns:
            Dictionary with 'spawned' and 'skipped' task lists
        """
        spawned = []
        skipped = []

        # Define stage configurations
        stages = [
            {
                'name': 'discovery',
                'task_id_field': 'celery_discovery_task_id',
                'task_callable': discover_articles_task,
                'enabled': True
            },
            {
                'name': 'preparation',
                'task_id_field': 'celery_preparation_task_id',
                'task_callable': prepare_content_task,
                'enabled': True
            },
            {
                'name': 'generation',
                'task_id_field': 'celery_generation_task_id',
                'task_callable': generate_comments_task,
                'enabled': True
            },
            {
                'name': 'posting',
                'task_id_field': 'celery_posting_task_id',
                'task_callable': post_comments_task,
                'enabled': not process.generate_only  # Only spawn if not generate_only
            }
        ]

        for stage in stages:
            if not stage['enabled']:
                skipped.append({
                    'process_id': str(process.id),
                    'stage': stage['name'],
                    'reason': 'disabled (generate_only=True)'
                })
                continue

            # Get current task ID for this stage
            current_task_id = getattr(process, stage['task_id_field'], None)

            # Check if task is still running (unless force_immediate)
            is_running = False
            if not force_immediate and current_task_id:
                try:
                    task_result = AsyncResult(current_task_id)
                    # Task is running if state is PENDING, STARTED, or RETRY
                    is_running = task_result.state in ['PENDING', 'STARTED', 'RETRY']

                    if is_running:
                        skipped.append({
                            'process_id': str(process.id),
                            'stage': stage['name'],
                            'task_id': current_task_id,
                            'state': task_result.state,
                            'reason': 'already running'
                        })
                        continue
                except Exception as e:
                    logger.warning(
                        f"Could not check status of {stage['name']} task {current_task_id} "
                        f"for process {process.id}: {e}. Will spawn new task."
                    )

            # Spawn new task for this stage
            try:
                new_task = stage['task_callable'].delay(str(process.id))

                # Update task ID in process
                setattr(process, stage['task_id_field'], new_task.id)

                spawned.append({
                    'process_id': str(process.id),
                    'process_name': process.name,
                    'stage': stage['name'],
                    'task_id': new_task.id
                })

                logger.info(
                    f"Spawned {stage['name']} task {new_task.id} "
                    f"for process {process.id} ('{process.name}')"
                )

            except Exception as e:
                logger.error(
                    f"Failed to spawn {stage['name']} task for process {process.id}: {e}"
                )
                skipped.append({
                    'process_id': str(process.id),
                    'stage': stage['name'],
                    'reason': f'spawn failed: {str(e)}'
                })

        return {'spawned': spawned, 'skipped': skipped}


# Register the task as a Celery task
@celery_app.task(
    name='src.tasks.scheduler.trigger_monitoring_pipeline',
    queue='scheduler'
)
def trigger_monitoring_pipeline(force_immediate: bool = False) -> Dict[str, Any]:
    """
    Periodically trigger pipeline stage tasks for all active monitoring processes.

    This task runs every few minutes and ensures continuous monitoring by:
    1. Finding all running monitoring processes
    2. For each process, checking each pipeline stage
    3. Spawning stage tasks only if no task is currently running for that stage

    This implements continuous monitoring without double-spawning tasks.

    Args:
        force_immediate: If True, immediately trigger for newly started processes
                        (called from MonitoringService after process.start_process)

    Returns:
        Dictionary with spawned task counts and details
    """
    try:
        # Create instance of SchedulingTask and run async method
        scheduler = SchedulingTask()
        result = asyncio.run(scheduler._trigger_pipeline_async(force_immediate=force_immediate))
        return result
    except Exception as exc:
        logger.error(f"Pipeline trigger failed: {exc}")
        raise
