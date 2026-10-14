"""Queue myMoment HTTP conversations on an AiohttpStubSession."""

from __future__ import annotations

from tests.fixtures.loaders import load_html_fixture
from tests.fixtures.stubs import AiohttpStubResponse, AiohttpStubSession

MYMOMENT_BASE_URL = "https://www.mymoment.ch"
LOGIN_URL = f"{MYMOMENT_BASE_URL}/accounts/login/"
HOME_URL = f"{MYMOMENT_BASE_URL}/"


def logged_in_page() -> AiohttpStubResponse:
    """A page with the logout form myMoment shows to authenticated users."""
    return AiohttpStubResponse(status=200, body=load_html_fixture("articles_index"))


def logged_out_page() -> AiohttpStubResponse:
    return AiohttpStubResponse(status=200, body=load_html_fixture("accounts_login"))


def queue_login(http: AiohttpStubSession, *, succeed: bool = True, session_cookie: str = "fresh-session") -> None:
    """Queue the Django login: form with CSRF, POST, landing page."""
    http.queue_response("GET", LOGIN_URL, logged_out_page())
    if succeed:
        http.queue_response(
            "POST",
            LOGIN_URL,
            AiohttpStubResponse(
                status=302,
                headers={"Location": "/", "Set-Cookie": f"sessionid={session_cookie}; Path=/"},
            ),
        )
        http.queue_response("GET", HOME_URL, logged_in_page())
    else:
        http.queue_response("POST", LOGIN_URL, logged_out_page())


def queue_article(http: AiohttpStubSession, article_id: str = "3170", fixture: str = "articles_get") -> None:
    http.queue_response(
        "GET",
        f"{MYMOMENT_BASE_URL}/article/{article_id}/",
        AiohttpStubResponse(status=200, body=load_html_fixture(fixture)),
    )
