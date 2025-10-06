"""
Article monitoring task for myMoment scraping.

This module implements background tasks for monitoring myMoment articles,
discovering new content, and triggering comment generation workflows.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass

from celery import current_task
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from src.tasks.worker import celery_app, BaseTask
from src.models.monitoring_process import MonitoringProcess
from src.models.mymoment_login import MyMomentLogin
from src.models.ai_comment import AIComment
from src.services.scraper_service import ScraperService, ScrapingConfig, ArticleMetadata, SessionContext
from src.services.monitoring_service import MonitoringService
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)


@dataclass
class MonitoringResult:
    """Result of article monitoring operation."""
    process_id: uuid.UUID
    articles_discovered: int
    new_articles: int
    errors: List[str]
    execution_time_seconds: float
    status: str  # success, partial, failed


class ArticleMonitoringTask(BaseTask):
    """Base class for article monitoring tasks."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()


@celery_app.task(
    bind=True,
    base=ArticleMonitoringTask,
    name='src.tasks.article_monitor.start_monitoring_process',
    queue='monitoring',
    max_retries=3,
    default_retry_delay=60
)
def start_monitoring_process(self, process_id: str) -> Dict[str, Any]:
    """
    Start article monitoring for a specific monitoring process.

    Args:
        process_id: UUID of the monitoring process to start

    Returns:
        Dictionary with monitoring results
    """
    try:
        result = asyncio.run(self._start_monitoring_process_async(uuid.UUID(process_id)))
        return {
            'process_id': str(result.process_id),
            'articles_discovered': result.articles_discovered,
            'new_articles': result.new_articles,
            'errors': result.errors,
            'execution_time_seconds': result.execution_time_seconds,
            'status': result.status
        }
    except Exception as exc:
        logger.error(f"Article monitoring failed for process {process_id}: {exc}")
        self.retry(exc=exc, countdown=60)


