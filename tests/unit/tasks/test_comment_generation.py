from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.tasks import comment_generation
from src.tasks.comment_generation import CommentGenerationTask
from src.services.llm_types import GenerationResult
from tests.fixtures.assertions import assert_task_result_shape
from tests.fixtures.builders import build_scenario
from tests.fixtures.stubs import CeleryTaskContextStub, build_litellm_exception


pytestmark = [pytest.mark.unit, pytest.mark.database, pytest.mark.celery, pytest.mark.llm]


def _bind_task_sessions(task, db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def _get_async_session():
        return session_factory()

    task.get_async_session = _get_async_session
    return task


async def test_generate_single_comment_persists_provider_model_and_token_metadata(
    db_session,
    db_engine,
    monkeypatch,
):
    scenario = await build_scenario("prepared_not_generated", db_session)
    await db_session.commit()

    task = _bind_task_sessions(CommentGenerationTask(), db_engine)

    async def fake_generate_with_llm(*, formatted_prompt, system_prompt, llm_config, log_context):
        assert scenario["ai_comment"].article_title in formatted_prompt
        assert system_prompt == scenario["prompt"].system_prompt
        assert llm_config.provider_name == scenario["provider"].provider_name
        assert llm_config.model_name == scenario["provider"].model_name
        return GenerationResult(
            comment_content=(
                "<p>This generated feedback is intentionally detailed, specific, and long enough "
                "to satisfy validation for the task pipeline.</p>"
            ),
            reasoning_content="The article already has a clear structure, so the feedback stays concrete.",
            prompt_tokens=21,
            completion_tokens=56,
            total_tokens=77,
            finish_reason="stop",
            model_used="gpt-4.1-mini",
            provider_used="openai",
            generation_time_ms=123,
        )

    monkeypatch.setattr(task, "_generate_comment_with_llm", fake_generate_with_llm)

    result = await task._generate_single_comment_async(scenario["ai_comment"].id)

    assert_task_result_shape(result, required_keys=("status", "ai_comment_id"), expected_status="generated")
    assert result["generation_time_ms"] == 123

    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "generated"
    assert scenario["ai_comment"].ai_model_name == "gpt-4.1-mini"
    assert scenario["ai_comment"].ai_provider_name == "openai"
    assert scenario["ai_comment"].generation_tokens == 77
    assert scenario["ai_comment"].generation_time_ms == 123
    assert scenario["ai_comment"].reasoning_content.startswith("The article already has")
    assert scenario["ai_comment"].has_valid_ai_prefix is True


async def test_generate_single_comment_skips_rows_that_are_already_generated(db_session, db_engine):
    scenario = await build_scenario("generated_not_posted", db_session)
    await db_session.commit()

    task = _bind_task_sessions(CommentGenerationTask(), db_engine)
    result = await task._generate_single_comment_async(scenario["ai_comment"].id)

    assert result["status"] == "skipped"
    assert result["reason"] == "already_generated"


async def test_update_generated_comment_is_a_stale_no_op(db_session, db_engine):
    scenario = await build_scenario("generated_not_posted", db_session)
    original_model = scenario["ai_comment"].ai_model_name
    original_provider = scenario["ai_comment"].ai_provider_name
    original_tokens = scenario["ai_comment"].generation_tokens
    await db_session.commit()

    task = _bind_task_sessions(CommentGenerationTask(), db_engine)
    await task._update_generated_comment(
        scenario["ai_comment"].id,
        {
            "comment_content": "<p>Replacement comment.</p>",
            "reasoning_content": "Replacement reasoning.",
            "ai_model_name": "different-model",
            "ai_provider_name": "different-provider",
            "generation_tokens": 999,
            "generation_time_ms": 999,
        },
        expected_status="prepared",
    )

    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "generated"
    assert scenario["ai_comment"].ai_model_name == original_model
    assert scenario["ai_comment"].ai_provider_name == original_provider
    assert scenario["ai_comment"].generation_tokens == original_tokens


async def test_mark_comment_failed_persists_generation_failure_metadata(db_session, db_engine):
    scenario = await build_scenario("prepared_not_generated", db_session)
    await db_session.commit()

    task = _bind_task_sessions(CommentGenerationTask(), db_engine)
    await task._mark_comment_failed(
        scenario["ai_comment"].id,
        "Max retries exhausted: llm timeout",
        expected_status="prepared",
    )

    await db_session.refresh(scenario["ai_comment"])
    assert scenario["ai_comment"].status == "failed"
    assert scenario["ai_comment"].error_message == "Max retries exhausted: llm timeout"
    assert scenario["ai_comment"].failed_at is not None
    assert scenario["ai_comment"].comment_content == ""


def test_generate_single_comment_wrapper_uses_capped_backoff_and_marks_failure(
    monkeypatch,
):
    retry_stub = CeleryTaskContextStub(retries=3)
    marked_failures: list[dict[str, object]] = []

    llm_error = build_litellm_exception("timeout", message="llm timeout")

    async def fail_generation(_ai_comment_id):
        raise llm_error

    async def fake_mark_failed(ai_comment_id, error_message, expected_status="prepared"):
        marked_failures.append(
            {
                "ai_comment_id": ai_comment_id,
                "error_message": error_message,
                "expected_status": expected_status,
            }
        )
        return None

    retry_stub._generate_single_comment_async = fail_generation
    retry_stub._mark_comment_failed = fake_mark_failed

    ai_comment_id = "d4de0afd-0553-4fef-9fc1-df5dd7e75c2b"
    result = comment_generation.generate_comment_for_article.run.__func__(retry_stub, ai_comment_id)

    assert result["status"] == "failed"
    assert retry_stub.retry_calls[0]["countdown"] == 300
    assert marked_failures[0]["expected_status"] == "prepared"
    assert "Max retries exhausted" in marked_failures[0]["error_message"]
