"""
Comment posting task for myMoment monitoring processes.

This module implements Task 4 of the refactored monitoring pipeline:
- Reads generated AIComments with status='generated'
- Posts comments through the platform interface (`connect`, `post_comment`)
- Uses short-lived database sessions with no external I/O inside transactions
- Implements Pattern 4: Batch Read with Cached Reference Data
"""

import asyncio
import logging
import uuid
from contextlib import AsyncExitStack
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from celery.exceptions import MaxRetriesExceededError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select, update

from src.tasks.worker import celery_app, BaseTask
from src.tasks.process_guards import get_process_skip_reason
from src.models.ai_comment import AIComment
from src.platforms import (
    ArticleRef,
    PlatformAccount,
    PlatformAuthError,
    PlatformConnection,
    PlatformRejected,
    PostedComment,
    connect,
)
from src.platforms.accounts import load_platform_account
from src.config.database import get_database_manager
from src.config.encryption import DecryptionError

logger = logging.getLogger(__name__)

# Final failures: wrong credentials, a refused comment, missing data.
# Everything else (PlatformUnavailable, unexpected errors) is retried.
_NOT_RETRYABLE = (PlatformAuthError, PlatformRejected, ValueError)


class PostingDeferred(Exception):
    """Batch posting left comments 'generated' after retryable errors."""


