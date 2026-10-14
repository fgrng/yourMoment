"""
AI comment generation task for myMoment monitoring processes.

This module implements Task 3 of the refactored monitoring pipeline:
- Reads a prepared AIComment with full article content
- Formats prompts with article data
- Generates comments via LLM API calls (outside database sessions)
- Updates AIComment records with generated content and metadata
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass

from celery import current_task
from celery.exceptions import MaxRetriesExceededError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, update

from src.config.logging import format_log_context
from src.tasks.worker import celery_app, BaseTask
from src.tasks.process_guards import get_process_skip_reason
from src.models.ai_comment import AIComment
from src.models.llm_provider import LLMProviderConfiguration
from src.models.prompt_template import PromptTemplate
from src.services.llm_service import LLMProviderError, generate_completion_standalone
from src.services.comment_service import validate_comment, ensure_html_paragraphs
from src.services.llm_types import LLMGenerationConfig, GenerationResult
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)
llm_summary_logger = logging.getLogger("yourmoment.llm")


@dataclass
class CommentSnapshot:
    """Lightweight snapshot of an AIComment for processing."""
    id: uuid.UUID
    mymoment_article_id: str
    article_title: str
    article_content: str
    article_author: str
    article_category: Optional[int]
    article_published_at: Optional[datetime]
    article_url: str
    llm_provider_id: Optional[uuid.UUID]
    prompt_template_id: Optional[uuid.UUID]
    article_raw_html: Optional[str]
    article_edited_at: Optional[datetime]
    monitoring_process_id: Optional[uuid.UUID]
    status: str


@dataclass
class PromptConfig:
    """Cached prompt template configuration."""
    template_model: PromptTemplate


class CommentGenerationTask(BaseTask):
    """Task for generating AI comments from prepared articles."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()

    async def _read_comment_snapshot(self, ai_comment_id: uuid.UUID) -> Optional[CommentSnapshot]:
        """Read a single AIComment with the fields needed for generation."""
        session = await self.get_async_session()
        async with session:
            ai_comment = await session.get(AIComment, ai_comment_id)
            if not ai_comment:
                return None

            return CommentSnapshot(
                id=ai_comment.id,
                mymoment_article_id=ai_comment.mymoment_article_id,
                article_title=ai_comment.article_title,
                article_content=ai_comment.article_content,
                article_author=ai_comment.article_author,
                article_category=ai_comment.article_category,
                article_published_at=ai_comment.article_published_at,
                article_url=ai_comment.article_url,
                llm_provider_id=ai_comment.llm_provider_id,
                prompt_template_id=ai_comment.prompt_template_id,
                article_raw_html=ai_comment.article_raw_html,
                article_edited_at=ai_comment.article_edited_at,
                monitoring_process_id=ai_comment.monitoring_process_id,
                status=ai_comment.status,
            )

    def _format_user_prompt(
        self,
        article_snapshot: CommentSnapshot,
        prompt_config: PromptConfig
    ) -> str:
        """
        Format user prompt template with article data.

        Args:
            article_snapshot: Article data snapshot
            prompt_config: Prompt configuration containing template model

        Returns:
            Formatted user prompt string
        """
        # Build context dictionary from article snapshot
        context = {
            'article_title': article_snapshot.article_title or '',
            'article_content': article_snapshot.article_content or '',
            'article_author': article_snapshot.article_author or '',
            'article_category': str(article_snapshot.article_category) if article_snapshot.article_category else '',
            'article_published_at': article_snapshot.article_published_at.isoformat() if article_snapshot.article_published_at else '',
            'article_url': article_snapshot.article_url or '',
            'article_raw_html': (article_snapshot.article_raw_html or '')[:5000],
            'article_edited_at': article_snapshot.article_edited_at.isoformat() if article_snapshot.article_edited_at else '',
        }

        # Render using model method
        return prompt_config.template_model.render_prompt(context)

    async def _generate_comment_with_llm(
        self,
        formatted_prompt: str,
        system_prompt: str,
        llm_config: LLMGenerationConfig,
        log_context: Dict[str, Any],
    ) -> GenerationResult:
        """
        Generate comment using LLM API.

        Calls generate_completion_standalone() directly with a DTO,
        avoiding unnecessary database sessions.

        Args:
            formatted_prompt: User prompt with article data filled in
            system_prompt: System prompt to guide generation
            llm_config: LLM provider configuration DTO

        Returns:
            GenerationResult containing content and metadata

        Raises:
            LLMProviderError: If generation fails
        """
        return await generate_completion_standalone(
            user_prompt=formatted_prompt,
            config=llm_config,
            system_prompt=system_prompt,
            log_context=log_context,
        )

    def _build_log_context(
        self,
        process_id: uuid.UUID,
        comment_snapshot: CommentSnapshot,
    ) -> Dict[str, Any]:
        """Build stable identifiers for task and LLM logs."""
        task_request = getattr(current_task, "request", None)
        return {
            "process_id": process_id,
            "task_id": getattr(task_request, "id", None),
            "ai_comment_id": comment_snapshot.id,
            "mymoment_article_id": comment_snapshot.mymoment_article_id,
            "llm_provider_id": comment_snapshot.llm_provider_id,
            "prompt_template_id": comment_snapshot.prompt_template_id,
        }

    def _add_ai_prefix(self, comment_text: str) -> str:
        """
        Add AI comment prefix to generated text.

        Prepends the configured AI_COMMENT_PREFIX from settings.

        Args:
            comment_text: Generated comment text

        Returns:
            Comment text with AI prefix prepended
        """
        return AIComment.apply_ai_prefix(comment_text)

    async def _update_generated_comment(
        self,
        ai_comment_id: uuid.UUID,
        comment_data: Dict[str, Any],
        expected_status: str = "prepared",
    ) -> None:
        """
        Update AIComment record with generated comment data.

        Uses Pattern 3: Iterative Single-Record Updates.
        Quick update with no long operations.

        Args:
            ai_comment_id: AIComment UUID to update
            comment_data: Dictionary with comment content and metadata
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
                    comment_content=comment_data["comment_content"],
                    reasoning_content=comment_data.get("reasoning_content"),
                    ai_model_name=comment_data["ai_model_name"],
                    ai_provider_name=comment_data["ai_provider_name"],
                    generation_tokens=comment_data.get("generation_tokens"),
                    generation_time_ms=comment_data["generation_time_ms"],
                    status="generated",
                    error_message=None,
                    failed_at=None,
                )
            )

            if result.rowcount:
                await session.commit()
                return

            ai_comment = await session.get(AIComment, ai_comment_id)
            if not ai_comment:
                raise ValueError(f"AIComment {ai_comment_id} not found")
            if ai_comment.status in {"generated", "posted"}:
                logger.info(
                    "Skipping stale generation update for AIComment %s already in status=%s",
                    ai_comment_id,
                    ai_comment.status,
                )
                return
            raise ValueError(
                f"AIComment {ai_comment_id} expected status {expected_status}, got {ai_comment.status}"
            )

    async def _mark_comment_failed(
        self,
        ai_comment_id: uuid.UUID,
        error_message: str,
        expected_status: str = "prepared",
    ) -> None:
        """
        Mark AIComment as failed with error message.

        Swallows its own exceptions so that a DB error here never escalates
        and causes the per-comment handler to retry _mark_comment_failed
        with a compounding error message.

        Args:
            ai_comment_id: AIComment UUID to mark as failed
            error_message: Error description
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
                        comment_content="",
                    )
                )
                if result.rowcount:
                    await session.commit()
                    return

                ai_comment = await session.get(AIComment, ai_comment_id)
                if not ai_comment:
                    logger.warning(f"AIComment {ai_comment_id} not found for failure marking")
                    return
                logger.info(
                    "Skipping stale generation failure mark for AIComment %s with current status=%s",
                    ai_comment_id,
                    ai_comment.status,
                )
        except Exception as db_err:
            logger.error(
                f"Failed to mark AIComment {ai_comment_id} as failed "
                f"(original error: {error_message!r}): {db_err}"
            )

    async def _generate_single_comment_async(self, ai_comment_id: uuid.UUID) -> Dict[str, Any]:
        """Generate one AI comment by moving prepared -> generated idempotently."""
        start_time = datetime.utcnow()
        snapshot = await self._read_comment_snapshot(ai_comment_id)
        if not snapshot:
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "skipped",
                "reason": "missing",
                "execution_time_seconds": 0,
            }

        if snapshot.status != "prepared":
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

        log_context = self._build_log_context(
            snapshot.monitoring_process_id or uuid.UUID(int=0),
            snapshot,
        )
        log_context_str = format_log_context(**log_context)

        session = await self.get_async_session()
        async with session:
            provider = (
                await session.get(LLMProviderConfiguration, snapshot.llm_provider_id)
                if snapshot.llm_provider_id
                else None
            )
            prompt_template = (
                await session.get(PromptTemplate, snapshot.prompt_template_id)
                if snapshot.prompt_template_id
                else None
            )

        if not provider:
            error_msg = f"LLM provider configuration not found for comment {snapshot.id}"
            await self._mark_comment_failed(snapshot.id, error_msg, expected_status="prepared")
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "failed",
                "reason": error_msg,
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }
        if not prompt_template:
            error_msg = f"Prompt template not found for comment {snapshot.id}"
            await self._mark_comment_failed(snapshot.id, error_msg, expected_status="prepared")
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "failed",
                "reason": error_msg,
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }

        llm_config = LLMGenerationConfig.from_model(provider, provider.get_api_key())
        prompt_config = PromptConfig(template_model=prompt_template)

        try:
            formatted_prompt = self._format_user_prompt(snapshot, prompt_config)
            llm_summary_logger.info("comment_generation_start %s", log_context_str)
            gen_result = await self._generate_comment_with_llm(
                formatted_prompt=formatted_prompt,
                system_prompt=prompt_template.system_prompt,
                llm_config=llm_config,
                log_context=log_context,
            )

            normalized_content = ensure_html_paragraphs(gen_result.comment_content)
            comment_with_prefix = self._add_ai_prefix(normalized_content)
            validation = validate_comment(comment_with_prefix)
            if not validation["is_valid"]:
                error_msg = (
                    f"Comment failed validation for article {snapshot.mymoment_article_id}: "
                    f"{validation['errors']}"
                )
                await self._mark_comment_failed(snapshot.id, error_msg, expected_status="prepared")
                return {
                    "ai_comment_id": str(ai_comment_id),
                    "status": "failed",
                    "reason": error_msg,
                    "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
                }

            await self._update_generated_comment(
                snapshot.id,
                {
                    "comment_content": comment_with_prefix,
                    "reasoning_content": gen_result.reasoning_content,
                    "ai_model_name": gen_result.model_used,
                    "ai_provider_name": gen_result.provider_used,
                    "generation_tokens": gen_result.total_tokens,
                    "generation_time_ms": gen_result.generation_time_ms,
                },
                expected_status="prepared",
            )
            llm_summary_logger.info(
                "comment_generation_done %s",
                format_log_context(
                    **log_context,
                    status="generated",
                    provider=gen_result.provider_used,
                    model=gen_result.model_used,
                    duration_ms=gen_result.generation_time_ms or 0,
                    total_tokens=gen_result.total_tokens,
                ),
            )
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "generated",
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
                "generation_time_ms": gen_result.generation_time_ms,
            }
        except Exception as exc:
            llm_summary_logger.error(
                "comment_generation_failed %s",
                format_log_context(
                    **log_context,
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                ),
            )
            raise


