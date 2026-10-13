"""
Request validation middleware for yourMoment application.

Provides enhanced request validation and security checks
using Pydantic for consistent data validation across all API endpoints.
"""

import json
import logging
import re
import urllib.parse
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class RequestValidationConfig(BaseModel):
    """Configuration for request validation middleware."""
    max_request_size: int = Field(default=10 * 1024 * 1024, description="Maximum request size in bytes (10MB)")
    max_json_depth: int = Field(default=10, description="Maximum JSON nesting depth")
    max_array_length: int = Field(default=1000, description="Maximum array length in JSON")
    max_string_length: int = Field(default=10000, description="Maximum string length")
    allowed_content_types: Set[str] = Field(
        default={"application/json", "application/x-www-form-urlencoded", "multipart/form-data"},
        description="Allowed content types"
    )
    forbidden_patterns: List[str] = Field(
        default=[
            r"<script.*?>.*?</script>",  # Script tags
            r"javascript:",              # JavaScript protocols
            r"vbscript:",               # VBScript protocols
            r"on\w+\s*=",               # Event handlers
            r"expression\s*\(",         # CSS expressions
            r"@import",                 # CSS imports
            r"\\x[0-9a-fA-F]{2}",      # Hex encoded characters
            r"\\u[0-9a-fA-F]{4}",      # Unicode encoded characters
        ],
        description="Regex patterns for potentially malicious content"
    )
    require_content_length: bool = Field(default=True, description="Require Content-Length header")
    validate_json_structure: bool = Field(default=True, description="Validate JSON structure and depth")