@dataclass
class CommentSnapshot:
    """Lightweight snapshot of an AIComment for posting."""
    id: uuid.UUID
    mymoment_article_id: str
    article_url: str
    comment_content: str
    mymoment_login_id: uuid.UUID
    article_title: str
    is_hidden: bool
    monitoring_process_id: Optional[uuid.UUID]
    user_id: uuid.UUID
    status: str


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
    ) -> tuple[List[CommentSnapshot], Dict[uuid.UUID, PlatformAccount]]:
        """
        Read generated AIComments and cache their platform accounts.

        Uses Pattern 4: Batch Read with Cached Reference Data.
        Reads all comments in one session, then the accounts in a second one.
        Inactive, missing or undecryptable accounts are absent from the cache;
        database errors abort the batch.

        Args:
            process_id: Monitoring process UUID

        Returns:
            Tuple of (comment_snapshots, cached_accounts)
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
            comment_snapshots = [_snapshot(c) for c in result.scalars().all()]
        # Session closed

        logger.info(f"Read {len(comment_snapshots)} generated comments for process {process_id}")

        # Step 2: Read and cache platform accounts (decrypted once per login)
        cached_accounts: Dict[uuid.UUID, PlatformAccount] = {}
        logins = {(c.mymoment_login_id, c.user_id) for c in comment_snapshots if c.mymoment_login_id}

        if logins:
            session = await self.get_async_session()
            async with session:
                for login_id, user_id in logins:
                    try:
                        account = await load_platform_account(session, login_id, user_id)
                    except DecryptionError as e:
                        logger.error(f"Failed to decrypt platform account {login_id}: {e}")
                        continue
                    if account is not None:
                        cached_accounts[login_id] = account
            # Session closed

        logger.info(f"Cached {len(cached_accounts)} platform accounts")

        return comment_snapshots, cached_accounts

    async def _read_comment_snapshot(self, ai_comment_id: uuid.UUID) -> Optional[CommentSnapshot]:
        """Read a single AIComment with the fields required for posting."""
        session = await self.get_async_session()
        async with session:
            ai_comment = await session.get(AIComment, ai_comment_id)
            return _snapshot(ai_comment) if ai_comment else None

    async def _load_platform_account(self, snapshot: CommentSnapshot) -> PlatformAccount:
        """Load the comment's platform account; a missing account is final (ValueError)."""
        session = await self.get_async_session()
        async with session:
            account = await load_platform_account(
                session, snapshot.mymoment_login_id, snapshot.user_id
            )
        if account is None:
            raise ValueError(
                f"Platform account {snapshot.mymoment_login_id} not found or inactive"
            )
        return account

    async def _publish(self, platform: PlatformConnection, snapshot: CommentSnapshot) -> PostedComment:
        """
        Post one comment through the platform interface, outside any DB session.

        The AI prefix (FR-006) is applied here, exactly once.
        """
        posted = await platform.post_comment(
            ArticleRef(id=snapshot.mymoment_article_id, url=snapshot.article_url),
            AIComment.apply_ai_prefix(snapshot.comment_content),
            hidden=snapshot.is_hidden,
        )
        logger.info(f"Successfully posted comment to article {snapshot.mymoment_article_id}")
        return posted

    def _comment_id(self, posted: PostedComment, snapshot: CommentSnapshot) -> str:
        """
        The platform's comment ID, else a unique placeholder.

        Platforms like myMoment don't return comment IDs after posting, so we
        generate one for tracking: {article_id}-{timestamp}-{ai_comment_id_prefix}
        """
        if posted.external_id:
            return posted.external_id

        timestamp = int(datetime.utcnow().timestamp())
        placeholder_id = f"{snapshot.mymoment_article_id}-{timestamp}-{str(snapshot.id)[:8]}"
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
                .values(status="posting")
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
                        AIComment.status == "posting",
                    )
                )
                .values(status="posted", **values)
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
                            AIComment.status == "posting",
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
        expected_status: str = "posting",
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
        Mark a comment as failed, trying generated first and falling back to posting.

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
            expected_status="posting",
        )

    def _is_retryable_posting_error(self, exc: Exception) -> bool:
        """Decide by error type: auth failures and refused comments do not loop through retries."""
        return not isinstance(exc, _NOT_RETRYABLE)

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

        account = await self._load_platform_account(snapshot)
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

        posted_to_platform = False
        try:
            async with connect(account) as platform:
                posted = await self._publish(platform, snapshot)
                posted_to_platform = True

            posted_at = datetime.utcnow()
            try:
                updated = await self._finalize_posted_comment(
                    snapshot.id,
                    comment_id=self._comment_id(posted, snapshot),
                    posted_at=posted_at,
                    login_id=snapshot.mymoment_login_id,
                )
            except Exception as finalize_error:
                logger.error(
                    "Comment posted for AIComment %s but finalization failed: %s",
                    snapshot.id,
                    finalize_error,
                )
                return {
                    "ai_comment_id": str(ai_comment_id),
                    "status": "posting",
                    "reason": "finalization_failed",
                    "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
                }
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "posted" if updated else "skipped",
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }
        except Exception as exc:
            if not posted_to_platform:
                await self._revert_comment_claim(snapshot.id)
            logger.error("Failed to post comment for AIComment %s: %s", snapshot.id, exc)
            raise

    async def _post_comments_async(self, process_id: uuid.UUID) -> Dict[str, Any]:
        """
        Main async method for comment posting.

        Implements the posting workflow using Pattern 4:
        1. Read generated AIComments and cache platform accounts (batch read)
        2. Connect once per platform account (outside DB session)
        3. For each comment: post through the platform interface (outside DB session)
        4. Update AIComment status one at a time (single updates)

        Errors are handled by type: refused comments and wrong credentials
        mark the comment failed; retryable errors leave it 'generated' and
        count it as deferred, so the Celery task retries the batch.

        Args:
            process_id: Monitoring process UUID

        Returns:
            Result dictionary with counts and errors
        """
        start_time = datetime.utcnow()
        errors = []
        posted_count = 0
        failed_count = 0
        deferred_count = 0

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
                    'deferred': 0,
                    'errors': [],
                    'execution_time_seconds': 0,
                    'status': 'skipped',
                    'reason': skip_reason,
                }

            # Step 1: Read and cache (Pattern 4)
            comment_snapshots, cached_accounts = await self._read_and_cache_for_posting(process_id)

            if not comment_snapshots:
                logger.info(f"No generated comments to post for process {process_id}")
                execution_time = (datetime.utcnow() - start_time).total_seconds()
                return {
                    'posted': 0,
                    'failed': 0,
                    'deferred': 0,
                    'errors': [],
                    'execution_time_seconds': execution_time,
                    'status': 'success'
                }

            logger.info(f"Starting comment posting for process {process_id}: "
                       f"{len(comment_snapshots)} comments")

            async def _handle_failure(snapshot: CommentSnapshot, exc: Exception) -> None:
                nonlocal failed_count, deferred_count
                errors.append(f"Failed to post comment for AIComment {snapshot.id}: {exc}")
                logger.error(errors[-1])
                if self._is_retryable_posting_error(exc):
                    deferred_count += 1
                    return
                try:
                    await self._mark_comment_failed_safe(snapshot.id, str(exc))
                except Exception as mark_error:
                    logger.error(f"Failed to mark comment as failed: {mark_error}")
                failed_count += 1

            async with AsyncExitStack() as stack:
                # Step 2: One connection per platform account
                connections: Dict[uuid.UUID, PlatformConnection] = {}
                connect_errors: Dict[uuid.UUID, Exception] = {}
                for login_id, account in cached_accounts.items():
                    try:
                        connections[login_id] = await stack.enter_async_context(connect(account))
                        logger.info(f"Connected platform account {login_id}")
                    except Exception as e:
                        connect_errors[login_id] = e
                        logger.error(f"Failed to connect platform account {login_id}: {e}")

                # Step 3: Post comments one at a time (outside DB sessions)
                for comment_snapshot in comment_snapshots:
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

                    login_id = comment_snapshot.mymoment_login_id
                    platform = connections.get(login_id)
                    if platform is None:
                        await _handle_failure(
                            comment_snapshot,
                            connect_errors.get(login_id)
                            or ValueError(f"Platform account {login_id} not found or inactive"),
                        )
                        continue

                    claimed = await self._claim_comment_for_posting(
                        ai_comment_id=comment_snapshot.id,
                    )
                    if not claimed:
                        logger.info(
                            "Skipping stale posting claim for AIComment %s inside batch posting",
                            comment_snapshot.id,
                        )
                        continue

                    try:
                        posted = await self._publish(platform, comment_snapshot)
                    except Exception as e:
                        await self._revert_comment_claim(comment_snapshot.id)
                        await _handle_failure(comment_snapshot, e)
                        continue

                    try:
                        updated = await self._finalize_posted_comment(
                            ai_comment_id=comment_snapshot.id,
                            comment_id=self._comment_id(posted, comment_snapshot),
                            posted_at=datetime.utcnow(),
                            login_id=login_id,
                        )
                    except Exception as finalize_error:
                        logger.error(
                            "Comment posted for AIComment %s but finalization failed: %s",
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

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            logger.info(f"Comment posting completed for process {process_id}: "
                       f"{posted_count} posted, {failed_count} failed, {deferred_count} deferred, "
                       f"{len(errors)} errors, {execution_time:.2f}s")

            return {
                'posted': posted_count,
                'failed': failed_count,
                'deferred': deferred_count,
                'errors': errors,
                'execution_time_seconds': execution_time,
                'status': 'success' if failed_count == 0 and deferred_count == 0 else 'partial'
            }

        except Exception as e:
            error_msg = f"Comment posting failed: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            return {
                'posted': posted_count,
                'failed': failed_count,
                'deferred': deferred_count,
                'errors': errors,
                'execution_time_seconds': execution_time,
                'status': 'failed'
            }


