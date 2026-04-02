"""
AI comment generation task for myMoment monitoring processes.

This module implements Task 3 of the refactored monitoring pipeline:
- Reads prepared AIComments with full article content
- Caches LLM provider configurations and prompt templates in memory
- Formats prompts with article data
- Generates comments via LLM API calls (outside database sessions)
- Updates AIComment records with generated content and metadata
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

    async def _read_and_cache_for_generation(
        self,
        process_id: uuid.UUID
    ) -> tuple[List[CommentSnapshot], Dict[uuid.UUID, LLMGenerationConfig], Dict[uuid.UUID, PromptConfig]]:
        """
        Read prepared AIComments and cache reference data.

        Uses Pattern 4: Batch Read with Cached Reference Data.
        Reads all prepared AIComments, then caches LLM providers and prompt templates
        to avoid repeated database lookups during generation.

        Args:
            process_id: Monitoring process UUID

        Returns:
            Tuple of (comment_snapshots, llm_configs_cache, prompt_configs_cache)
        """
        # Step 1: Read prepared AIComments
        session = await self.get_async_session()
        async with session:
            result = await session.execute(
                select(AIComment).where(
                    and_(
                        AIComment.monitoring_process_id == process_id,
                        AIComment.status == 'prepared'
                    )
                )
            )
            ai_comments = result.scalars().all()

            # Extract unique foreign key IDs
            unique_llm_ids = set(c.llm_provider_id for c in ai_comments if c.llm_provider_id)
            unique_prompt_ids = set(c.prompt_template_id for c in ai_comments if c.prompt_template_id)

            # Create lightweight snapshots
            comment_snapshots = [
                CommentSnapshot(
                    id=c.id,
                    mymoment_article_id=c.mymoment_article_id,
                    article_title=c.article_title,
                    article_content=c.article_content,
                    article_author=c.article_author,
                    article_category=c.article_category,
                    article_published_at=c.article_published_at,
                    article_url=c.article_url,
                    llm_provider_id=c.llm_provider_id,
                    prompt_template_id=c.prompt_template_id,
                    article_raw_html=c.article_raw_html,
                    article_edited_at=c.article_edited_at,
                    monitoring_process_id=c.monitoring_process_id,
                    status=c.status,
                )
                for c in ai_comments
            ]
        # Session closed

        logger.info(f"Read {len(comment_snapshots)} prepared AIComments for process {process_id}")

        # Step 2: Cache LLM provider configurations as DTOs
        llm_configs_cache = {}
        if unique_llm_ids:
            session = await self.get_async_session()
            async with session:
                result = await session.execute(
                    select(LLMProviderConfiguration).where(
                        LLMProviderConfiguration.id.in_(unique_llm_ids)
                    )
                )
                providers = result.scalars().all()
                llm_configs_cache = {
                    p.id: LLMGenerationConfig.from_model(p, p.get_api_key())
                    for p in providers
                }
            # Session closed
            logger.info(f"Cached {len(llm_configs_cache)} LLM provider DTOs")

        # Step 3: Cache prompt templates
        prompt_configs_cache = {}
        if unique_prompt_ids:
            session = await self.get_async_session()
            async with session:
                result = await session.execute(
                    select(PromptTemplate).where(
                        PromptTemplate.id.in_(unique_prompt_ids)
                    )
                )
                templates = result.scalars().all()
                prompt_configs_cache = {
                    t.id: PromptConfig(template_model=t)
                    for t in templates
                }
            # Session closed
            logger.info(f"Cached {len(prompt_configs_cache)} prompt templates")

        return comment_snapshots, llm_configs_cache, prompt_configs_cache

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
        except LLMProviderError as exc:
            error_msg = (
                f"LLM generation failed for article {snapshot.mymoment_article_id}: {exc}"
            )
            llm_summary_logger.error(
                "comment_generation_failed %s",
                format_log_context(**log_context, status="failed", error=str(exc)),
            )
            await self._mark_comment_failed(snapshot.id, error_msg, expected_status="prepared")
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "failed",
                "reason": str(exc),
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }
        except Exception as exc:
            error_msg = (
                f"Unexpected error generating comment for article "
                f"{snapshot.mymoment_article_id}: {exc}"
            )
            llm_summary_logger.error(
                "comment_generation_failed %s",
                format_log_context(
                    **log_context,
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                ),
            )
            await self._mark_comment_failed(snapshot.id, error_msg, expected_status="prepared")
            return {
                "ai_comment_id": str(ai_comment_id),
                "status": "failed",
                "reason": str(exc),
                "execution_time_seconds": (datetime.utcnow() - start_time).total_seconds(),
            }

    async def _generate_comments_async(self, process_id: uuid.UUID) -> Dict[str, Any]:
        """
        Main async method for comment generation.

        Implements the generation workflow using Pattern 4:
        1. Batch read prepared AIComments and cache reference data
        2. For each comment: format prompt, call LLM API, update record
        3. Handle errors per article (one failure doesn't stop others)
        4. Track timing and aggregate results

        Args:
            process_id: Monitoring process UUID

        Returns:
            Result dictionary with counts and errors
        """
        start_time = datetime.utcnow()
        generated_count = 0
        failed_count = 0
        errors = []
        total_generation_time_ms = 0

        try:
            skip_reason = await get_process_skip_reason(
                self.get_async_session,
                process_id,
            )
            if skip_reason:
                return {
                    'generated': 0,
                    'failed': 0,
                    'errors': [],
                    'execution_time_seconds': 0,
                    'avg_generation_time_ms': 0,
                    'status': 'skipped',
                    'reason': skip_reason,
                }

            # Step 1: Read and cache (Pattern 4)
            comment_snapshots, llm_configs, prompt_configs = await self._read_and_cache_for_generation(
                process_id
            )

            if not comment_snapshots:
                logger.info(f"No prepared AIComments found for process {process_id}")
                return {
                    'generated': 0,
                    'failed': 0,
                    'errors': [],
                    'execution_time_seconds': 0,
                    'avg_generation_time_ms': 0,
                    'status': 'success'
                }

            logger.info(f"Starting comment generation for {len(comment_snapshots)} articles")

            # Step 2: Process each comment
            for i, comment_snapshot in enumerate(comment_snapshots, 1):
                log_context = self._build_log_context(process_id, comment_snapshot)
                log_context_str = format_log_context(**log_context)
                try:
                    skip_reason = await get_process_skip_reason(
                        self.get_async_session,
                        comment_snapshot.monitoring_process_id,
                    )
                    if skip_reason:
                        logger.info(
                            "Skipping generation for AIComment %s: %s",
                            comment_snapshot.id,
                            skip_reason,
                        )
                        continue

                    # Get cached configurations
                    llm_config = llm_configs.get(comment_snapshot.llm_provider_id)
                    prompt_config = prompt_configs.get(comment_snapshot.prompt_template_id)

                    if not llm_config:
                        error_msg = f"LLM provider configuration not found for comment {comment_snapshot.id}"
                        logger.error(error_msg)
                        await self._mark_comment_failed(comment_snapshot.id, error_msg)
                        failed_count += 1
                        errors.append(error_msg)
                        continue

                    if not prompt_config:
                        error_msg = f"Prompt template not found for comment {comment_snapshot.id}"
                        logger.error(error_msg)
                        await self._mark_comment_failed(comment_snapshot.id, error_msg)
                        failed_count += 1
                        errors.append(error_msg)
                        continue

                    # Format user prompt with article data
                    formatted_prompt = self._format_user_prompt(comment_snapshot, prompt_config)
                    llm_summary_logger.info(
                        "comment_generation_start %s",
                        log_context_str,
                    )

                    # Generate comment via LLM (outside DB session)
                    gen_result = await self._generate_comment_with_llm(
                        formatted_prompt=formatted_prompt,
                        system_prompt=prompt_config.template_model.system_prompt,
                        llm_config=llm_config,
                        log_context=log_context,
                    )

                    # Normalize to HTML paragraphs, then add AI prefix
                    normalized_content = ensure_html_paragraphs(gen_result.comment_content)
                    comment_with_prefix = self._add_ai_prefix(normalized_content)

                    # Validate comment before persisting (mirrors CommentService quality gate)
                    validation = validate_comment(comment_with_prefix)
                    if not validation["is_valid"]:
                        error_msg = f"Comment failed validation for article {comment_snapshot.mymoment_article_id}: {validation['errors']}"
                        logger.error(error_msg)
                        await self._mark_comment_failed(comment_snapshot.id, error_msg)
                        failed_count += 1
                        errors.append(error_msg)
                        continue

                    # Update AIComment record
                    comment_data = {
                        'comment_content': comment_with_prefix,
                        'reasoning_content': gen_result.reasoning_content,
                        'ai_model_name': gen_result.model_used,
                        'ai_provider_name': gen_result.provider_used,
                        'generation_tokens': gen_result.total_tokens,
                        'generation_time_ms': gen_result.generation_time_ms
                    }

                    await self._update_generated_comment(comment_snapshot.id, comment_data)

                    generated_count += 1
                    gen_time_ms = gen_result.generation_time_ms or 0
                    total_generation_time_ms += gen_time_ms
                    llm_summary_logger.info(
                        "comment_generation_done %s",
                        format_log_context(
                            **log_context,
                            status="generated",
                            provider=gen_result.provider_used,
                            model=gen_result.model_used,
                            duration_ms=gen_time_ms,
                            total_tokens=gen_result.total_tokens,
                        ),
                    )

                    logger.info(
                        f"[{i}/{len(comment_snapshots)}] Generated comment for "
                        f"{comment_snapshot.article_title!r} via {gen_result.model_used} "
                        f"({gen_time_ms:.0f}ms, {gen_result.total_tokens or 0} tokens) "
                        f"{log_context_str}"
                    )

                except LLMProviderError as e:
                    error_msg = f"LLM generation failed for article {comment_snapshot.mymoment_article_id}: {str(e)}"
                    llm_summary_logger.error(
                        "comment_generation_failed %s",
                        format_log_context(**log_context, status="failed", error=str(e)),
                    )
                    logger.error(error_msg)
                    await self._mark_comment_failed(comment_snapshot.id, error_msg)
                    failed_count += 1
                    errors.append(error_msg)

                except Exception as e:
                    error_msg = f"Unexpected error generating comment for article {comment_snapshot.mymoment_article_id}: {str(e)}"
                    llm_summary_logger.error(
                        "comment_generation_failed %s",
                        format_log_context(
                            **log_context,
                            status="failed",
                            error_type=type(e).__name__,
                            error=str(e),
                        ),
                    )
                    logger.error(error_msg)
                    await self._mark_comment_failed(comment_snapshot.id, error_msg)
                    failed_count += 1
                    errors.append(error_msg)

            # Calculate statistics
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            avg_generation_time = total_generation_time_ms / generated_count if generated_count > 0 else 0

            logger.info(
                f"Comment generation completed for process {process_id}: "
                f"{generated_count} generated, {failed_count} failed, "
                f"avg generation time: {avg_generation_time:.0f}ms, "
                f"total time: {execution_time:.2f}s"
            )

            return {
                'generated': generated_count,
                'failed': failed_count,
                'errors': errors,
                'execution_time_seconds': execution_time,
                'avg_generation_time_ms': avg_generation_time,
                'status': 'success' if failed_count == 0 else 'partial'
            }

        except Exception as e:
            error_msg = f"Comment generation failed: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            return {
                'generated': generated_count,
                'failed': failed_count,
                'errors': errors,
                'execution_time_seconds': execution_time,
                'avg_generation_time_ms': 0,
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
    base=CommentGenerationTask,
    name='src.tasks.comment_generation.generate_comment_for_article',
    queue='generation',
    max_retries=3,
    default_retry_delay=180
)
def generate_comment_for_article(self, ai_comment_id: Any, *compat_args: Any) -> Dict[str, Any]:
    """Generate a comment for a single AIComment row."""
    try:
        ai_comment_id = _normalize_identifier(ai_comment_id, compat_args)
        task_id = getattr(self.request, "id", None)
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
        logger.error(
            "Single-comment generation task failed %s",
            format_log_context(
                task_id=getattr(self.request, "id", None),
                ai_comment_id=ai_comment_id,
                error=str(exc),
            ),
        )
        self.retry(exc=exc, countdown=180)


@celery_app.task(
    bind=True,
    base=CommentGenerationTask,
    name='src.tasks.comment_generation.generate_comments_for_articles',
    queue='generation',
    max_retries=3,
    default_retry_delay=180
)
def generate_comments_for_articles(self, process_id: Any, *compat_args: Any) -> Dict[str, Any]:
    """
    Celery task wrapper for AI comment generation.

    This is the entry point for the generation stage of the monitoring pipeline.
    Generates AI comments for prepared articles with status='prepared',
    updates them to status='generated'.

    Args:
        process_id: Monitoring process UUID as string

    Returns:
        Dictionary with generation results:
        - generated: Number of comments successfully generated
        - failed: Number of comments that failed generation
        - errors: List of error messages
        - execution_time_seconds: Task execution time
        - avg_generation_time_ms: Average LLM generation time per comment
        - status: 'success', 'partial', or 'failed'
    """
    try:
        process_id = _normalize_identifier(process_id, compat_args)
        task_id = getattr(self.request, "id", None)
        logger.info(
            "Starting comment generation task %s",
            format_log_context(task_id=task_id, process_id=process_id),
        )
        result = asyncio.run(self._generate_comments_async(uuid.UUID(process_id)))
        logger.info(
            "Comment generation task completed %s",
            format_log_context(
                task_id=task_id,
                process_id=process_id,
                generated=result.get("generated"),
                failed=result.get("failed"),
                status=result.get("status"),
            ),
        )
        return result

    except Exception as exc:
        logger.error(
            "Comment generation task failed %s",
            format_log_context(
                task_id=getattr(self.request, "id", None),
                process_id=process_id,
                error=str(exc),
            ),
        )
        # Retry with exponential backoff
        self.retry(exc=exc, countdown=180)
