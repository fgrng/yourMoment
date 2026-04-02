"""Small proof checks for shared adapter stubs."""

from __future__ import annotations

import pytest

from tests.fixtures.assertions import assert_task_result_shape
from tests.fixtures.stubs import (
    AiohttpStubResponse,
    AiohttpStubSession,
    build_litellm_exception,
    build_litellm_success_payload,
)


def test_litellm_success_stub_matches_expected_shape():
    payload = build_litellm_success_payload()

    assert payload.choices[0].finish_reason == "stop"
    assert payload.usage.total_tokens == 30


@pytest.mark.asyncio
async def test_aiohttp_session_stub_queues_and_records_requests():
    session = AiohttpStubSession()
    session.queue_response(
        "GET",
        "https://www.mymoment.ch/articles/",
        AiohttpStubResponse(status=200, body="<html></html>"),
    )

    async with session.get("https://www.mymoment.ch/articles/") as response:
        assert response.status == 200
        assert await response.text() == "<html></html>"

    assert session.requests == [
        {"method": "GET", "url": "https://www.mymoment.ch/articles/", "kwargs": {}}
    ]


def test_shared_assertion_helper_accepts_task_payloads():
    result = {"status": "success", "execution_time_seconds": 0.1}
    assert_task_result_shape(
        result,
        required_keys=("status", "execution_time_seconds"),
        expected_status="success",
    )


def test_litellm_exception_stub_returns_real_exception_types():
    exc = build_litellm_exception("timeout", message="boom")

    assert exc.__class__.__name__ == "Timeout"
    assert "boom" in str(exc)
