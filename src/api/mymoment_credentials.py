"""Endpoints for CRUD, validation, and testing of encrypted myMoment login credentials."""

import uuid
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import get_current_user
from src.api.schemas import (
    MyMomentCredentialsRequest,
    MyMomentCredentialsResponse,
    ErrorResponse
)
from src.config.database import get_session
from src.models.user import User
from src.services.mymoment_credentials_service import (
    MyMomentCredentialsService,
    MyMomentCredentialsServiceError,
    MyMomentCredentialsValidationError,
    MyMomentCredentialsNotFoundError
)
from src.api.error_utils import http_error


router = APIRouter(prefix="/mymoment-credentials", tags=["myMoment Credentials"])

logger = logging.getLogger(__name__)


def _map_validation_error(message: str) -> tuple[int, str, str, Optional[dict]]:
    """Determine response metadata for a validation failure."""
    normalized = message.strip()
    lowered = normalized.lower()

    if "already exist" in lowered:
        return (
            status.HTTP_409_CONFLICT,
            "mymoment_credentials_conflict",
            "Credentials name already exists.",
            {"field": "name"}
        )

    if "username and password cannot be empty" in lowered:
        return (
            status.HTTP_400_BAD_REQUEST,
            "mymoment_credentials_missing_fields",
            "Username and password are required.",
            {"fields": ["username", "password"]}
        )

    if "username cannot be empty" in lowered:
        return (
            status.HTTP_400_BAD_REQUEST,
            "mymoment_credentials_invalid_username",
            "Username is required.",
            {"field": "username"}
        )

    if "password cannot be empty" in lowered:
        return (
            status.HTTP_400_BAD_REQUEST,
            "mymoment_credentials_invalid_password",
            "Password is required.",
            {"field": "password"}
        )

    if "name cannot be empty" in lowered:
        return (
            status.HTTP_400_BAD_REQUEST,
            "mymoment_credentials_invalid_name",
            "Credential name is required.",
            {"field": "name"}
        )

    if normalized.lower().startswith("failed to"):
        return (
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "mymoment_credentials_service_error",
            "Failed to process credentials request. Please try again later.",
            None
        )

    return (
        status.HTTP_400_BAD_REQUEST,
        "mymoment_credentials_validation_error",
        "Invalid myMoment credentials request.",
        {"reason": normalized} if normalized else None
    )


def _handle_credentials_service_error(e: MyMomentCredentialsServiceError) -> None:
    """Normalize service errors into standardized HTTP responses."""
    message = str(e)

    if isinstance(e, MyMomentCredentialsValidationError):
        status_code, error_code, response_message, detail = _map_validation_error(message)
        if status_code >= 500:
            logger.error("Validation failure escalated to server error: %s", message)
        else:
            logger.warning("Credentials validation failed: %s", message)
        raise http_error(status_code, error_code, response_message, detail=detail)

    if isinstance(e, MyMomentCredentialsNotFoundError):
        logger.info("Credentials not found: %s", message)
        raise http_error(
            status.HTTP_404_NOT_FOUND,
            "mymoment_credentials_not_found",
            "Credentials not found."
        )

    logger.error("Credentials service error: %s", message, exc_info=True)
    raise http_error(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "mymoment_credentials_service_error",
        "Failed to process credentials request. Please try again later."
    )


def _raise_not_found() -> None:
    """Raise a standardized not found response."""
    raise http_error(
        status.HTTP_404_NOT_FOUND,
        "mymoment_credentials_not_found",
        "Credentials not found."
    )


def _raise_validation_failure(reason: Optional[str] = None) -> None:
    """Raise a standardized validation failure response."""
    detail = {"reason": reason} if reason else None
    raise http_error(
        status.HTTP_400_BAD_REQUEST,
        "mymoment_credentials_validation_error",
        "Invalid myMoment credentials request.",
        detail=detail
    )


async def get_credentials_service(db: AsyncSession = Depends(get_session)) -> MyMomentCredentialsService:
    """Dependency to get credentials service."""
    return MyMomentCredentialsService(db)


@router.post(
    "/create",
    response_model=MyMomentCredentialsResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Bad request - validation error"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        409: {"model": ErrorResponse, "description": "Conflict - credentials name already exists"}
    }
)
async def create_credentials(
    request: MyMomentCredentialsRequest,
    current_user: User = Depends(get_current_user),
    service: MyMomentCredentialsService = Depends(get_credentials_service)
):
    """
    Create new myMoment credentials.

    Creates new encrypted credentials for accessing myMoment platform.
    The password is automatically encrypted using Fernet encryption before storage.
    """
    try:
        credentials = await service.create_credentials(
            user_id=current_user.id,
            username=request.username,
            password=request.password,
            name=request.name,
            is_admin=request.is_admin
        )

        return MyMomentCredentialsResponse.model_validate(credentials)

    except MyMomentCredentialsServiceError as e:
        _handle_credentials_service_error(e)


