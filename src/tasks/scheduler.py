"""
Task scheduling and coordination service for yourMoment application.

This module implements essential periodic tasks for system health checks
and basic maintenance operations.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from celery.result import AsyncResult

from src.tasks.worker import celery_app, BaseTask
from src.models.ai_comment import AIComment
from src.models.monitoring_process import MonitoringProcess
from src.models.mymoment_session import MyMomentSession
from src.config.database import get_database_manager
from src.config.settings import get_settings

logger = logging.getLogger(__name__)


class SchedulingTask(BaseTask):
    """Base class for scheduling tasks."""

    DISCOVERY_LEASE_SECONDS = 30
    DISCOVERY_MIN_BACKOFF_SECONDS = 30
    DISCOVERY_MAX_BACKOFF_SECONDS = 600

    def __init__(self):
        self.db_manager = get_database_manager()
        self.settings = get_settings()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()

    async def _trigger_pipeline_async(
        self,
        force_immediate: bool = False,
        process_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Async implementation of pipeline triggering.

        Args:
            force_immediate: Legacy flag retained for compatibility. Durable
                            backpressure and in-flight guards still apply.
            process_ids: Optional list of process IDs. If provided, only these
                        processes are checked/dispatched (process-scoped mode).
        """
        start_time = datetime.utcnow()

        # Import automated scheduler task
        from src.tasks.article_discovery import discover_articles

        spawned_tasks = []
        skipped_tasks = []
        errors = []
        trigger_mode = "process_scoped" if process_ids is not None else "periodic_global"

        async with await self.get_async_session() as session:
            try:
                running_processes: List[MonitoringProcess] = []

                if process_ids is not None:
                    normalized_process_ids: List[uuid.UUID] = []
                    for process_id in process_ids:
                        try:
                            normalized_process_ids.append(uuid.UUID(str(process_id)))
                        except (ValueError, TypeError, AttributeError):
                            error_msg = f"Invalid process ID received for pipeline trigger: {process_id}"
                            errors.append(error_msg)
                            logger.warning(error_msg)

                    if normalized_process_ids:
                        result = await session.execute(
                            select(MonitoringProcess)
                            .where(
                                and_(
                                    MonitoringProcess.status == "running",
                                    MonitoringProcess.is_active == True,
                                    MonitoringProcess.id.in_(normalized_process_ids),
                                )
                            )
                        )
                        running_processes = result.scalars().all()

                    logger.info(
                        "Pipeline trigger mode=process_scoped requested=%d valid=%d running=%d force_immediate=%s",
                        len(process_ids),
                        len(normalized_process_ids),
                        len(running_processes),
                        force_immediate,
                    )
                else:
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

                    logger.info(
                        "Pipeline trigger mode=periodic_global running=%d force_immediate=%s",
                        len(running_processes),
                        force_immediate,
                    )

                # For each process, check and spawn discovery only. Per-article
                # prepare/generate/post tasks are chained from discovery.
                discovery_metrics = []
                for process in running_processes:
                    try:
                        process_spawned = await self._spawn_stage_tasks_for_process(
                            session,
                            process,
                            discover_articles,
                            force_immediate=force_immediate
                        )

                        spawned_tasks.extend(process_spawned['spawned'])
                        skipped_tasks.extend(process_spawned['skipped'])
                        if process_spawned.get('discovery_metrics'):
                            discovery_metrics.append(process_spawned['discovery_metrics'])

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
                    f"{len(skipped_tasks)} tasks skipped, "
                    f"{len(errors)} errors"
                )

                return {
                    'trigger_mode': trigger_mode,
                    'processes_checked': len(running_processes),
                    'tasks_spawned': len(spawned_tasks),
                    'tasks_skipped': len(skipped_tasks),
                    'spawned_details': spawned_tasks,
                    'skipped_details': skipped_tasks,
                    'discovery_metrics': discovery_metrics,
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
                    'trigger_mode': trigger_mode,
                    'processes_checked': 0,
                    'tasks_spawned': 0,
                    'tasks_skipped': 0,
                    'spawned_details': [],
                    'skipped_details': [],
                    'discovery_metrics': [],
                    'errors': errors,
                    'execution_time_seconds': execution_time,
                    'timestamp': datetime.utcnow().isoformat()
                }

    @staticmethod
    def _utcnow() -> datetime:
        """Return an aware UTC timestamp for scheduler durability fields."""
        return datetime.now(timezone.utc)

    def _compute_discovery_backoff_seconds(self, empty_streak: int) -> int:
        """Compute exponential discovery backoff with a floor and cap."""
        base_interval = max(
            int(self.settings.monitoring.ARTICLE_DISCOVERY_INTERVAL_SECONDS),
            self.DISCOVERY_MIN_BACKOFF_SECONDS,
        )
        return min(
            base_interval * (2 ** max(empty_streak - 1, 0)),
            self.DISCOVERY_MAX_BACKOFF_SECONDS,
        )

    async def _count_discovered_backlog(
        self,
        session: AsyncSession,
        process_id: uuid.UUID,
    ) -> int:
        """Count exact discovered-stage backlog for a monitoring process."""
        result = await session.execute(
            select(func.count(AIComment.id)).where(
                and_(
                    AIComment.monitoring_process_id == process_id,
                    AIComment.status == "discovered",
                )
            )
        )
        return int(result.scalar_one() or 0)

    def _extract_discovered_count(self, task_result: AsyncResult) -> Optional[int]:
        """Extract the discovered count from a terminal discovery task result."""
        result_payload = task_result.result
        if isinstance(result_payload, dict):
            discovered = result_payload.get("discovered")
            try:
                return int(discovered) if discovered is not None else None
            except (TypeError, ValueError):
                return None
        return None

    def _refresh_discovery_state_from_terminal_result(
        self,
        process: MonitoringProcess,
        current_task_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        Consume terminal discovery task state to update durable cooldown/backoff.

        The scheduler sees the previous discovery task's result; we convert that
        into the next eligibility window before evaluating whether to enqueue again.
        """
        if not current_task_id:
            return {
                "task_state": None,
                "last_discovered_count": None,
            }

        try:
            task_result = AsyncResult(current_task_id)
            task_state = task_result.state
            last_discovered_count = None

            if task_state in {"SUCCESS", "FAILURE", "REVOKED"}:
                now_utc = self._utcnow()
                discovered_count = self._extract_discovered_count(task_result)
                last_discovered_count = discovered_count

                if discovered_count is not None:
                    if discovered_count == 0:
                        process.discovery_empty_streak = (process.discovery_empty_streak or 0) + 1
                        delay_seconds = self._compute_discovery_backoff_seconds(
                            process.discovery_empty_streak
                        )
                        process.next_discovery_at = now_utc + timedelta(seconds=delay_seconds)
                    else:
                        process.discovery_empty_streak = 0
                        process.next_discovery_at = now_utc
                else:
                    # FAILURE or REVOKED with no parseable result: apply a minimum
                    # cooldown (one base interval) to prevent tight-loop retries on
                    # persistent scraping/auth errors. Do not increment the streak
                    # because this is not a zero-hit discovery, it is an error.
                    min_delay = max(
                        int(self.settings.monitoring.ARTICLE_DISCOVERY_INTERVAL_SECONDS),
                        self.DISCOVERY_MIN_BACKOFF_SECONDS,
                    )
                    process.next_discovery_at = now_utc + timedelta(seconds=min_delay)

                process.discovery_queued_at = None
                process.celery_discovery_task_id = None

                logger.info(
                    "Discovery task %s for process %s reached terminal state %s (discovered=%s, streak=%s, next_discovery_at=%s)",
                    current_task_id,
                    process.id,
                    task_state,
                    discovered_count,
                    process.discovery_empty_streak,
                    process.next_discovery_at.isoformat() if process.next_discovery_at else None,
                )

            return {
                "task_state": task_state,
                "last_discovered_count": last_discovered_count,
            }
        except Exception as exc:
            logger.warning(
                "Could not refresh terminal state for discovery task %s on process %s: %s",
                current_task_id,
                process.id,
                exc,
            )
            return {
                "task_state": None,
                "last_discovered_count": None,
            }

    def _build_discovery_metrics(
        self,
        process: MonitoringProcess,
        pending_backlog_count: int,
        skip_reason: Optional[str],
        last_discovered_count: Optional[int],
    ) -> Dict[str, Any]:
        """Build scheduler discovery metrics for a single process."""
        next_eligible_at = MonitoringProcess._normalize_utc(process.next_discovery_at)
        queued_at = MonitoringProcess._normalize_utc(process.discovery_queued_at)

        if queued_at is not None:
            lease_until = queued_at + timedelta(seconds=self.DISCOVERY_LEASE_SECONDS)
            if next_eligible_at is None or lease_until > next_eligible_at:
                next_eligible_at = lease_until

        return {
            "process_id": str(process.id),
            "process_name": process.name,
            "last_discovered_count": last_discovered_count,
            "zero_hit_streak": int(process.discovery_empty_streak or 0),
            "pending_backlog_count": pending_backlog_count,
            "next_eligible_discovery_at": (
                next_eligible_at.isoformat() if next_eligible_at is not None else None
            ),
            "skip_reason": skip_reason,
        }

    async def _spawn_stage_tasks_for_process(
        self,
        session: AsyncSession,
        process: MonitoringProcess,
        discover_articles_task,
        force_immediate: bool = False
    ) -> Dict[str, Any]:
        """
        Spawn discovery task for a single process, checking if the task is already running.

        Args:
            session: Database session used for backlog counting and state persistence
            process: MonitoringProcess instance
            discover_articles_task: Discovery task callable
            force_immediate: Legacy flag retained for compatibility. Durable
                            backpressure and in-flight guards still apply.

        Returns:
            Dictionary with 'spawned' and 'skipped' task lists
        """
        spawned = []
        skipped = []
        discovery_metrics: Optional[Dict[str, Any]] = None

        stages = [
            {
                'name': 'discovery',
                'task_id_field': 'celery_discovery_task_id',
                'task_callable': discover_articles_task,
                'enabled': True
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

            current_task_id = getattr(process, stage['task_id_field'], None)
            terminal_state = self._refresh_discovery_state_from_terminal_result(
                process,
                current_task_id,
            )
            current_task_id = getattr(process, stage['task_id_field'], None)
            last_discovered_count = terminal_state["last_discovered_count"]
            pending_backlog_count = await self._count_discovered_backlog(session, process.id)

            if pending_backlog_count > 0:
                reason = 'pending_discovered_backlog'
                skipped.append({
                    'process_id': str(process.id),
                    'stage': stage['name'],
                    'reason': reason,
                    'pending_backlog_count': pending_backlog_count,
                })
                discovery_metrics = self._build_discovery_metrics(
                    process,
                    pending_backlog_count,
                    reason,
                    last_discovered_count,
                )
                logger.info(
                    "Skipping discovery for process %s due to discovered backlog=%d",
                    process.id,
                    pending_backlog_count,
                )
                continue

            now_utc = self._utcnow()
            next_discovery_at = MonitoringProcess._normalize_utc(process.next_discovery_at)
            if next_discovery_at is not None and next_discovery_at > now_utc:
                reason = 'cooldown_active'
                skipped.append({
                    'process_id': str(process.id),
                    'stage': stage['name'],
                    'reason': reason,
                    'next_discovery_at': next_discovery_at.isoformat(),
                })
                discovery_metrics = self._build_discovery_metrics(
                    process,
                    pending_backlog_count,
                    reason,
                    last_discovered_count,
                )
                logger.info(
                    "Skipping discovery for process %s due to cooldown until %s",
                    process.id,
                    next_discovery_at.isoformat(),
                )
                continue

            queued_at = MonitoringProcess._normalize_utc(process.discovery_queued_at)
            lease_cutoff = now_utc - timedelta(seconds=self.DISCOVERY_LEASE_SECONDS)
            if queued_at is not None and queued_at > lease_cutoff:
                reason = 'discovery_lease_active'
                skipped.append({
                    'process_id': str(process.id),
                    'stage': stage['name'],
                    'reason': reason,
                    'discovery_queued_at': queued_at.isoformat(),
                })
                discovery_metrics = self._build_discovery_metrics(
                    process,
                    pending_backlog_count,
                    reason,
                    last_discovered_count,
                )
                logger.info(
                    "Skipping discovery for process %s due to active queue lease set at %s",
                    process.id,
                    queued_at.isoformat(),
                )
                continue

            # Get current task ID for this stage
            current_task_id = getattr(process, stage['task_id_field'], None)

            # Check if task is still running. This remains an additional guard,
            # not the primary backpressure mechanism.
            is_running = False
            if current_task_id:
                try:
                    task_result = AsyncResult(current_task_id)
                    # PENDING means "unknown or queued" in Celery — it is also the
                    # state of expired results. Only treat STARTED and RETRY as
                    # genuinely running to avoid permanently blocking re-spawning
                    # when a task has completed and its result TTL has expired.
                    is_running = task_result.state in ['STARTED', 'RETRY']

                    if is_running:
                        skipped.append({
                            'process_id': str(process.id),
                            'stage': stage['name'],
                            'task_id': current_task_id,
                            'state': task_result.state,
                            'reason': 'already running'
                        })
                        discovery_metrics = self._build_discovery_metrics(
                            process,
                            pending_backlog_count,
                            'already running',
                            last_discovered_count,
                        )
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
                process.discovery_queued_at = now_utc

                spawned.append({
                    'process_id': str(process.id),
                    'process_name': process.name,
                    'stage': stage['name'],
                    'task_id': new_task.id
                })
                discovery_metrics = self._build_discovery_metrics(
                    process,
                    pending_backlog_count,
                    None,
                    last_discovered_count,
                )

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
                discovery_metrics = self._build_discovery_metrics(
                    process,
                    pending_backlog_count,
                    f'spawn failed: {str(e)}',
                    last_discovered_count,
                )

        return {
            'spawned': spawned,
            'skipped': skipped,
            'discovery_metrics': discovery_metrics,
        }


# Register the task as a Celery task
@celery_app.task(
    name='src.tasks.scheduler.trigger_monitoring_pipeline',
    queue='scheduler'
)
def trigger_monitoring_pipeline(
    force_immediate: bool = False,
    process_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Periodically trigger pipeline stage tasks for all active monitoring processes.

    This task runs every few minutes and ensures continuous monitoring by:
    1. Finding all running monitoring processes (or only process_ids if provided)
    2. For each process, checking the discovery stage
    3. Spawning discovery only if no discovery task is currently running

    Discovery is the only scheduler-driven stage. Per-article prepare/generate/post
    tasks are chained from newly discovered AIComment rows.

    Args:
        force_immediate: Legacy flag retained for backward compatibility.
                        Durable backpressure and in-flight guards still apply.
        process_ids: Optional list of process IDs to scope the trigger to specific
                    processes instead of a global scan. Preferred over
                    force_immediate for process-startup kickoffs.

    Returns:
        Dictionary with spawned task counts and details
    """
    try:
        if process_ids is not None:
            logger.info(
                "Received process-scoped pipeline trigger for %d process ids (force_immediate=%s)",
                len(process_ids),
                force_immediate,
            )
        else:
            logger.info(
                "Received periodic global pipeline trigger (force_immediate=%s)",
                force_immediate,
            )

        # Create instance of SchedulingTask and run async method
        scheduler = SchedulingTask()
        result = asyncio.run(
            scheduler._trigger_pipeline_async(
                force_immediate=force_immediate,
                process_ids=process_ids,
            )
        )
        return result
    except Exception as exc:
        logger.error(f"Pipeline trigger failed: {exc}")
        raise
