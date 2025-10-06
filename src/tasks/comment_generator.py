"""
Comment generation task for AI-powered comment creation.

This module implements background tasks for generating AI comments on myMoment articles
using configured LLM providers with proper attribution and login context.
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
from src.models.monitoring_process import MonitoringProcess
from src.models.mymoment_login import MyMomentLogin
from src.models.ai_comment import AIComment
from src.models.prompt_template import PromptTemplate
from src.models.llm_provider import LLMProviderConfiguration
from src.services.llm_service import LLMProviderService
from src.config.database import get_database_manager
from src.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class CommentGenerationResult:
    """Result of comment generation operation."""
    process_id: uuid.UUID
    articles_processed: int
    comments_generated: int
    comments_posted: int
    errors: List[str]
    execution_time_seconds: float
    status: str  # success, partial, failed


class CommentGenerationTask(BaseTask):
    """Base class for comment generation tasks."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()


@celery_app.task(
    bind=True,
    base=CommentGenerationTask,
    name='src.tasks.comment_generator.generate_comments_for_process',
    queue='comments',
    max_retries=3,
    default_retry_delay=120
)
def generate_comments_for_process(self, process_id: str) -> Dict[str, Any]:
    """
    Generate AI comments for new articles in a monitoring process.

    Args:
        process_id: UUID of the monitoring process

    Returns:
        Dictionary with comment generation results
    """
    try:
        result = asyncio.run(self._generate_comments_for_process_async(uuid.UUID(process_id)))
        return {
            'process_id': str(result.process_id),
            'articles_processed': result.articles_processed,
            'comments_generated': result.comments_generated,
            'comments_posted': result.comments_posted,
            'errors': result.errors,
            'execution_time_seconds': result.execution_time_seconds,
            'status': result.status
        }
    except Exception as exc:
        logger.error(f"Comment generation failed for process {process_id}: {exc}")
        self.retry(exc=exc, countdown=120)


