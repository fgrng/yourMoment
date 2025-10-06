"""Prompt template endpoints for managing reusable system and user prompts."""

import uuid
from typing import List, Optional
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    PromptTemplateCreate,
    PromptTemplateUpdate,
    PromptTemplateResponse,
    PlaceholderListResponse,
    PlaceholderInfoResponse,
)
from src.services.prompt_service import (
    PromptService,
    PromptServiceError,
    TemplateValidationError,
    TemplateNotFoundError,
    TemplateAccessError
)
from src.services.prompt_placeholders import SUPPORTED_PLACEHOLDERS
from src.api.auth import get_current_user
from src.config.database import get_session
from src.models.user import User
from src.api.error_utils import http_error
import logging

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/prompt-templates", tags=["Prompt Templates"])

class TemplateCategoryEnum(str, Enum):
    """Valid template category values."""
    SYSTEM = "SYSTEM"
    USER = "USER"

def _extract_reason(message: str) -> Optional[str]:
    """Extract a user-safe reason from an exception message."""
    if not message:
        return None
    if ":" in message:
        _, reason = message.split(":", 1)
        sanitized = reason.strip()
        return sanitized or None
    return message if message.strip() else None


def _handle_prompt_service_error(e: Exception, operation: str, user_id: Optional[uuid.UUID] = None) -> None:
    """
    Convert service errors to HTTP exceptions with consistent error handling.

    Args:
        e: Exception to handle
        operation: Operation description for logging
        user_id: Optional user ID for logging context

    Raises:
        HTTPException: With normalized error payload depending on the failure type.
    """
    if isinstance(e, TemplateValidationError):
        reason = _extract_reason(str(e))
        logger.warning(
            "Prompt template validation failure during %s for user %s: %s",
            operation,
            user_id,
            reason or str(e)
        )
        detail = {"reason": reason} if reason else None
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "prompt_template_validation_error",
            "Prompt template validation failed.",
            detail=detail
        )

    if isinstance(e, TemplateNotFoundError):
        logger.info(
            "Prompt template not found during %s for user %s",
            operation,
            user_id
        )
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "prompt_template_not_found",
            "Prompt template not found."
        )

    if isinstance(e, TemplateAccessError):
        reason = _extract_reason(str(e))
        logger.warning(
            "Prompt template access denied during %s for user %s: %s",
            operation,
            user_id,
            reason or str(e)
        )
        detail = {"reason": reason} if reason else None
        raise http_error(
            status.HTTP_403_FORBIDDEN,
            "prompt_template_access_denied",
            "You do not have permission to perform this action on the prompt template.",
            detail=detail
        )

    if isinstance(e, PromptServiceError):
        logger.error(
            "Prompt service error during %s for user %s",
            operation,
            user_id,
            exc_info=True
        )
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "prompt_template_service_error",
            f"Failed to {operation}. Please try again later."
        )

    logger.error(
        "Unexpected error during %s for user %s",
        operation,
        user_id,
        exc_info=True
    )
    raise http_error(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "internal_server_error",
        "An unexpected error occurred. Please try again later."
    )


@router.get(
    "/placeholders",
    response_model=PlaceholderListResponse,
    summary="List supported prompt placeholders"
)
async def list_supported_placeholders() -> PlaceholderListResponse:
    """Return metadata for all supported prompt placeholders."""

    items = [
        PlaceholderInfoResponse(
            name=info.name,
            is_required=info.is_required,
            description=info.description,
            example_value=info.example_value,
        )
        for info in SUPPORTED_PLACEHOLDERS.values()
    ]
    return PlaceholderListResponse(items=items)


