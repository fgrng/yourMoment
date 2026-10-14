"""
Article content preparation task for myMoment monitoring processes.

This module implements Task 2 of the refactored monitoring pipeline:
- Reads one discovered article (status='discovered')
- Fetches its full content through the platform interface
- Updates the AIComment record with content and status='prepared'
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass

from celery.exceptions import MaxRetriesExceededError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, update

from src.tasks.worker import celery_app, BaseTask
from src.tasks.process_guards import get_process_skip_reason
from src.models.ai_comment import AIComment
from src.platforms import ArticleContent, ArticleRef, PlatformAccount, connect
from src.platforms.accounts import load_platform_account
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

    async def _load_platform_account(self, snapshot: ArticleSnapshot) -> PlatformAccount:
        """Load the decrypted platform account of the AIComment."""
        session = await self.get_async_session()
        async with session:
            account = await load_platform_account(
                session, snapshot.mymoment_login_id, snapshot.user_id
            )
        if account is None:
            raise RuntimeError(
                f"Platform account {snapshot.mymoment_login_id} not found or inactive"
            )
        return account

    async def _update_article_content(
        self,
        ai_comment_id: uuid.UUID,
        content: ArticleContent,
        expected_status: str = "discovered",
    ) -> bool:
        """
        Update single AIComment record with article content.

        Uses Pattern 3: Quick update with short-lived session (< 50ms).

        Args:
            ai_comment_id: AIComment UUID to update
            content: Article content read from the platform

        Returns:
            True if update successful, False otherwise
        """
        try:
            session = await self.get_async_session()
            async with session:
                values = {
                    "article_content": content.body_text,
                    "article_raw_html": content.body_html,
                    "article_title": content.title,
                    "article_scraped_at": datetime.utcnow(),
                    "status": "prepared",
                    "error_message": None,
                    "failed_at": None,
                }
                # The schema still stores myMoment's integer IDs
                category_id = _as_int(content.category)
                if category_id is not None:
                    values["article_category"] = category_id
                arrangement_id = _as_int(content.extra.get("arrangement"))
                if arrangement_id is not None:
                    values["article_task_id"] = arrangement_id

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

        try:
            account = await self._load_platform_account(snapshot)
            async with connect(account) as platform:
                content = await platform.fetch_article(
                    ArticleRef(id=snapshot.mymoment_article_id, url=snapshot.article_url)
                )

            updated = await self._update_article_content(
                snapshot.ai_comment_id,
                content,
                expected_status="discovered",
            )
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "prepared" if updated else "skipped",
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }

        except Exception as exc:
            logger.error(
                "Preparation failed for article %s: %s",
                snapshot.mymoment_article_id,
                exc,
            )
            raise


def _as_int(value: Optional[str]) -> Optional[int]:
    """Convert a platform ID string to the integer column, None if not numeric."""
    if value is None or not value.isdigit():
        return None
    return int(value)


def _normalize_identifier(identifier: Any, compat_args: tuple[Any, ...]) -> str:
    """Accept both Celery invocation and legacy direct task calls in tests."""
    if isinstance(identifier, str):
        return identifier
    if compat_args and isinstance(compat_args[0], str):
        return compat_args[0]
    return str(identifier)


@celery_app.task(
    bind=True,
    base=ArticlePreparationTask,
    name='src.tasks.article_preparation.prepare_article_content',
    queue='preparation',
    max_retries=3,
    default_retry_delay=60
)
def prepare_article_content(self, ai_comment_id: Any, *compat_args: Any) -> Dict[str, Any]:
    """Prepare one AIComment row for downstream generation."""
    ai_comment_id = _normalize_identifier(ai_comment_id, compat_args)
    try:
        logger.info(f"Starting single-article preparation task for AIComment {ai_comment_id}")
        result = asyncio.run(self._prepare_single_article_async(uuid.UUID(ai_comment_id)))
        logger.info(f"Single-article preparation task completed: {result}")
        return result
    except Exception as exc:
        countdown = min(60 * (2 ** self.request.retries), 300)
        logger.warning(
            f"Single-article preparation task failed, retrying "
            f"(attempt {self.request.retries + 1}/{self.max_retries}, countdown {countdown}s) "
            f"for AIComment {ai_comment_id}: {exc}"
        )
        try:
            self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            logger.error(f"Max retries exhausted for single-article preparation of AIComment {ai_comment_id}")
            asyncio.run(
                self._mark_article_failed(
                    uuid.UUID(ai_comment_id),
                    f"Max retries exhausted: {exc}",
                    expected_status="discovered",
                )
            )
            return {
                "ai_comment_id": ai_comment_id,
                "status": "failed",
                "reason": f"Max retries exhausted: {exc}",
                "execution_time_seconds": 0,
            }
