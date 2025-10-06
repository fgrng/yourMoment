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


def get_environment():
    """Get current environment."""
    settings = get_settings()
    return settings.app.ENVIRONMENT


def is_development():
    """Check if running in development mode."""
    settings = get_settings()
    return settings.is_development


def is_production():
    """Check if running in production mode."""
    settings = get_settings()
    return settings.is_production


def get_base_url():
    """
    Get the base URL for the application.

    Useful for constructing absolute URLs for:
    - Email verification links
    - OAuth callbacks
    - Webhook URLs
    - API documentation

    Returns:
        str: Base URL (e.g., "https://yourmoment.example.com" or "http://localhost:8000")
    """
    settings = get_settings()
    return settings.app.BASE_URL


def build_absolute_url(path: str) -> str:
    """
    Build an absolute URL by combining BASE_URL with a relative path.

    Args:
        path: Relative path (e.g., "/dashboard", "/api/v1/auth/verify")

    Returns:
        str: Absolute URL (e.g., "https://yourmoment.example.com/dashboard")

    Examples:
        >>> build_absolute_url("/dashboard")
        "http://localhost:8000/dashboard"

        >>> build_absolute_url("/api/v1/auth/verify?token=abc123")
        "http://localhost:8000/api/v1/auth/verify?token=abc123"
    """
    base_url = get_base_url()

    # Remove trailing slash from base URL if present
    base_url = base_url.rstrip('/')

    # Ensure path starts with /
    if not path.startswith('/'):
        path = '/' + path

    return f"{base_url}{path}"


def build_redirect_url(path: str, use_absolute: bool = None) -> str:
    """
    Build a redirect URL (relative in development, absolute in production).

    Args:
        path: Path to redirect to (e.g., "/dashboard")
        use_absolute: Force absolute (True) or relative (False).
                     If None, uses absolute in production, relative in development.

    Returns:
        str: Redirect URL

    Examples:
        # In development (ENVIRONMENT=development):
        >>> build_redirect_url("/dashboard")
        "/dashboard"

        # In production (ENVIRONMENT=production):
        >>> build_redirect_url("/dashboard")
        "https://yourmoment.example.com/dashboard"

        # Force absolute:
        >>> build_redirect_url("/dashboard", use_absolute=True)
        "https://yourmoment.example.com/dashboard"
    """
    if use_absolute is None:
        # Default: absolute in production, relative in development
        use_absolute = is_production()

    if use_absolute:
        return build_absolute_url(path)
    else:
        # Ensure path starts with /
        if not path.startswith('/'):
            path = '/' + path
        return path
