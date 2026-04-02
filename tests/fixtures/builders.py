"""Reusable higher-level DB scenarios for service and task unit tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings

from tests.fixtures.factories import (
    create_article_version,
    create_discovered_ai_comment,
    create_generated_ai_comment,
    create_llm_provider,
    create_monitoring_process,
    create_monitoring_process_login,
    create_mymoment_login,
    create_mymoment_session,
    create_posted_ai_comment,
    create_prepared_ai_comment,
    create_tracked_student,
    create_user,
    create_user_prompt_template,
)

ScenarioData = dict[str, Any]


def _with_overrides(overrides: Mapping[str, Any] | None, key: str, defaults: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    if overrides and overrides.get(key):
        merged.update(dict(overrides[key]))
    return merged


async def _base_monitoring_bundle(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    user = await create_user(session, **_with_overrides(overrides, "user", {}))
    login = await create_mymoment_login(
        session,
        user=user,
        **_with_overrides(overrides, "login", {}),
    )
    mymoment_session = await create_mymoment_session(
        session,
        mymoment_login=login,
        **_with_overrides(overrides, "mymoment_session", {}),
    )
    provider = await create_llm_provider(
        session,
        user=user,
        **_with_overrides(overrides, "provider", {}),
    )
    prompt = await create_user_prompt_template(
        session,
        user=user,
        **_with_overrides(overrides, "prompt", {}),
    )
    process = await create_monitoring_process(
        session,
        user=user,
        llm_provider=provider,
        mymoment_logins=[login],
        prompt_templates=[prompt],
        **_with_overrides(
            overrides,
            "process",
            {
                "status": "running",
                "started_at": datetime.utcnow(),
                "generate_only": False,
                "hide_comments": False,
            },
        ),
    )
    await session.flush()
    return {
        "name": "base_monitoring_bundle",
        "user": user,
        "login": login,
        "logins": [login],
        "mymoment_session": mymoment_session,
        "provider": provider,
        "providers": [provider],
        "prompt": prompt,
        "prompts": [prompt],
        "process": process,
        "processes": [process],
        "ai_comments": [],
    }


async def _scenario_minimal_happy_path(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    scenario = await _base_monitoring_bundle(session, overrides)
    scenario["name"] = "minimal_happy_path"
    return scenario


async def _scenario_multi_login_monitoring(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    scenario = await _base_monitoring_bundle(session, overrides)
    secondary_login = await create_mymoment_login(
        session,
        user=scenario["user"],
        **_with_overrides(overrides, "secondary_login", {}),
    )
    secondary_session = await create_mymoment_session(
        session,
        mymoment_login=secondary_login,
        **_with_overrides(overrides, "secondary_mymoment_session", {}),
    )
    await create_monitoring_process_login(
        session,
        monitoring_process=scenario["process"],
        mymoment_login=secondary_login,
    )
    await session.refresh(scenario["process"])
    scenario["name"] = "multi_login_monitoring"
    scenario["secondary_login"] = secondary_login
    scenario["secondary_mymoment_session"] = secondary_session
    scenario["logins"].append(secondary_login)
    scenario["mymoment_sessions"] = [scenario["mymoment_session"], secondary_session]
    return scenario


async def _scenario_generate_only_process(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    merged_overrides = dict(overrides or {})
    merged_process = dict(merged_overrides.get("process", {}))
    merged_process.setdefault("generate_only", True)
    merged_overrides["process"] = merged_process
    scenario = await _base_monitoring_bundle(session, merged_overrides)
    comment = await create_generated_ai_comment(
        session,
        user=scenario["user"],
        monitoring_process=scenario["process"],
        mymoment_login=scenario["login"],
        prompt_template=scenario["prompt"],
        llm_provider=scenario["provider"],
        is_hidden=False,
        **_with_overrides(overrides, "ai_comment", {}),
    )
    scenario["name"] = "generate_only_process"
    scenario["ai_comment"] = comment
    scenario["ai_comments"] = [comment]
    return scenario


async def _scenario_hidden_comment_process(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    merged_overrides = dict(overrides or {})
    merged_process = dict(merged_overrides.get("process", {}))
    merged_process.setdefault("hide_comments", True)
    merged_overrides["process"] = merged_process
    scenario = await _base_monitoring_bundle(session, merged_overrides)
    comment = await create_generated_ai_comment(
        session,
        user=scenario["user"],
        monitoring_process=scenario["process"],
        mymoment_login=scenario["login"],
        prompt_template=scenario["prompt"],
        llm_provider=scenario["provider"],
        is_hidden=True,
        **_with_overrides(overrides, "ai_comment", {}),
    )
    scenario["name"] = "hidden_comment_process"
    scenario["ai_comment"] = comment
    scenario["ai_comments"] = [comment]
    return scenario


async def _scenario_provider_fallback(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    scenario = await _base_monitoring_bundle(session, overrides)
    primary_provider = scenario["provider"]
    primary_provider.is_active = False
    fallback_provider = await create_llm_provider(
        session,
        user=scenario["user"],
        **_with_overrides(
            overrides,
            "fallback_provider",
            {"provider_name": "mistral", "model_name": "mistral-small-latest"},
        ),
    )
    scenario["process"].llm_provider = fallback_provider
    scenario["process"].llm_provider_id = fallback_provider.id
    await session.flush()
    scenario["name"] = "provider_fallback"
    scenario["primary_provider"] = primary_provider
    scenario["fallback_provider"] = fallback_provider
    scenario["provider"] = fallback_provider
    scenario["providers"] = [primary_provider, fallback_provider]
    return scenario


async def _scenario_expired_mymoment_session(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    scenario = await _base_monitoring_bundle(session, overrides)
    expired_overrides = _with_overrides(overrides, "expired_mymoment_session", {})
    expired_session = scenario["mymoment_session"]
    expired_session.expires_at = expired_overrides.get(
        "expires_at",
        datetime.utcnow() - timedelta(hours=1),
    )
    expired_session.is_active = expired_overrides.get("is_active", True)
    await session.flush()
    scenario["name"] = "expired_mymoment_session"
    scenario["expired_mymoment_session"] = expired_session
    scenario["mymoment_session"] = expired_session
    scenario["mymoment_sessions"] = [expired_session]
    return scenario


async def _scenario_article_discovered_not_prepared(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    scenario = await _base_monitoring_bundle(session, overrides)
    comment = await create_discovered_ai_comment(
        session,
        user=scenario["user"],
        monitoring_process=scenario["process"],
        mymoment_login=scenario["login"],
        prompt_template=scenario["prompt"],
        llm_provider=scenario["provider"],
        **_with_overrides(overrides, "ai_comment", {}),
    )
    scenario["name"] = "article_discovered_not_prepared"
    scenario["ai_comment"] = comment
    scenario["ai_comments"] = [comment]
    return scenario


async def _scenario_prepared_not_generated(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    scenario = await _base_monitoring_bundle(session, overrides)
    comment = await create_prepared_ai_comment(
        session,
        user=scenario["user"],
        monitoring_process=scenario["process"],
        mymoment_login=scenario["login"],
        prompt_template=scenario["prompt"],
        llm_provider=scenario["provider"],
        **_with_overrides(overrides, "ai_comment", {}),
    )
    scenario["name"] = "prepared_not_generated"
    scenario["ai_comment"] = comment
    scenario["ai_comments"] = [comment]
    return scenario


async def _scenario_generated_not_posted(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    scenario = await _base_monitoring_bundle(session, overrides)
    comment = await create_generated_ai_comment(
        session,
        user=scenario["user"],
        monitoring_process=scenario["process"],
        mymoment_login=scenario["login"],
        prompt_template=scenario["prompt"],
        llm_provider=scenario["provider"],
        **_with_overrides(overrides, "ai_comment", {}),
    )
    scenario["name"] = "generated_not_posted"
    scenario["ai_comment"] = comment
    scenario["ai_comments"] = [comment]
    return scenario


async def _scenario_posted_comment_audit_snapshot(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    scenario = await _base_monitoring_bundle(session, overrides)
    comment = await create_posted_ai_comment(
        session,
        user=scenario["user"],
        monitoring_process=scenario["process"],
        mymoment_login=scenario["login"],
        prompt_template=scenario["prompt"],
        llm_provider=scenario["provider"],
        is_hidden=scenario["process"].hide_comments,
        **_with_overrides(overrides, "ai_comment", {}),
    )
    scenario["name"] = "posted_comment_audit_snapshot"
    scenario["ai_comment"] = comment
    scenario["ai_comments"] = [comment]
    return scenario


async def _scenario_cross_user_access_denied(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    scenario = await _base_monitoring_bundle(session, overrides)
    actor = await create_user(session, **_with_overrides(overrides, "actor", {}))
    foreign_comment = await create_generated_ai_comment(
        session,
        user=scenario["user"],
        monitoring_process=scenario["process"],
        mymoment_login=scenario["login"],
        prompt_template=scenario["prompt"],
        llm_provider=scenario["provider"],
        **_with_overrides(overrides, "ai_comment", {}),
    )
    scenario["name"] = "cross_user_access_denied"
    scenario["actor"] = actor
    scenario["foreign_comment"] = foreign_comment
    scenario["ai_comment"] = foreign_comment
    scenario["ai_comments"] = [foreign_comment]
    return scenario


async def _scenario_max_process_limit_reached(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    scenario = await _base_monitoring_bundle(session, overrides)
    limit = get_settings().monitoring.MAX_MONITORING_PROCESSES
    processes = [scenario["process"]]
    for index in range(2, limit + 1):
        process = await create_monitoring_process(
            session,
            user=scenario["user"],
            llm_provider=scenario["provider"],
            mymoment_logins=scenario["logins"],
            prompt_templates=scenario["prompts"],
            name=f"Limit Process {index}",
            status="created",
            generate_only=False,
        )
        processes.append(process)
    scenario["name"] = "max_process_limit_reached"
    scenario["processes"] = processes
    scenario["process_limit"] = limit
    return scenario


async def _scenario_student_backup_with_versions(
    session: AsyncSession,
    overrides: Mapping[str, Any] | None,
) -> ScenarioData:
    user = await create_user(session, **_with_overrides(overrides, "user", {}))
    admin_login = await create_mymoment_login(
        session,
        user=user,
        **_with_overrides(overrides, "admin_login", {"is_admin": True, "name": "Admin Login"}),
    )
    tracked_student = await create_tracked_student(
        session,
        user=user,
        mymoment_login=admin_login,
        **_with_overrides(overrides, "tracked_student", {}),
    )
    version_1 = await create_article_version(
        session,
        user=user,
        tracked_student=tracked_student,
        mymoment_article_id=3210,
        version_number=1,
        **_with_overrides(overrides, "article_version_1", {}),
    )
    version_2 = await create_article_version(
        session,
        user=user,
        tracked_student=tracked_student,
        mymoment_article_id=3210,
        version_number=2,
        content="Updated versioned article content.",
        **_with_overrides(overrides, "article_version_2", {}),
    )
    return {
        "name": "student_backup_with_versions",
        "user": user,
        "admin_login": admin_login,
        "tracked_student": tracked_student,
        "article_versions": [version_1, version_2],
        "latest_article_version": version_2,
    }


_SCENARIOS: dict[str, Callable[[AsyncSession, Mapping[str, Any] | None], Any]] = {
    "minimal_happy_path": _scenario_minimal_happy_path,
    "multi_login_monitoring": _scenario_multi_login_monitoring,
    "generate_only_process": _scenario_generate_only_process,
    "hidden_comment_process": _scenario_hidden_comment_process,
    "provider_fallback": _scenario_provider_fallback,
    "expired_mymoment_session": _scenario_expired_mymoment_session,
    "article_discovered_not_prepared": _scenario_article_discovered_not_prepared,
    "prepared_not_generated": _scenario_prepared_not_generated,
    "generated_not_posted": _scenario_generated_not_posted,
    "posted_comment_audit_snapshot": _scenario_posted_comment_audit_snapshot,
    "cross_user_access_denied": _scenario_cross_user_access_denied,
    "max_process_limit_reached": _scenario_max_process_limit_reached,
    "student_backup_with_versions": _scenario_student_backup_with_versions,
}


async def build_scenario(
    name: str,
    session: AsyncSession,
    overrides: Mapping[str, Any] | None = None,
) -> ScenarioData:
    """Persist and return a named scenario on the supplied async session."""
    try:
        builder = _SCENARIOS[name]
    except KeyError as exc:
        available = ", ".join(sorted(_SCENARIOS))
        raise ValueError(f"unknown scenario {name!r}; available scenarios: {available}") from exc

    scenario = await builder(session, overrides)
    await session.flush()
    return scenario


__all__ = ["build_scenario"]