@router.get("/index", response_model=List[PromptTemplateResponse])
async def get_prompt_templates(
    category: Optional[TemplateCategoryEnum] = Query(None, description="Filter by template category"),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum number of templates to return"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Get user's prompt templates.

    Returns a list of prompt templates owned by the current user.
    Optionally filter by category (SYSTEM or USER).
    """
    try:
        service = PromptService(session)

        # Convert enum to string if provided
        category_filter = category.value if category else None

        templates = await service.list_templates(
            user_id=current_user.id,
            category=category_filter,
            limit=limit,
            active_only=True  # Only return active templates by default
        )

        logger.debug(f"Retrieved {len(templates)} templates for user {current_user.id}")

        # Convert to response format
        return [
            PromptTemplateResponse(
                id=template.id,
                name=template.name,
                description=template.description,
                system_prompt=template.system_prompt,
                user_prompt_template=template.user_prompt_template,
                category=template.category,
                is_active=template.is_active,
                created_at=template.created_at
            )
            for template in templates
        ]

    except Exception as e:
        _handle_prompt_service_error(e, "retrieve prompt templates", current_user.id)


@router.get("/{template_id}", response_model=PromptTemplateResponse)
async def get_prompt_template_by_id(
    template_id: uuid.UUID = Path(..., description="Template unique identifier"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Get a specific prompt template by ID.

    Returns the prompt template if it exists and belongs to the current user.
    System templates are also accessible to all users.
    """
    try:
        service = PromptService(session)

        template = await service.get_template(template_id, current_user.id)
        if not template:
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "prompt_template_not_found",
                "Prompt template not found."
            )

        logger.debug(f"Retrieved template {template_id} for user {current_user.id}")

        return PromptTemplateResponse(
            id=template.id,
            name=template.name,
            description=template.description,
            system_prompt=template.system_prompt,
            user_prompt_template=template.user_prompt_template,
            category=template.category,
            is_active=template.is_active,
            created_at=template.created_at
        )

    except HTTPException:
        raise
    except Exception as e:
        _handle_prompt_service_error(e, "retrieve prompt template", current_user.id)


@router.post("/create", status_code=status.HTTP_201_CREATED, response_model=PromptTemplateResponse)
async def create_prompt_template(
    template_data: PromptTemplateCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Create a new prompt template.

    Creates a new prompt template owned by the current user.
    The template will be set to USER category and active by default.
    """
    try:
        service = PromptService(session)

        template = await service.create_template(
            request=template_data,
            user_id=current_user.id,
            category="USER",  # User-created templates are always USER category
            is_active=True
        )

        logger.info(f"Created prompt template {template.id} for user {current_user.id}")

        # Convert to response format
        return PromptTemplateResponse(
            id=template.id,
            name=template.name,
            description=template.description,
            system_prompt=template.system_prompt,
            user_prompt_template=template.user_prompt_template,
            category=template.category,
            is_active=template.is_active,
            created_at=template.created_at
        )

    except Exception as e:
        _handle_prompt_service_error(e, "create prompt template", current_user.id)


@router.patch("/{template_id}", response_model=PromptTemplateResponse)
async def update_prompt_template(
    template_id: uuid.UUID = Path(..., description="Template unique identifier"),
    template_data: PromptTemplateUpdate = ...,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Update a prompt template.

    Updates a prompt template owned by the current user.
    Only provided fields will be updated (partial update).
    """
    try:
        service = PromptService(session)

        # First verify template exists and user owns it
        existing_template = await service.get_template(template_id, current_user.id)
        if not existing_template:
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "prompt_template_not_found",
                "Prompt template not found."
            )

        template = await service.update_template(
            template_id=template_id,
            user_id=current_user.id,
            request=template_data
        )

        logger.info(f"Updated prompt template {template_id} for user {current_user.id}")

        # Convert to response format
        return PromptTemplateResponse(
            id=template.id,
            name=template.name,
            description=template.description,
            system_prompt=template.system_prompt,
            user_prompt_template=template.user_prompt_template,
            category=template.category,
            is_active=template.is_active,
            created_at=template.created_at
        )

    except HTTPException:
        raise
    except Exception as e:
        _handle_prompt_service_error(e, "update prompt template", current_user.id)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt_template(
    template_id: uuid.UUID = Path(..., description="Template unique identifier"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Delete a prompt template.

    Deletes a prompt template owned by the current user.
    System templates cannot be deleted by users.
    """
    try:
        service = PromptService(session)

        # First verify template exists and user owns it
        existing_template = await service.get_template(template_id, current_user.id)
        if not existing_template:
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "prompt_template_not_found",
                "Prompt template not found."
            )

        # Prevent deletion of system templates
        if existing_template.category == "SYSTEM":
            raise http_error(
                status.HTTP_403_FORBIDDEN,
                "prompt_template_access_denied",
                "System templates cannot be deleted."
            )

        await service.delete_template(template_id, current_user.id)

        logger.info(f"Deleted prompt template {template_id} for user {current_user.id}")

    except HTTPException:
        raise
    except Exception as e:
        _handle_prompt_service_error(e, "delete prompt template", current_user.id)
