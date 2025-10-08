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
from sqlalchemy import select, and_

from src.tasks.worker import celery_app, BaseTask
from src.models.ai_comment import AIComment
from src.models.llm_provider import LLMProviderConfiguration
from src.models.prompt_template import PromptTemplate
from src.services.llm_service import LLMProviderService, LLMProviderError
from src.config.database import get_database_manager
from src.config.settings import get_settings

logger = logging.getLogger(__name__)


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


@dataclass
class LLMConfig:
    """Cached LLM provider configuration."""
    provider_name: str
    model_name: str
    api_key: str
    max_tokens: Optional[int]
    temperature: Optional[float]


@dataclass
class PromptConfig:
    """Cached prompt template configuration."""
    system_prompt: str
    user_prompt_template: str


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
    ) -> tuple[List[CommentSnapshot], Dict[uuid.UUID, LLMConfig], Dict[uuid.UUID, PromptConfig]]:
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
                    prompt_template_id=c.prompt_template_id
                )
                for c in ai_comments
            ]
        # Session closed

        logger.info(f"Read {len(comment_snapshots)} prepared AIComments for process {process_id}")

        # Step 2: Cache LLM provider configurations
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
                    p.id: LLMConfig(
                        provider_name=p.provider_name,
                        model_name=p.model_name,
                        api_key=p.get_api_key(),  # Decrypt once and cache
                        max_tokens=p.max_tokens,
                        temperature=p.temperature
                    )
                    for p in providers
                }
            # Session closed
            logger.info(f"Cached {len(llm_configs_cache)} LLM provider configurations")

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
                    t.id: PromptConfig(
                        system_prompt=t.system_prompt,
                        user_prompt_template=t.user_prompt_template
                    )
                    for t in templates
                }
            # Session closed
            logger.info(f"Cached {len(prompt_configs_cache)} prompt templates")

        return comment_snapshots, llm_configs_cache, prompt_configs_cache

    def _format_user_prompt(
        self,
        article_snapshot: CommentSnapshot,
        prompt_template: PromptConfig
    ) -> str:
        """
        Format user prompt template with article data.

        Handles missing placeholders gracefully by leaving them as-is or
        replacing with empty strings where appropriate.

        Args:
            article_snapshot: Article data snapshot
            prompt_template: Prompt template configuration

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
        }

        # Format the template
        formatted_prompt = prompt_template.user_prompt_template
        for placeholder, value in context.items():
            formatted_prompt = formatted_prompt.replace(f"{{{placeholder}}}", value)

        return formatted_prompt

    async def _generate_comment_with_llm(
        self,
        formatted_prompt: str,
        system_prompt: str,
        llm_config: LLMConfig
    ) -> tuple[str, int]:
        """
        Generate comment using LLM API.

        Calls LLMProviderService.generate_completion() outside any database session.

        Args:
            formatted_prompt: User prompt with article data filled in
            system_prompt: System prompt to guide generation
            llm_config: LLM provider configuration

        Returns:
            Tuple of (generated_text, generation_time_ms)

        Raises:
            LLMProviderError: If generation fails
        """
        start_time = datetime.utcnow()

        # Create a temporary session for LLMProviderService
        # Note: The service will use this session but won't hold it during API calls
        session = await self.get_async_session()
        async with session:
            # Create a temporary LLMProviderConfiguration object for generation
            # We can't use the cached config directly, so we recreate it
            temp_provider = LLMProviderConfiguration(
                id=uuid.uuid4(),  # Temporary ID
                user_id=uuid.uuid4(),  # Temporary user ID
                provider_name=llm_config.provider_name,
                model_name=llm_config.model_name,
                max_tokens=llm_config.max_tokens,
                temperature=llm_config.temperature
            )
            temp_provider.set_api_key(llm_config.api_key)

            # Initialize LLM service
            llm_service = LLMProviderService(session)

            # Generate completion (this happens outside the DB session internally)
            generated_text = await llm_service.generate_completion(
                user_prompt=formatted_prompt,
                provider_config=temp_provider,
                system_prompt=system_prompt
            )

        # Session closed

        # Calculate generation time
        end_time = datetime.utcnow()
        generation_time_ms = int((end_time - start_time).total_seconds() * 1000)

        return generated_text, generation_time_ms

    def _add_ai_prefix(self, comment_text: str) -> str:
        """
        Add AI comment prefix to generated text.

        Prepends the configured AI_COMMENT_PREFIX from settings.

        Args:
            comment_text: Generated comment text

        Returns:
            Comment text with AI prefix prepended
        """
        settings = get_settings()
        prefix = settings.monitoring.AI_COMMENT_PREFIX

        # Add prefix with a space separator if comment doesn't start with whitespace
        if comment_text and not comment_text[0].isspace():
            return f"{prefix} {comment_text}"
        else:
            return f"{prefix}{comment_text}"

    async def _update_generated_comment(
        self,
        ai_comment_id: uuid.UUID,
        comment_data: Dict[str, Any]
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
            ai_comment = await session.get(AIComment, ai_comment_id)

            if not ai_comment:
                raise ValueError(f"AIComment {ai_comment_id} not found")

            # Update fields
            ai_comment.comment_content = comment_data['comment_content']
            ai_comment.ai_model_name = comment_data['ai_model_name']
            ai_comment.ai_provider_name = comment_data['ai_provider_name']
            ai_comment.generation_tokens = comment_data.get('generation_tokens')
            ai_comment.generation_time_ms = comment_data['generation_time_ms']
            ai_comment.status = 'generated'

            # Commit single record
            await session.commit()
        # Session closed (< 50ms)

    async def _mark_comment_failed(
        self,
        ai_comment_id: uuid.UUID,
        error_message: str
    ) -> None:
        """
        Mark AIComment as failed with error message.

        Args:
            ai_comment_id: AIComment UUID to mark as failed
            error_message: Error description
        """
        session = await self.get_async_session()
        async with session:
            ai_comment = await session.get(AIComment, ai_comment_id)

            if not ai_comment:
                logger.warning(f"AIComment {ai_comment_id} not found for failure marking")
                return

            ai_comment.status = 'failed'
            ai_comment.error_message = error_message
            ai_comment.failed_at = datetime.utcnow()

            await session.commit()
        # Session closed

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
                try:
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

                    # Generate comment via LLM (outside DB session)
                    generated_text, generation_time_ms = await self._generate_comment_with_llm(
                        formatted_prompt=formatted_prompt,
                        system_prompt=prompt_config.system_prompt,
                        llm_config=llm_config
                    )

                    # Add AI prefix
                    comment_with_prefix = self._add_ai_prefix(generated_text)

                    # Update AIComment record
                    comment_data = {
                        'comment_content': comment_with_prefix,
                        'ai_model_name': llm_config.model_name,
                        'ai_provider_name': llm_config.provider_name,
                        'generation_tokens': None,  # Not available from current API
                        'generation_time_ms': generation_time_ms
                    }

                    await self._update_generated_comment(comment_snapshot.id, comment_data)

                    generated_count += 1
                    total_generation_time_ms += generation_time_ms

                    # Log progress
                    if i % 10 == 0 or i == len(comment_snapshots):
                        avg_time = total_generation_time_ms / generated_count if generated_count > 0 else 0
                        logger.info(
                            f"Generation progress: {i}/{len(comment_snapshots)} processed, "
                            f"{generated_count} generated, {failed_count} failed, "
                            f"avg time: {avg_time:.0f}ms"
                        )

                except LLMProviderError as e:
                    error_msg = f"LLM generation failed for article {comment_snapshot.mymoment_article_id}: {str(e)}"
                    logger.error(error_msg)
                    await self._mark_comment_failed(comment_snapshot.id, error_msg)
                    failed_count += 1
                    errors.append(error_msg)

                except Exception as e:
                    error_msg = f"Unexpected error generating comment for article {comment_snapshot.mymoment_article_id}: {str(e)}"
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


@celery_app.task(
    bind=True,
    base=CommentGenerationTask,
    name='src.tasks.comment_generation.generate_comments_for_articles',
    queue='generation',
    max_retries=3,
    default_retry_delay=180
)
def generate_comments_for_articles(self, process_id: str) -> Dict[str, Any]:
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
        logger.info(f"Starting comment generation task for process {process_id}")
        result = asyncio.run(self._generate_comments_async(uuid.UUID(process_id)))
        logger.info(f"Comment generation task completed: {result}")
        return result

    except Exception as exc:
        logger.error(f"Comment generation task failed for process {process_id}: {exc}")
        # Retry with exponential backoff
        self.retry(exc=exc, countdown=180)
