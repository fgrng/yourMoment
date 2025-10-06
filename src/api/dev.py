"""Development-only utilities for seeding, introspection, and environment diagnostics."""

from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_database_manager
from src.config.settings import get_settings
from src.api.utils import development_only

router = APIRouter(prefix="/dev", tags=["Development"])


@router.get("/seed-status")
@development_only
async def get_seed_status() -> Dict[str, Any]:
    """
    Check the status of seeded development data.

    Returns information about test users, credentials, and other seeded data.
    """
    db_manager = get_database_manager()
    engine = await db_manager.create_engine()

    async with AsyncSession(engine) as session:
        from sqlalchemy import select, func
        from src.models.user import User
        from src.models.mymoment_login import MyMomentLogin
        from src.models.llm_provider import LLMProviderConfiguration
        from src.models.prompt_template import PromptTemplate
        from src.models.monitoring_process import MonitoringProcess

        # Count seeded data
        user_count = await session.scalar(select(func.count(User.id)))
        mymoment_count = await session.scalar(select(func.count(MyMomentLogin.id)))
        llm_provider_count = await session.scalar(select(func.count(LLMProviderConfiguration.id)))
        prompt_count = await session.scalar(select(func.count(PromptTemplate.id)))
        process_count = await session.scalar(select(func.count(MonitoringProcess.id)))

        # Check for test user specifically
        test_user = await session.scalar(
            select(User).where(User.email == "test@yourmoment.dev")
        )

        return {
            "seeded": test_user is not None,
            "test_user_exists": test_user is not None,
            "counts": {
                "users": user_count,
                "mymoment_logins": mymoment_count,
                "llm_providers": llm_provider_count,
                "prompt_templates": prompt_count,
                "monitoring_processes": process_count
            },
            "test_credentials": {
                "email": "test@yourmoment.dev",
                "password": "password123"
            } if test_user else None
        }


@router.post("/seed")
@development_only
async def trigger_seed() -> Dict[str, str]:
    """
    Trigger database seeding programmatically.

    Equivalent to running 'python manage.py seed' from the API.
    """
    try:
        from seed_db import seed_database
        await seed_database()
        return {"status": "success", "message": "Database seeding completed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Seeding failed: {str(e)}")


@router.post("/reset")
@development_only
async def trigger_reset() -> Dict[str, str]:
    """
    Reset and seed the database programmatically.

    ⚠️  WARNING: This will DELETE ALL DATA and recreate tables.
    Equivalent to running 'python manage.py reset' from the API.
    """
    try:
        from seed_db import reset_database
        await reset_database()
        return {"status": "success", "message": "Database reset and seeding completed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")


@router.get("/environment")
@development_only
async def get_environment_info() -> Dict[str, Any]:
    """Get current environment information and configuration."""
    settings = get_settings()

    # Construct database URL from sqlite file path
    database_url = f"sqlite+aiosqlite:///{settings.database.DB_SQLITE_FILE}"

    return {
        "app_name": settings.app.APP_NAME,
        "app_version": settings.app.APP_VERSION,
        "base_url": settings.app.BASE_URL,
        "environment": settings.app.ENVIRONMENT,
        "debug": settings.app.DEBUG,
        "database_url": database_url,
        "cors_origins": settings.app.CORS_ORIGINS.split(",") if settings.app.CORS_ORIGINS else ["*"],
        "allowed_hosts": settings.app.ALLOWED_HOSTS.split(","),
    }


@router.get("/health/detailed")
@development_only
async def detailed_health_check() -> Dict[str, Any]:
    """
    Detailed health check with database connectivity test.

    More comprehensive than the basic /health endpoint.
    """
    settings = get_settings()

    health_info = {
        "status": "healthy",
        "service": "yourMoment API (Development)",
        "environment": settings.app.ENVIRONMENT,
        "database": "unknown"
    }

    try:
        db_manager = get_database_manager()
        engine = await db_manager.create_engine()

        async with AsyncSession(engine) as session:
            from sqlalchemy import text
            result = await session.execute(text("SELECT 1"))
            if result.scalar() == 1:
                health_info["database"] = "connected"
            else:
                health_info["database"] = "error"
                health_info["status"] = "degraded"
    except Exception as e:
        health_info["database"] = f"error: {str(e)}"
        health_info["status"] = "degraded"

    return health_info


@router.get("/routes")
@development_only
async def list_routes() -> Dict[str, Any]:
    """List all registered API routes for debugging."""
    from src.main import app

    routes = []
    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            routes.append({
                "path": route.path,
                "methods": list(route.methods),
                "name": getattr(route, 'name', None)
            })

    return {
        "total_routes": len(routes),
        "routes": sorted(routes, key=lambda x: x['path'])
    }
