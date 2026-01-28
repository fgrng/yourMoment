"""
FastAPI application factory for yourMoment.

Creates and configures the FastAPI application with all routers and middleware.
"""

import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.middleware.error_handler import ErrorHandlerMiddleware
from src.middleware.validation import RequestValidationMiddleware, RequestValidationConfig
from src.config.logging import setup_logging
from src.config.settings import get_settings

from src.api.auth import router as auth_router
from src.api.mymoment_credentials import router as mymoment_credentials_router
from src.api.llm_providers import router as llm_providers_router
from src.api.monitoring_processes import router as monitoring_processes_router
from src.api.prompt_templates import router as prompt_templates_router
from src.api.mymoment_articles import router as mymoment_articles_router
from src.api.comments import router as comments_router
from src.api.student_backup import router as student_backup_router
from src.api.web import router as web_router
from src.config.database import get_database_manager
from src.lib.health import (
    check_celery_health,
    check_database_health,
    check_redis_health,
    get_start_time_iso,
    get_uptime_seconds,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    # Startup: configure logging and initialize database
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting yourMoment API")

    db_manager = get_database_manager()
    settings = get_settings()

    # Create tables if they don't exist (for development)
    if settings.is_development:
        logger.info("Development mode: ensuring database tables exist")
        engine = await db_manager.create_engine()
        async with engine.begin() as conn:
            from src.models.base import Base
            await conn.run_sync(Base.metadata.create_all)

    logger.info("yourMoment API startup complete")
    yield

    # Shutdown: close database connections
    logger.info("Shutting down yourMoment API")
    await db_manager.close()
    logger.info("yourMoment API shutdown complete")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""

    # Get environment settings
    settings = get_settings()
    environment = settings.app.ENVIRONMENT
    # Enable debug mode for development and testing environments
    debug = environment in ("development", "testing")

    app = FastAPI(
        title="yourMoment API",
        description="AI-powered myMoment article commenting system",
        version="1.0.0",
        lifespan=lifespan,
        debug=debug,
        docs_url="/docs" if debug else None,
        redoc_url="/redoc" if debug else None
    )

    # Configure validation middleware
    validation_config = RequestValidationConfig(
        max_request_size=10 * 1024 * 1024,  # 10MB
        max_json_depth=10,
        max_array_length=1000,
        max_string_length=10000,
        require_content_length=True,
        validate_json_structure=True,
        sanitize_strings=True
    )

    # Add middleware in reverse order (last added is first executed)
    # 1. Error handling middleware (outermost)
    app.add_middleware(ErrorHandlerMiddleware)

    # 2. Request validation middleware
    app.add_middleware(RequestValidationMiddleware, config=validation_config)

    # 3. Gzip compression
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # 4. Trusted host middleware (security)
    if not debug:
        allowed_hosts = settings.app.ALLOWED_HOSTS.split(",")
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    # 5. CORS middleware
    cors_origins = ["*"] if debug else settings.app.CORS_ORIGINS.split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["*"],
    )

    # Mount static files
    static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
    if os.path.exists(static_dir):
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Include API routers with prefix
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(mymoment_credentials_router, prefix="/api/v1")
    app.include_router(mymoment_articles_router, prefix="/api/v1")
    app.include_router(prompt_templates_router, prefix="/api/v1")
    app.include_router(comments_router, prefix="/api/v1")
    app.include_router(llm_providers_router, prefix="/api/v1")
    app.include_router(monitoring_processes_router, prefix="/api/v1")
    app.include_router(student_backup_router, prefix="/api/v1")

    # Include web interface router (no prefix - serves at root)
    app.include_router(web_router)

    # Development-only endpoints
    if debug:
        from src.api.dev import router as dev_router
        app.include_router(dev_router, prefix="/api/v1")

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        checks = {
            "database": await check_database_health(),
            "redis": await check_redis_health(),
            "celery_worker": await check_celery_health(),
        }

        overall_status = "healthy" if all(
            check.get("status") == "healthy" for check in checks.values()
        ) else "degraded"

        return {
            "status": overall_status,
            "service": "yourMoment API",
            "version": os.getenv("APP_VERSION", "0.1.0"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime_seconds": round(get_uptime_seconds(), 2),
            "started_at": get_start_time_iso(),
            "checks": checks,
        }

    return app


# Create the app instance
app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
