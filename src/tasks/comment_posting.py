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

from celery.exceptions import MaxRetriesExceededError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select, update

from src.tasks.worker import celery_app, BaseTask
from src.tasks.process_guards import get_process_skip_reason
from src.models.ai_comment import AIComment
from src.models.mymoment_login import MyMomentLogin
from src.services.scraper_service import (
    ScraperService,
    ScrapingConfig,
    ScrapingError,
    SessionContext,
)
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
    is_hidden: bool
    monitoring_process_id: Optional[uuid.UUID]
    user_id: uuid.UUID
    status: str


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
                    article_title=c.article_title,
                    is_hidden=c.is_hidden,
                    monitoring_process_id=c.monitoring_process_id,
                    user_id=c.user_id,
                    status=c.status,
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

    async def _read_comment_snapshot(self, ai_comment_id: uuid.UUID) -> Optional[CommentSnapshot]:
        """Read a single AIComment with the fields required for posting."""
        session = await self.get_async_session()
        async with session:
            ai_comment = await session.get(AIComment, ai_comment_id)
            if not ai_comment:
                return None

            return CommentSnapshot(
                id=ai_comment.id,
                mymoment_article_id=ai_comment.mymoment_article_id,
                comment_content=ai_comment.comment_content or "",
                mymoment_login_id=ai_comment.mymoment_login_id,
                article_title=ai_comment.article_title,
                is_hidden=ai_comment.is_hidden,
                monitoring_process_id=ai_comment.monitoring_process_id,
                user_id=ai_comment.user_id,
                status=ai_comment.status,
            )

    async def _post_single_comment(
        self,
        context: SessionContext,
        article_id: str,
        comment_content: str,
        scraper: ScraperService,
        hide_comment: bool = False
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
            hide_comment: Whether to hide the comment on myMoment

        Returns:
            True if posting succeeded, False if myMoment returned an unsuccessful response
        """
        try:
            success = await scraper.post_comment(
                context=context,
                article_id=article_id,
                comment_content=comment_content,
                hide_comment=hide_comment
            )

            if success:
                logger.info(f"Successfully posted comment to article {article_id}")
            else:
                logger.warning(f"Comment posting returned False for article {article_id}")

            return success

        except Exception as e:
            logger.error(f"Failed to post comment to article {article_id}: {e}")
            raise

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

    async def _claim_comment_for_posting(
        self,
        ai_comment_id: uuid.UUID,
    ) -> bool:
        """Atomically claim a generated comment before any external POST occurs."""
        session = await self.get_async_session()
        async with session:
            result = await session.execute(
                update(AIComment)
                .where(
                    and_(
                        AIComment.id == ai_comment_id,
                        AIComment.status == "generated",
                    )
                )
                .values(status="posted")
            )
            if result.rowcount:
                await session.commit()
                logger.debug("Claimed AIComment %s for posting", ai_comment_id)
                return True

            ai_comment = await session.get(AIComment, ai_comment_id)
            if ai_comment:
                logger.info(
                    "Skipping stale posting claim for AIComment %s with current status=%s",
                    ai_comment_id,
                    ai_comment.status,
                )
            else:
                logger.info("Skipping posting claim for missing AIComment %s", ai_comment_id)
            return False

    async def _finalize_posted_comment(
        self,
        ai_comment_id: uuid.UUID,
        comment_id: str,
        posted_at: datetime,
        login_id: Optional[uuid.UUID] = None,
    ) -> bool:
        """
        Finalize a claimed AIComment after successful posting.

        Uses Pattern 3: Iterative Single-Record Updates.
        Short-lived session for single update operation.

        Args:
            ai_comment_id: AIComment UUID
            comment_id: MyMoment comment ID (placeholder)
            posted_at: When the comment was posted
        """
        values: Dict[str, Any] = {
            "mymoment_comment_id": comment_id,
            "posted_at": posted_at,
            "error_message": None,
            "failed_at": None,
        }
        if login_id is not None:
            values["mymoment_login_id"] = login_id

        session = await self.get_async_session()
        async with session:
            result = await session.execute(
                update(AIComment)
                .where(
                    and_(
                        AIComment.id == ai_comment_id,
                        AIComment.status == "posted",
                    )
                )
                .values(**values)
            )
            if result.rowcount:
                await session.commit()
                logger.debug(f"Finalized posted AIComment {ai_comment_id}")
                return True

            ai_comment = await session.get(AIComment, ai_comment_id)
            if ai_comment:
                logger.info(
                    "Skipping stale posting finalize for AIComment %s with current status=%s",
                    ai_comment_id,
                    ai_comment.status,
                )
            else:
                logger.info("Skipping posting finalize for missing AIComment %s", ai_comment_id)
            return False

    async def _revert_comment_claim(
        self,
        ai_comment_id: uuid.UUID,
    ) -> bool:
        """Best-effort revert of a posting claim. Never raises."""
        try:
            session = await self.get_async_session()
            async with session:
                result = await session.execute(
                    update(AIComment)
                    .where(
                        and_(
                            AIComment.id == ai_comment_id,
                            AIComment.status == "posted",
                        )
                    )
                    .values(
                        status="generated",
                        mymoment_comment_id=None,
                        posted_at=None,
                        error_message=None,
                        failed_at=None,
                    )
                )
                if result.rowcount:
                    await session.commit()
                    logger.debug("Reverted posting claim for AIComment %s", ai_comment_id)
                    return True

                ai_comment = await session.get(AIComment, ai_comment_id)
                if ai_comment:
                    logger.info(
                        "Skipping stale posting claim revert for AIComment %s with current status=%s",
                        ai_comment_id,
                        ai_comment.status,
                    )
                else:
                    logger.info("Skipping posting claim revert for missing AIComment %s", ai_comment_id)
                return False
        except Exception as exc:
            logger.warning("Best-effort revert failed for AIComment %s: %s", ai_comment_id, exc)
            return False

    async def _mark_comment_failed(
        self,
        ai_comment_id: uuid.UUID,
        error_msg: str,
        expected_status: str = "posted",
    ) -> bool:
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
                    error_message=error_msg,
                    failed_at=datetime.utcnow(),
                    mymoment_comment_id=None,
                    posted_at=None,
                    retry_count=AIComment.retry_count + 1,
                )
            )
            if result.rowcount:
                await session.commit()
                logger.debug(f"Updated AIComment {ai_comment_id} to status='failed'")
                return True

            ai_comment = await session.get(AIComment, ai_comment_id)
            if not ai_comment:
                raise ValueError(f"AIComment {ai_comment_id} not found")
            logger.info(
                "Skipping stale posting failure mark for AIComment %s with current status=%s",
                ai_comment_id,
                ai_comment.status,
            )
            return False

    async def _mark_comment_failed_safe(
        self,
        ai_comment_id: uuid.UUID,
        error_msg: str,
    ) -> bool:
        """
        Mark a comment as failed, trying generated first and falling back to posted.

        This handles terminal paths where retry cleanup may already have reverted the claim,
        while still covering stuck-claim edge cases.
        """
        updated = await self._mark_comment_failed(
            ai_comment_id,
            error_msg,
            expected_status="generated",
        )
        if updated:
            return True
        return await self._mark_comment_failed(
            ai_comment_id,
            error_msg,
            expected_status="posted",
        )

    def _is_retryable_posting_error(self, exc: Exception) -> bool:
        """Classify posting failures so auth/config issues do not loop through retries."""
        if isinstance(exc, ValueError):
            return False

        if isinstance(exc, ScrapingError):
            error_text = str(exc).lower()
            non_retryable_fragments = (
                "failed to authenticate with mymoment",
                "session not authenticated",
            )
            return not any(fragment in error_text for fragment in non_retryable_fragments)

        return True

    async def _post_single_comment_async(self, ai_comment_id: uuid.UUID) -> Dict[str, Any]:
        """Post one generated comment if the process is still allowed to publish."""
        start_time = datetime.utcnow()
        snapshot = await self._read_comment_snapshot(ai_comment_id)
        if not snapshot:
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "skipped",
                "reason": "missing",
                "execution_time_seconds": 0,
            }

        if snapshot.status != "generated":
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "skipped",
                "reason": f"already_{snapshot.status}",
                "execution_time_seconds": 0,
            }

        skip_reason = await get_process_skip_reason(
            self.get_async_session,
            snapshot.monitoring_process_id,
            require_posting_enabled=True,
        )
        if skip_reason:
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "skipped",
                "reason": skip_reason,
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }

        scraping_config = ScrapingConfig.from_settings()
        claimed = await self._claim_comment_for_posting(
            snapshot.id,
        )
        if not claimed:
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "skipped",
                "reason": "already_claimed",
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }

        posted_to_mymoment = False
        try:
            session = await self.get_async_session()
            async with session:
                async with ScraperService(session, scraping_config) as scraper:
                    try:
                        context = await scraper.initialize_session_for_login(
                            login_id=snapshot.mymoment_login_id,
                            user_id=snapshot.user_id,
                        )
                        success = await self._post_single_comment(
                            context=context,
                            article_id=snapshot.mymoment_article_id,
                            comment_content=snapshot.comment_content,
                            scraper=scraper,
                            hide_comment=snapshot.is_hidden,
                        )
                    finally:
                        try:
                            await scraper.cleanup_session(snapshot.mymoment_login_id)
                        except Exception as cleanup_error:
                            logger.warning(
                                "Failed to cleanup posting session for login %s: %s",
                                snapshot.mymoment_login_id,
                                cleanup_error,
                            )

            if not success:
                await self._revert_comment_claim(snapshot.id)
                raise RuntimeError("Comment posting returned False")

            posted_to_mymoment = True
            posted_at = datetime.utcnow()
            comment_id = self._generate_placeholder_comment_id(
                snapshot.mymoment_article_id,
                snapshot.id,
            )
            try:
                updated = await self._finalize_posted_comment(
                    snapshot.id,
                    comment_id=comment_id,
                    posted_at=posted_at,
                    login_id=snapshot.mymoment_login_id,
                )
            except Exception as finalize_error:
                logger.error(
                    "Comment posted to myMoment for AIComment %s but finalization failed: %s",
                    snapshot.id,
                    finalize_error,
                )
                return {
                    "ai_comment_id": str(ai_comment_id),
                    "status": "posted",
                    "reason": "finalization_failed",
                    "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
                }
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "posted" if updated else "skipped",
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }
        except Exception as exc:
            if not posted_to_mymoment:
                await self._revert_comment_claim(snapshot.id)
            logger.error("Failed to post comment for AIComment %s: %s", snapshot.id, exc)
            raise

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
            skip_reason = await get_process_skip_reason(
                self.get_async_session,
                process_id,
                require_posting_enabled=True,
            )
            if skip_reason:
                return {
                    'posted': 0,
                    'failed': 0,
                    'errors': [],
                    'execution_time_seconds': 0,
                    'status': 'skipped',
                    'reason': skip_reason,
                }

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
                            skip_reason = await get_process_skip_reason(
                                self.get_async_session,
                                comment_snapshot.monitoring_process_id,
                                require_posting_enabled=True,
                            )
                            if skip_reason:
                                logger.info(
                                    "Skipping posting for AIComment %s: %s",
                                    comment_snapshot.id,
                                    skip_reason,
                                )
                                continue

                            # Find session context for this comment's login
                            context = session_contexts.get(comment_snapshot.mymoment_login_id)

                            if not context:
                                error_msg = f"No session found for login {comment_snapshot.mymoment_login_id}"
                                logger.error(error_msg)
                                await self._mark_comment_failed(
                                    comment_snapshot.id,
                                    error_msg,
                                    expected_status="generated",
                                )
                                failed_count += 1
                                continue

                            # Apply rate limiting between posts
                            if idx > 0:
                                await asyncio.sleep(scraping_config.rate_limit_delay)

                            claimed = await self._claim_comment_for_posting(
                                ai_comment_id=comment_snapshot.id,
                            )

                            if not claimed:
                                logger.info(
                                    "Skipping stale posting claim for AIComment %s inside batch posting",
                                    comment_snapshot.id,
                                )
                                continue

                            posted_to_mymoment = False
                            try:
                                success = await self._post_single_comment(
                                    context=context,
                                    article_id=comment_snapshot.mymoment_article_id,
                                    comment_content=comment_snapshot.comment_content,
                                    scraper=scraper,
                                    hide_comment=comment_snapshot.is_hidden
                                )

                                if not success:
                                    await self._revert_comment_claim(comment_snapshot.id)
                                    raise RuntimeError("Comment posting returned False")

                                posted_to_mymoment = True
                                posted_at = datetime.utcnow()
                                comment_id = self._generate_placeholder_comment_id(
                                    comment_snapshot.mymoment_article_id,
                                    comment_snapshot.id,
                                )
                                try:
                                    updated = await self._finalize_posted_comment(
                                        ai_comment_id=comment_snapshot.id,
                                        comment_id=comment_id,
                                        posted_at=posted_at,
                                        login_id=comment_snapshot.mymoment_login_id,
                                    )
                                except Exception as finalize_error:
                                    logger.error(
                                        "Comment posted to myMoment for AIComment %s but finalization failed: %s",
                                        comment_snapshot.id,
                                        finalize_error,
                                    )
                                    posted_count += 1
                                    continue

                                if updated:
                                    posted_count += 1
                                    logger.info(
                                        f"Posted comment {posted_count}/{len(comment_snapshots)}: "
                                        f"'{comment_snapshot.article_title[:50]}'"
                                    )
                                else:
                                    logger.info(
                                        "Skipping stale posting completion for AIComment %s",
                                        comment_snapshot.id,
                                    )
                            except Exception:
                                if not posted_to_mymoment:
                                    await self._revert_comment_claim(comment_snapshot.id)
                                raise

                        except Exception as e:
                            error_msg = f"Failed to post comment for AIComment {comment_snapshot.id}: {str(e)}"
                            errors.append(error_msg)
                            logger.error(error_msg)

                            try:
                                await self._mark_comment_failed_safe(
                                    comment_snapshot.id,
                                    str(e),
                                )
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


def _normalize_identifier(identifier: Any, compat_args: tuple[Any, ...]) -> str:
    """Accept both Celery invocation and legacy direct task calls in tests."""
    if isinstance(identifier, str):
        return identifier
    if compat_args and isinstance(compat_args[0], str):
        return compat_args[0]
    return str(identifier)


@celery_app.task(
    bind=True,
    base=CommentPostingTask,
    name='src.tasks.comment_posting.post_comment_for_article',
    queue='posting',
    max_retries=3,
    default_retry_delay=60
)
def post_comment_for_article(self, ai_comment_id: Any, *compat_args: Any) -> Dict[str, Any]:
    """Post a single generated AIComment row."""
    ai_comment_id = _normalize_identifier(ai_comment_id, compat_args)
    ai_comment_uuid = uuid.UUID(ai_comment_id)
    try:
        logger.info(f"Starting single-comment posting task for AIComment {ai_comment_id}")
        result = asyncio.run(self._post_single_comment_async(ai_comment_uuid))
        logger.info(f"Single-comment posting task completed: {result}")
        return result
    except Exception as exc:
        countdown = min(60 * (2 ** self.request.retries), 300)
        retryable = self._is_retryable_posting_error(exc)
        retries_exhausted = self.request.retries >= self.max_retries
        retry_recovery_failed = False

        if retryable and not retries_exhausted:
            logger.warning(
                f"Single-comment posting task failed, retrying "
                f"(attempt {self.request.retries + 1}/{self.max_retries}, countdown {countdown}s) "
                f"for AIComment {ai_comment_id}: {exc}"
            )
            try:
                reverted = asyncio.run(
                    self._revert_comment_claim(ai_comment_uuid)
                )
            except Exception as revert_error:
                logger.error(
                    "Failed to revert posting claim for AIComment %s before retry: %s",
                    ai_comment_id,
                    revert_error,
                )
                reverted = False

            if not reverted:
                try:
                    retry_snapshot = asyncio.run(self._read_comment_snapshot(ai_comment_uuid))
                    reverted = bool(retry_snapshot and retry_snapshot.status == "generated")
                except Exception as snapshot_error:
                    logger.error(
                        "Failed to verify retry readiness for AIComment %s after revert attempt: %s",
                        ai_comment_id,
                        snapshot_error,
                    )

            if reverted:
                try:
                    self.retry(exc=exc, countdown=countdown)
                except MaxRetriesExceededError:
                    retries_exhausted = True
            else:
                retries_exhausted = True
                retry_recovery_failed = True

        if retry_recovery_failed:
            terminal_reason = f"Retry recovery failed after posting error: {exc}"
        elif retryable and retries_exhausted:
            terminal_reason = f"Max retries exhausted: {exc}"
        else:
            terminal_reason = str(exc)
        logger.error(f"Single-comment posting failed permanently for AIComment {ai_comment_id}: {terminal_reason}")
        asyncio.run(
            self._mark_comment_failed_safe(
                ai_comment_uuid,
                terminal_reason,
            )
        )
        return {
            "ai_comment_id": ai_comment_id,
            "status": "failed",
            "reason": terminal_reason,
            "execution_time_seconds": 0,
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
def post_comments_for_articles(self, process_id: Any, *compat_args: Any) -> Dict[str, Any]:
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
        process_id = _normalize_identifier(process_id, compat_args)
        logger.info(f"Starting comment posting task for process {process_id}")
        result = asyncio.run(self._post_comments_async(uuid.UUID(process_id)))
        logger.info(f"Comment posting task completed: {result}")
        return result

    except Exception as exc:
        logger.error(f"Comment posting task failed for process {process_id}: {exc}")
        # Let Celery handle retry with exponential backoff
        raise exc
