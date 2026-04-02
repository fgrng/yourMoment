"""
Helpers for stopping queued chain work once a monitoring process is no longer running.
"""

import uuid
from typing import Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.monitoring_process import MonitoringProcess


async def get_process_skip_reason(
    get_async_session: Callable[[], Awaitable[AsyncSession]],
    monitoring_process_id: Optional[uuid.UUID],
    *,
    require_posting_enabled: bool = False,
) -> Optional[str]:
    """
    Return a skip reason when the parent process should not continue work.

    The monitoring process row is the durable source of truth for whether queued
    preparation/generation/posting tasks are still allowed to perform external I/O.
    """
    if not monitoring_process_id:
        return None

    session = await get_async_session()
    async with session:
        process = await session.get(MonitoringProcess, monitoring_process_id)

    if not process or not process.is_active or process.status != "running":
        return "process_not_running"

    if require_posting_enabled and process.generate_only:
        return "generate_only"

    return None
