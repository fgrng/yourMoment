"""
Comment generation service for yourMoment application.

Implements T048: AI comment generation with German prefix requirement and
multi-provider LLM support. Integrates with prompt templates, LLM providers,
and scraping service for end-to-end comment generation and posting workflow.
"""

import asyncio
import uuid
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass

import instructor
import openai
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from src.models.ai_comment import AIComment
from src.models.prompt_template import PromptTemplate
from src.models.llm_provider import LLMProviderConfiguration
from src.models.monitoring_process import MonitoringProcess
from src.services.llm_service import LLMProviderService
from src.config.settings import get_settings
from src.services.scraper_service import (
    ScraperService,
    SessionContext,
    ScrapingError
)

logger = logging.getLogger(__name__)


@dataclass
class CommentGenerationConfig:
    """Configuration for comment generation operations."""
    max_comment_length: int = 500
    min_comment_length: int = 50
    generation_timeout: int = 30  # seconds
    max_retries: int = 3
    retry_delay: float = 2.0
    enable_content_validation: bool = True
    enable_profanity_filter: bool = True
    fallback_to_next_provider: bool = True


@dataclass
class CommentRequest:
    """Request parameters for comment generation."""
    article_id: str
    article_title: str
    article_content: str
    article_author: str
    article_published_at: Optional[datetime] = None
    article_raw_html: Optional[str] = None  # Raw HTML content for advanced processing
    article_url: Optional[str] = None  # myMoment article URL
    article_category: Optional[int] = None  # myMoment category ID
    article_edited_at: Optional[datetime] = None  # Last edit timestamp
    mymoment_username: str = ""
    prompt_template_id: Optional[uuid.UUID] = None
    llm_provider_id: Optional[uuid.UUID] = None
    highlight_text: Optional[str] = None


@dataclass
class CommentResponse:
    """Response from comment generation."""
    content: str
    is_valid: bool
    has_ai_prefix: bool
    provider_used: str
    model_used: str
    generation_time: float
    token_count: Optional[int] = None
    validation_errors: List[str] = None
    fallback_used: bool = False


class CommentGenerationError(Exception):
    """Base exception for comment generation operations."""
    pass


class CommentValidationError(CommentGenerationError):
    """Raised when generated comment fails validation."""
    pass


class ProviderExhaustionError(CommentGenerationError):
    """Raised when all configured LLM providers fail."""
    pass


class CommentStructure(BaseModel):
    """Structured comment response from LLM."""
    comment_content: str
    confidence_level: float
    reasoning: Optional[str] = None