@router.get(
    "/index",
    response_model=List[MyMomentCredentialsResponse],
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"}
    }
)
async def get_credentials(
    is_admin: Optional[bool] = Query(
        default=None,
        description="Filter by admin status. True=admin logins only, False=non-admin only, None=all"
    ),
    current_user: User = Depends(get_current_user),
    service: MyMomentCredentialsService = Depends(get_credentials_service)
):
    """
    Get all myMoment credentials for the current user.

    Returns a list of all active credentials owned by the authenticated user.
    Passwords are not included in the response for security reasons.

    Query parameters:
        is_admin: Optional filter. If True, returns only admin logins.
                  If False, returns only non-admin logins (for monitoring).
                  If not specified, returns all logins.
    """
    credentials_list = await service.get_user_credentials(current_user.id, is_admin=is_admin)
    return [MyMomentCredentialsResponse.model_validate(creds) for creds in credentials_list]


@router.get(
    "/{credentials_id}",
    response_model=MyMomentCredentialsResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Not found"}
    }
)
async def get_credentials_by_id(
    credentials_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: MyMomentCredentialsService = Depends(get_credentials_service)
):
    """
    Get specific myMoment credentials by ID.

    Returns the credentials if they exist and belong to the authenticated user.
    Password is not included in the response for security reasons.
    """
    credentials = await service.get_credentials_by_id(credentials_id, current_user.id)

    if not credentials:
        _raise_not_found()

    return MyMomentCredentialsResponse.model_validate(credentials)


@router.put(
    "/{credentials_id}",
    response_model=MyMomentCredentialsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad request - validation error"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Not found"},
        409: {"model": ErrorResponse, "description": "Conflict - credentials name already exists"}
    }
)
async def update_credentials(
    credentials_id: uuid.UUID,
    request: MyMomentCredentialsRequest,
    current_user: User = Depends(get_current_user),
    service: MyMomentCredentialsService = Depends(get_credentials_service)
):
    """
    Update existing myMoment credentials.

    Updates the specified credentials with new values. All fields are optional
    in the update operation. Password will be re-encrypted if provided.
    """
    try:
        credentials = await service.update_credentials(
            user_id=current_user.id,
            credentials_id=credentials_id,
            username=request.username,
            password=request.password,
            name=request.name,
            is_admin=request.is_admin
        )

        if not credentials:
            _raise_not_found()

        return MyMomentCredentialsResponse.model_validate(credentials)

    except MyMomentCredentialsServiceError as e:
        _handle_credentials_service_error(e)


@router.patch(
    "/{credentials_id}",
    response_model=MyMomentCredentialsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Bad request - validation error"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Not found"},
        409: {"model": ErrorResponse, "description": "Conflict - credentials name already exists"}
    }
)
async def patch_credentials(
    credentials_id: uuid.UUID,
    request: MyMomentCredentialsRequest,
    current_user: User = Depends(get_current_user),
    service: MyMomentCredentialsService = Depends(get_credentials_service)
):
    """
    Partially update existing myMoment credentials (PATCH).

    Same as PUT but follows PATCH HTTP semantics. Updates the specified
    credentials with new values. All fields are optional.
    """
    try:
        credentials = await service.update_credentials(
            user_id=current_user.id,
            credentials_id=credentials_id,
            username=request.username,
            password=request.password,
            name=request.name,
            is_admin=request.is_admin
        )

        if not credentials:
            _raise_not_found()

        return MyMomentCredentialsResponse.model_validate(credentials)

    except MyMomentCredentialsServiceError as e:
        _handle_credentials_service_error(e)


@router.delete(
    "/{credentials_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Not found"}
    }
)
async def delete_credentials(
    credentials_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: MyMomentCredentialsService = Depends(get_credentials_service)
):
    """
    Delete myMoment credentials.

    Soft deletes the specified credentials by marking them as inactive.
    The credentials will no longer be available for use in monitoring processes.
    """
    success = await service.delete_credentials(credentials_id, current_user.id)

    if not success:
        _raise_not_found()


