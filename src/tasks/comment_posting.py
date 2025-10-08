"""
Comment posting task for myMoment monitoring processes.

This module implements Task 4 of the refactored monitoring pipeline:
- Reads generated AIComments with status='generated'
- Posts comments to myMoment using authenticated sessions
- Uses short-lived database sessions with no external I/O inside transactions
- Implements Pattern 4: Batch Read with Cached Reference Data
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
from src.services.scraper_service import ScraperService, ScrapingConfig, SessionContext
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)


@dataclass
class CommentSnapshot:
    """Lightweight snapshot of an AIComment for posting."""
    id: uuid.UUID
    mymoment_article_id: str
    comment_content: str
    mymoment_login_id: uuid.UUID
    article_title: str


@dataclass
class LoginCredentials:
    """Cached login credentials for posting."""
    login_id: uuid.UUID
    username: str
    password: str


class CommentPostingTask(BaseTask):
    """Task for posting generated comments to myMoment."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()

    async def _read_and_cache_for_posting(
        self,
        process_id: uuid.UUID
    ) -> tuple[List[CommentSnapshot], Dict[uuid.UUID, LoginCredentials]]:
        """
        Read generated AIComments and cache MyMomentLogin credentials.

        Uses Pattern 4: Batch Read with Cached Reference Data.
        Reads all comments in one session, then reads login credentials in separate sessions.

        Args:
            process_id: Monitoring process UUID

        Returns:
            Tuple of (comment_snapshots, cached_logins)
        """
        # Step 1: Read AIComments to post
        session = await self.get_async_session()
        async with session:
            result = await session.execute(
                select(AIComment).where(
                    and_(
                        AIComment.monitoring_process_id == process_id,
                        AIComment.status == 'generated',
                        AIComment.comment_content.isnot(None)
                    )
                )
            )
            ai_comments = result.scalars().all()

            # Extract unique login IDs
            unique_login_ids = set(c.mymoment_login_id for c in ai_comments if c.mymoment_login_id)

            # Create lightweight snapshots
            comment_snapshots = [
                CommentSnapshot(
                    id=c.id,
                    mymoment_article_id=c.mymoment_article_id,
                    comment_content=c.comment_content,
                    mymoment_login_id=c.mymoment_login_id,
                    article_title=c.article_title
                )
                for c in ai_comments
            ]
        # Session closed

        logger.info(f"Read {len(comment_snapshots)} generated comments for process {process_id}")
        logger.debug(f"Unique logins needed: {len(unique_login_ids)}")

        # Step 2: Read and cache login credentials
        cached_logins = {}

        if unique_login_ids:
            session = await self.get_async_session()
            async with session:
                result = await session.execute(
                    select(MyMomentLogin).where(
                        MyMomentLogin.id.in_(unique_login_ids)
                    )
                )
                logins = result.scalars().all()

                for login in logins:
                    try:
                        # Decrypt credentials once and cache
                        username = login.get_username()
                        password = login.get_password()

                        cached_logins[login.id] = LoginCredentials(
                            login_id=login.id,
                            username=username,
                            password=password
                        )
                    except Exception as e:
                        logger.error(f"Failed to decrypt credentials for login {login.id}: {e}")
                        continue
            # Session closed

        logger.info(f"Cached credentials for {len(cached_logins)} logins")

        return comment_snapshots, cached_logins

    async def _post_single_comment(
        self,
        context: SessionContext,
        article_id: str,
        comment_content: str,
        scraper: ScraperService
    ) -> bool:
        """
        Post a single comment to myMoment.

        This method runs OUTSIDE any database session.
        Uses ScraperService.post_comment() to perform the HTTP request.

        Args:
            context: Authenticated session context
            article_id: MyMoment article ID
            comment_content: Comment text (with AI prefix)
            scraper: ScraperService instance

        Returns:
            True if posting succeeded, False otherwise
        """
        try:
            success = await scraper.post_comment(
                context=context,
                article_id=article_id,
                comment_content=comment_content
            )

            if success:
                logger.info(f"Successfully posted comment to article {article_id}")
            else:
                logger.warning(f"Comment posting returned False for article {article_id}")

            return success

        except Exception as e:
            logger.error(f"Failed to post comment to article {article_id}: {e}")
            return False

    def _generate_placeholder_comment_id(
        self,
        article_id: str,
        ai_comment_id: uuid.UUID
    ) -> str:
        """
        Generate unique placeholder comment ID.

        myMoment doesn't return comment IDs after posting, so we generate
        a unique identifier for tracking purposes.

        Format: {article_id}-{timestamp}-{ai_comment_id_prefix}

        Args:
            article_id: MyMoment article ID
            ai_comment_id: AIComment UUID

        Returns:
            Unique placeholder comment ID
        """
        timestamp = int(datetime.utcnow().timestamp())
        comment_id_prefix = str(ai_comment_id)[:8]
        placeholder_id = f"{article_id}-{timestamp}-{comment_id_prefix}"

        logger.debug(f"Generated placeholder comment ID: {placeholder_id}")
        return placeholder_id

    async def _update_posted_comment(
        self,
        ai_comment_id: uuid.UUID,
        comment_id: str,
        posted_at: datetime
    ) -> None:
        """
        Update AIComment with posted status.

        Uses Pattern 3: Iterative Single-Record Updates.
        Short-lived session for single update operation.

        Args:
            ai_comment_id: AIComment UUID
            comment_id: MyMoment comment ID (placeholder)
            posted_at: When the comment was posted
        """
        session = await self.get_async_session()
        async with session:
            ai_comment = await session.get(AIComment, ai_comment_id)

            if not ai_comment:
                raise ValueError(f"AIComment {ai_comment_id} not found")

            # Update fields
            ai_comment.mymoment_comment_id = comment_id
            ai_comment.status = 'posted'
            ai_comment.posted_at = posted_at
            ai_comment.error_message = None  # Clear any previous errors

            # Commit single record
            await session.commit()

        # Session closed automatically (< 50ms)
        logger.debug(f"Updated AIComment {ai_comment_id} to status='posted'")

    async def _mark_comment_failed(
        self,
        ai_comment_id: uuid.UUID,
        error_msg: str
    ) -> None:
        """
        Mark AIComment as failed with error message.

        Uses Pattern 3: Iterative Single-Record Updates.
        Increments retry_count and sets failed_at timestamp.

        Args:
            ai_comment_id: AIComment UUID
            error_msg: Error message describing the failure
        """
        session = await self.get_async_session()
        async with session:
            ai_comment = await session.get(AIComment, ai_comment_id)

            if not ai_comment:
                raise ValueError(f"AIComment {ai_comment_id} not found")

            # Update fields
            ai_comment.status = 'failed'
            ai_comment.error_message = error_msg
            ai_comment.failed_at = datetime.utcnow()
            ai_comment.retry_count += 1

            # Commit single record
            await session.commit()

        # Session closed automatically (< 50ms)
        logger.debug(f"Updated AIComment {ai_comment_id} to status='failed', retry_count={ai_comment.retry_count}")

    async def _post_comments_async(self, process_id: uuid.UUID) -> Dict[str, Any]:
        """
        Main async method for comment posting.

        Implements the posting workflow using Pattern 4:
        1. Read generated AIComments and cache login credentials (batch read)
        2. Initialize scraper sessions for unique logins (outside DB session)
        3. For each comment: post to myMoment (outside DB session)
        4. Update AIComment status one at a time (single updates)

        Args:
            process_id: Monitoring process UUID

        Returns:
            Result dictionary with counts and errors
        """
        start_time = datetime.utcnow()
        errors = []
        posted_count = 0
        failed_count = 0

        try:
            # Step 1: Read and cache (Pattern 4)
            comment_snapshots, cached_logins = await self._read_and_cache_for_posting(process_id)

            if not comment_snapshots:
                logger.info(f"No generated comments to post for process {process_id}")
                execution_time = (datetime.utcnow() - start_time).total_seconds()
                return {
                    'posted': 0,
                    'failed': 0,
                    'errors': [],
                    'execution_time_seconds': execution_time,
                    'status': 'success'
                }

            logger.info(f"Starting comment posting for process {process_id}: "
                       f"{len(comment_snapshots)} comments")

            # Step 2: Initialize scraper and sessions (outside DB session)
            scraping_config = ScrapingConfig.from_settings()

            # Get user_id for session initialization
            session = await self.get_async_session()
            async with session:
                # Get user_id from first comment
                first_comment = await session.get(AIComment, comment_snapshots[0].id)
                if not first_comment:
                    raise ValueError("Failed to get user_id from first comment")
                user_id = first_comment.user_id
            # Session closed

            # Create scraper session for temporary use
            session = await self.get_async_session()
            async with session:
                async with ScraperService(session, scraping_config) as scraper:
                    # Initialize session contexts for each unique login
                    session_contexts: Dict[uuid.UUID, SessionContext] = {}

                    for login_id, credentials in cached_logins.items():
                        try:
                            context = await scraper.initialize_session_for_login(
                                login_id=login_id,
                                user_id=user_id
                            )
                            session_contexts[login_id] = context
                            logger.info(f"Initialized session for login {login_id} (user: {credentials.username})")
                        except Exception as e:
                            error_msg = f"Failed to initialize session for login {login_id}: {str(e)}"
                            errors.append(error_msg)
                            logger.error(error_msg)
                            # Continue with other logins

                    if not session_contexts:
                        raise ValueError("Failed to initialize any sessions for posting")

                    # Step 3: Post comments one at a time (outside DB sessions)
                    for idx, comment_snapshot in enumerate(comment_snapshots):
                        try:
                            # Find session context for this comment's login
                            context = session_contexts.get(comment_snapshot.mymoment_login_id)

                            if not context:
                                error_msg = f"No session found for login {comment_snapshot.mymoment_login_id}"
                                logger.error(error_msg)
                                await self._mark_comment_failed(comment_snapshot.id, error_msg)
                                failed_count += 1
                                continue

                            # Apply rate limiting between posts
                            if idx > 0:
                                await asyncio.sleep(scraping_config.rate_limit_delay)

                            # Post comment (outside DB session)
                            posted_at = datetime.utcnow()
                            success = await self._post_single_comment(
                                context=context,
                                article_id=comment_snapshot.mymoment_article_id,
                                comment_content=comment_snapshot.comment_content,
                                scraper=scraper
                            )

                            if success:
                                # Generate placeholder comment ID
                                comment_id = self._generate_placeholder_comment_id(
                                    comment_snapshot.mymoment_article_id,
                                    comment_snapshot.id
                                )

                                # Update AIComment with posted status (separate session)
                                await self._update_posted_comment(
                                    ai_comment_id=comment_snapshot.id,
                                    comment_id=comment_id,
                                    posted_at=posted_at
                                )

                                posted_count += 1
                                logger.info(f"Posted comment {posted_count}/{len(comment_snapshots)}: "
                                          f"'{comment_snapshot.article_title[:50]}'")
                            else:
                                # Mark as failed
                                error_msg = "Comment posting returned False"
                                await self._mark_comment_failed(comment_snapshot.id, error_msg)
                                failed_count += 1
                                errors.append(f"Article {comment_snapshot.mymoment_article_id}: {error_msg}")

                        except Exception as e:
                            error_msg = f"Failed to post comment for AIComment {comment_snapshot.id}: {str(e)}"
                            errors.append(error_msg)
                            logger.error(error_msg)

                            try:
                                await self._mark_comment_failed(comment_snapshot.id, str(e))
                            except Exception as mark_error:
                                logger.error(f"Failed to mark comment as failed: {mark_error}")

                            failed_count += 1

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            logger.info(f"Comment posting completed for process {process_id}: "
                       f"{posted_count} posted, {failed_count} failed, "
                       f"{len(errors)} errors, {execution_time:.2f}s")

            return {
                'posted': posted_count,
                'failed': failed_count,
                'errors': errors,
                'execution_time_seconds': execution_time,
                'status': 'success' if failed_count == 0 else 'partial'
            }

        except Exception as e:
            error_msg = f"Comment posting failed: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            return {
                'posted': posted_count,
                'failed': failed_count,
                'errors': errors,
                'execution_time_seconds': execution_time,
                'status': 'failed'
            }