class SecurityValidationResult(BaseModel):
    """Result of security validation checks."""
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class RequestValidationMiddleware:
    """
    Middleware for comprehensive request validation and security checks.

    Performs input validation and security checks on all
    incoming requests before they reach the API endpoints.
    """

    def __init__(self, app, config: Optional[RequestValidationConfig] = None):
        self.app = app
        self.config = config or RequestValidationConfig()
        self._compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.config.forbidden_patterns]

    async def __call__(self, scope: Dict[str, Any], receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)

        # Skip validation for certain paths (health checks, static files, etc.)
        if self._should_skip_validation(request):
            await self.app(scope, receive, send)
            return

        try:
            # Read body once and cache it
            body = b""
            if request.method in {"POST", "PUT", "PATCH"}:
                body = await request.body()

            # Validate the request (pass body to avoid re-reading)
            validation_result = await self._validate_request(request, body)

            if not validation_result.is_valid:
                response = self._create_validation_error_response(validation_result.errors)
                await response(scope, receive, send)
                return

            # Log any warnings
            for warning in validation_result.warnings:
                logger.warning(f"Request validation warning for {request.url}: {warning}")

            # Create new receive callable that returns cached body
            async def receive_with_cached_body():
                return {"type": "http.request", "body": body, "more_body": False}

            # Proceed with the request using cached body
            await self.app(scope, receive_with_cached_body, send)

        except Exception as exc:
            logger.error(f"Request validation middleware error: {exc}")
            response = self._create_internal_error_response()
            await response(scope, receive, send)

    def _should_skip_validation(self, request: Request) -> bool:
        """Check if validation should be skipped for this request."""
        skip_paths = {"/health", "/", "/docs", "/openapi.json", "/redoc"}
        path = request.url.path

        # Skip health checks and documentation
        if path in skip_paths:
            return True

        # Skip static files
        if path.startswith("/static/"):
            return True

        # Skip OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return True

        return False

    async def _validate_request(self, request: Request, body: bytes = b"") -> SecurityValidationResult:
        """
        Perform comprehensive request validation.

        Args:
            request: The incoming HTTP request
            body: Pre-read request body (to avoid consuming stream)

        Returns:
            SecurityValidationResult with validation outcome
        """
        errors = []
        warnings = []
        method_has_body = request.method in {"POST", "PUT", "PATCH"}
        content_type = self._request_content_type(request)

        # Validate request size
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > self.config.max_request_size:
                    errors.append(f"Request size {size} exceeds maximum allowed {self.config.max_request_size}")
            except ValueError:
                errors.append("Invalid Content-Length header")
        elif self.config.require_content_length and method_has_body:
            warnings.append("Missing Content-Length header")

        # Validate content type for body requests
        if method_has_body:
            if content_type and content_type not in self.config.allowed_content_types:
                errors.append(f"Content type '{content_type}' not allowed")

        # Validate headers for security
        self._validate_headers(request, errors, warnings)

        # Validate URL and query parameters
        self._validate_url(request, errors, warnings)

        # Validate request body if present
        if method_has_body and body:
            try:
                if content_type == "application/json":
                    self._validate_json_body(body, errors, warnings)
                elif content_type == "application/x-www-form-urlencoded":
                    self._validate_form_body(body, errors)
            except Exception as e:
                errors.append(f"Failed to validate request body: {str(e)}")

        return SecurityValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    def _request_content_type(self, request: Request) -> str:
        """Return the request Content-Type without parameters."""
        return request.headers.get("content-type", "").split(";")[0].strip()

    def _validate_headers(self, request: Request, errors: List[str], warnings: List[str]) -> None:
        """Validate request headers for security issues."""
        headers = request.headers

        # Check for suspicious headers
        suspicious_headers = [
            "x-forwarded-host", "x-real-ip", "x-forwarded-for"
        ]

        for header in suspicious_headers:
            if header in headers:
                value = headers[header]
                if self._contains_malicious_content(value):
                    errors.append(f"Malicious content detected in header '{header}'")

        # Validate User-Agent if present
        user_agent = headers.get("user-agent", "")
        if user_agent and len(user_agent) > 1000:
            warnings.append("Unusually long User-Agent header")

        # Check for potential header injection
        for name, value in headers.items():
            if "\n" in value or "\r" in value:
                errors.append(f"Header injection attempt detected in '{name}'")

    def _validate_url(self, request: Request, errors: List[str], warnings: List[str]) -> None:
        """Validate URL path and query parameters."""
        # Check path length
        if len(request.url.path) > 1000:
            errors.append("URL path too long")

        # Check for path traversal attempts
        if ".." in request.url.path or "%2e%2e" in str(request.url).lower():
            errors.append("Path traversal attempt detected")

        # Validate query parameters
        for key, value in request.query_params.items():
            # Check parameter name
            if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_-]*$", key):
                warnings.append(f"Unusual query parameter name: '{key}'")

            # Check parameter value
            if len(value) > self.config.max_string_length:
                errors.append(f"Query parameter '{key}' value too long")

            if self._contains_malicious_content(value):
                errors.append(f"Malicious content in query parameter '{key}'")

    def _validate_json_body(self, body: bytes, errors: List[str], warnings: List[str]) -> None:
        """Validate JSON request body."""
        try:
            data = json.loads(body.decode("utf-8"))

            if self.config.validate_json_structure:
                self._validate_json_structure(data, errors, warnings)

        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON: {str(e)}")
        except UnicodeDecodeError:
            errors.append("Invalid UTF-8 encoding in JSON body")

    def _validate_form_body(self, body: bytes, errors: List[str]) -> None:
        """Validate form-encoded request body."""
        try:
            pairs = body.decode("utf-8").split("&")

            for pair in pairs:
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    key = urllib.parse.unquote_plus(key)
                    value = urllib.parse.unquote_plus(value)

                    if len(value) > self.config.max_string_length:
                        errors.append(f"Form field '{key}' value too long")

                    if self._contains_malicious_content(value):
                        errors.append(f"Malicious content in form field '{key}'")

        except UnicodeDecodeError:
            errors.append("Invalid UTF-8 encoding in form body")

    def _validate_json_structure(self, data: Any, errors: List[str], warnings: List[str], depth: int = 0) -> None:
        """Validate JSON structure recursively."""
        if depth > self.config.max_json_depth:
            errors.append(f"JSON nesting too deep (max: {self.config.max_json_depth})")
            return

        if isinstance(data, dict):
            if len(data) > 100:  # Arbitrary large object limit
                warnings.append("Large JSON object detected")

            for key, value in data.items():
                if not isinstance(key, str):
                    errors.append("Non-string keys in JSON object")
                elif len(key) > 100:
                    errors.append("JSON key too long")

                self._validate_json_structure(value, errors, warnings, depth + 1)

        elif isinstance(data, list):
            if len(data) > self.config.max_array_length:
                errors.append(f"JSON array too long (max: {self.config.max_array_length})")

            for item in data:
                self._validate_json_structure(item, errors, warnings, depth + 1)

        elif isinstance(data, str):
            if len(data) > self.config.max_string_length:
                errors.append(f"JSON string too long (max: {self.config.max_string_length})")

    def _contains_malicious_content(self, text: str) -> bool:
        """Check if text contains potentially malicious patterns."""
        for pattern in self._compiled_patterns:
            if pattern.search(text):
                return True
        return False

    def _create_validation_error_response(self, errors: List[str]) -> JSONResponse:
        """Create a validation error response."""
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "request_validation_error",
                "message": "Request validation failed",
                "detail": errors,
                "error_id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat()
            }
        )

    def _create_internal_error_response(self) -> JSONResponse:
        """Create an internal error response."""
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "validation_middleware_error",
                "message": "Request validation middleware error",
                "error_id": str(uuid.uuid4()),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
