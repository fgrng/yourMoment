"""Factories for AI comment pipeline states."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.models.ai_comment import AIComment

from tests.fixtures.factories._shared import ensure_same_user, next_sequence, require_owner


def _set_default(d: dict[str, Any], key: str, value: Any) -> None:
    if d.get(key) is None:
        d[key] = value


def _apply_state_defaults(status: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    defaults = dict(kwargs)
    prefix = get_settings().monitoring.AI_COMMENT_PREFIX

    if status in {"prepared", "generated", "posted", "failed"}:
        _set_default(defaults, "article_content", "This is a prepared article body.")
        _set_default(defaults, "article_raw_html", "<div class='article'><p>This is a prepared article body.</p></div>")

    if status in {"generated", "posted"}:
        _set_default(
            defaults,
            "comment_content",
            f"<p>{prefix}</p><p>Constructive feedback for the student article.</p>",
        )
        _set_default(defaults, "reasoning_content", "The article is encouraging and specific.")
        _set_default(defaults, "ai_model_name", "gpt-4o-mini")
        _set_default(defaults, "ai_provider_name", "openai")
        _set_default(defaults, "generation_tokens", 123)
        _set_default(defaults, "generation_time_ms", 456)

    if status == "posted":
        _set_default(defaults, "mymoment_comment_id", f"comment-{next_sequence('posted_comment_id')}")
        _set_default(defaults, "posted_at", datetime.utcnow())

    if status == "failed":
        _set_default(defaults, "error_message", "Generation failed in fixture setup.")
        _set_default(defaults, "failed_at", datetime.utcnow())
        _set_default(defaults, "retry_count", 1)

    return defaults


async def create_ai_comment(
    session: AsyncSession,
    *,
    user: Any = None,
    user_id: Any = None,
    monitoring_process: Any = None,
    monitoring_process_id: Any = None,
    mymoment_login: Any = None,
    mymoment_login_id: Any = None,
    prompt_template: Any = None,
    prompt_template_id: Any = None,
    llm_provider: Any = None,
    llm_provider_id: Any = None,
    status: str = "discovered",
    **overrides: Any,
) -> AIComment:
    """Persist a valid `AIComment` in the requested pipeline state."""
    owner = require_owner(user=user, user_id=user_id)
    ensure_same_user(*(record for record in (monitoring_process, mymoment_login, prompt_template, llm_provider) if record is not None))

    # status=posted requires a login
    if status == "posted" and mymoment_login is None and mymoment_login_id is None:
        from tests.fixtures.factories.mymoment import create_mymoment_login
        mymoment_login = await create_mymoment_login(session, user=owner["user"], user_id=owner["user_id"])

    index = next_sequence("ai_comment")
    
    # Start with caller-provided overrides and factory defaults
    fields = {
        "mymoment_article_id": overrides.pop("mymoment_article_id", f"article-{index}"),
        "user": owner["user"],
        "user_id": owner["user_id"],
        "mymoment_login": mymoment_login,
        "mymoment_login_id": mymoment_login.id if mymoment_login is not None else mymoment_login_id,
        "monitoring_process": monitoring_process,
        "monitoring_process_id": (
            monitoring_process.id if monitoring_process is not None else monitoring_process_id
        ),
        "prompt_template": prompt_template,
        "prompt_template_id": prompt_template.id if prompt_template is not None else prompt_template_id,
        "llm_provider": llm_provider,
        "llm_provider_id": llm_provider.id if llm_provider is not None else llm_provider_id,
        "article_title": overrides.pop("article_title", f"Article Title {index}"),
        "article_author": overrides.pop("article_author", f"Author {index}"),
        "article_category": overrides.pop("article_category", 7),
        "article_task_id": overrides.pop("article_task_id", 4),
        "article_url": overrides.pop("article_url", f"https://www.mymoment.ch/article/{index}/"),
        "article_published_at": overrides.pop("article_published_at", datetime.utcnow()),
        "article_edited_at": overrides.pop("article_edited_at", datetime.utcnow()),
        "article_scraped_at": overrides.pop("article_scraped_at", datetime.utcnow()),
        "article_metadata": overrides.pop("article_metadata", {"source": "fixture"}),
        "is_hidden": overrides.pop("is_hidden", False),
        "status": status,
        "ai_model_name": overrides.pop("ai_model_name", None),
        "ai_provider_name": overrides.pop("ai_provider_name", None),
        "generation_tokens": overrides.pop("generation_tokens", None),
        "generation_time_ms": overrides.pop("generation_time_ms", None),
        "created_at": overrides.pop("created_at", datetime.utcnow()),
        "posted_at": overrides.pop("posted_at", None),
        "failed_at": overrides.pop("failed_at", None),
        "error_message": overrides.pop("error_message", None),
        "retry_count": overrides.pop("retry_count", 0),
        "is_active": overrides.pop("is_active", True),
    }
    
    # Handle content fields separately to allow explicit None overrides if status permits
    fields["article_content"] = overrides.pop("article_content", None)
    fields["article_raw_html"] = overrides.pop("article_raw_html", None)
    fields["comment_content"] = overrides.pop("comment_content", None)
    fields["reasoning_content"] = overrides.pop("reasoning_content", None)
    
    # Merge any remaining developer-provided overrides
    fields.update(overrides)

    # Apply state-based defaults for any fields that are still None
    resolved = _apply_state_defaults(status, fields)

    comment = AIComment(**resolved)
    session.add(comment)
    await session.flush()
    return comment


async def create_discovered_ai_comment(session: AsyncSession, **kwargs: Any) -> AIComment:
    """Persist a `discovered` AI comment."""
    return await create_ai_comment(session, status="discovered", **kwargs)


async def create_prepared_ai_comment(session: AsyncSession, **kwargs: Any) -> AIComment:
    """Persist a `prepared` AI comment."""
    return await create_ai_comment(session, status="prepared", **kwargs)


async def create_generated_ai_comment(session: AsyncSession, **kwargs: Any) -> AIComment:
    """Persist a `generated` AI comment."""
    return await create_ai_comment(session, status="generated", **kwargs)


async def create_posted_ai_comment(session: AsyncSession, **kwargs: Any) -> AIComment:
    """Persist a `posted` AI comment."""
    return await create_ai_comment(session, status="posted", **kwargs)


async def create_failed_ai_comment(session: AsyncSession, **kwargs: Any) -> AIComment:
    """Persist a `failed` AI comment."""
    return await create_ai_comment(session, status="failed", **kwargs)
