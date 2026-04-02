"""Reusable adapter stubs for unit tests."""

from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from celery.exceptions import MaxRetriesExceededError


def build_litellm_success_payload(
    *,
    comment_content: str = "<p>Fixture comment.</p>",
    reasoning_content: str = "Fixture reasoning.",
    model: str = "openai/gpt-4o-mini",
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
    structured: bool = True,
) -> Any:
    """Return a LiteLLM-like completion payload object."""
    if structured:
        message_content = json.dumps(
            {
                "reasoning_content": reasoning_content,
                "comment_content": comment_content,
            }
        )
        message = SimpleNamespace(content=message_content, reasoning_content=None)
    else:
        message = SimpleNamespace(content=comment_content, reasoning_content=reasoning_content)

    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage, model=model)


def build_litellm_exception(
    kind: str,
    *,
    message: str = "fixture error",
    provider: str = "openai",
    model: str = "gpt-4o-mini",
) -> Exception:
    """Return an actual LiteLLM exception instance for the requested kind."""
    import litellm

    mapping = {
        "authentication": lambda: litellm.exceptions.AuthenticationError(message, provider, model),
        "rate_limit": lambda: litellm.exceptions.RateLimitError(message, provider, model),
        "context_window": lambda: litellm.exceptions.ContextWindowExceededError(message, model, provider),
        "connection": lambda: litellm.exceptions.APIConnectionError(message, provider, model),
        "timeout": lambda: litellm.exceptions.Timeout(message, model, provider),
        "service_unavailable": lambda: litellm.exceptions.ServiceUnavailableError(message, provider, model),
    }
    try:
        return mapping[kind]()
    except KeyError as exc:
        raise ValueError(f"unsupported LiteLLM exception kind: {kind!r}") from exc


@dataclass
class AiohttpStubResponse:
    """Minimal `aiohttp` response stub supporting async context-manager use."""

    status: int = 200
    body: str | bytes = ""
    headers: dict[str, str] = field(default_factory=dict)
    url: str = "https://www.mymoment.ch/"
    closed: bool = False

    async def __aenter__(self) -> "AiohttpStubResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.close()

    async def text(self) -> str:
        if isinstance(self.body, bytes):
            return self.body.decode("utf-8")
        return self.body

    async def read(self) -> bytes:
        if isinstance(self.body, bytes):
            return self.body
        return self.body.encode("utf-8")

    async def json(self) -> Any:
        return json.loads(await self.text())

    def close(self) -> None:
        self.closed = True


class AiohttpStubSession:
    """Queue-driven `aiohttp.ClientSession` stub for scraper tests."""

    def __init__(self) -> None:
        self._routes: dict[tuple[str, str], deque[AiohttpStubResponse]] = defaultdict(deque)
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def queue_response(self, method: str, url: str, response: AiohttpStubResponse) -> None:
        self._routes[(method.upper(), url)].append(response)

    def request(self, method: str, url: str, **kwargs: Any) -> AiohttpStubResponse:
        self.requests.append({"method": method.upper(), "url": url, "kwargs": kwargs})
        key = (method.upper(), url)
        if not self._routes[key]:
            raise AssertionError(f"no queued aiohttp response for {method.upper()} {url}")
        return self._routes[key].popleft()

    def get(self, url: str, **kwargs: Any) -> AiohttpStubResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> AiohttpStubResponse:
        return self.request("POST", url, **kwargs)

    async def close(self) -> None:
        self.closed = True


@dataclass
class CeleryRequestStub:
    """Minimal Celery request object for bound task tests."""

    id: str = "fixture-task-id"
    retries: int = 0


class CeleryTaskContextStub:
    """Bound-task stub that records retry attempts."""

    def __init__(
        self,
        *,
        task_id: str = "fixture-task-id",
        retries: int = 0,
        max_retries: int = 3,
        retry_exception: Exception | None = None,
    ) -> None:
        self.request = CeleryRequestStub(id=task_id, retries=retries)
        self.max_retries = max_retries
        self.retry_calls: list[dict[str, Any]] = []
        self._retry_exception = retry_exception

    def retry(self, *, exc: Exception, countdown: int) -> None:
        self.retry_calls.append({"exc": exc, "countdown": countdown})
        if self._retry_exception is not None:
            raise self._retry_exception
        raise MaxRetriesExceededError()


__all__ = [
    "AiohttpStubResponse",
    "AiohttpStubSession",
    "CeleryRequestStub",
    "CeleryTaskContextStub",
    "build_litellm_exception",
    "build_litellm_success_payload",
]
