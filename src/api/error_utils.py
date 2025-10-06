"""Shared helpers for constructing normalized API error responses."""

from typing import Optional

from fastapi import HTTPException

from src.api.schemas import ErrorResponse


def build_error_payload(
    error: str,
    message: str,
    *,
    detail: Optional[dict] = None
) -> dict:
    """Serialize an ErrorResponse payload for FastAPI."""
    return ErrorResponse(error=error, message=message, detail=detail).model_dump()


def http_error(
    status_code: int,
    error: str,
    message: str,
    *,
    detail: Optional[dict] = None
) -> HTTPException:
    """Create an HTTPException carrying a normalized ErrorResponse payload."""
    return HTTPException(
        status_code=status_code,
        detail=build_error_payload(error=error, message=message, detail=detail)
    )