@router.post(
    "/{credentials_id}/validate",
    responses={
        200: {"description": "Credentials are valid"},
        400: {"model": ErrorResponse, "description": "Bad request - validation failed"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Not found"}
    }
)
async def validate_credentials(
    credentials_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: MyMomentCredentialsService = Depends(get_credentials_service)
):
    """
    Validate myMoment credentials.

    Checks if the credentials exist and can be properly decrypted.
    This endpoint does not actually attempt to authenticate with myMoment,
    it only validates that the stored data is accessible.
    """
    is_valid, error_message = await service.validate_credentials(credentials_id, current_user.id)

    if not is_valid:
        normalized_error = (error_message or "").strip()
        if "not found" in normalized_error.lower():
            _raise_not_found()
        _raise_validation_failure(normalized_error or None)

    return {"message": "Credentials are valid"}


@router.post(
    "/{credentials_id}/test",
    responses={
        200: {"description": "Authentication test successful"},
        400: {"model": ErrorResponse, "description": "Bad request - authentication failed"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        404: {"model": ErrorResponse, "description": "Not found"}
    }
)
async def test_credentials(
    credentials_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: MyMomentCredentialsService = Depends(get_credentials_service),
    db: AsyncSession = Depends(get_session)
):
    """
    Test myMoment credentials by attempting to authenticate with the platform.

    This endpoint attempts to create a real session on the myMoment platform
    using the stored credentials. It verifies that:
    - Credentials can be decrypted
    - Username and password are accepted by myMoment
    - A valid session can be established

    The test session is automatically cleaned up after verification.
    """
    from src.services.scraper_service import ScraperService, AuthenticationError, ScrapingError, SessionError
    from src.services.mymoment_session_service import MyMomentSessionService

    # Get the credentials
    credentials = await service.get_credentials_by_id(credentials_id, current_user.id)

    if not credentials:
        _raise_not_found()

    # Validate credentials can be decrypted
    is_valid, error_message = await service.validate_credentials(credentials_id, current_user.id)

    if not is_valid:
        normalized_error = (error_message or "").strip()
        _raise_validation_failure(
            normalized_error or "Credentials could not be validated."
        )

    # Initialize services for scraping
    session_service = MyMomentSessionService(db)
    scraper_service = ScraperService(db)

    try:
        # Attempt to initialize and authenticate a session
        context = await scraper_service._initialize_single_session(credentials_id, current_user.id)

        if not context.is_authenticated:
            logger.warning(
                "Authentication failed during credential test for credentials %s",
                credentials_id
            )
            raise http_error(
                status.HTTP_400_BAD_REQUEST,
                "mymoment_credentials_authentication_failed",
                "Failed to authenticate with the myMoment platform."
            )

        # Clean up the test session
        await scraper_service.cleanup_session(credentials_id)

        # Also deactivate the database session record
        if context.session_id:
            await session_service.deactivate_session(context.session_id)

        return {
            "message": "Authentication successful",
            "username": credentials.username,
            "platform": "myMoment"
        }

    except AuthenticationError as e:
        # Clean up on authentication failure
        await scraper_service.cleanup_session(credentials_id)
        logger.warning(
            "Authentication failed during credential test for credentials %s: %s",
            credentials_id,
            e
        )
        raise http_error(
            status.HTTP_401_UNAUTHORIZED,
            "mymoment_credentials_authentication_failed",
            "Authentication failed. Please verify your username and password are correct."
        )

    except SessionError as e:
        # Clean up on session error
        await scraper_service.cleanup_session(credentials_id)
        error_message = str(e)

        # Check if it's an authentication failure wrapped in SessionError
        if "Authentication failed" in error_message or "Login failed" in error_message:
            logger.warning(
                "Authentication failed (via SessionError) during credential test for credentials %s: %s",
                credentials_id,
                e
            )
            raise http_error(
                status.HTTP_401_UNAUTHORIZED,
                "mymoment_credentials_authentication_failed",
                "Authentication failed. Please verify your username and password are correct."
            )

        # Generic session error
        logger.error(
            "Session initialization error during credential test for credentials %s: %s",
            credentials_id,
            e,
            exc_info=True
        )
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "mymoment_credentials_session_error",
            f"Unable to initialize a session with the myMoment platform: {error_message}"
        )

    except ScrapingError as e:
        # Clean up on scraping error (catch-all for other ScrapingError subclasses)
        await scraper_service.cleanup_session(credentials_id)
        logger.error(
            "Scraping error during credential test for credentials %s: %s",
            credentials_id,
            e,
            exc_info=True
        )
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "mymoment_credentials_scraping_error",
            "Unable to complete scraping validation for the provided credentials."
        )

    except Exception as e:
        # Clean up on unexpected error
        await scraper_service.cleanup_session(credentials_id)
        logger.error(
            "Unexpected error during credential test for credentials %s",
            credentials_id,
            exc_info=True
        )
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "mymoment_credentials_test_error",
            "An unexpected error occurred while testing credentials."
        )
