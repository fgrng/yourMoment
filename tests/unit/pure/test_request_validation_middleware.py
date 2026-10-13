"""Pure unit tests for request validation middleware behavior."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

from src.middleware.validation import RequestValidationMiddleware


async def _echo(request: Request) -> Response:
    return Response(await request.body(), media_type="application/json")


def _client() -> TestClient:
    app = Starlette(routes=[Route("/api/echo", _echo, methods=["POST"])])
    return TestClient(RequestValidationMiddleware(app))


def test_json_body_reaches_endpoint_unchanged() -> None:
    """A valid JSON body is passed through to the endpoint byte for byte."""
    body = b'{"comment": "Hallo  Welt"}'

    response = _client().post(
        "/api/echo", content=body, headers={"content-type": "application/json"}
    )

    assert response.content == body


def test_malformed_json_body_is_rejected() -> None:
    """A body that is not valid JSON is rejected before reaching the endpoint."""
    response = _client().post(
        "/api/echo",
        content=b'{"comment": ',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