class ArticleMonitoringTaskHelpers:
    """Helper methods for ArticleMonitoringTask - mixed into the task class."""

    async def _start_monitoring_process_async(self, process_id: uuid.UUID) -> MonitoringResult:
        """Async implementation of monitoring process start."""
        start_time = datetime.utcnow()
        errors = []

        session = await self.get_async_session()
        async with session:
            try:
                # Get monitoring process
                result = await session.execute(
                    select(MonitoringProcess).where(MonitoringProcess.id == process_id)
                )
                process = result.scalar_one_or_none()

                if not process:
                    raise ValueError(f"Monitoring process {process_id} not found")

                # Update process status to running
                await self._update_process_status(session, process_id, "running", start_time)

                # Get associated myMoment logins
                logins = await self._get_process_logins(session, process_id)
                if not logins:
                    raise ValueError(f"No active myMoment logins found for process {process_id}")

                logger.info(f"Starting article monitoring for process {process.name} with {len(logins)} logins")

                # Initialize scraping service with config from settings
                scraping_config = ScrapingConfig.from_settings()

                async with ScraperService(session, scraping_config) as scraper:
                    # Initialize sessions for all logins
                    session_contexts = await scraper.initialize_sessions_for_process(
                        process_id, process.user_id
                    )

                    # Discover articles using all session contexts
                    discovered_articles = []
                    for context in session_contexts:
                        try:
                            login_articles = await self._discover_articles_for_context(
                                scraper, context, process
                            )
                            discovered_articles.extend(login_articles)
                            logger.info(f"Discovered {len(login_articles)} articles for login {context.username}")
                        except Exception as e:
                            error_msg = f"Failed to discover articles for login {context.username}: {str(e)}"
                            errors.append(error_msg)
                            logger.error(error_msg)

                # Process discovered articles
                new_articles_count = await self._process_discovered_articles(
                    session, process_id, discovered_articles, logins
                )

                # Update process statistics
                await self._update_process_statistics(
                    session, process_id, len(discovered_articles), new_articles_count
                )

                # Schedule comment generation for new articles
                if new_articles_count > 0:
                    await self._schedule_comment_generation(process_id, new_articles_count)

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                status = "success" if not errors else "partial"

                logger.info(f"Article monitoring completed for process {process.name}: "
                          f"{len(discovered_articles)} discovered, {new_articles_count} new, "
                          f"{len(errors)} errors")

                return MonitoringResult(
                    process_id=process_id,
                    articles_discovered=len(discovered_articles),
                    new_articles=new_articles_count,
                    errors=errors,
                    execution_time_seconds=execution_time,
                    status=status
                )

            except Exception as e:
                error_msg = f"Article monitoring failed: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

                # Update process status to failed
                await self._update_process_status(session, process_id, "failed")

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                return MonitoringResult(
                    process_id=process_id,
                    articles_discovered=0,
                    new_articles=0,
                    errors=errors,
                    execution_time_seconds=execution_time,
                    status="failed"
                )

    async def _update_process_status(self, session: AsyncSession, process_id: uuid.UUID,
                                   status: str, timestamp: Optional[datetime] = None):
        """Update monitoring process status."""
        update_data = {"status": status, "last_activity_at": timestamp or datetime.utcnow()}

        if status == "running":
            update_data["started_at"] = timestamp
        elif status in ["stopped", "completed", "failed"]:
            update_data["stopped_at"] = timestamp or datetime.utcnow()

        await session.execute(
            update(MonitoringProcess)
            .where(MonitoringProcess.id == process_id)
            .values(**update_data)
        )
        await session.commit()

    async def _get_process_logins(self, session: AsyncSession, process_id: uuid.UUID) -> List[MyMomentLogin]:
        """Get active myMoment logins for a monitoring process."""
        from src.models.monitoring_process_login import MonitoringProcessLogin

        result = await session.execute(
            select(MyMomentLogin)
            .join(MonitoringProcessLogin, MonitoringProcessLogin.mymoment_login_id == MyMomentLogin.id)
            .where(
                and_(
                    MonitoringProcessLogin.monitoring_process_id == process_id,
                    MonitoringProcessLogin.is_active == True,
                    MyMomentLogin.is_active == True
                )
            )
        )
        return list(result.scalars().all())

    async def _discover_articles_for_context(self, scraper: ScraperService,
                                           context: SessionContext, process: MonitoringProcess) -> List[ArticleMetadata]:
        """Discover articles for a specific session context."""
        try:
            # Map monitoring process filters to scraper parameters
            tab = process.tab_filter or "alle"
            category = str(process.category_filter) if process.category_filter else None
            limit = 20  # Default limit per login

            # Use scraper service to discover articles
            articles = await scraper.discover_new_articles(
                context=context,
                tab=tab,
                category=category,
                limit=limit
            )

            return articles

        except Exception as e:
            logger.error(f"Failed to discover articles for context {context.username}: {e}")
            return []

    async def _process_discovered_articles(self, session: AsyncSession, process_id: uuid.UUID,
                                         articles: List[ArticleMetadata],
                                         logins: List[MyMomentLogin]) -> int:
        """Process discovered articles and create AIComment records with article snapshots."""
        new_articles_count = 0

        # Get process details for comments
        result = await session.execute(
            select(MonitoringProcess).where(MonitoringProcess.id == process_id)
        )
        process = result.scalar_one()

        # Initialize scraper to fetch full article content
        scraping_config = ScrapingConfig.from_settings()
        scraper = ScraperService(session, scraping_config)

        for article_metadata in articles:
            try:
                # Create AIComment record with article snapshot for each login
                # This represents the article being "discovered" and queued for comment generation
                for login in logins:
                    # Check if this specific article+login combination already exists
                    existing_comment = await session.execute(
                        select(AIComment).where(
                            and_(
                                AIComment.mymoment_article_id == article_metadata.id,
                                AIComment.monitoring_process_id == process_id,
                                AIComment.mymoment_login_id == login.id
                            )
                        )
                    )

                    if existing_comment.scalar_one_or_none():
                        continue  # Article already discovered for this login+process combination

                    # Fetch full article content for this login
                    article_content_data = None
                    try:
                        # Initialize session for this login
                        context = await scraper.initialize_session_for_login(
                            login_id=login.id,
                            user_id=process.user_id
                        )

                        # Fetch full article content
                        article_content_data = await scraper.get_article_content(
                            context=context,
                            article_id=article_metadata.id
                        )

                        # Cleanup session
                        await scraper.cleanup_session(login.id)
                    except Exception as e:
                        logger.error(f"Failed to fetch article content for {article_metadata.id}: {e}")
                        # Continue with metadata only if content fetch fails
                        article_content_data = None

                    ai_comment = AIComment(
                        # Article snapshot fields
                        mymoment_article_id=article_metadata.id,
                        article_title=article_metadata.title,
                        article_author=article_metadata.author,
                        article_category=article_metadata.category_id,
                        article_url=article_metadata.url,
                        article_content=article_content_data.get('content', '') if article_content_data else '',
                        article_raw_html=article_content_data.get('full_html', '') if article_content_data else '',
                        article_published_at=None,  # Not available from metadata
                        article_scraped_at=datetime.utcnow(),

                        # Process and login attribution
                        user_id=process.user_id,
                        mymoment_login_id=login.id,
                        monitoring_process_id=process_id,

                        # Comment fields (will be filled by comment generator)
                        comment_content=None,
                        status='discovered',  # Status: discovered -> generated -> posted
                        ai_model_name=None,
                        ai_provider_name=None
                    )

                    session.add(ai_comment)
                    new_articles_count += 1

                logger.debug(f"Created AIComment with full content for article: {article_metadata.title}")

            except Exception as e:
                logger.error(f"Failed to process article {article_metadata.id}: {e}")
                continue

        await session.commit()
        return new_articles_count

    async def _update_process_statistics(self, session: AsyncSession, process_id: uuid.UUID,
                                       articles_discovered: int, new_articles: int):
        """Update monitoring process statistics."""
        await session.execute(
            update(MonitoringProcess)
            .where(MonitoringProcess.id == process_id)
            .values(
                articles_discovered=MonitoringProcess.articles_discovered + articles_discovered,
                last_activity_at=datetime.utcnow()
            )
        )
        await session.commit()

    async def _schedule_comment_generation(self, process_id: uuid.UUID, new_articles_count: int):
        """Schedule comment generation tasks for new articles."""
        # Import here to avoid circular import
        from src.tasks.comment_generator import generate_comments_for_process

        # Schedule comment generation task
        generate_comments_for_process.apply_async(
            args=[str(process_id)],
            countdown=10,  # Wait seconds before starting comment generation
            queue='comments'
        )

        logger.info(f"Scheduled comment generation for {new_articles_count} new articles "
                   f"in process {process_id}")

    async def _stop_monitoring_process_async(self, process_id: uuid.UUID) -> Dict[str, Any]:
        """Async implementation of monitoring process stop."""
        session = await self.get_async_session()
        async with session:
            # Update process status to stopped
            await self._update_process_status(session, process_id, "stopped")

            logger.info(f"Stopped monitoring process {process_id}")

            return {
                'process_id': str(process_id),
                'status': 'stopped',
                'stopped_at': datetime.utcnow().isoformat()
            }