def _normalize_identifier(identifier: Any, compat_args: tuple[Any, ...]) -> str:
    """Accept both Celery invocation and legacy direct task calls in tests."""
    if isinstance(identifier, str):
        return identifier
    if compat_args and isinstance(compat_args[0], str):
        return compat_args[0]
    return str(identifier)


@celery_app.task(
    bind=True,
    base=CommentGenerationTask,
    name='src.tasks.comment_generation.generate_comment_for_article',
    queue='generation',
    max_retries=3,
    default_retry_delay=60
)
def generate_comment_for_article(self, ai_comment_id: Any, *compat_args: Any) -> Dict[str, Any]:
    """Generate a comment for a single AIComment row."""
    ai_comment_id = _normalize_identifier(ai_comment_id, compat_args)
    task_id = getattr(self.request, "id", None)
    try:
        logger.info(
            "Starting single-comment generation task %s",
            format_log_context(task_id=task_id, ai_comment_id=ai_comment_id),
        )
        result = asyncio.run(self._generate_single_comment_async(uuid.UUID(ai_comment_id)))
        logger.info(
            "Single-comment generation task completed %s",
            format_log_context(
                task_id=task_id,
                ai_comment_id=ai_comment_id,
                status=result.get("status"),
            ),
        )
        return result
    except Exception as exc:
        countdown = min(60 * (2 ** self.request.retries), 300)
        logger.warning(
            "Single-comment generation task failed, retrying %s",
            format_log_context(
                task_id=task_id,
                ai_comment_id=ai_comment_id,
                attempt=self.request.retries + 1,
                max_retries=self.max_retries,
                countdown=countdown,
                error=str(exc),
            ),
        )
        try:
            self.retry(exc=exc, countdown=countdown)
        except MaxRetriesExceededError:
            logger.error(
                "Max retries exhausted for single-comment generation %s",
                format_log_context(task_id=task_id, ai_comment_id=ai_comment_id),
            )
            asyncio.run(
                self._mark_comment_failed(
                    uuid.UUID(ai_comment_id),
                    f"Max retries exhausted: {exc}",
                    expected_status="prepared",
                )
            )
            return {
                "ai_comment_id": ai_comment_id,
                "status": "failed",
                "reason": f"Max retries exhausted: {exc}",
                "execution_time_seconds": 0,
            }
