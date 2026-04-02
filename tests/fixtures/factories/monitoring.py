"""Factories for monitoring-process records and junction links."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.monitoring_process import MonitoringProcess
from src.models.monitoring_process_login import MonitoringProcessLogin
from src.models.monitoring_process_prompt import MonitoringProcessPrompt

from tests.fixtures.factories._shared import ensure_same_user, next_sequence, require_owner


async def create_monitoring_process_login(
    session: AsyncSession,
    *,
    monitoring_process: MonitoringProcess,
    mymoment_login: Any,
    **overrides: Any,
) -> MonitoringProcessLogin:
    """Persist a monitoring-process/login junction row."""
    ensure_same_user(monitoring_process, mymoment_login)
    link = MonitoringProcessLogin(
        monitoring_process=monitoring_process,
        mymoment_login=mymoment_login,
        is_active=overrides.pop("is_active", True),
        **overrides,
    )
    session.add(link)
    await session.flush()
    return link


async def create_monitoring_process_prompt(
    session: AsyncSession,
    *,
    monitoring_process: MonitoringProcess,
    prompt_template: Any,
    **overrides: Any,
) -> MonitoringProcessPrompt:
    """Persist a monitoring-process/prompt junction row."""
    if prompt_template.user_id is not None:
        ensure_same_user(monitoring_process, prompt_template)
    link = MonitoringProcessPrompt(
        monitoring_process=monitoring_process,
        prompt_template=prompt_template,
        weight=overrides.pop("weight", 1.0),
        is_active=overrides.pop("is_active", True),
        **overrides,
    )
    session.add(link)
    await session.flush()
    return link


async def create_monitoring_process(
    session: AsyncSession,
    *,
    user: Any = None,
    user_id: Any = None,
    llm_provider: Any = None,
    llm_provider_id: Any = None,
    mymoment_logins: Iterable[Any] | None = None,
    prompt_templates: Iterable[Any] | None = None,
    prompt_weights: dict[Any, float] | None = None,
    **overrides: Any,
) -> MonitoringProcess:
    """Persist a valid `MonitoringProcess` and optional junction rows."""
    owner = require_owner(user=user, user_id=user_id)
    if llm_provider is not None:
        ensure_same_user(owner["user"] or type("Owner", (), {"user_id": owner["user_id"]})(), llm_provider)
        llm_provider_id = llm_provider.id

    index = next_sequence("monitoring_process")
    process = MonitoringProcess(
        user=owner["user"],
        user_id=owner["user_id"],
        llm_provider=llm_provider,
        llm_provider_id=llm_provider_id,
        name=overrides.pop("name", f"Process {index}"),
        description=overrides.pop("description", f"Monitoring process {index}"),
        generate_only=overrides.pop("generate_only", False),
        hide_comments=overrides.pop("hide_comments", False),
        category_filter=overrides.pop("category_filter", 7),
        task_filter=overrides.pop("task_filter", None),
        search_filter=overrides.pop("search_filter", "sample"),
        tab_filter=overrides.pop("tab_filter", "home"),
        sort_option=overrides.pop("sort_option", "recent"),
        max_duration_minutes=overrides.pop("max_duration_minutes", 60),
        status=overrides.pop("status", "created"),
        started_at=overrides.pop("started_at", None),
        stopped_at=overrides.pop("stopped_at", None),
        last_activity_at=overrides.pop("last_activity_at", datetime.utcnow()),
        is_active=overrides.pop("is_active", True),
        **overrides,
    )
    session.add(process)
    await session.flush()

    for login in mymoment_logins or ():
        await create_monitoring_process_login(
            session,
            monitoring_process=process,
            mymoment_login=login,
        )

    for prompt in prompt_templates or ():
        weight = 1.0
        if prompt_weights:
            weight = prompt_weights.get(prompt.id, prompt_weights.get(prompt, 1.0))
        await create_monitoring_process_prompt(
            session,
            monitoring_process=process,
            prompt_template=prompt,
            weight=weight,
        )

    return process