# Mix helpers into the task class
for name in dir(ArticleMonitoringTaskHelpers):
    if not name.startswith('_') or name.startswith('_start_') or name.startswith('_stop_') or name.startswith('_update_') or name.startswith('_get_') or name.startswith('_discover_') or name.startswith('_process_') or name.startswith('_schedule_'):
        if callable(getattr(ArticleMonitoringTaskHelpers, name)):
            setattr(ArticleMonitoringTask, name, getattr(ArticleMonitoringTaskHelpers, name))


@celery_app.task(
    bind=True,
    base=ArticleMonitoringTask,
    name='src.tasks.article_monitor.stop_monitoring_process',
    queue='monitoring'
)
def stop_monitoring_process(self, process_id: str) -> Dict[str, Any]:
    """
    Stop article monitoring for a specific monitoring process.

    Args:
        process_id: UUID of the monitoring process to stop

    Returns:
        Dictionary with stop operation results
    """
    try:
        result = asyncio.run(self._stop_monitoring_process_async(uuid.UUID(process_id)))
        return result
    except Exception as exc:
        logger.error(f"Failed to stop monitoring process {process_id}: {exc}")
        raise


@celery_app.task(
    name='src.tasks.article_monitor.periodic_monitoring_check',
    queue='monitoring'
)
def periodic_monitoring_check() -> Dict[str, Any]:
    """
    Periodic task to check and restart monitoring processes.

    This task runs periodically to:
    - Check for processes that should be running
    - Restart failed processes if within retry limits
    - Update process health status
    """
    try:
        result = asyncio.run(_periodic_monitoring_check_async())
        return result
    except Exception as exc:
        logger.error(f"Periodic monitoring check failed: {exc}")
        raise

