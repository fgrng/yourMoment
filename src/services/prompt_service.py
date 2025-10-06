"""
Prompt template service for yourMoment application.

Implements T049: Comprehensive prompt template management with placeholder validation,
template rendering, user-scoped template management, and integration with comment
generation service for AI-powered myMoment commenting.
"""

import re
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set, Tuple
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.models.prompt_template import PromptTemplate
from src.models.user import User
from src.api.schemas import PromptTemplateCreate, PromptTemplateUpdate
from src.services.prompt_placeholders import (
    PlaceholderInfo,
    SUPPORTED_PLACEHOLDERS as GLOBAL_SUPPORTED_PLACEHOLDERS,
)

logger = logging.getLogger(__name__)


@dataclass
class TemplateValidationResult:
    """Result of template validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    placeholders_used: List[str]
    missing_required_placeholders: List[str]


@dataclass
class TemplateRenderResult:
    """Result of template rendering."""
    rendered_prompt: str
    missing_placeholders: List[str]
    unused_placeholders: List[str]
    render_errors: List[str]


class TemplatePreviewRequest(BaseModel):
    """Request model for template preview/rendering."""
    template_id: Optional[uuid.UUID] = None
    system_prompt: Optional[str] = None
    user_prompt_template: Optional[str] = None
    context: Dict[str, str] = Field(default_factory=dict)


class PromptServiceError(Exception):
    """Base exception for prompt service operations."""
    pass


class TemplateNotFoundError(PromptServiceError):
    """Raised when a template cannot be found."""
    pass


class TemplateValidationError(PromptServiceError):
    """Raised when template validation fails."""
    pass


class TemplateAccessError(PromptServiceError):
    """Raised when user lacks access to a template."""
    pass


class PromptService:
    """
    Comprehensive prompt template management service.

    Features:
    - Template CRUD operations with user isolation
    - Placeholder system with validation (article_title, article_content, etc.)
    - Template syntax validation and error reporting
    - Template rendering with context substitution
    - System template management with user template overrides
    - Template categories and organization
    - Preview/testing capabilities
    - Integration with comment generation service
    """

    # Supported placeholder definitions
    SUPPORTED_PLACEHOLDERS: Dict[str, PlaceholderInfo] = GLOBAL_SUPPORTED_PLACEHOLDERS

    # Template validation patterns
    PLACEHOLDER_PATTERN = re.compile(r'\{([^}]+)\}')
    INVALID_CHARS_PATTERN = re.compile(r'[<>"\'\\\x00-\x1f]')

    def __init__(self, db_session: AsyncSession):
        """
        Initialize prompt template service.

        Args:
            db_session: Database session for operations
        """
        self.db_session = db_session

    # Template CRUD Operations

    async def create_template(
        self,
        request: PromptTemplateCreate,
        user_id: Optional[uuid.UUID] = None,
        *,
        category: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> PromptTemplate:
        """
        Create a new prompt template.

        Args:
            request: Template creation parameters
            user_id: User ID (required for USER templates, must be None for SYSTEM)

        Returns:
            Created PromptTemplate instance

        Raises:
            TemplateValidationError: If template data is invalid
            PromptServiceError: If creation fails
        """
        try:
            # Validate category and user_id consistency
            resolved_category = category or ("USER" if user_id else "SYSTEM")
            resolved_is_active = True if is_active is None else is_active

            if resolved_category == "SYSTEM" and user_id is not None:
                raise TemplateValidationError("SYSTEM templates cannot have a user_id")

            if resolved_category == "USER" and user_id is None:
                raise TemplateValidationError("USER templates require a user_id")

            # Validate template content
            validation_result = await self.validate_template(
                system_prompt=request.system_prompt,
                user_prompt_template=request.user_prompt_template
            )

            if not validation_result.is_valid:
                raise TemplateValidationError(
                    f"Template validation failed: {', '.join(validation_result.errors)}"
                )

            # Check for name conflicts (user-scoped)
            await self._check_template_name_conflict(request.name, user_id)

            # Create template
            template = PromptTemplate(
                name=request.name,
                description=request.description,
                system_prompt=request.system_prompt,
                user_prompt_template=request.user_prompt_template,
                category=resolved_category,
                user_id=user_id,
                is_active=resolved_is_active
            )

            self.db_session.add(template)
            await self.db_session.commit()
            await self.db_session.refresh(template)

            logger.info(
                f"Created {resolved_category.lower()} template '{request.name}' "
                f"(ID: {template.id}, User: {user_id})"
            )
            return template
        except TemplateValidationError:
            raise
        except IntegrityError as e:
            await self.db_session.rollback()
            raise PromptServiceError(f"Template creation failed: {e}")
        except Exception as e:
            await self.db_session.rollback()
            logger.error(f"Unexpected error creating template: {e}")
            raise PromptServiceError(f"Template creation failed: {e}")

    async def get_template(
        self,
        template_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None
    ) -> PromptTemplate:
        """
        Get template by ID with access control.

        Args:
            template_id: Template ID
            user_id: User ID for access validation (None allows SYSTEM templates only)

        Returns:
            PromptTemplate instance

        Raises:
            TemplateNotFoundError: If template not found or not accessible
        """
        try:
            # Build access control query
            if user_id:
                # User can access their own templates and system templates
                conditions = and_(
                    PromptTemplate.id == template_id,
                    or_(
                        and_(
                            PromptTemplate.category == "USER",
                            PromptTemplate.user_id == user_id
                        ),
                        PromptTemplate.category == "SYSTEM"
                    )
                )
            else:
                # Only system templates when no user_id provided
                conditions = and_(
                    PromptTemplate.id == template_id,
                    PromptTemplate.category == "SYSTEM"
                )

            conditions = and_(conditions, PromptTemplate.is_active.is_(True))

            stmt = (
                select(PromptTemplate)
                .options(selectinload(PromptTemplate.monitoring_process_prompts))
                .where(conditions)
            )
            result = await self.db_session.execute(stmt)
            template = result.scalar_one_or_none()

            if not template:
                raise TemplateNotFoundError(
                    f"Template {template_id} not found or not accessible"
                )

            return template

        except TemplateNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error fetching template {template_id}: {e}")
            raise PromptServiceError(f"Failed to fetch template: {e}")

    async def list_templates(
        self,
        user_id: Optional[uuid.UUID] = None,
        category: Optional[str] = None,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0
    ) -> List[PromptTemplate]:
        """
        List templates with filtering and pagination.

        Args:
            user_id: User ID for access control (None shows SYSTEM templates only)
            category: Optional category filter ("SYSTEM" or "USER")
            active_only: Whether to show only active templates
            limit: Maximum number of templates to return
            offset: Number of templates to skip

        Returns:
            List of PromptTemplate instances
        """
        try:
            # Build base query
            conditions = []

            # Access control with category filter
            if user_id:
                if category:
                    # Specific category requested
                    if category == "USER":
                        # User's own USER templates only
                        conditions.append(and_(
                            PromptTemplate.category == "USER",
                            PromptTemplate.user_id == user_id
                        ))
                    elif category == "SYSTEM":
                        # SYSTEM templates only
                        conditions.append(PromptTemplate.category == "SYSTEM")
                else:
                    # No category filter - show both USER (theirs) and SYSTEM
                    access_conditions = or_(
                        and_(
                            PromptTemplate.category == "USER",
                            PromptTemplate.user_id == user_id
                        ),
                        PromptTemplate.category == "SYSTEM"
                    )
                    conditions.append(access_conditions)
            else:
                # Only system templates when no user_id provided
                conditions.append(PromptTemplate.category == "SYSTEM")

            # Active filter
            if active_only:
                conditions.append(PromptTemplate.is_active.is_(True))

            # Build and execute query
            stmt = select(PromptTemplate).where(and_(*conditions))
            stmt = stmt.order_by(PromptTemplate.category, PromptTemplate.name)
            stmt = stmt.limit(limit).offset(offset)

            result = await self.db_session.execute(stmt)
            templates = result.scalars().all()

            return list(templates)

        except Exception as e:
            logger.error(f"Error listing templates: {e}")
            raise PromptServiceError(f"Failed to list templates: {e}")

    async def update_template(
        self,
        template_id: uuid.UUID,
        request: PromptTemplateUpdate,
        user_id: uuid.UUID
    ) -> PromptTemplate:
        """
        Update an existing template.

        Args:
            template_id: Template ID to update
            request: Update parameters
            user_id: User ID for access validation

        Returns:
            Updated PromptTemplate instance

        Raises:
            TemplateNotFoundError: If template not found
            TemplateAccessError: If user lacks access
            TemplateValidationError: If update data is invalid
        """
        try:
            # Get template with access control
            template = await self.get_template(template_id, user_id)

            # Check write access (only USER templates owned by user)
            if template.category == "SYSTEM":
                raise TemplateAccessError("Cannot modify system templates")

            if template.user_id != user_id:
                raise TemplateAccessError("Cannot modify another user's template")

            # Track what's being changed for validation
            system_prompt = request.system_prompt or template.system_prompt
            user_prompt_template = (
                request.user_prompt_template or template.user_prompt_template
            )

            # Validate template content if prompts are being changed
            if request.system_prompt or request.user_prompt_template:
                validation_result = await self.validate_template(
                    system_prompt=system_prompt,
                    user_prompt_template=user_prompt_template
                )

                if not validation_result.is_valid:
                    raise TemplateValidationError(
                        f"Template validation failed: {', '.join(validation_result.errors)}"
                    )

            # Check for name conflicts if name is being changed
            if request.name and request.name != template.name:
                await self._check_template_name_conflict(request.name, user_id, template_id)

            # Apply updates
            if request.name:
                template.name = request.name
            if request.description is not None:
                template.description = request.description
            if request.system_prompt:
                template.system_prompt = request.system_prompt
            if request.user_prompt_template:
                template.user_prompt_template = request.user_prompt_template
            if request.is_active is not None:
                template.is_active = request.is_active
            await self.db_session.commit()
            await self.db_session.refresh(template)

            logger.info(f"Updated template '{template.name}' (ID: {template_id})")
            return template

        except (TemplateNotFoundError, TemplateAccessError, TemplateValidationError):
            raise
        except Exception as e:
            await self.db_session.rollback()
            logger.error(f"Error updating template {template_id}: {e}")
            raise PromptServiceError(f"Template update failed: {e}")

    async def delete_template(
        self,
        template_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> bool:
        """
        Delete a user template.

        Args:
            template_id: Template ID to delete
            user_id: User ID for access validation

        Returns:
            True if template was deleted

        Raises:
            TemplateNotFoundError: If template not found
            TemplateAccessError: If user lacks access
        """
        try:
            # Get template with access control
            template = await self.get_template(template_id, user_id)

            # Check delete access (only USER templates owned by user)
            if template.category == "SYSTEM":
                raise TemplateAccessError("Cannot delete system templates")

            if template.user_id != user_id:
                raise TemplateAccessError("Cannot delete another user's template")

            # Soft delete template and deactivate associations
            template.is_active = False
            template.updated_at = datetime.utcnow()

            for association in template.monitoring_process_prompts or []:
                association.is_active = False

            await self.db_session.commit()

            logger.info(f"Deleted template '{template.name}' (ID: {template_id})")
            return True

        except (TemplateNotFoundError, TemplateAccessError):
            raise
        except Exception as e:
            await self.db_session.rollback()
            logger.error(f"Error deleting template {template_id}: {e}")
            raise PromptServiceError(f"Template deletion failed: {e}")

    # Template Validation

    async def validate_template(
        self,
        system_prompt: str,
        user_prompt_template: str
    ) -> TemplateValidationResult:
        """
        Validate template content and placeholders.

        Args:
            system_prompt: System prompt content
            user_prompt_template: User prompt template with placeholders

        Returns:
            TemplateValidationResult with validation details
        """
        errors = []
        warnings = []

        try:
            # Basic content validation
            if not system_prompt or not system_prompt.strip():
                errors.append("System prompt cannot be empty")
            elif len(system_prompt.strip()) < 10:
                errors.append("System prompt too short (minimum 10 characters)")

            if not user_prompt_template or not user_prompt_template.strip():
                errors.append("User prompt template cannot be empty")
            elif len(user_prompt_template.strip()) < 10:
                errors.append("User prompt template too short (minimum 10 characters)")

            # Check for invalid characters
            if self.INVALID_CHARS_PATTERN.search(system_prompt):
                warnings.append("System prompt contains potentially problematic characters")

            if self.INVALID_CHARS_PATTERN.search(user_prompt_template):
                warnings.append("User prompt template contains potentially problematic characters")

            # Extract and validate placeholders
            placeholders_used = self._extract_placeholders(user_prompt_template)

            # Check for unsupported placeholders
            unsupported_placeholders = []
            for placeholder in placeholders_used:
                if placeholder not in self.SUPPORTED_PLACEHOLDERS:
                    unsupported_placeholders.append(placeholder)

            if unsupported_placeholders:
                errors.append(
                    f"Unsupported placeholders: {', '.join(unsupported_placeholders)}. "
                    f"Supported: {', '.join(self.SUPPORTED_PLACEHOLDERS.keys())}"
                )

            # Check for required placeholders
            required_placeholders = {
                name for name, info in self.SUPPORTED_PLACEHOLDERS.items()
                if info.is_required
            }
            missing_required = list(required_placeholders - set(placeholders_used))

            if missing_required:
                warnings.append(
                    f"Missing recommended placeholders: {', '.join(missing_required)}"
                )

            # Check placeholder syntax
            placeholder_syntax_errors = self._validate_placeholder_syntax(user_prompt_template)
            errors.extend(placeholder_syntax_errors)

            return TemplateValidationResult(
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                placeholders_used=placeholders_used,
                missing_required_placeholders=missing_required
            )

        except Exception as e:
            logger.error(f"Template validation error: {e}")
            return TemplateValidationResult(
                is_valid=False,
                errors=[f"Validation error: {e}"],
                warnings=[],
                placeholders_used=[],
                missing_required_placeholders=[]
            )

    # Template Rendering

    async def render_template(
        self,
        template_id: uuid.UUID,
        context: Dict[str, Any],
        user_id: Optional[uuid.UUID] = None
    ) -> TemplateRenderResult:
        """
        Render template with provided context.

        Args:
            template_id: Template ID to render
            context: Context values for placeholder replacement
            user_id: User ID for access validation

        Returns:
            TemplateRenderResult with rendered content and metadata

        Raises:
            TemplateNotFoundError: If template not found
        """
        try:
            # Get template
            template = await self.get_template(template_id, user_id)

            # Render template
            return await self.render_template_content(
                system_prompt=template.system_prompt,
                user_prompt_template=template.user_prompt_template,
                context=context
            )

        except TemplateNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Template rendering error: {e}")
            raise PromptServiceError(f"Template rendering failed: {e}")

    async def render_template_content(
        self,
        system_prompt: str,
        user_prompt_template: str,
        context: Dict[str, Any]
    ) -> TemplateRenderResult:
        """
        Render template content with context (without database lookup).

        Args:
            system_prompt: System prompt content
            user_prompt_template: User prompt template
            context: Context values for placeholder replacement

        Returns:
            TemplateRenderResult with rendered content and metadata
        """
        render_errors = []

        try:
            # Convert context values to strings and validate
            string_context = {}
            for key, value in context.items():
                if value is not None:
                    string_context[key] = str(value)

            # Extract placeholders from template
            placeholders_in_template = self._extract_placeholders(user_prompt_template)

            # Check for missing and unused placeholders
            missing_placeholders = [
                p for p in placeholders_in_template
                if p not in string_context
            ]

            unused_placeholders = [
                k for k in string_context.keys()
                if k not in placeholders_in_template
            ]

            # Perform replacement
            rendered_prompt = user_prompt_template
            for placeholder, value in string_context.items():
                placeholder_pattern = "{" + placeholder + "}"
                if placeholder_pattern in rendered_prompt:
                    rendered_prompt = rendered_prompt.replace(placeholder_pattern, value)

            # Check if any placeholders remain unresolved
            remaining_placeholders = self._extract_placeholders(rendered_prompt)
            if remaining_placeholders:
                render_errors.append(
                    f"Unresolved placeholders: {', '.join(remaining_placeholders)}"
                )

            return TemplateRenderResult(
                rendered_prompt=rendered_prompt,
                missing_placeholders=missing_placeholders,
                unused_placeholders=unused_placeholders,
                render_errors=render_errors
            )

        except Exception as e:
            logger.error(f"Template content rendering error: {e}")
            return TemplateRenderResult(
                rendered_prompt=user_prompt_template,
                missing_placeholders=[],
                unused_placeholders=[],
                render_errors=[f"Rendering failed: {e}"]
            )

    async def preview_template(self, request: TemplatePreviewRequest) -> Dict[str, Any]:
        """
        Preview template rendering with sample or provided context.

        Args:
            request: Preview request with template info and context

        Returns:
            Dictionary with preview results

        Raises:
            TemplateNotFoundError: If template_id provided but not found
            PromptServiceError: If preview fails
        """
        try:
            # Get template content
            if request.template_id:
                template = await self.get_template(request.template_id)
                system_prompt = template.system_prompt
                user_prompt_template = template.user_prompt_template
            else:
                system_prompt = request.system_prompt or ""
                user_prompt_template = request.user_prompt_template or ""

            # Use provided context or generate sample context
            context = request.context
            if not context:
                context = self.get_sample_context()

            # Validate template
            validation_result = await self.validate_template(system_prompt, user_prompt_template)

            # Render template
            render_result = await self.render_template_content(
                system_prompt, user_prompt_template, context
            )

            return {
                "system_prompt": system_prompt,
                "user_prompt_template": user_prompt_template,
                "context_used": context,
                "rendered_prompt": render_result.rendered_prompt,
                "validation": {
                    "is_valid": validation_result.is_valid,
                    "errors": validation_result.errors,
                    "warnings": validation_result.warnings,
                    "placeholders_used": validation_result.placeholders_used
                },
                "rendering": {
                    "missing_placeholders": render_result.missing_placeholders,
                    "unused_placeholders": render_result.unused_placeholders,
                    "render_errors": render_result.render_errors
                }
            }

        except TemplateNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Template preview error: {e}")
            raise PromptServiceError(f"Template preview failed: {e}")

    # System Template Management

    async def get_default_system_template(self) -> PromptTemplate:
        """
        Get the default system template for comment generation.

        Returns:
            Default system PromptTemplate

        Raises:
            PromptServiceError: If no default template available
        """
        try:
            # Find active system template
            stmt = select(PromptTemplate).where(
                and_(
                    PromptTemplate.category == "SYSTEM",
                    PromptTemplate.is_active.is_(True)
                )
            ).limit(1)

            result = await self.db_session.execute(stmt)
            template = result.scalar_one_or_none()

            if template:
                return template

            # Create default template if none exists
            return await self._create_default_system_template()

        except Exception as e:
            logger.error(f"Error getting default system template: {e}")
            raise PromptServiceError(f"Failed to get default template: {e}")

    async def _create_default_system_template(self) -> PromptTemplate:
        """Create default system template."""
        try:
            default_template = PromptTemplate(
                name="Default AI Comment Generator",
                description="System default template for generating contextual German comments on myMoment articles",
                system_prompt=(
                    "Du bist ein hilfsreicher KI-Assistent, der konstruktive und höfliche Kommentare "
                    "zu deutschen Texten verfasst. Deine Aufgabe ist es, einen kurzen, relevanten "
                    "Kommentar zu schreiben, der den Inhalt würdigt oder eine hilfreiche Frage stellt. "
                    "Der Kommentar soll freundlich, respektvoll und auf Deutsch verfasst sein. "
                    "Halte dich an diese Richtlinien:\n"
                    "- Sei konstruktiv und ermutigend\n"
                    "- Vermeide kontroverse oder kritische Themen\n"
                    "- Stelle bei Bedarf höfliche, interessierte Fragen\n"
                    "- Verwende einen freundlichen, persönlichen Ton\n"
                    "- Beziehe dich konkret auf den Artikelinhalt"
                ),
                user_prompt_template=(
                    "Bitte verfasse einen kurzen, freundlichen Kommentar (50-200 Wörter) zu folgendem Artikel:\n\n"
                    "Titel: {article_title}\n"
                    "Autor: {article_author}\n"
                    "Inhalt: {article_content}\n\n"
                    "Der Kommentar soll konstruktiv und interessiert sein, den Inhalt würdigen oder "
                    "eine hilfreiche Frage stellen. Verwende einen persönlichen, freundlichen Ton."
                ),
                category="SYSTEM",
                user_id=None,
                is_active=True
            )

            self.db_session.add(default_template)
            await self.db_session.commit()
            await self.db_session.refresh(default_template)

            logger.info("Created default system template")
            return default_template

        except Exception as e:
            await self.db_session.rollback()
            logger.error(f"Failed to create default system template: {e}")
            raise PromptServiceError(f"Failed to create default template: {e}")

    async def create_system_templates(self) -> List[PromptTemplate]:
        """
        Create a collection of useful system templates.

        Returns:
            List of created system templates
        """
        templates_data = [
            {
                "name": "Friendly Discussion Starter",
                "description": "Generates friendly, discussion-starting comments",
                "system_prompt": (
                    "Du bist ein engagierter Community-Teilnehmer, der andere zu Diskussionen "
                    "anregt. Verfasse Kommentare, die höfliche Fragen stellen oder interessante "
                    "Aspekte des Artikels hervorheben, um andere zum Antworten zu ermutigen."
                ),
                "user_prompt_template": (
                    "Verfasse einen einladenden Kommentar zu diesem Artikel, der andere zur "
                    "Diskussion anregt:\n\n"
                    "Titel: {article_title}\n"
                    "Inhalt: {article_content}\n\n"
                    "Stelle eine interessante Frage oder hebe einen diskussionswürdigen Aspekt hervor."
                )
            },
            {
                "name": "Supportive Encourager",
                "description": "Generates supportive and encouraging comments",
                "system_prompt": (
                    "Du bist eine ermutigende Person, die andere unterstützt und positive "
                    "Rückmeldungen gibt. Deine Kommentare sollen aufbauend wirken und den "
                    "Autor in seinem Schaffen bestärken."
                ),
                "user_prompt_template": (
                    "Schreibe einen unterstützenden, ermutigenden Kommentar zu diesem Artikel:\n\n"
                    "Titel: {article_title}\n"
                    "Autor: {article_author}\n"
                    "Inhalt: {article_content}\n\n"
                    "Betone positive Aspekte und ermutige den Autor."
                )
            },
            {
                "name": "Thoughtful Questioner",
                "description": "Generates thoughtful questions about article content",
                "system_prompt": (
                    "Du bist eine nachdenkliche Person, die durchdachte Fragen stellt. "
                    "Deine Kommentare enthalten interessante Fragen, die das Thema vertiefen "
                    "oder neue Perspektiven eröffnen."
                ),
                "user_prompt_template": (
                    "Formuliere eine durchdachte Frage zu diesem Artikel:\n\n"
                    "Titel: {article_title}\n"
                    "Inhalt: {article_content}\n\n"
                    "Die Frage soll zum Nachdenken anregen oder eine neue Perspektive eröffnen."
                )
            }
        ]

        created_templates = []

        try:
            for template_data in templates_data:
                # Check if template already exists
                stmt = select(PromptTemplate).where(
                    and_(
                        PromptTemplate.name == template_data["name"],
                        PromptTemplate.category == "SYSTEM"
                    )
                )
                result = await self.db_session.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    logger.info(f"System template '{template_data['name']}' already exists")
                    created_templates.append(existing)
                    continue

                # Create new template
                template = PromptTemplate(
                    name=template_data["name"],
                    description=template_data["description"],
                    system_prompt=template_data["system_prompt"],
                    user_prompt_template=template_data["user_prompt_template"],
                    category="SYSTEM",
                    user_id=None,
                    is_active=True
                )

                self.db_session.add(template)
                created_templates.append(template)

            await self.db_session.commit()

            for template in created_templates:
                await self.db_session.refresh(template)

            logger.info(f"Created/verified {len(created_templates)} system templates")
            return created_templates

        except Exception as e:
            await self.db_session.rollback()
            logger.error(f"Failed to create system templates: {e}")
            raise PromptServiceError(f"System template creation failed: {e}")

    # Utility Methods

    def get_supported_placeholders(self) -> Dict[str, PlaceholderInfo]:
        """Get information about all supported placeholders."""
        return self.SUPPORTED_PLACEHOLDERS.copy()

    def get_sample_context(self) -> Dict[str, str]:
        """Get sample context values for template testing."""
        return {
            info.name: info.example_value
            for info in self.SUPPORTED_PLACEHOLDERS.values()
        }

    def _extract_placeholders(self, template: str) -> List[str]:
        """Extract placeholder names from template string."""
        matches = self.PLACEHOLDER_PATTERN.findall(template)
        return list(set(matches))  # Remove duplicates

    def _validate_placeholder_syntax(self, template: str) -> List[str]:
        """Validate placeholder syntax in template."""
        errors = []

        try:
            # Check for malformed braces
            open_count = template.count('{')
            close_count = template.count('}')

            if open_count != close_count:
                errors.append(f"Mismatched braces: {open_count} opening, {close_count} closing")

            # Check for empty placeholders
            if '{}' in template:
                errors.append("Empty placeholders {} are not allowed")

            # Check for nested placeholders
            if re.search(r'\{[^}]*\{', template) or re.search(r'\}[^{]*\}', template):
                errors.append("Nested or malformed placeholders detected")

            # Check for whitespace in placeholders
            whitespace_placeholders = re.findall(r'\{\s+([^}]*)\s+\}', template)
            if whitespace_placeholders:
                errors.append("Placeholders should not contain leading/trailing whitespace")

        except Exception as e:
            errors.append(f"Syntax validation error: {e}")

        return errors

    async def _check_template_name_conflict(
        self,
        name: str,
        user_id: Optional[uuid.UUID],
        exclude_template_id: Optional[uuid.UUID] = None
    ):
        """Check for template name conflicts within user scope."""
        try:
            conditions = [PromptTemplate.name == name]

            if user_id:
                # Check within user's templates
                conditions.append(PromptTemplate.user_id == user_id)
            else:
                # Check within system templates
                conditions.append(PromptTemplate.category == "SYSTEM")

            if exclude_template_id:
                conditions.append(PromptTemplate.id != exclude_template_id)

            stmt = select(PromptTemplate).where(and_(*conditions))
            result = await self.db_session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                scope = "system templates" if not user_id else "your templates"
                raise TemplateValidationError(f"Template name '{name}' already exists in {scope}")

        except TemplateValidationError:
            raise
        except Exception as e:
            logger.error(f"Error checking template name conflict: {e}")
            raise PromptServiceError(f"Name conflict check failed: {e}")

    async def get_template_usage_statistics(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """
        Get usage statistics for templates owned by a user.

        Args:
            user_id: User ID

        Returns:
            Dictionary with template usage statistics
        """
        try:
            # Get user templates
            user_templates = await self.list_templates(
                user_id=user_id,
                category="USER",
                active_only=False
            )

            # Get system templates accessible to user
            system_templates = await self.list_templates(
                category="SYSTEM",
                active_only=True
            )

            statistics = {
                "user_templates": {
                    "total": len(user_templates),
                    "active": sum(1 for t in user_templates if t.is_active),
                    "inactive": sum(1 for t in user_templates if not t.is_active)
                },
                "system_templates_available": len(system_templates),
                "total_accessible": len(user_templates) + len(system_templates),
                "templates": []
            }

            # Add template details
            for template in user_templates + system_templates:
                placeholders = template.extract_placeholders()
                validation = template.validate_placeholders()

                statistics["templates"].append({
                    "id": str(template.id),
                    "name": template.name,
                    "category": template.category,
                    "is_active": template.is_active,
                    "placeholder_count": len(placeholders),
                    "valid_placeholders": all(validation.values()),
                    "created_at": template.created_at.isoformat() if hasattr(template, 'created_at') else None
                })

            return statistics

        except Exception as e:
            logger.error(f"Error getting template statistics for user {user_id}: {e}")
            return {"error": str(e)}

    async def cleanup_inactive_templates(self, days_inactive: int = 90) -> int:
        """
        Clean up old inactive user templates.

        Args:
            days_inactive: Number of days a template must be inactive

        Returns:
            Number of templates cleaned up
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_inactive)

            # Find old inactive user templates
            stmt = select(PromptTemplate).where(
                and_(
                    PromptTemplate.category == "USER",
                    PromptTemplate.is_active.is_(False),
                    PromptTemplate.updated_at < cutoff_date
                )
            )
            result = await self.db_session.execute(stmt)
            old_templates = result.scalars().all()

            if not old_templates:
                return 0

            # Delete old templates
            for template in old_templates:
                await self.db_session.delete(template)

            await self.db_session.commit()

            logger.info(f"Cleaned up {len(old_templates)} inactive templates")
            return len(old_templates)

        except Exception as e:
            logger.error(f"Error cleaning up templates: {e}")
            await self.db_session.rollback()
            return 0
