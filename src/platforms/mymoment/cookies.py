"""Cookie persistence for the myMoment adapter.

The adapter loads and saves the cookie jar of a platform account through a
`CookieStore`. The serialized format is the one already stored in the
MyMomentSession rows, so existing sessions stay usable.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from http.cookies import SimpleCookie
from typing import Any, Dict, Optional, Protocol

from aiohttp import CookieJar
from yarl import URL

from src.utils.datetimes import utcnow

logger = logging.getLogger(__name__)


class CookieStore(Protocol):
    """Loads and saves the serialized cookie jar per platform account."""

    async def load(self, account_id: uuid.UUID) -> Optional[Dict[str, Any]]: ...

    async def save(self, account_id: uuid.UUID, data: Dict[str, Any]) -> None: ...

    async def discard(self, account_id: uuid.UUID) -> None: ...


def serialize_cookie_jar(
    jar: CookieJar, csrf_token: Optional[str] = None
) -> Dict[str, Any]:
    """Serialize a cookie jar into a persistable dictionary."""
    cookies = []
    for cookie in jar:
        expires = None
        expires_value = cookie["expires"]
        if expires_value:
            try:
                expires = parsedate_to_datetime(expires_value).isoformat()
            except (TypeError, ValueError, IndexError):
                expires = None

        cookies.append(
            {
                "name": cookie.key,
                "value": cookie.value,
                "domain": cookie["domain"] or None,
                "path": cookie["path"] or "/",
                "expires": expires,
            }
        )

    return {
        "cookies": cookies,
        "csrf_token": csrf_token,
        "saved_at": utcnow().isoformat(),
    }


def restore_cookie_jar(
    jar: CookieJar, data: Optional[Dict[str, Any]], base_url: str
) -> bool:
    """Put persisted cookies into the jar; return True if there were any."""
    cookies = data.get("cookies") if isinstance(data, dict) else None
    if not isinstance(cookies, list) or not cookies:
        return False

    base = URL(base_url)
    for cookie_data in cookies:
        simple_cookie = SimpleCookie()
        simple_cookie[cookie_data["name"]] = cookie_data["value"]
        morsel = simple_cookie[cookie_data["name"]]

        domain = cookie_data.get("domain")
        if domain:
            morsel["domain"] = domain

        path = cookie_data.get("path") or "/"
        morsel["path"] = path

        expires = cookie_data.get("expires")
        if expires:
            expires_dt = datetime.fromisoformat(expires)
            if expires_dt.tzinfo is None:
                expires_dt = expires_dt.replace(tzinfo=UTC)
            else:
                expires_dt = expires_dt.astimezone(UTC)
            morsel["expires"] = format_datetime(expires_dt, usegmt=True)

        cookie_domain = (domain or base.host or "").lstrip(".")
        cookie_path = path if path.startswith("/") else f"/{path}"
        if cookie_domain:
            response_url = URL.build(
                scheme=base.scheme or "https", host=cookie_domain, path=cookie_path
            )
        else:
            response_url = base.with_path(cookie_path)

        jar.update_cookies(simple_cookie, response_url=response_url)

    return True
