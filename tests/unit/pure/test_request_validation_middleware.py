"""Pure unit tests for request validation middleware behavior."""

import asyncio

from starlette.requests import Request

from src.middleware.validation import (
    RequestValidationConfig,
    RequestValidationMiddleware,
    SecurityValidationResult,
)


def _model_fields(model: type) -> dict:
    return getattr(model, "model_fields", getattr(model, "__fields__", {}))


def _request(method: str = "POST", headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/test",
            "headers": raw_headers,
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )


def test_validation_result_exposes_no_sanitized_payload() -> None:
    """Sanitized request data is not part of middleware output."""
    fields = _model_fields(SecurityValidationResult)
    assert "sanitized_data" not in fields


def test_config_exposes_no_string_sanitization_flag() -> None:
    """String sanitization is not a configurable middleware behavior."""
    fields = _model_fields(RequestValidationConfig)
    assert "sanitize_strings" not in fields


def test_json_body_validation_preserves_validation_without_sanitizing() -> None:
    """JSON structure validation still runs, but string sanitization does not."""
    middleware = RequestValidationMiddleware(app=None)
    body = b'{"comment": "<script>alert(1)</script>"}'
    request = _request(
        headers={
            "content-type": "application/json",
            "content-length": str(len(body)),
        }
    )

    result = asyncio.run(middleware._validate_request(request, body))

    assert result.is_valid is True
    assert result.errors == []
    assert "String content was sanitized" not in result.warnings
    assert not hasattr(middleware, "_sanitize_string")