def _snapshot(ai_comment: AIComment) -> CommentSnapshot:
    return CommentSnapshot(
        id=ai_comment.id,
        mymoment_article_id=ai_comment.mymoment_article_id,
        article_url=ai_comment.article_url,
        comment_content=ai_comment.comment_content or "",
        mymoment_login_id=ai_comment.mymoment_login_id,
        article_title=ai_comment.article_title,
        is_hidden=ai_comment.is_hidden,
        monitoring_process_id=ai_comment.monitoring_process_id,
        user_id=ai_comment.user_id,
        status=ai_comment.status,
    )


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
        - deferred: Number of comments left 'generated' after retryable errors
        - errors: List of error messages
        - execution_time_seconds: Task execution time
        - status: 'success', 'partial', or 'failed'
    """
    try:
        process_id = _normalize_identifier(process_id, compat_args)
        logger.info(f"Starting comment posting task for process {process_id}")
        result = asyncio.run(self._post_comments_async(uuid.UUID(process_id)))
        logger.info(f"Comment posting task completed: {result}")
        if result.get('deferred'):
            # Celery's autoretry runs the batch again; it picks up the comments still 'generated'
            raise PostingDeferred(f"{result['deferred']} comments deferred: {result['errors']}")
        return result

    except Exception as exc:
        logger.error(f"Comment posting task failed for process {process_id}: {exc}")
        # Let Celery handle retry with exponential backoff
        raise exc