class CommentService:
    """
    AI comment generation service with multi-provider LLM support.

    Features:
    - German AI prefix enforcement (FR-006)
    - Multi-provider LLM integration (OpenAI, Mistral, HuggingFace)
    - Prompt template processing with placeholder replacement
    - Comment validation and quality assurance
    - Fallback strategies for provider failures
    - Integration with scraping service for comment posting
    - Rate limiting and retry mechanisms
    """

    def __init__(
        self,
        db_session: AsyncSession,
        scraper_service: Optional[ScraperService] = None,
        config: Optional[CommentGenerationConfig] = None
    ):
        """
        Initialize comment generation service.

        Args:
            db_session: Database session for operations
            scraper_service: Optional scraper service for comment posting
            config: Comment generation configuration (optional)
        """
        self.db_session = db_session
        self.scraper_service = scraper_service
        self.config = config or CommentGenerationConfig()

        # Initialize LLM provider service
        self.llm_service = LLMProviderService(db_session)

        # Rate limiting
        self._generation_lock = asyncio.Lock()
        self._last_generation_time = {}

    async def generate_comment(
        self,
        request: CommentRequest,
        user_id: uuid.UUID,
        monitoring_process_id: uuid.UUID
    ) -> CommentResponse:
        """
        Generate AI comment for an article using configured LLM providers.

        Args:
            request: Comment generation request parameters
            user_id: User ID for provider access validation
            monitoring_process_id: Monitoring process ID for comment attribution

        Returns:
            CommentResponse with generated comment and metadata

        Raises:
            CommentGenerationError: If comment generation fails
            ProviderExhaustionError: If all providers fail
        """
        start_time = datetime.utcnow()

        try:
            # Get prompt template (use default if not specified)
            template = await self._get_prompt_template(request.prompt_template_id, user_id)

            # Render prompt with article context
            rendered_prompt = await self._render_prompt(template, request)

            # Get LLM providers (ordered by preference)
            providers = await self._get_provider_chain(request.llm_provider_id, user_id)

            if not providers:
                raise ProviderExhaustionError("No active LLM providers configured")

            # Try each provider until successful
            last_error = None
            for i, provider_config in enumerate(providers):
                try:
                    logger.info(f"Attempting comment generation with provider {provider_config.provider_name}")

                    # Apply rate limiting per provider
                    await self._rate_limit_provider(provider_config.id)

                    # Generate comment using this provider
                    response = await self._generate_with_provider(
                        provider_config,
                        template,
                        rendered_prompt,
                        request,
                        user_id,
                        fallback_used=(i > 0)
                    )

                    # Calculate generation time
                    generation_time = (datetime.utcnow() - start_time).total_seconds()
                    response.generation_time = generation_time

                    logger.info(
                        f"Successfully generated comment using {provider_config.provider_name} "
                        f"in {generation_time:.2f}s"
                    )
                    return response

                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"Provider {provider_config.provider_name} failed: {e}. "
                        f"{'Trying next provider...' if i < len(providers) - 1 else 'No more providers available.'}"
                    )

                    if not self.config.fallback_to_next_provider:
                        break

            # All providers failed
            generation_time = (datetime.utcnow() - start_time).total_seconds()
            raise ProviderExhaustionError(
                f"All {len(providers)} LLM providers failed. "
                f"Last error: {last_error}"
            )

        except Exception as e:
            logger.error(f"Comment generation failed: {e}")
            if isinstance(e, (CommentGenerationError, ProviderExhaustionError)):
                raise
            raise CommentGenerationError(f"Comment generation failed: {e}")

    async def generate_and_post_comment(
        self,
        request: CommentRequest,
        user_id: uuid.UUID,
        monitoring_process_id: uuid.UUID,
        mymoment_login_id: uuid.UUID,
        session_context: Optional[SessionContext] = None
    ) -> Dict[str, Any]:
        """
        Generate AI comment and post it to myMoment platform.

        Args:
            request: Comment generation request parameters
            user_id: User ID for validation
            monitoring_process_id: Monitoring process ID
            mymoment_login_id: MyMoment login to use for posting
            session_context: Optional existing session context

        Returns:
            Dictionary with generation and posting results

        Raises:
            CommentGenerationError: If generation or posting fails
        """
        try:
            # Generate comment
            comment_response = await self.generate_comment(request, user_id, monitoring_process_id)

            # Validate comment before posting
            if not comment_response.is_valid:
                raise CommentValidationError(
                    f"Generated comment failed validation: {comment_response.validation_errors}"
                )

            # Post comment if scraper service is available
            posted = False
            posting_error = None

            if self.scraper_service and session_context:
                try:
                    posted = await self.scraper_service.post_comment(
                        session_context,
                        request.article_id,
                        comment_response.content,
                        request.highlight_text
                    )
                except ScrapingError as e:
                    posting_error = str(e)
                    logger.error(f"Failed to post comment: {e}")

            # Store comment in database
            comment_record = await self._store_comment(
                request,
                comment_response,
                monitoring_process_id,
                mymoment_login_id,
                posted
            )

            return {
                "comment_id": comment_record.id,
                "comment_content": comment_response.content,
                "generation_successful": True,
                "posting_successful": posted,
                "posting_error": posting_error,
                "provider_used": comment_response.provider_used,
                "model_used": comment_response.model_used,
                "generation_time": comment_response.generation_time,
                "fallback_used": comment_response.fallback_used
            }

        except Exception as e:
            logger.error(f"Comment generation and posting failed: {e}")
            if isinstance(e, CommentGenerationError):
                raise
            raise CommentGenerationError(f"Comment generation and posting failed: {e}")

    async def _generate_with_provider(
        self,
        provider_config: LLMProviderConfiguration,
        template: PromptTemplate,
        rendered_prompt: str,
        request: CommentRequest,
        user_id: uuid.UUID,
        fallback_used: bool = False
    ) -> CommentResponse:
        """
        Generate comment using a specific LLM provider.

        Args:
            provider_config: LLM provider configuration
            template: Prompt template used
            rendered_prompt: Rendered user prompt
            request: Original request parameters
            user_id: User ID
            fallback_used: Whether this is a fallback provider

        Returns:
            CommentResponse with generated comment

        Raises:
            CommentGenerationError: If generation fails
        """
        try:
            # Get provider configuration for generation
            generation_config = await self.llm_service.get_provider_for_generation(
                provider_config.id,
                user_id
            )

            # Initialize provider-specific client
            client = await self._initialize_provider_client(provider_config, generation_config)

            # Generate comment using instructor
            async with asyncio.timeout(self.config.generation_timeout):
                response = await self._call_llm(
                    client,
                    provider_config,
                    template.system_prompt,
                    rendered_prompt
                )

            # Extract comment text
            if isinstance(response, CommentStructure):
                comment_content = response.comment_content
                token_count = None  # Would need provider-specific token counting
            else:
                comment_content = str(response)
                token_count = None

            # Ensure German AI prefix (FR-006)
            comment_content = self._ensure_german_prefix(comment_content)

            # Validate generated comment
            validation_result = self._validate_comment(comment_content, request)

            return CommentResponse(
                content=comment_content,
                is_valid=validation_result["is_valid"],
                has_ai_prefix=validation_result["has_ai_prefix"],
                provider_used=provider_config.provider_name,
                model_used=provider_config.model_name,
                generation_time=0.0,  # Will be set by caller
                token_count=token_count,
                validation_errors=validation_result["errors"],
                fallback_used=fallback_used
            )

        except asyncio.TimeoutError:
            raise CommentGenerationError(
                f"Comment generation timed out after "
                f"{self.config.generation_timeout}s "
                f"using {provider_config.provider_name}"
            )
        except Exception as e:
            logger.error(f"Provider {provider_config.provider_name} generation failed: {e}")
            raise CommentGenerationError(f"LLM generation failed: {e}")

    async def _initialize_provider_client(
        self,
        provider_config: LLMProviderConfiguration,
        generation_config: Dict[str, Any]
    ) -> Union[instructor.Instructor, Any]:
        """
        Initialize provider-specific LLM client with instructor.

        Args:
            provider_config: Provider configuration
            generation_config: Generation configuration with API key

        Returns:
            Initialized instructor client

        Raises:
            CommentGenerationError: If client initialization fails
        """
        try:
            api_key = generation_config["api_key"]
            provider_name = provider_config.provider_name.lower()

            if provider_name == "openai":
                base_client = openai.AsyncOpenAI(api_key=api_key)
                return instructor.from_openai(base_client)

            if provider_name == "mistral":
                try:
                    from mistralai.client import Mistral
                    from instructor.providers.mistral.client import from_mistral
                except ImportError as exc:
                    raise CommentGenerationError(
                        "mistralai package is required for Mistral support"
                    ) from exc

                base_client = Mistral(api_key=api_key)
                return from_mistral(base_client, use_async=True)

            if provider_name == "huggingface":
                base_client = openai.AsyncOpenAI(
                    api_key=api_key,
                    base_url="https://api-inference.huggingface.co/v1"
                )
                return instructor.from_openai(base_client)

            raise CommentGenerationError(f"Unsupported provider: {provider_name}")

        except Exception as e:
            logger.error(f"Failed to initialize {provider_config.provider_name} client: {e}")
            raise CommentGenerationError(f"Client initialization failed: {e}")

    async def _call_llm(
        self,
        client: instructor.Instructor,
        provider_config: LLMProviderConfiguration,
        system_prompt: str,
        user_prompt: str
    ) -> CommentStructure:
        """
        Make structured LLM API call using instructor.

        Args:
            client: Instructor client
            provider_config: Provider configuration
            system_prompt: System prompt
            user_prompt: User prompt

        Returns:
            Structured CommentStructure response

        Raises:
            CommentGenerationError: If LLM call fails
        """
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            # Use instructor to get structured response
            response = await client.chat.completions.create(
                model=provider_config.model_name,
                messages=messages,
                response_model=CommentStructure,
                max_tokens=provider_config.max_tokens,
                temperature=provider_config.temperature
            )

            return response

        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            raise CommentGenerationError(f"LLM API call failed: {e}")

    async def _get_prompt_template(
        self,
        template_id: Optional[uuid.UUID],
        user_id: uuid.UUID
    ) -> PromptTemplate:
        """
        Get prompt template by ID or fallback to default system template.

        Args:
            template_id: Optional template ID
            user_id: User ID for access validation

        Returns:
            PromptTemplate instance

        Raises:
            CommentGenerationError: If template not found
        """
        try:
            if template_id:
                # Get specific template (check user access)
                stmt = select(PromptTemplate).where(
                    and_(
                        PromptTemplate.id == template_id,
                        PromptTemplate.is_active.is_(True),
                        ((PromptTemplate.category == "USER") &
                         (PromptTemplate.user_id == user_id)) |
                        (PromptTemplate.category == "SYSTEM")
                    )
                )
                result = await self.db_session.execute(stmt)
                template = result.scalar_one_or_none()

                if not template:
                    raise CommentGenerationError(
                        f"Prompt template {template_id} not found or not "
                        "accessible"
                    )

                return template

            else:
                # Get default system template
                stmt = select(PromptTemplate).where(
                    and_(
                        PromptTemplate.category == "SYSTEM",
                        PromptTemplate.is_active.is_(True)
                    )
                ).limit(1)
                result = await self.db_session.execute(stmt)
                template = result.scalar_one_or_none()

                if not template:
                    # Create default template if none exists
                    template = await self._create_default_template()

                return template

        except Exception as e:
            logger.error(f"Failed to get prompt template: {e}")
            raise CommentGenerationError(f"Template retrieval failed: {e}")

    async def _create_default_template(self) -> PromptTemplate:
        """Create and store default system prompt template."""
        default_template = PromptTemplate(
            name="Default German Comment Generator",
            description="System default template for generating contextual German comments",
            system_prompt=(
                "Du bist ein hilfsreicher KI-Assistent, der konstruktive und höfliche Kommentare "
                "zu deutschen Texten verfasst. Deine Aufgabe ist es, einen kurzen, relevanten "
                "Kommentar zu schreiben, der den Inhalt würdigt oder eine hilfreiche Frage stellt. "
                "Der Kommentar soll freundlich, respektvoll und auf Deutsch verfasst sein."
            ),
            user_prompt_template=(
                "Bitte verfasse einen kurzen Kommentar (50-200 Wörter) zu folgendem Artikel:\n\n"
                "Titel: {article_title}\n"
                "Autor: {article_author}\n"
                "Inhalt: {article_content}\n\n"
                "Der Kommentar soll konstruktiv und freundlich sein."
            ),
            category="SYSTEM",
            user_id=None,
            is_active=True
        )

        self.db_session.add(default_template)
        await self.db_session.commit()
        await self.db_session.refresh(default_template)

        logger.info("Created default prompt template")
        return default_template

    async def _render_prompt(self, template: PromptTemplate, request: CommentRequest) -> str:
        """
        Render prompt template with article context.

        Args:
            template: Prompt template
            request: Comment request with context data

        Returns:
            Rendered prompt string

        Raises:
            CommentGenerationError: If template rendering fails
        """
        try:
            # Prepare context dictionary
            context = {
                "article_title": request.article_title,
                "article_content": request.article_content[:2000],  # Limit content length
                "article_author": request.article_author,
                "mymoment_username": request.mymoment_username,
            }

            # Optional context fields
            if request.article_published_at:
                context["article_published_at"] = (
                    request.article_published_at.strftime("%Y-%m-%d")
                )

            if request.article_raw_html:
                context["article_raw_html"] = request.article_raw_html[:5000]  # Limit HTML length

            # Check for missing required placeholders
            missing_keys = template.get_missing_context_keys(context)
            if missing_keys:
                logger.warning(
                    f"Missing context keys for template: {missing_keys}"
                )

            # Render template
            rendered = template.render_prompt(context)
            return rendered

        except Exception as e:
            logger.error(f"Failed to render prompt template: {e}")
            raise CommentGenerationError(f"Prompt rendering failed: {e}")

    async def _get_provider_chain(
        self,
        preferred_provider_id: Optional[uuid.UUID],
        user_id: uuid.UUID
    ) -> List[LLMProviderConfiguration]:
        """
        Get ordered list of LLM providers (preferred first, then others).

        Args:
            preferred_provider_id: Optional preferred provider ID
            user_id: User ID for provider access

        Returns:
            List of provider configurations in preference order
        """
        try:
            # Get all active providers for user
            all_providers = await self.llm_service.get_active_providers(user_id)

            if not all_providers:
                return []

            # If preferred provider specified, move it to front
            if preferred_provider_id:
                preferred_providers = [p for p in all_providers if p.id == preferred_provider_id]
                other_providers = [p for p in all_providers if p.id != preferred_provider_id]
                return preferred_providers + other_providers

            # Otherwise, use all providers in order
            return all_providers

        except Exception as e:
            logger.error(f"Failed to get provider chain: {e}")
            return []

    def _ensure_german_prefix(self, comment_content: str) -> str:
        """
        Ensure comment starts with required German AI prefix (FR-006).

        Args:
            comment_content: Original comment text

        Returns:
            Comment text with German AI prefix
        """
        ai_prefix = self._get_ai_prefix()
        if comment_content.startswith(ai_prefix):
            return comment_content

        # Add prefix with proper spacing
        if comment_content.startswith(" "):
            return f"{ai_prefix}{comment_content}"
        else:
            return f"{ai_prefix} {comment_content}"

    def _validate_comment(self, comment_content: str, request: CommentRequest) -> Dict[str, Any]:
        """
        Validate generated comment against quality and requirement criteria.

        Args:
            comment_content: Generated comment text
            request: Original request for context

        Returns:
            Dictionary with validation results
        """
        errors = []

        # Check German AI prefix (FR-006)
        ai_prefix = self._get_ai_prefix()
        has_ai_prefix = comment_content.startswith(ai_prefix)
        if not has_ai_prefix:
            errors.append("Missing required German AI prefix")

        # Check length constraints
        content_without_prefix = comment_content.replace(ai_prefix, "").strip()
        content_length = len(content_without_prefix)

        if content_length < self.config.min_comment_length:
            errors.append(
                f"Comment too short ({content_length} < "
                f"{self.config.min_comment_length} chars)"
            )

        if content_length > self.config.max_comment_length:
            errors.append(
                f"Comment too long ({content_length} > "
                f"{self.config.max_comment_length} chars)"
            )

        # Check for empty content
        if not content_without_prefix:
            errors.append("Comment content is empty after prefix")

        # Basic quality checks if enabled
        if self.config.enable_content_validation:
            # Check for repetitive text
            words = content_without_prefix.split()
            if len(words) > 5 and len(set(words)) < len(words) * 0.5:
                errors.append("Comment appears to be repetitive")

            # Check for placeholder text
            placeholder_patterns = [r'\{[^}]+\}', r'<[^>]+>', r'\[.*\]']
            for pattern in placeholder_patterns:
                if re.search(pattern, content_without_prefix):
                    errors.append("Comment contains unresolved placeholders")
                    break

        return {
            "is_valid": len(errors) == 0,
            "has_ai_prefix": has_ai_prefix,
            "errors": errors,
            "content_length": content_length
        }

    async def _rate_limit_provider(self, provider_id: uuid.UUID):
        """Apply per-provider rate limiting."""
        async with self._generation_lock:
            last_time = self._last_generation_time.get(provider_id, 0)
            now = asyncio.get_event_loop().time()
            elapsed = now - last_time

            if elapsed < self.config.retry_delay:
                sleep_time = self.config.retry_delay - elapsed
                await asyncio.sleep(sleep_time)

            self._last_generation_time[provider_id] = asyncio.get_event_loop().time()

    async def _store_comment(
        self,
        request: CommentRequest,
        response: CommentResponse,
        monitoring_process_id: uuid.UUID,
        mymoment_login_id: uuid.UUID,
        is_posted: bool
    ) -> AIComment:
        """
        Store generated AI comment with article snapshot in database.

        Args:
            request: Original comment request (contains article snapshot data)
            response: Comment generation response
            monitoring_process_id: Monitoring process ID
            mymoment_login_id: MyMoment login ID
            is_posted: Whether comment was successfully posted

        Returns:
            Created AIComment record

        Raises:
            CommentGenerationError: If storage fails
        """
        try:
            # Get user_id from monitoring process
            stmt = select(MonitoringProcess).where(MonitoringProcess.id == monitoring_process_id)
            result = await self.db_session.execute(stmt)
            process = result.scalar_one_or_none()

            if not process:
                raise CommentGenerationError(f"Monitoring process {monitoring_process_id} not found")

            user_id = process.user_id

            # Create AIComment record with article snapshot
            ai_comment = AIComment(
                # myMoment identifiers
                mymoment_article_id=request.article_id,
                mymoment_comment_id=None,  # Will be set after successful posting to myMoment

                # Foreign keys
                user_id=user_id,
                mymoment_login_id=mymoment_login_id if is_posted else None,
                monitoring_process_id=monitoring_process_id,
                prompt_template_id=request.prompt_template_id,
                llm_provider_id=request.llm_provider_id,

                # Article snapshot fields
                article_title=request.article_title,
                article_author=request.article_author,
                article_category=request.article_category,
                article_url=request.article_url or self._build_article_url(request.article_id),
                article_content=request.article_content,
                article_raw_html=request.article_raw_html or "",
                article_published_at=request.article_published_at,
                article_edited_at=request.article_edited_at,
                article_scraped_at=datetime.utcnow(),

                # AI comment fields
                comment_content=response.content,
                status="posted" if is_posted else "generated",
                ai_model_name=response.model_used,
                ai_provider_name=response.provider_used,
                generation_tokens=response.token_count,
                generation_time_ms=int(response.generation_time * 1000) if response.generation_time else None,

                # Timestamps
                created_at=datetime.utcnow(),
                posted_at=datetime.utcnow() if is_posted else None,

                # Status
                is_active=True
            )

            self.db_session.add(ai_comment)
            await self.db_session.commit()
            await self.db_session.refresh(ai_comment)

            logger.info(
                f"Stored AI comment with article snapshot: {ai_comment.id} "
                f"(article: {request.article_id}, status: {ai_comment.status})"
            )
            return ai_comment

        except Exception as e:
            logger.error(f"Failed to store AI comment: {e}")
            await self.db_session.rollback()
            raise CommentGenerationError(f"AI comment storage failed: {e}")

    async def update_comment_posted_status(
        self,
        ai_comment_id: uuid.UUID,
        mymoment_comment_id: str,
        posted_at: Optional[datetime] = None
    ) -> AIComment:
        """
        Update AI comment status after successful posting to myMoment.

        Args:
            ai_comment_id: AI comment ID
            mymoment_comment_id: Comment ID from myMoment platform
            posted_at: When posted (defaults to now)

        Returns:
            Updated AIComment record

        Raises:
            CommentGenerationError: If update fails
        """
        try:
            # Get comment
            stmt = select(AIComment).where(AIComment.id == ai_comment_id)
            result = await self.db_session.execute(stmt)
            ai_comment = result.scalar_one_or_none()

            if not ai_comment:
                raise CommentGenerationError(f"AI comment {ai_comment_id} not found")

            # Update status
            ai_comment.mark_as_posted(mymoment_comment_id, posted_at)

            await self.db_session.commit()
            await self.db_session.refresh(ai_comment)

            logger.info(f"Updated AI comment {ai_comment_id} as posted with myMoment ID {mymoment_comment_id}")
            return ai_comment

        except Exception as e:
            logger.error(f"Failed to update AI comment posted status: {e}")
            await self.db_session.rollback()
            raise CommentGenerationError(f"AI comment update failed: {e}")

    async def update_comment_failed_status(
        self,
        ai_comment_id: uuid.UUID,
        error_message: str,
        failed_at: Optional[datetime] = None
    ) -> AIComment:
        """
        Update AI comment status after failed posting attempt.

        Args:
            ai_comment_id: AI comment ID
            error_message: Error description
            failed_at: When failed (defaults to now)

        Returns:
            Updated AIComment record

        Raises:
            CommentGenerationError: If update fails
        """
        try:
            # Get comment
            stmt = select(AIComment).where(AIComment.id == ai_comment_id)
            result = await self.db_session.execute(stmt)
            ai_comment = result.scalar_one_or_none()

            if not ai_comment:
                raise CommentGenerationError(f"AI comment {ai_comment_id} not found")

            # Update status
            ai_comment.mark_as_failed(error_message, failed_at)

            await self.db_session.commit()
            await self.db_session.refresh(ai_comment)

            logger.info(f"Updated AI comment {ai_comment_id} as failed: {error_message}")
            return ai_comment

        except Exception as e:
            logger.error(f"Failed to update AI comment failed status: {e}")
            await self.db_session.rollback()
            raise CommentGenerationError(f"AI comment update failed: {e}")

    async def get_user_comment_statistics(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """
        Get AI comment generation statistics for a user.

        Args:
            user_id: User ID

        Returns:
            Dictionary with AI comment statistics
        """
        try:
            # Get AI comment statistics directly (user_id is directly on AIComment)
            stmt = select(AIComment).where(
                and_(
                    AIComment.user_id == user_id,
                    AIComment.is_active.is_(True)
                )
            )
            result = await self.db_session.execute(stmt)
            ai_comments = result.scalars().all()

            total_comments = len(ai_comments)
            posted_comments = sum(1 for c in ai_comments if c.status == "posted")
            failed_comments = sum(1 for c in ai_comments if c.status == "failed")
            generated_comments = sum(1 for c in ai_comments if c.status == "generated")

            success_rate = (posted_comments / total_comments * 100) if total_comments > 0 else 0.0

            # Calculate average generation time
            generation_times = [c.generation_time_ms for c in ai_comments if c.generation_time_ms]
            avg_generation_time_ms = sum(generation_times) / len(generation_times) if generation_times else 0

            return {
                "total_comments": total_comments,
                "posted_comments": posted_comments,
                "failed_comments": failed_comments,
                "generated_comments": generated_comments,
                "success_rate": success_rate,
                "avg_generation_time_ms": avg_generation_time_ms,
                "total_articles_commented": len(set(c.mymoment_article_id for c in ai_comments))
            }

        except Exception as e:
            logger.error(f"Failed to get comment statistics for user {user_id}: {e}")
            return {"error": str(e)}

    async def cleanup_failed_comments(self, max_age_hours: int = 24) -> int:
        """
        Cleanup old failed AI comment generation attempts.

        Args:
            max_age_hours: Maximum age of failed comments to keep

        Returns:
            Number of comments cleaned up
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)

            # Find failed AI comments older than cutoff
            stmt = select(AIComment).where(
                and_(
                    AIComment.status == "failed",
                    AIComment.created_at < cutoff_time,
                    AIComment.is_active.is_(True)
                )
            )
            result = await self.db_session.execute(stmt)
            old_failed_comments = result.scalars().all()

            if not old_failed_comments:
                return 0

            # Soft delete old failed comments
            for comment in old_failed_comments:
                comment.is_active = False
                comment.status = "deleted"

            await self.db_session.commit()

            logger.info(
                f"Cleaned up {len(old_failed_comments)} old failed AI comments"
            )
            return len(old_failed_comments)

        except Exception as e:
            logger.error(f"Failed to cleanup old AI comments: {e}")
            await self.db_session.rollback()
            return 0

    def _get_ai_prefix(self) -> str:
        """
        Get the required German AI prefix from settings.

        Returns:
            AI comment prefix string
        """
        settings = get_settings()
        return settings.monitoring.AI_COMMENT_PREFIX

    def _build_article_url(self, article_id: str) -> str:
        """
        Build article URL from article ID using configured base URL.

        Args:
            article_id: Article ID

        Returns:
            Full article URL
        """
        settings = get_settings()
        base_url = settings.scraper.MYMOMENT_BASE_URL
        return f"{base_url}/article/{article_id}/"
