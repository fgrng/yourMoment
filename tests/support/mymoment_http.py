"""Queue myMoment HTTP conversations on an AiohttpStubSession."""

from __future__ import annotations

from typing import Mapping, Optional
from urllib.parse import urlencode

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
    """Queue the Django login: form with CSRF, POST, landing page, home page check."""
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
        http.queue_response("GET", HOME_URL, logged_in_page())
    else:
        http.queue_response("POST", LOGIN_URL, logged_out_page())
        http.queue_response("GET", HOME_URL, logged_out_page())


def queue_article(http: AiohttpStubSession, article_id: str = "3170", fixture: str = "articles_get") -> None:
    http.queue_response(
        "GET",
        f"{MYMOMENT_BASE_URL}/article/{article_id}/",
        AiohttpStubResponse(status=200, body=load_html_fixture(fixture)),
    )


def queue_comment_post(http: AiohttpStubSession, article_id: str = "3170", status: int = 302) -> None:
    """Queue myMoment's answer to the comment form: a redirect back to the article."""
    headers = {"Location": f"/article/{article_id}/"} if status == 302 else {}
    http.queue_response(
        "POST",
        f"{MYMOMENT_BASE_URL}/article/{article_id}/comment/",
        AiohttpStubResponse(status=status, headers=headers),
    )


def queue_article_list(
    http: AiohttpStubSession,
    target: Optional[Mapping[str, str]] = None,
    body: Optional[str] = None,
) -> None:
    """Queue the article index for a target; myMoment filters by query parameters."""
    target = target or {}
    params = {"tab": target.get("classroom", "alle")}
    if "category" in target:
        params["kategorie"] = target["category"]
    if "arrangement" in target:
        params["aufgabe"] = target["arrangement"]
    http.queue_response(
        "GET",
        f"{MYMOMENT_BASE_URL}/articles/?{urlencode(params)}",
        AiohttpStubResponse(status=200, body=body if body is not None else load_html_fixture("articles_index")),
    )