async def _periodic_monitoring_check_async() -> Dict[str, Any]:
    """Async implementation of periodic monitoring check."""
    db_manager = get_database_manager()
    sessionmaker = await db_manager.create_sessionmaker()

    checked_processes = 0
    restarted_processes = 0
    errors = []

    async with sessionmaker() as session:
        # Find processes that should be running but aren't
        result = await session.execute(
            select(MonitoringProcess).where(
                and_(
                    MonitoringProcess.status.in_(["running", "failed"]),
                    MonitoringProcess.is_active == True
                )
            )
        )
        processes = result.scalars().all()

        for process in processes:
            checked_processes += 1

            try:
                # Check if process has exceeded maximum duration
                if process.started_at and process.max_duration_minutes:
                    max_runtime = timedelta(minutes=process.max_duration_minutes)
                    if datetime.utcnow() - process.started_at > max_runtime:
                        # Process exceeded maximum runtime, stop it
                        await _update_process_status_sync(session, process.id, "completed")
                        logger.info(f"Process {process.name} completed after exceeding max duration")
                        continue

                # For failed processes, consider restarting if errors are below threshold
                if process.status == "failed" and process.errors_encountered < 3:
                    # Restart the process
                    start_monitoring_process.apply_async(
                        args=[str(process.id)],
                        queue='monitoring'
                    )
                    restarted_processes += 1
                    logger.info(f"Restarted failed process {process.name}")

            except Exception as e:
                error_msg = f"Error checking process {process.name}: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

    logger.info(f"Periodic monitoring check completed: {checked_processes} checked, "
               f"{restarted_processes} restarted")

    return {
        'checked_processes': checked_processes,
        'restarted_processes': restarted_processes,
        'errors': errors,
        'timestamp': datetime.utcnow().isoformat()
    }


async def _update_process_status_sync(session: AsyncSession, process_id: uuid.UUID, status: str):
    """Helper function to update process status synchronously."""
    await session.execute(
        update(MonitoringProcess)
        .where(MonitoringProcess.id == process_id)
        .values(status=status, last_activity_at=datetime.utcnow())
    )
    await session.commit()


@celery_app.task(
    name='src.tasks.article_monitor.cleanup_old_articles',
    queue='monitoring'
)
def cleanup_old_articles() -> Dict[str, Any]:
    """
    Clean up old article records based on retention policy.

    This task removes articles that are older than the configured retention period.
    """
    try:
        result = asyncio.run(_cleanup_old_articles_async())
        return result
    except Exception as exc:
        logger.error(f"Article cleanup failed: {exc}")
        raise

async def _cleanup_old_articles_async() -> Dict[str, Any]:
    """Async implementation of AIComment cleanup."""
    db_manager = get_database_manager()
    sessionmaker = await db_manager.create_sessionmaker()

    # Default retention: 365 days (can be configured via environment)
    retention_days = 365
    cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

    deleted_comments = 0

    async with sessionmaker() as session:
        # Find AIComment records older than retention period
        result = await session.execute(
            select(AIComment).where(AIComment.created_at < cutoff_date)
        )
        old_comments = result.scalars().all()

        for ai_comment in old_comments:
            try:
                # Delete AIComment record (includes article snapshot and comment)
                await session.delete(ai_comment)
                deleted_comments += 1
            except Exception as e:
                logger.error(f"Failed to delete AIComment {ai_comment.id}: {e}")
                continue

        await session.commit()

    logger.info(f"AIComment cleanup completed: {deleted_comments} records deleted")

    return {
        'deleted_articles': deleted_comments,  # Keep key name for compatibility
        'cutoff_date': cutoff_date.isoformat(),
        'timestamp': datetime.utcnow().isoformat()
    }
