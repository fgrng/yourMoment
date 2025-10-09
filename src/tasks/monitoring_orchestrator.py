"""
Monitoring orchestrator task for coordinating the monitoring pipeline.

This module implements the orchestration logic for the refactored monitoring pipeline:
- Coordinates execution of the four pipeline stages (discover → prepare → generate → post)
- Manages stage transitions and progress tracking
- Enforces process timeouts (max_duration_minutes)
- Handles generate_only mode
- Aggregates errors and statistics across stages
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dataclasses import dataclass

from celery import current_task
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from src.tasks.worker import celery_app, BaseTask
from src.models.monitoring_process import MonitoringProcess
from src.models.ai_comment import AIComment
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)


@dataclass
class ProcessStatus:
    """Current status of a monitoring process."""
    process_id: uuid.UUID
    user_id: uuid.UUID
    started_at: Optional[datetime]
    max_duration_minutes: int
    generate_only: bool
    is_running: bool
    current_stage: Optional[str]


@dataclass
class StageStats:
    """Statistics for AIComments by status."""
    discovered: int = 0
    prepared: int = 0
    generated: int = 0
    posted: int = 0
    failed: int = 0
    total: int = 0


class MonitoringOrchestratorTask(BaseTask):
    """Task for orchestrating the monitoring workflow across pipeline stages."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()

    async def _get_process_status(
        self,
        process_id: uuid.UUID
    ) -> Optional[ProcessStatus]:
        """
        Read MonitoringProcess and return current status.

        Args:
            process_id: Monitoring process UUID

        Returns:
            ProcessStatus object or None if not found
        """
        session = await self.get_async_session()
        async with session:
            result = await session.execute(
                select(MonitoringProcess).where(
                    MonitoringProcess.id == process_id
                )
            )
            process = result.scalar_one_or_none()

            if not process:
                return None

            return ProcessStatus(
                process_id=process.id,
                user_id=process.user_id,
                started_at=process.started_at,
                max_duration_minutes=process.max_duration_minutes,
                generate_only=process.generate_only,
                is_running=process.is_running,
                current_stage=None  # Will be determined by orchestrator
            )

    async def _count_ai_comments_by_status(
        self,
        process_id: uuid.UUID
    ) -> StageStats:
        """
        Count AIComments by status for the monitoring process.

        Args:
            process_id: Monitoring process UUID

        Returns:
            StageStats with counts per status
        """
        session = await self.get_async_session()
        async with session:
            # Query to count AIComments grouped by status
            result = await session.execute(
                select(
                    AIComment.status,
                    func.count(AIComment.id)
                ).where(
                    AIComment.monitoring_process_id == process_id
                ).group_by(AIComment.status)
            )

            status_counts = dict(result.fetchall())

            stats = StageStats(
                discovered=status_counts.get('discovered', 0),
                prepared=status_counts.get('prepared', 0),
                generated=status_counts.get('generated', 0),
                posted=status_counts.get('posted', 0),
                failed=status_counts.get('failed', 0)
            )
            stats.total = sum([
                stats.discovered,
                stats.prepared,
                stats.generated,
                stats.posted,
                stats.failed
            ])

            return stats

    async def _update_process_metadata(
        self,
        process_id: uuid.UUID,
        stage: str,
        stats: StageStats
    ) -> None:
        """
        Update MonitoringProcess metadata with current stage and stats.

        Note: This is optional - MonitoringProcess doesn't have dedicated fields
        for stage tracking yet. Currently just logs the information.

        Args:
            process_id: Monitoring process UUID
            stage: Current pipeline stage
            stats: Statistics from _count_ai_comments_by_status
        """
        logger.info(
            f"Process {process_id} stage '{stage}' stats: "
            f"discovered={stats.discovered}, prepared={stats.prepared}, "
            f"generated={stats.generated}, posted={stats.posted}, "
            f"failed={stats.failed}, total={stats.total}"
        )

    async def _check_timeout(
        self,
        process_status: ProcessStatus
    ) -> bool:
        """
        Check if the monitoring process has exceeded its timeout.

        Args:
            process_status: Current process status

        Returns:
            True if process has timed out, False otherwise
        """
        if not process_status.started_at:
            return False

        elapsed_time = datetime.utcnow() - process_status.started_at
        max_duration = timedelta(minutes=process_status.max_duration_minutes)

        if elapsed_time > max_duration:
            logger.warning(
                f"Process {process_status.process_id} exceeded max duration "
                f"({process_status.max_duration_minutes} minutes). "
                f"Elapsed: {elapsed_time.total_seconds() / 60:.1f} minutes"
            )
            return True

        return False

    async def _stop_process(
        self,
        process_id: uuid.UUID,
        reason: str
    ) -> None:
        """
        Stop the monitoring process.

        Args:
            process_id: Monitoring process UUID
            reason: Reason for stopping
        """
        session = await self.get_async_session()
        async with session:
            result = await session.execute(
                select(MonitoringProcess).where(
                    MonitoringProcess.id == process_id
                )
            )
            process = result.scalar_one_or_none()

            if process:
                process.status = 'failed'
                if reason == "Pipeline complete" or reason == "Generate-only mode complete":
                    process.status = 'stopped'
                process.stopped_at = datetime.utcnow()
                await session.commit()
                logger.info(f"Process {process_id} stopped: {reason}")

    async def _handle_discover_stage(
        self,
        process_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Handle the discovery stage: run article discovery and schedule preparation.

        Args:
            process_id: Monitoring process UUID

        Returns:
            Result dictionary from discovery task
        """
        from src.tasks.article_discovery import ArticleDiscoveryTask

        logger.info(f"Orchestrator: Starting discovery stage for process {process_id}")

        # Run discovery task
        discovery_task = ArticleDiscoveryTask()
        result = await discovery_task._discover_articles_async(process_id)

        logger.info(
            f"Orchestrator: Discovery complete for process {process_id}. "
            f"Discovered: {result.get('discovered', 0)}, Errors: {len(result.get('errors', []))}"
        )

        # Schedule preparation stage if articles were discovered
        if result.get('discovered', 0) > 0:
            logger.info(f"Orchestrator: Scheduling preparation stage for process {process_id}")
            celery_app.send_task(
                'src.tasks.monitoring_orchestrator.orchestrate_monitoring_process',
                args=[str(process_id), 'prepare']
            )
        else:
            logger.warning(f"Orchestrator: No articles discovered for process {process_id}. Pipeline complete.")
            await self._stop_process(process_id, "No articles discovered")

        return result

    async def _handle_prepare_stage(
        self,
        process_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Handle the preparation stage: prepare content and schedule generation.

        Args:
            process_id: Monitoring process UUID

        Returns:
            Result dictionary from preparation task
        """
        from src.tasks.article_preparation import ArticlePreparationTask

        logger.info(f"Orchestrator: Starting preparation stage for process {process_id}")

        # Run preparation task
        preparation_task = ArticlePreparationTask()
        result = await preparation_task._prepare_content_async(process_id)

        logger.info(
            f"Orchestrator: Preparation complete for process {process_id}. "
            f"Prepared: {result.get('prepared', 0)}, Failed: {result.get('failed', 0)}"
        )

        # Schedule generation stage if articles were prepared
        if result.get('prepared', 0) > 0:
            logger.info(f"Orchestrator: Scheduling generation stage for process {process_id}")
            celery_app.send_task(
                'src.tasks.monitoring_orchestrator.orchestrate_monitoring_process',
                args=[str(process_id), 'generate']
            )
        else:
            logger.warning(f"Orchestrator: No articles prepared for process {process_id}. Pipeline complete.")
            await self._stop_process(process_id, "No articles prepared successfully")

        return result

    async def _handle_generate_stage(
        self,
        process_id: uuid.UUID,
        process_status: ProcessStatus
    ) -> Dict[str, Any]:
        """
        Handle the generation stage: generate comments and conditionally schedule posting.

        Args:
            process_id: Monitoring process UUID
            process_status: Current process status (to check generate_only flag)

        Returns:
            Result dictionary from generation task
        """
        from src.tasks.comment_generation import CommentGenerationTask

        logger.info(f"Orchestrator: Starting generation stage for process {process_id}")

        # Run generation task
        generation_task = CommentGenerationTask()
        result = await generation_task._generate_comments_async(process_id)

        logger.info(
            f"Orchestrator: Generation complete for process {process_id}. "
            f"Generated: {result.get('generated', 0)}, Failed: {result.get('failed', 0)}"
        )

        # Check generate_only flag
        if process_status.generate_only:
            logger.info(
                f"Orchestrator: Process {process_id} is in generate_only mode. "
                "Stopping after generation."
            )
            await self._stop_process(process_id, "Generate-only mode complete")
        elif result.get('generated', 0) > 0:
            # Schedule posting stage
            logger.info(f"Orchestrator: Scheduling posting stage for process {process_id}")
            celery_app.send_task(
                'src.tasks.monitoring_orchestrator.orchestrate_monitoring_process',
                args=[str(process_id), 'post']
            )
        else:
            logger.warning(f"Orchestrator: No comments generated for process {process_id}. Pipeline complete.")
            await self._stop_process(process_id, "No comments generated successfully")

        return result

    async def _handle_post_stage(
        self,
        process_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Handle the posting stage: post comments and mark process complete.

        Args:
            process_id: Monitoring process UUID

        Returns:
            Result dictionary from posting task
        """
        from src.tasks.comment_posting import CommentPostingTask

        logger.info(f"Orchestrator: Starting posting stage for process {process_id}")

        # Run posting task
        posting_task = CommentPostingTask()
        result = await posting_task._post_comments_async(process_id)

        logger.info(
            f"Orchestrator: Posting complete for process {process_id}. "
            f"Posted: {result.get('posted', 0)}, Failed: {result.get('failed', 0)}"
        )

        # Mark process complete
        await self._stop_process(process_id, "Pipeline complete")

        return result

    async def _orchestrate_async(
        self,
        process_id: uuid.UUID,
        stage: str
    ) -> Dict[str, Any]:
        """
        Main orchestration logic for monitoring workflow.

        Coordinates pipeline stages:
        - stage='discover': Run discovery, schedule preparation
        - stage='prepare': Run preparation, schedule generation
        - stage='generate': Run generation, conditionally schedule posting
        - stage='post': Run posting, mark complete

        Args:
            process_id: Monitoring process UUID
            stage: Pipeline stage to execute ('discover', 'prepare', 'generate', 'post')

        Returns:
            Result dictionary with overall workflow status
        """
        start_time = datetime.utcnow()

        try:
            # Get process status
            process_status = await self._get_process_status(process_id)
            if not process_status:
                error_msg = f"Process {process_id} not found"
                logger.error(f"Orchestrator: {error_msg}")
                return {
                    'success': False,
                    'stage': stage,
                    'error': error_msg
                }

            # Check if process is still running
            if not process_status.is_running:
                logger.warning(
                    f"Orchestrator: Process {process_id} is not running. "
                    f"Skipping stage '{stage}'."
                )
                return {
                    'success': False,
                    'stage': stage,
                    'error': 'Process is not running'
                }

            # Check timeout
            if await self._check_timeout(process_status):
                await self._stop_process(process_id, "Max duration exceeded")
                return {
                    'success': False,
                    'stage': stage,
                    'error': 'Process timeout exceeded'
                }

            # Get current statistics
            stats = await self._count_ai_comments_by_status(process_id)
            await self._update_process_metadata(process_id, stage, stats)

            # Execute stage handler
            result = {}
            if stage == 'discover':
                result = await self._handle_discover_stage(process_id)
            elif stage == 'prepare':
                result = await self._handle_prepare_stage(process_id)
            elif stage == 'generate':
                result = await self._handle_generate_stage(process_id, process_status)
            elif stage == 'post':
                result = await self._handle_post_stage(process_id)
            else:
                error_msg = f"Unknown stage: {stage}"
                logger.error(f"Orchestrator: {error_msg}")
                return {
                    'success': False,
                    'stage': stage,
                    'error': error_msg
                }

            # Calculate execution time
            execution_time = datetime.utcnow() - start_time
            execution_time_ms = int(execution_time.total_seconds() * 1000)

            # Add orchestration metadata to result
            result['success'] = True
            result['stage'] = stage
            result['execution_time_ms'] = execution_time_ms
            result['stats'] = {
                'discovered': stats.discovered,
                'prepared': stats.prepared,
                'generated': stats.generated,
                'posted': stats.posted,
                'failed': stats.failed,
                'total': stats.total
            }

            logger.info(
                f"Orchestrator: Stage '{stage}' for process {process_id} "
                f"completed in {execution_time_ms}ms"
            )

            return result

        except Exception as e:
            execution_time = datetime.utcnow() - start_time
            execution_time_ms = int(execution_time.total_seconds() * 1000)

            logger.exception(
                f"Orchestrator: Error in stage '{stage}' for process {process_id}: {str(e)}"
            )

            return {
                'success': False,
                'stage': stage,
                'error': str(e),
                'execution_time_ms': execution_time_ms
            }


# Register Celery task
@celery_app.task(
    bind=True,
    name='src.tasks.monitoring_orchestrator.orchestrate_monitoring_process',
    base=MonitoringOrchestratorTask,
    max_retries=0,  # Orchestrator should not retry automatically
    acks_late=True,
    reject_on_worker_lost=True
)
def orchestrate_monitoring_process(self, process_id: str, stage: str) -> Dict[str, Any]:
    """
    Orchestrate monitoring workflow stages.

    Args:
        process_id: Monitoring process UUID as string
        stage: Pipeline stage to execute:
            - 'discover': Run article discovery, schedule preparation
            - 'prepare': Run content preparation, schedule generation
            - 'generate': Run comment generation, conditionally schedule posting
            - 'post': Run comment posting, mark complete

    Returns:
        Result dictionary with workflow status, statistics, and errors
    """
    # Convert process_id to UUID
    process_uuid = uuid.UUID(process_id)

    logger.info(
        f"Orchestrator task started: process_id={process_id}, stage={stage}, "
        f"task_id={current_task.request.id if current_task else 'N/A'}"
    )

    # Run async orchestration
    result = asyncio.run(self._orchestrate_async(process_uuid, stage))

    logger.info(
        f"Orchestrator task completed: process_id={process_id}, stage={stage}, "
        f"success={result.get('success', False)}"
    )

    return result
