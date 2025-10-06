"""
Comment posting task for posting AI-generated comments to myMoment.

This module implements background tasks for posting AI comments to myMoment
using authenticated sessions and updating the AIComment status to 'posted'.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from celery import current_task
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update

from src.tasks.worker import celery_app, BaseTask
from src.models.monitoring_process import MonitoringProcess
from src.models.mymoment_login import MyMomentLogin
from src.models.ai_comment import AIComment
from src.services.scraper_service import ScraperService, ScrapingConfig
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)


@dataclass
class CommentPostingResult:
    """Result of comment posting operation."""
    process_id: uuid.UUID
    comments_posted: int
    errors: List[str]
    execution_time_seconds: float
    status: str  # success, partial, failed


class CommentPostingTask(BaseTask):
    """Base class for comment posting tasks."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()

    async def _post_comments_for_process_async(self, process_id: uuid.UUID) -> CommentPostingResult:
        """Async implementation of comment posting using AIComment model."""
        start_time = datetime.utcnow()
        errors = []
        comments_posted = 0

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

                # Get AIComment records that need posting (status='generated')
                ai_comments = await self._get_comments_needing_posting(session, process_id)

                if not ai_comments:
                    logger.info(f"No comments need posting for process {process.name}")
                    execution_time = (datetime.utcnow() - start_time).total_seconds()
                    return CommentPostingResult(
                        process_id=process_id,
                        comments_posted=0,
                        errors=[],
                        execution_time_seconds=execution_time,
                        status="success"
                    )

                logger.info(f"Posting {len(ai_comments)} comments for process {process.name}")

                # Initialize scraping service for posting comments
                scraping_config = ScrapingConfig.from_settings()

                async with ScraperService(session, scraping_config) as scraper:
                    # Initialize sessions for all logins in the process
                    session_contexts = await scraper.initialize_sessions_for_process(
                        process_id, process.user_id
                    )

                    # Group comments by login for posting
                    for ai_comment in ai_comments:
                        try:
                            # Find the session context for this comment's login
                            session_context = next(
                                (ctx for ctx in session_contexts if ctx.login_id == ai_comment.mymoment_login_id),
                                None
                            )

                            if not session_context:
                                error_msg = f"No session found for login {ai_comment.mymoment_login_id}"
                                errors.append(error_msg)
                                logger.error(error_msg)
                                continue

                            # Post comment to myMoment
                            post_success = await scraper.post_comment(
                                context=session_context,
                                article_id=ai_comment.mymoment_article_id,
                                comment_content=ai_comment.comment_content
                            )

                            if not post_success:
                                error_msg = f"Failed to post comment for AIComment {ai_comment.id}: Post returned False"
                                errors.append(error_msg)
                                logger.error(error_msg)
                                continue

                            # Generate a placeholder comment ID (myMoment doesn't return one)
                            # Format: article_id-timestamp-aicomment_id to ensure uniqueness
                            posted_timestamp = datetime.utcnow()
                            placeholder_comment_id = f"{ai_comment.mymoment_article_id}-{int(posted_timestamp.timestamp())}-{str(ai_comment.id)[:8]}"

                            # Update AIComment with posted status
                            ai_comment.mymoment_comment_id = placeholder_comment_id
                            ai_comment.status = 'posted'
                            ai_comment.posted_at = posted_timestamp
                            ai_comment.updated_at = posted_timestamp

                            # Explicitly add to session to ensure tracking
                            session.add(ai_comment)

                            comments_posted += 1
                            logger.info(f"Posted comment for article '{ai_comment.article_title}' as {session_context.username}")
                            logger.debug(f"Updated AIComment {ai_comment.id}: status={ai_comment.status}, mymoment_comment_id={ai_comment.mymoment_comment_id}")

                        except Exception as e:
                            error_msg = f"Failed to post comment for AIComment {ai_comment.id}: {str(e)}"
                            errors.append(error_msg)
                            logger.error(error_msg)

                # Flush changes to database before committing
                await session.flush()
                logger.debug(f"Flushed {comments_posted} AIComment updates to database")

                # Commit all updates
                await session.commit()
                logger.info(f"Committed {comments_posted} AIComment status updates to database")

                # Update process statistics
                await session.execute(
                    update(MonitoringProcess)
                    .where(MonitoringProcess.id == process_id)
                    .values(
                        comments_posted=MonitoringProcess.comments_posted + comments_posted,
                        last_activity_at=datetime.utcnow()
                    )
                )
                await session.commit()

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                status = "success" if not errors else "partial"

                logger.info(f"Comment posting completed for process {process.name}: "
                          f"{len(ai_comments)} comments processed, {comments_posted} posted, "
                          f"{len(errors)} errors")

                # Allow cleanup tasks to complete before event loop closes
                await asyncio.sleep(0.1)

                return CommentPostingResult(
                    process_id=process_id,
                    comments_posted=comments_posted,
                    errors=errors,
                    execution_time_seconds=execution_time,
                    status=status
                )

            except Exception as e:
                error_msg = f"Comment posting failed: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

                execution_time = (datetime.utcnow() - start_time).total_seconds()

                # Allow cleanup tasks to complete before event loop closes
                await asyncio.sleep(0.1)

                return CommentPostingResult(
                    process_id=process_id,
                    comments_posted=0,
                    errors=errors,
                    execution_time_seconds=execution_time,
                    status="failed"
                )

    async def _get_comments_needing_posting(self, session: AsyncSession, process_id: uuid.UUID) -> List[AIComment]:
        """Get AIComment records that need to be posted (status='generated')."""
        result = await session.execute(
            select(AIComment).where(
                and_(
                    AIComment.monitoring_process_id == process_id,
                    AIComment.status == 'generated',
                    AIComment.comment_content.isnot(None),
                    AIComment.posted_at.is_(None)
                )
            )
        )
        return result.scalars().all()


@celery_app.task(
    bind=True,
    base=CommentPostingTask,
    name='src.tasks.comment_poster.post_comments_for_process',
    queue='comments',
    max_retries=3,
    default_retry_delay=120
)
def post_comments_for_process(self, process_id: str) -> Dict[str, Any]:
    """
    Post AI-generated comments to myMoment for a monitoring process.

    Args:
        process_id: UUID of the monitoring process

    Returns:
        Dictionary with comment posting results
    """
    try:
        result = asyncio.run(self._post_comments_for_process_async(uuid.UUID(process_id)))
        return {
            'process_id': str(result.process_id),
            'comments_posted': result.comments_posted,
            'errors': result.errors,
            'execution_time_seconds': result.execution_time_seconds,
            'status': result.status
        }
    except Exception as exc:
        logger.error(f"Comment posting failed for process {process_id}: {exc}")
        self.retry(exc=exc, countdown=120)