class CommentGenerationTaskHelpers:
    """Helper methods for CommentGenerationTask - mixed into the task class."""

    async def _generate_comments_for_process_async(self, process_id: uuid.UUID) -> CommentGenerationResult:
        """Async implementation of comment generation using AIComment model."""
        start_time = datetime.utcnow()
        errors = []
        comments_generated = 0

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

                # Get AIComment records that need comment generation (status='discovered')
                ai_comments = await self._get_comments_needing_generation(session, process_id)
                if not ai_comments:
                    logger.info(f"No articles need comments for process {process.name}")
                    execution_time = (datetime.utcnow() - start_time).total_seconds()
                    return CommentGenerationResult(
                        process_id=process_id,
                        articles_processed=0,
                        comments_generated=0,
                        comments_posted=0,
                        errors=[],
                        execution_time_seconds=execution_time,
                        status="success"
                    )

                logger.info(f"Generating comments for {len(ai_comments)} AIComment records in process {process.name}")

                # Get LLM provider configuration for user
                llm_config = await self._get_llm_provider_config(session, process.user_id)
                if not llm_config:
                    raise ValueError(f"No active LLM provider found for user {process.user_id}")

                # Initialize LLM service
                llm_service = LLMProviderService(session)

                # Process each AIComment record
                for ai_comment in ai_comments:
                    try:
                        # Generate comment content using LLM
                        comment_content = await self._generate_comment_content(
                            session, ai_comment, llm_service, llm_config, process
                        )

                        # Update AIComment with generated content
                        ai_comment.comment_content = comment_content
                        ai_comment.status = 'generated'
                        ai_comment.ai_model_name = llm_config.model_name
                        ai_comment.ai_provider_name = llm_config.provider_name
                        ai_comment.updated_at = datetime.utcnow()

                        comments_generated += 1
                        logger.info(f"Generated comment for article '{ai_comment.article_title}'")

                    except Exception as e:
                        error_msg = f"Failed to generate comment for AIComment {ai_comment.id}: {str(e)}"
                        errors.append(error_msg)
                        logger.error(error_msg)

                # Commit all updates
                await session.commit()

                # Update process statistics
                from sqlalchemy import update
                await session.execute(
                    update(MonitoringProcess)
                    .where(MonitoringProcess.id == process_id)
                    .values(
                        comments_generated=MonitoringProcess.comments_generated + comments_generated,
                        last_activity_at=datetime.utcnow()
                    )
                )
                await session.commit()

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                status = "success" if not errors else "partial"

                logger.info(f"Comment generation completed for process {process.name}: "
                          f"{len(ai_comments)} articles processed, {comments_generated} comments generated, "
                          f"{len(errors)} errors")

                # Schedule comment posting task for generated comments
                if (not process.generate_only) and (comments_generated > 0):
                    await self._schedule_comment_posting(process_id, comments_generated)

                return CommentGenerationResult(
                    process_id=process_id,
                    articles_processed=len(ai_comments),
                    comments_generated=comments_generated,
                    comments_posted=0,  # Posting happens in separate task
                    errors=errors,
                    execution_time_seconds=execution_time,
                    status=status
                )

            except Exception as e:
                error_msg = f"Comment generation failed: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                return CommentGenerationResult(
                    process_id=process_id,
                    articles_processed=0,
                    comments_generated=0,
                    comments_posted=0,
                    errors=errors,
                    execution_time_seconds=execution_time,
                    status="failed"
                )

    async def _get_comments_needing_generation(self, session: AsyncSession, process_id: uuid.UUID) -> List[AIComment]:
        """Get AIComment records that need comment content generated (status='discovered')."""
        result = await session.execute(
            select(AIComment).where(
                and_(
                    AIComment.monitoring_process_id == process_id,
                    AIComment.status == 'discovered',
                    AIComment.comment_content.is_(None)
                )
            )
        )
        return result.scalars().all()

    async def _get_llm_provider_config(self, session: AsyncSession, user_id: uuid.UUID) -> Optional[LLMProviderConfiguration]:
        """Get active LLM provider configuration for user."""
        result = await session.execute(
            select(LLMProviderConfiguration).where(
                and_(
                    LLMProviderConfiguration.user_id == user_id,
                    LLMProviderConfiguration.is_active == True
                )
            ).limit(1)
        )
        return result.scalar_one_or_none()

    async def _generate_comment_content(
        self,
        session: AsyncSession,
        ai_comment: AIComment,
        llm_service: LLMProviderService,
        llm_config: LLMProviderConfiguration,
        process: MonitoringProcess
    ) -> str:
        """Generate comment content using LLM for an AIComment record."""

        # Get prompt templates for this process
        prompt_template = await self._get_prompt_template(session, process)

        if not prompt_template:
            raise ValueError(f"No prompt template found for process {process.id}")

        # Format user prompt template with article data from AIComment snapshot
        try:
            formatted_user_prompt = prompt_template.user_prompt_template.format(
                article_title=ai_comment.article_title or "",
                article_author=ai_comment.article_author or "",
                article_content=ai_comment.article_content or "",
                article_raw_html=ai_comment.article_raw_html or ""
            )
        except KeyError as e:
            raise ValueError(f"Missing placeholder in prompt template: {e}")

        # Generate comment using LLM service with system and user prompts
        generated_text = await llm_service.generate_completion(
            user_prompt=formatted_user_prompt,
            system_prompt=prompt_template.system_prompt,
            provider_config=llm_config
        )

        # Add German prefix as per FR-006
        settings = get_settings()
        comment_prefix = settings.monitoring.AI_COMMENT_PREFIX + " "
        final_comment = comment_prefix + generated_text.strip()

        return final_comment

    async def _get_prompt_template(self, session: AsyncSession, process: MonitoringProcess) -> Optional[PromptTemplate]:
        """Get a prompt template for the monitoring process."""
        # Get prompt templates associated with this process
        from src.models.monitoring_process_prompt import MonitoringProcessPrompt

        result = await session.execute(
            select(PromptTemplate)
            .join(MonitoringProcessPrompt)
            .where(MonitoringProcessPrompt.monitoring_process_id == process.id)
            .limit(1)
        )

        return result.scalar_one_or_none()

    async def _schedule_comment_posting(self, process_id: uuid.UUID, comments_count: int):
        """Schedule comment posting task for generated comments."""
        # Import here to avoid circular import
        from src.tasks.comment_poster import post_comments_for_process

        # Schedule comment posting task
        post_comments_for_process.apply_async(
            args=[str(process_id)],
            countdown=10,  # Wait 10 seconds before starting comment posting
            queue='comments'
        )

        logger.info(f"Scheduled comment posting for {comments_count} generated comments "
                   f"in process {process_id}")


# Mix helpers into the task class
for name in dir(CommentGenerationTaskHelpers):
    if not name.startswith('_') or name.startswith('_generate_') or name.startswith('_get_') or name.startswith('_schedule_'):
        if callable(getattr(CommentGenerationTaskHelpers, name)):
            setattr(CommentGenerationTask, name, getattr(CommentGenerationTaskHelpers, name))
