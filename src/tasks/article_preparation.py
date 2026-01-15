"""
Article content preparation task for myMoment monitoring processes.

This module implements Task 2 of the refactored monitoring pipeline:
- Reads discovered articles (status='discovered') for a monitoring process
- Fetches full content for each article using ScraperService
- Updates AIComment records with content and status='prepared'
- Uses Pattern 3: Iterative Single-Record Updates with short DB sessions
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from celery import current_task
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from src.tasks.worker import celery_app, BaseTask
from src.models.ai_comment import AIComment
from src.models.mymoment_login import MyMomentLogin
from src.services.scraper_service import ScraperService, ScrapingConfig
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)


@dataclass
class ArticleSnapshot:
    """Snapshot of discovered article for preparation."""
    ai_comment_id: uuid.UUID
    mymoment_article_id: str
    article_title: str
    article_url: str
    mymoment_login_id: uuid.UUID
    user_id: uuid.UUID


class ArticlePreparationTask(BaseTask):
    """Task for preparing article content (fetching full text and HTML)."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()

    async def _read_discovered_articles(self, process_id: uuid.UUID) -> List[ArticleSnapshot]:
        """
        Read discovered AIComment records for a monitoring process.

        Uses short-lived session to read all discovered articles.
        Creates lightweight snapshots to avoid holding DB session during scraping.

        Args:
            process_id: Monitoring process UUID

        Returns:
            List of ArticleSnapshot objects
        """
        session = await self.get_async_session()
        async with session:
            # Read all discovered AIComments for this process
            result = await session.execute(
                select(AIComment).where(
                    and_(
                        AIComment.monitoring_process_id == process_id,
                        AIComment.status == 'discovered',
                        AIComment.is_active == True
                    )
                )
            )
            ai_comments = result.scalars().all()

            # Create lightweight snapshots
            snapshots = [
                ArticleSnapshot(
                    ai_comment_id=comment.id,
                    mymoment_article_id=comment.mymoment_article_id,
                    article_title=comment.article_title,
                    article_url=comment.article_url,
                    mymoment_login_id=comment.mymoment_login_id,
                    user_id=comment.user_id
                )
                for comment in ai_comments
            ]

        # Session closed automatically (< 100ms)
        logger.info(f"Read {len(snapshots)} discovered articles for process {process_id}")
        return snapshots

    async def _scrape_single_article_content(
        self,
        article_id: str,
        login_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> Optional[Dict[str, Any]]:
        """
        Scrape full content for a single article.

        This method runs OUTSIDE any long-lived database session.
        Initializes a temporary session, fetches content, cleans up.

        Args:
            article_id: MyMoment article ID
            login_id: MyMomentLogin UUID
            user_id: User UUID

        Returns:
            Dictionary with article content data or None if failed
        """
        try:
            # Initialize scraper with config (outside DB session)
            scraping_config = ScrapingConfig.from_settings()

            # Create temporary session for scraping
            session = await self.get_async_session()
            async with session:
                async with ScraperService(session, scraping_config) as scraper:
                    try:
                        # Initialize myMoment session for this login
                        context = await scraper.initialize_session_for_login(
                            login_id=login_id,
                            user_id=user_id
                        )

                        # Fetch article content (HTTP request outside DB transaction)
                        content_data = await scraper.get_article_content(
                            context=context,
                            article_id=article_id
                        )

                        # Cleanup session
                        await scraper.cleanup_session(login_id)

                        if content_data:
                            logger.debug(f"Scraped content for article {article_id}")
                            return content_data
                        else:
                            logger.warning(f"No content returned for article {article_id}")
                            return None

                    except Exception as e:
                        logger.error(f"Failed to scrape article {article_id}: {e}")
                        return None

        except Exception as e:
            logger.error(f"Scraping session failed for article {article_id}: {e}")
            return None

    async def _update_article_content(
        self,
        ai_comment_id: uuid.UUID,
        content_data: Dict[str, Any]
    ) -> bool:
        """
        Update single AIComment record with article content.

        Uses Pattern 3: Quick update with short-lived session (< 50ms).

        Args:
            ai_comment_id: AIComment UUID to update
            content_data: Dictionary with article content fields

        Returns:
            True if update successful, False otherwise
        """
        try:
            session = await self.get_async_session()
            async with session:
                # Read AIComment record
                ai_comment = await session.get(AIComment, ai_comment_id)

                if not ai_comment:
                    logger.error(f"AIComment {ai_comment_id} not found")
                    return False

                # Update content fields
                ai_comment.article_content = content_data.get('content', '')
                ai_comment.article_raw_html = content_data.get('full_html', '')

                # Update metadata if available
                if 'title' in content_data:
                    ai_comment.article_title = content_data['title']

                # Update category and task IDs extracted from detail page
                if 'category_id' in content_data and content_data['category_id'] is not None:
                    ai_comment.article_category = content_data['category_id']
                if 'task_id' in content_data and content_data['task_id'] is not None:
                    ai_comment.article_task_id = content_data['task_id']

                # Note: article_published_at is not available from scraper yet
                # It would need to be added to ScraperService.get_article_content()

                # Update scraping timestamp
                ai_comment.article_scraped_at = datetime.utcnow()

                # Update status to 'prepared'
                ai_comment.status = 'prepared'

                # Commit single record
                await session.commit()

            # Session closed automatically (< 50ms)
            logger.debug(f"Updated article content for AIComment {ai_comment_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to update AIComment {ai_comment_id}: {e}")
            return False

    async def _mark_article_failed(
        self,
        ai_comment_id: uuid.UUID,
        error_message: str
    ) -> bool:
        """
        Mark AIComment as failed with error message.

        Args:
            ai_comment_id: AIComment UUID to mark as failed
            error_message: Error description

        Returns:
            True if update successful
        """
        try:
            session = await self.get_async_session()
            async with session:
                ai_comment = await session.get(AIComment, ai_comment_id)

                if not ai_comment:
                    logger.error(f"AIComment {ai_comment_id} not found")
                    return False

                # Mark as failed
                ai_comment.status = 'failed'
                ai_comment.error_message = error_message
                ai_comment.failed_at = datetime.utcnow()

                await session.commit()

            logger.info(f"Marked AIComment {ai_comment_id} as failed: {error_message}")
            return True

        except Exception as e:
            logger.error(f"Failed to mark AIComment {ai_comment_id} as failed: {e}")
            return False

    async def _prepare_content_async(self, process_id: uuid.UUID) -> Dict[str, Any]:
        """
        Main async method for article content preparation.

        Implements the preparation workflow using Pattern 3:
        1. Read all discovered AIComments (short session)
        2. For each article: scrape content (outside DB session)
        3. For each article: update AIComment (short session < 50ms)
        4. Apply rate limiting between fetches

        Args:
            process_id: Monitoring process UUID

        Returns:
            Result dictionary with counts and errors
        """
        start_time = datetime.utcnow()
        errors = []
        prepared_count = 0
        failed_count = 0

        try:
            # Step 1: Read discovered articles (short-lived session)
            articles = await self._read_discovered_articles(process_id)

            if not articles:
                logger.info(f"No discovered articles found for process {process_id}")
                return {
                    'prepared': 0,
                    'failed': 0,
                    'errors': [],
                    'execution_time_seconds': 0,
                    'status': 'success'
                }

            logger.info(f"Starting preparation for {len(articles)} articles in process {process_id}")

            # Get rate limit config
            scraping_config = ScrapingConfig.from_settings()
            rate_limit_delay = scraping_config.rate_limit_delay

            # Step 2 & 3: For each article - scrape and update iteratively
            for idx, article in enumerate(articles):
                try:
                    # Scrape article content (outside DB session)
                    content_data = await self._scrape_single_article_content(
                        article_id=article.mymoment_article_id,
                        login_id=article.mymoment_login_id,
                        user_id=article.user_id
                    )

                    if content_data:
                        # Update AIComment with content (short DB session)
                        success = await self._update_article_content(
                            ai_comment_id=article.ai_comment_id,
                            content_data=content_data
                        )

                        if success:
                            prepared_count += 1
                            logger.info(f"Prepared article {idx + 1}/{len(articles)}: {article.article_title}")
                        else:
                            # Update failed but we got content - mark as failed
                            error_msg = "Failed to update AIComment record"
                            await self._mark_article_failed(article.ai_comment_id, error_msg)
                            errors.append(f"Article {article.mymoment_article_id}: {error_msg}")
                            failed_count += 1
                    else:
                        # Scraping failed - mark as failed
                        error_msg = "Failed to scrape article content"
                        await self._mark_article_failed(article.ai_comment_id, error_msg)
                        errors.append(f"Article {article.mymoment_article_id}: {error_msg}")
                        failed_count += 1

                    # Apply rate limiting between fetches (except after last article)
                    if idx < len(articles) - 1:
                        await asyncio.sleep(rate_limit_delay)

                except Exception as e:
                    # Individual article failure - log and continue
                    error_msg = f"Preparation failed for article {article.mymoment_article_id}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)

                    # Mark as failed
                    await self._mark_article_failed(article.ai_comment_id, str(e))
                    failed_count += 1

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            logger.info(f"Article preparation completed for process {process_id}: "
                       f"{prepared_count} prepared, "
                       f"{failed_count} failed, "
                       f"{execution_time:.2f}s")

            return {
                'prepared': prepared_count,
                'failed': failed_count,
                'errors': errors,
                'execution_time_seconds': execution_time,
                'status': 'success' if failed_count == 0 else 'partial'
            }

        except Exception as e:
            error_msg = f"Article preparation failed: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            return {
                'prepared': prepared_count,
                'failed': failed_count,
                'errors': errors,
                'execution_time_seconds': execution_time,
                'status': 'failed'
            }


@celery_app.task(
    bind=True,
    base=ArticlePreparationTask,
    name='src.tasks.article_preparation.prepare_content_of_articles',
    queue='preparation',
    max_retries=3,
    default_retry_delay=120
)
def prepare_content_of_articles(self, process_id: str) -> Dict[str, Any]:
    """
    Celery task wrapper for article content preparation.

    This is the entry point for the preparation stage of the monitoring pipeline.
    Fetches full content for discovered articles and updates AIComment records
    with status='prepared'.

    Args:
        process_id: Monitoring process UUID as string

    Returns:
        Dictionary with preparation results:
        - prepared: Number of articles successfully prepared
        - failed: Number of articles that failed
        - errors: List of error messages
        - execution_time_seconds: Task execution time
        - status: 'success', 'partial', or 'failed'
    """
    try:
        logger.info(f"Starting article preparation task for process {process_id}")
        result = asyncio.run(self._prepare_content_async(uuid.UUID(process_id)))
        logger.info(f"Article preparation task completed: {result}")
        return result

    except Exception as exc:
        logger.error(f"Article preparation task failed for process {process_id}: {exc}")
        # Retry with exponential backoff
        self.retry(exc=exc, countdown=120)
