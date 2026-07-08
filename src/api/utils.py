"""Utility decorators and helpers shared by API modules."""

from functools import wraps
from fastapi import HTTPException
from src.config.settings import get_settings


def development_only(func):
    """
    Decorator to restrict endpoint access to development environment only.

    Usage:
        @router.get("/debug-endpoint")
        @development_only
        async def debug_endpoint():
            return {"debug": "data"}
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        settings = get_settings()
        if not settings.is_development:
            raise HTTPException(
                status_code=404,
                detail="Endpoint not available in production"
            )
        return await func(*args, **kwargs)
    return wrapper
