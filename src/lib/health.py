import asyncio
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Dict, Optional

import redis.asyncio as redis
from celery.exceptions import TimeoutError as CeleryTimeoutError
from sqlalchemy import text

from src.config.database import get_database_manager
from src.config.settings import get_settings
from src.tasks.worker import celery_app


APP_START_TIME = datetime.now(timezone.utc)
_redis_client: Optional[redis.Redis] = None


async def check_database_health() -> Dict[str, Any]:
    start = perf_counter()
    try:
        db_manager = get_database_manager()
        engine = await db_manager.create_engine()

        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            is_healthy = result.scalar() == 1

        latency_ms = round((perf_counter() - start) * 1000, 2)
        if is_healthy:
            return {"status": "healthy", "latency_ms": latency_ms}
        return {
            "status": "unhealthy",
            "latency_ms": latency_ms,
            "error": "Unexpected database response"
        }
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}


async def _get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.from_url(
            settings.celery.CELERY_BROKER_URL,
            encoding="utf-8",
            decode_responses=True
        )
    return _redis_client


async def check_redis_health() -> Dict[str, Any]:
    start = perf_counter()
    try:
        client = await _get_redis_client()
        response = await client.ping()
        latency_ms = round((perf_counter() - start) * 1000, 2)
        if response:
            return {"status": "healthy", "latency_ms": latency_ms}
        return {
            "status": "unhealthy",
            "latency_ms": latency_ms,
            "error": "Redis ping returned falsy response"
        }
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}


async def check_celery_health() -> Dict[str, Any]:
    start = perf_counter()
    try:
        responses = await asyncio.to_thread(celery_app.control.ping, timeout=1.0)
        latency_ms = round((perf_counter() - start) * 1000, 2)
        if responses:
            return {
                "status": "healthy",
                "latency_ms": latency_ms,
                "workers": len(responses)
            }
        return {
            "status": "unhealthy",
            "latency_ms": latency_ms,
            "error": "No Celery workers responded"
        }
    except CeleryTimeoutError:
        return {"status": "unhealthy", "error": "Celery ping timed out"}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}


def get_uptime_seconds() -> float:
    return (datetime.now(timezone.utc) - APP_START_TIME).total_seconds()


def get_start_time_iso() -> str:
    return APP_START_TIME.isoformat()
