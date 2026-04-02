"""
Article content preparation task for myMoment monitoring processes.

This module implements Task 2 of the refactored monitoring pipeline:
- Reads discovered articles (status='discovered') for a monitoring process
- Fetches full content for each article using ScraperService
- Updates AIComment records with content and status='prepared'
- Authenticates once per login and reuses the HTTP session for all article fetches
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from celery import current_task
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select, update

from src.tasks.worker import celery_app, BaseTask
from src.tasks.process_guards import get_process_skip_reason
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
    monitoring_process_id: Optional[uuid.UUID]
    user_id: uuid.UUID
    status: str


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
                    monitoring_process_id=comment.monitoring_process_id,
                    user_id=comment.user_id,
                    status=comment.status,
                )
                for comment in ai_comments
            ]

        # Session closed automatically (< 100ms)
        logger.info(f"Read {len(snapshots)} discovered articles for process {process_id}")
        return snapshots

    async def _read_article_snapshot(self, ai_comment_id: uuid.UUID) -> Optional[ArticleSnapshot]:
        """Read a single AIComment as a lightweight snapshot."""
        session = await self.get_async_session()
        async with session:
            ai_comment = await session.get(AIComment, ai_comment_id)
            if not ai_comment:
                return None

            return ArticleSnapshot(
                ai_comment_id=ai_comment.id,
                mymoment_article_id=ai_comment.mymoment_article_id,
                article_title=ai_comment.article_title,
                article_url=ai_comment.article_url,
                mymoment_login_id=ai_comment.mymoment_login_id,
                monitoring_process_id=ai_comment.monitoring_process_id,
                user_id=ai_comment.user_id,
                status=ai_comment.status,
            )

    async def _prepare_articles_for_login(
        self,
        articles: List[ArticleSnapshot],
        login_id: uuid.UUID,
        user_id: uuid.UUID,
        scraping_config: ScrapingConfig,
    ) -> tuple[int, int, List[str]]:
        """
        Fetch content for all articles belonging to a single login.

        Authenticates with myMoment ONCE and reuses the HTTP session for all
        article fetches, avoiding repeated authentication overhead.

        Args:
            articles: List of ArticleSnapshot objects for this login
            login_id: MyMomentLogin UUID
            user_id: User UUID
            scraping_config: Scraping configuration

        Returns:
            Tuple of (prepared_count, failed_count, errors)
        """
        prepared_count = 0
        failed_count = 0
        errors = []

        auth_start = datetime.utcnow()
        session = await self.get_async_session()
        async with session:
            async with ScraperService(session, scraping_config) as scraper:
                # Authenticate ONCE for all articles of this login
                try:
                    context = await scraper.initialize_session_for_login(
                        login_id=login_id,
                        user_id=user_id
                    )
                    auth_time = (datetime.utcnow() - auth_start).total_seconds()
                    logger.info(
                        f"Authenticated login {login_id} in {auth_time:.2f}s — "
                        f"fetching content for {len(articles)} article(s)"
                    )
                except Exception as e:
                    error_msg = f"Authentication failed for login {login_id}: {e}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    for article in articles:
                        await self._mark_article_failed(article.ai_comment_id, error_msg)
                    return 0, len(articles), errors

                # Fetch content for each article, reusing the authenticated session
                for idx, article in enumerate(articles):
                    fetch_start = datetime.utcnow()
                    try:
                        skip_reason = await get_process_skip_reason(
                            self.get_async_session,
                            article.monitoring_process_id,
                        )
                        if skip_reason:
                            logger.info(
                                "Skipping preparation for AIComment %s: %s",
                                article.ai_comment_id,
                                skip_reason,
                            )
                            continue

                        content_data = await scraper.get_article_content(
                            context=context,
                            article_id=article.mymoment_article_id
                        )
                        fetch_time = (datetime.utcnow() - fetch_start).total_seconds()

                        if content_data:
                            success = await self._update_article_content(
                                ai_comment_id=article.ai_comment_id,
                                content_data=content_data
                            )
                            if success:
                                prepared_count += 1
                                logger.info(
                                    f"[{idx + 1}/{len(articles)}] Prepared: {article.article_title!r} "
                                    f"({fetch_time:.2f}s)"
                                )
                            else:
                                error_msg = "Failed to update AIComment record"
                                await self._mark_article_failed(article.ai_comment_id, error_msg)
                                errors.append(f"Article {article.mymoment_article_id}: {error_msg}")
                                failed_count += 1
                        else:
                            error_msg = "No content returned by scraper"
                            await self._mark_article_failed(article.ai_comment_id, error_msg)
                            errors.append(f"Article {article.mymoment_article_id}: {error_msg}")
                            failed_count += 1
                            logger.warning(
                                f"[{idx + 1}/{len(articles)}] No content for "
                                f"article {article.mymoment_article_id} ({fetch_time:.2f}s)"
                            )

                    except Exception as e:
                        fetch_time = (datetime.utcnow() - fetch_start).total_seconds()
                        error_msg = (
                            f"Preparation failed for article {article.mymoment_article_id}: {e}"
                        )
                        errors.append(error_msg)
                        logger.error(f"{error_msg} ({fetch_time:.2f}s)")
                        await self._mark_article_failed(article.ai_comment_id, str(e))
                        failed_count += 1

        return prepared_count, failed_count, errors

    async def _update_article_content(
        self,
        ai_comment_id: uuid.UUID,
        content_data: Dict[str, Any],
        expected_status: str = "discovered",
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
                values = {
                    "article_content": content_data.get("content", ""),
                    "article_raw_html": content_data.get("full_html", ""),
                    "article_scraped_at": datetime.utcnow(),
                    "status": "prepared",
                    "error_message": None,
                    "failed_at": None,
                }
                if "title" in content_data:
                    values["article_title"] = content_data["title"]
                if content_data.get("category_id") is not None:
                    values["article_category"] = content_data["category_id"]
                if content_data.get("task_id") is not None:
                    values["article_task_id"] = content_data["task_id"]

                result = await session.execute(
                    update(AIComment)
                    .where(
                        and_(
                            AIComment.id == ai_comment_id,
                            AIComment.status == expected_status,
                        )
                    )
                    .values(**values)
                )

                if result.rowcount:
                    await session.commit()
                    logger.debug(f"Updated article content for AIComment {ai_comment_id}")
                    return True

                ai_comment = await session.get(AIComment, ai_comment_id)
                if not ai_comment:
                    logger.error(f"AIComment {ai_comment_id} not found")
                    return False
                if ai_comment.status in {"prepared", "generated", "posted"}:
                    logger.info(
                        "Skipping stale preparation update for AIComment %s already in status=%s",
                        ai_comment_id,
                        ai_comment.status,
                    )
                    return True
                return False

        except Exception as e:
            logger.error(f"Failed to update AIComment {ai_comment_id}: {e}")
            return False

    async def _mark_article_failed(
        self,
        ai_comment_id: uuid.UUID,
        error_message: str,
        expected_status: str = "discovered",
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
                result = await session.execute(
                    update(AIComment)
                    .where(
                        and_(
                            AIComment.id == ai_comment_id,
                            AIComment.status == expected_status,
                        )
                    )
                    .values(
                        status="failed",
                        error_message=error_message,
                        failed_at=datetime.utcnow(),
                    )
                )

                if result.rowcount:
                    await session.commit()
                    logger.info(f"Marked AIComment {ai_comment_id} as failed: {error_message}")
                    return True

                ai_comment = await session.get(AIComment, ai_comment_id)
                if not ai_comment:
                    logger.error(f"AIComment {ai_comment_id} not found")
                    return False
                logger.info(
                    "Skipping stale failure mark for AIComment %s with current status=%s",
                    ai_comment_id,
                    ai_comment.status,
                )
                return ai_comment.status != expected_status

        except Exception as e:
            logger.error(f"Failed to mark AIComment {ai_comment_id} as failed: {e}")
            return False

    async def _prepare_single_article_async(self, ai_comment_id: uuid.UUID) -> Dict[str, Any]:
        """Prepare one article by fetching content and moving discovered -> prepared."""
        start_time = datetime.utcnow()
        snapshot = await self._read_article_snapshot(ai_comment_id)
        if not snapshot:
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "skipped",
                "reason": "missing",
                "execution_time_seconds": 0,
            }

        if snapshot.status != "discovered":
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "skipped",
                "reason": f"already_{snapshot.status}",
                "execution_time_seconds": 0,
            }

        skip_reason = await get_process_skip_reason(
            self.get_async_session,
            snapshot.monitoring_process_id,
        )
        if skip_reason:
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "skipped",
                "reason": skip_reason,
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }

        scraping_config = ScrapingConfig.from_settings()

        try:
            session = await self.get_async_session()
            async with session:
                async with ScraperService(session, scraping_config) as scraper:
                    context = await scraper.initialize_session_for_login(
                        login_id=snapshot.mymoment_login_id,
                        user_id=snapshot.user_id,
                    )
                    content_data = await scraper.get_article_content(
                        context=context,
                        article_id=snapshot.mymoment_article_id,
                    )
                    await scraper.cleanup_session(snapshot.mymoment_login_id)

            if not content_data:
                error_msg = "No content returned by scraper"
                await self._mark_article_failed(
                    snapshot.ai_comment_id,
                    error_msg,
                    expected_status="discovered",
                )
                return {
                    "ai_comment_id": str(ai_comment_id),
                    "status": "failed",
                    "reason": error_msg,
                    "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
                }

            updated = await self._update_article_content(
                snapshot.ai_comment_id,
                content_data,
                expected_status="discovered",
            )
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "prepared" if updated else "skipped",
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }

        except Exception as exc:
            error_msg = f"Preparation failed for article {snapshot.mymoment_article_id}: {exc}"
            logger.error(error_msg)
            await self._mark_article_failed(
                snapshot.ai_comment_id,
                error_msg,
                expected_status="discovered",
            )
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "failed",
                "reason": str(exc),
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }


def _normalize_identifier(identifier: Any, compat_args: tuple[Any, ...]) -> str:
    """Accept both Celery invocation and legacy direct task calls in tests."""
    if isinstance(identifier, str):
        return identifier
    if compat_args and isinstance(compat_args[0], str):
        return compat_args[0]
    return str(identifier)

    async def _prepare_content_async(self, process_id: uuid.UUID) -> Dict[str, Any]:
        """
        Main async method for article content preparation.

        Groups discovered articles by login_id so each login authenticates
        once and reuses its HTTP session for all article fetches.

        1. Read all discovered AIComments (short session)
        2. Group articles by login_id
        3. For each login: authenticate once, fetch all articles, update DB

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
            skip_reason = await get_process_skip_reason(
                self.get_async_session,
                process_id,
            )
            if skip_reason:
                return {
                    'prepared': 0,
                    'failed': 0,
                    'errors': [],
                    'execution_time_seconds': 0,
                    'status': 'skipped',
                    'reason': skip_reason,
                }

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

            # Step 2: Group by login_id to authenticate once per login
            articles_by_login: Dict[uuid.UUID, List[ArticleSnapshot]] = {}
            for article in articles:
                articles_by_login.setdefault(article.mymoment_login_id, []).append(article)

            scraping_config = ScrapingConfig.from_settings()

            logger.info(
                f"Starting preparation for {len(articles)} article(s) across "
                f"{len(articles_by_login)} login(s) for process {process_id}"
            )

            # Step 3: Process each login's articles with a shared auth session
            for login_id, login_articles in articles_by_login.items():
                user_id = login_articles[0].user_id
                p, f, errs = await self._prepare_articles_for_login(
                    login_articles, login_id, user_id, scraping_config
                )
                prepared_count += p
                failed_count += f
                errors.extend(errs)

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            logger.info(
                f"Article preparation completed for process {process_id}: "
                f"{prepared_count} prepared, {failed_count} failed, {execution_time:.2f}s"
            )

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
    name='src.tasks.article_preparation.prepare_article_content',
    queue='preparation',
    max_retries=3,
    default_retry_delay=120
)
def prepare_article_content(self, ai_comment_id: Any, *compat_args: Any) -> Dict[str, Any]:
    """Prepare one AIComment row for downstream generation."""
    try:
        ai_comment_id = _normalize_identifier(ai_comment_id, compat_args)
        logger.info(f"Starting single-article preparation task for AIComment {ai_comment_id}")
        result = asyncio.run(self._prepare_single_article_async(uuid.UUID(ai_comment_id)))
        logger.info(f"Single-article preparation task completed: {result}")
        return result
    except Exception as exc:
        logger.error(f"Single-article preparation task failed for AIComment {ai_comment_id}: {exc}")
        self.retry(exc=exc, countdown=120)


@celery_app.task(
    bind=True,
    base=ArticlePreparationTask,
    name='src.tasks.article_preparation.prepare_content_of_articles',
    queue='preparation',
    max_retries=3,
    default_retry_delay=120
)
def prepare_content_of_articles(self, process_id: Any, *compat_args: Any) -> Dict[str, Any]:
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
        process_id = _normalize_identifier(process_id, compat_args)
        logger.info(f"Starting article preparation task for process {process_id}")
        result = asyncio.run(self._prepare_content_async(uuid.UUID(process_id)))
        logger.info(f"Article preparation task completed: {result}")
        return result

    except Exception as exc:
        logger.error(f"Article preparation task failed for process {process_id}: {exc}")
        # Retry with exponential backoff
        self.retry(exc=exc, countdown=120)
