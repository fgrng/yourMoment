"""
Error handling middleware for yourMoment application.

Provides centralized error handling for all API responses, ensuring consistent
error formats and proper logging across the application.
"""

import logging
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import (
    IntegrityError,
    SQLAlchemyError,
    OperationalError,
    DataError
)

from src.services.auth_service import AuthServiceValidationError
from src.services.llm_service import (
    LLMProviderError,
    LLMProviderNotFoundError,
    LLMProviderValidationError
)
from src.services.mymoment_credentials_service import MyMomentCredentialsServiceError
from src.services.monitoring_service import (
    ProcessValidationError,
    ProcessOperationError
)
from src.services.prompt_service import PromptServiceError

logger = logging.getLogger(__name__)


class ErrorHandlerMiddleware:
    """
    Middleware for centralized error handling and response formatting.

    Catches unhandled exceptions and converts them to consistent JSON responses
    with proper HTTP status codes and error messages.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        try:
            # Process the request normally
            await self.app(scope, receive, send)
        except Exception as exc:
            # Handle any unhandled exceptions
            response = await self._handle_exception(request, exc)
            await response(scope, receive, send)

    async def _handle_exception(self, request: Request, exc: Exception) -> Response:
        """
        Convert exceptions to appropriate JSON error responses.

        Args:
            request: The incoming request
            exc: The exception that occurred

        Returns:
            JSONResponse with error details
        """
        error_id = str(uuid.uuid4())
        timestamp = datetime.utcnow().isoformat()

        # Log the error with context
        logger.error(
            f"Error {error_id} in {request.method} {request.url}: {type(exc).__name__}: {exc}",
            extra={
                "error_id": error_id,
                "request_method": request.method,
                "request_path": str(request.url.path),
                "request_query": str(request.url.query) if request.url.query else None,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "traceback": traceback.format_exc()
            }
        )

        # Determine error response based on exception type
        if isinstance(exc, ValidationError):
            return self._handle_validation_error(exc, error_id, timestamp)
        elif isinstance(exc, AuthServiceValidationError):
            return self._handle_auth_error(exc, error_id, timestamp)
        elif isinstance(exc, (
            LLMProviderValidationError,
            ProcessValidationError,
            MyMomentCredentialsServiceError
        )):
            return self._handle_business_validation_error(exc, error_id, timestamp)
        elif isinstance(exc, (
            LLMProviderNotFoundError,
            ProcessOperationError
        )):
            return self._handle_not_found_error(exc, error_id, timestamp)
        elif isinstance(exc, (
            LLMProviderError,
            PromptServiceError
        )):
            return self._handle_service_error(exc, error_id, timestamp)
        elif isinstance(exc, IntegrityError):
            return self._handle_database_integrity_error(exc, error_id, timestamp)
        elif isinstance(exc, OperationalError):
            return self._handle_database_operational_error(exc, error_id, timestamp)
        elif isinstance(exc, DataError):
            return self._handle_database_data_error(exc, error_id, timestamp)
        elif isinstance(exc, SQLAlchemyError):
            return self._handle_database_error(exc, error_id, timestamp)
        else:
            return self._handle_unexpected_error(exc, error_id, timestamp)

    def _handle_validation_error(self, exc: ValidationError, error_id: str, timestamp: str) -> JSONResponse:
        """Handle Pydantic validation errors."""
        errors = []
        for error in exc.errors():
            field_path = " -> ".join(str(loc) for loc in error["loc"])
            errors.append({
                "field": field_path,
                "message": error["msg"],
                "type": error["type"]
            })

        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "validation_error",
                "message": "Request validation failed",
                "detail": errors,
                "error_id": error_id,
                "timestamp": timestamp
            }
        )

    def _handle_auth_error(self, exc: AuthServiceValidationError, error_id: str, timestamp: str) -> JSONResponse:
        """Handle authentication errors."""
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": "authentication_error",
                "message": "Authentication failed",
                "error_id": error_id,
                "timestamp": timestamp
            },
            headers={"WWW-Authenticate": "Bearer"}
        )

    def _handle_business_validation_error(self, exc: Exception, error_id: str, timestamp: str) -> JSONResponse:
        """Handle business logic validation errors."""
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "business_validation_error",
                "message": str(exc),
                "error_id": error_id,
                "timestamp": timestamp
            }
        )

    def _handle_not_found_error(self, exc: Exception, error_id: str, timestamp: str) -> JSONResponse:
        """Handle resource not found errors."""
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "error": "resource_not_found",
                "message": str(exc),
                "error_id": error_id,
                "timestamp": timestamp
            }
        )

    def _handle_service_error(self, exc: Exception, error_id: str, timestamp: str) -> JSONResponse:
        """Handle service-level errors."""
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "service_error",
                "message": "An internal service error occurred",
                "error_id": error_id,
                "timestamp": timestamp
            }
        )

    def _handle_database_integrity_error(self, exc: IntegrityError, error_id: str, timestamp: str) -> JSONResponse:
        """Handle database integrity constraint violations."""
        message = "Resource already exists or constraint violation"
        if "unique" in str(exc).lower():
            message = "Resource with these details already exists"
        elif "foreign key" in str(exc).lower():
            message = "Referenced resource does not exist"

        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "database_constraint_error",
                "message": message,
                "error_id": error_id,
                "timestamp": timestamp
            }
        )

    def _handle_database_operational_error(self, exc: OperationalError, error_id: str, timestamp: str) -> JSONResponse:
        """Handle database operational errors."""
        logger.critical(f"Database operational error {error_id}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "database_unavailable",
                "message": "Database service temporarily unavailable",
                "error_id": error_id,
                "timestamp": timestamp
            }
        )

    def _handle_database_data_error(self, exc: DataError, error_id: str, timestamp: str) -> JSONResponse:
        """Handle database data format errors."""
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "invalid_data_format",
                "message": "Invalid data format provided",
                "error_id": error_id,
                "timestamp": timestamp
            }
        )

    def _handle_database_error(self, exc: SQLAlchemyError, error_id: str, timestamp: str) -> JSONResponse:
        """Handle general database errors."""
        logger.error(f"Database error {error_id}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "database_error",
                "message": "A database error occurred",
                "error_id": error_id,
                "timestamp": timestamp
            }
        )

    def _handle_unexpected_error(self, exc: Exception, error_id: str, timestamp: str) -> JSONResponse:
        """Handle unexpected/unclassified errors."""
        logger.critical(f"Unexpected error {error_id}: {type(exc).__name__}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred",
                "error_id": error_id,
                "timestamp": timestamp
            }
        )


def create_error_response(
    error_type: str,
    message: str,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail: Optional[Dict[str, Any]] = None
) -> JSONResponse:
    """
    Create a standardized error response.

    Utility function for creating consistent error responses in API endpoints.

    Args:
        error_type: Type of error (e.g., "validation_error", "not_found")
        message: Human-readable error message
        status_code: HTTP status code
        detail: Optional additional error details

    Returns:
        JSONResponse with standardized error format
    """
    error_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().isoformat()

    content = {
        "error": error_type,
        "message": message,
        "error_id": error_id,
        "timestamp": timestamp
    }

    if detail:
        content["detail"] = detail

    return JSONResponse(status_code=status_code, content=content)


# Convenience functions for common error types
def validation_error_response(message: str, detail: Optional[Dict[str, Any]] = None) -> JSONResponse:
    """Create a validation error response."""
    return create_error_response("validation_error", message, status.HTTP_400_BAD_REQUEST, detail)


def not_found_error_response(message: str = "Resource not found") -> JSONResponse:
    """Create a not found error response."""
    return create_error_response("not_found", message, status.HTTP_404_NOT_FOUND)


def unauthorized_error_response(message: str = "Authentication required") -> JSONResponse:
    """Create an unauthorized error response."""
    response = create_error_response("authentication_error", message, status.HTTP_401_UNAUTHORIZED)
    response.headers["WWW-Authenticate"] = "Bearer"
    return response


def forbidden_error_response(message: str = "Access denied") -> JSONResponse:
    """Create a forbidden error response."""
    return create_error_response("access_denied", message, status.HTTP_403_FORBIDDEN)


def conflict_error_response(message: str = "Resource conflict") -> JSONResponse:
    """Create a conflict error response."""
    return create_error_response("conflict", message, status.HTTP_409_CONFLICT)


def internal_error_response(message: str = "Internal server error") -> JSONResponse:
    """Create an internal server error response."""
    return create_error_response("internal_server_error", message, status.HTTP_500_INTERNAL_SERVER_ERROR)