@celery_app.task(
    bind=True,
    base=CommentPostingTask,
    name='src.tasks.comment_posting.post_comments_for_articles',
    queue='posting',
    max_retries=3,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,  # 10 minutes max backoff
    retry_jitter=True,
    default_retry_delay=60  # Start with 60 second delay
)
def post_comments_for_articles(self, process_id: str) -> Dict[str, Any]:
    """
    Celery task wrapper for comment posting.

    This is the entry point for the posting stage of the monitoring pipeline.
    Posts comments for AIComments with status='generated' and updates them to status='posted'.

    Retry configuration:
    - Max retries: 3
    - Exponential backoff: 60s, 120s, 240s
    - Jitter enabled to prevent thundering herd

    Args:
        process_id: Monitoring process UUID as string

    Returns:
        Dictionary with posting results:
        - posted: Number of comments successfully posted
        - failed: Number of comments that failed to post
        - errors: List of error messages
        - execution_time_seconds: Task execution time
        - status: 'success', 'partial', or 'failed'
    """
    try:
        logger.info(f"Starting comment posting task for process {process_id}")
        result = asyncio.run(self._post_comments_async(uuid.UUID(process_id)))
        logger.info(f"Comment posting task completed: {result}")
        return result

    except Exception as exc:
        logger.error(f"Comment posting task failed for process {process_id}: {exc}")
        # Let Celery handle retry with exponential backoff
        raise exc
