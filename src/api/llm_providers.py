"""CRUD endpoints for managing each user's LLM provider configurations and metadata."""

import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, Path
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    LLMProviderCreate,
    LLMProviderUpdate,
    LLMProviderResponse,
    ErrorResponse
)
from src.services.llm_service import (
    LLMProviderService,
    LLMProviderError,
    LLMProviderNotFoundError,
    LLMProviderValidationError
)
from src.api.auth import get_current_user
from src.config.database import get_session
from src.models.user import User
import logging

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/llm-providers", tags=["LLM Providers"])

async def get_llm_service(db: AsyncSession = Depends(get_session)) -> LLMProviderService:
    """Dependency to get LLM provider service."""
    return LLMProviderService(db)


@router.get(
    "/index",
    response_model=List[LLMProviderResponse],
    summary="List LLM provider configurations",
    description="Retrieve all LLM provider configurations for the authenticated user",
    responses={
        200: {"description": "LLM provider configurations retrieved successfully"},
        401: {"model": ErrorResponse, "description": "Unauthorized - invalid or missing token"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
async def get_llm_providers(
    current_user: User = Depends(get_current_user),
    llm_service: LLMProviderService = Depends(get_llm_service)
):
    """
    Get all LLM provider configurations for the authenticated user.

    Returns:
        List[LLMProviderResponse]: List of user's LLM provider configurations
    """
    try:
        providers = await llm_service.get_user_providers(current_user.id)

        # Convert to response models
        provider_responses = []
        for provider in providers:
            provider_responses.append(LLMProviderResponse(
                id=provider.id,
                provider_name=provider.provider_name,
                model_name=provider.model_name,
                max_tokens=provider.max_tokens,
                temperature=provider.temperature,
                is_active=provider.is_active,
                created_at=provider.created_at
            ))

        logger.info(f"Retrieved {len(provider_responses)} provider configurations for user {current_user.id}")
        return provider_responses

    except LLMProviderError as e:
        logger.error(f"LLM provider service error for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve provider configurations: {e}"
        )
    except Exception as e:
        logger.error(f"Unexpected error retrieving providers for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve provider configurations"
        )


@router.get(
    "/{provider_id}",
    response_model=LLMProviderResponse,
    summary="Get LLM provider configuration",
    description="Retrieve a specific LLM provider configuration by ID",
    responses={
        200: {"description": "LLM provider configuration retrieved successfully"},
        401: {"model": ErrorResponse, "description": "Unauthorized - invalid or missing token"},
        404: {"model": ErrorResponse, "description": "LLM provider configuration not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
async def get_llm_provider(
    provider_id: uuid.UUID = Path(..., description="LLM provider configuration ID"),
    current_user: User = Depends(get_current_user),
    llm_service: LLMProviderService = Depends(get_llm_service)
):
    """
    Get a specific LLM provider configuration by ID.

    Args:
        provider_id: UUID of the provider configuration
        current_user: Authenticated user
        llm_service: LLM provider service instance

    Returns:
        LLMProviderResponse: Provider configuration details
    """
    try:
        provider = await llm_service.get_provider_by_id(provider_id, current_user.id)

        if not provider:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="LLM provider configuration not found"
            )

        response = LLMProviderResponse(
            id=provider.id,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            max_tokens=provider.max_tokens,
            temperature=provider.temperature,
            is_active=provider.is_active,
            created_at=provider.created_at
        )

        logger.info(f"Retrieved provider {provider_id} for user {current_user.id}")
        return response

    except LLMProviderNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LLM provider configuration not found"
        )
    except LLMProviderError as e:
        logger.error(f"LLM provider service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve provider configuration: {e}"
        )
    except Exception as e:
        logger.error(f"Unexpected error retrieving provider {provider_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve provider configuration"
        )


@router.post(
    "/create",
    response_model=LLMProviderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create LLM provider configuration",
    description="Create new LLM provider configuration with encrypted API key storage",
    responses={
        201: {"description": "LLM provider configuration created successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request data"},
        401: {"model": ErrorResponse, "description": "Unauthorized - invalid or missing token"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
async def create_llm_provider(
    provider_data: LLMProviderCreate,
    current_user: User = Depends(get_current_user),
    llm_service: LLMProviderService = Depends(get_llm_service)
):
    """
    Create new LLM provider configuration for the authenticated user.

    Args:
        provider_data: LLM provider configuration data

    Returns:
        LLMProviderResponse: Created provider configuration
    """
    try:
        provider = await llm_service.create_provider_configuration(
            user_id=current_user.id,
            provider_name=provider_data.provider_name,
            api_key=provider_data.api_key,
            model_name=provider_data.model_name,
            max_tokens=provider_data.max_tokens,
            temperature=provider_data.temperature
        )

        provider_response = LLMProviderResponse(
            id=provider.id,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            max_tokens=provider.max_tokens,
            temperature=provider.temperature,
            is_active=provider.is_active,
            created_at=provider.created_at
        )

        logger.info(f"Created provider configuration {provider.id} for user {current_user.id}")
        return provider_response

    except LLMProviderValidationError as e:
        logger.warning(f"Validation error creating provider for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except LLMProviderError as e:
        logger.error(f"LLM provider service error for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create provider configuration: {e}"
        )
    except Exception as e:
        logger.error(f"Unexpected error creating provider for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create provider configuration"
        )


@router.patch(
    "/{provider_id}",
    response_model=LLMProviderResponse,
    summary="Update LLM provider configuration",
    description="Update existing LLM provider configuration",
    responses={
        200: {"description": "LLM provider configuration updated successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request data"},
        401: {"model": ErrorResponse, "description": "Unauthorized - invalid or missing token"},
        404: {"model": ErrorResponse, "description": "Provider configuration not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
async def update_llm_provider(
    provider_id: uuid.UUID = Path(..., description="LLM provider configuration ID"),
    update_data: LLMProviderUpdate = ...,
    current_user: User = Depends(get_current_user),
    llm_service: LLMProviderService = Depends(get_llm_service)
):
    """
    Update existing LLM provider configuration.

    Args:
        provider_id: ID of the provider configuration to update
        update_data: Update data

    Returns:
        LLMProviderResponse: Updated provider configuration
    """
    try:
        # Build update dictionary from non-None values
        updates = {}
        if update_data.api_key is not None:
            updates["api_key"] = update_data.api_key
        if update_data.model_name is not None:
            updates["model_name"] = update_data.model_name
        if update_data.max_tokens is not None:
            updates["max_tokens"] = update_data.max_tokens
        if update_data.temperature is not None:
            updates["temperature"] = update_data.temperature

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid update fields provided"
            )

        provider = await llm_service.update_provider_configuration(
            provider_id=provider_id,
            user_id=current_user.id,
            **updates
        )

        provider_response = LLMProviderResponse(
            id=provider.id,
            provider_name=provider.provider_name,
            model_name=provider.model_name,
            max_tokens=provider.max_tokens,
            temperature=provider.temperature,
            is_active=provider.is_active,
            created_at=provider.created_at
        )

        logger.info(f"Updated provider configuration {provider_id} for user {current_user.id}")
        return provider_response

    except HTTPException:
        # Re-raise HTTPException without catching it
        raise
    except LLMProviderNotFoundError as e:
        logger.warning(f"Provider {provider_id} not found for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider configuration not found"
        )
    except LLMProviderValidationError as e:
        logger.warning(f"Validation error updating provider {provider_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except LLMProviderError as e:
        logger.error(f"LLM provider service error updating {provider_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update provider configuration: {e}"
        )
    except Exception as e:
        logger.error(f"Unexpected error updating provider {provider_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update provider configuration"
        )


@router.delete(
    "/{provider_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete LLM provider configuration",
    description="Delete existing LLM provider configuration",
    responses={
        204: {"description": "LLM provider configuration deleted successfully"},
        401: {"model": ErrorResponse, "description": "Unauthorized - invalid or missing token"},
        404: {"model": ErrorResponse, "description": "Provider configuration not found"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    }
)
async def delete_llm_provider(
    provider_id: uuid.UUID = Path(..., description="LLM provider configuration ID"),
    current_user: User = Depends(get_current_user),
    llm_service: LLMProviderService = Depends(get_llm_service)
):
    """
    Delete existing LLM provider configuration.

    Args:
        provider_id: ID of the provider configuration to delete
    """
    try:
        await llm_service.delete_provider_configuration(
            provider_id=provider_id,
            user_id=current_user.id
        )

        logger.info(f"Deleted provider configuration {provider_id} for user {current_user.id}")
        return  # 204 No Content

    except LLMProviderNotFoundError as e:
        logger.warning(f"Provider {provider_id} not found for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider configuration not found"
        )
    except LLMProviderError as e:
        logger.error(f"LLM provider service error deleting {provider_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete provider configuration: {e}"
        )
    except Exception as e:
        logger.error(f"Unexpected error deleting provider {provider_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete provider configuration"
        )


# Additional endpoint to get supported providers info
@router.get(
    "/supported",
    response_model=dict,
    summary="Get supported LLM providers",
    description="Get information about supported LLM providers and their capabilities",
    responses={
        200: {"description": "Supported providers information retrieved successfully"}
    }
)
async def get_supported_providers(
    current_user: User = Depends(get_current_user),
    llm_service: LLMProviderService = Depends(get_llm_service)
):
    """
    Get information about supported LLM providers.

    Returns:
        dict: Information about supported providers
    """
    try:
        supported_providers = llm_service.get_supported_providers()
        logger.info(f"Retrieved supported providers info for user {current_user.id}")
        return supported_providers

    except Exception as e:
        logger.error(f"Error retrieving supported providers: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve supported providers information"
        )
