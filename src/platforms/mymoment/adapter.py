"""myMoment adapter: scrapes the Django site behind the platform interface.

Login with CSRF, reuse of the stored cookie jar, rate limiting and redirect
sanitizing are internal; callers only see `connect` and the connection.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http.cookies import CookieError
from typing import Any, AsyncIterator, Callable, Optional
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from src.platforms.errors import PlatformAuthError, PlatformRejected, PlatformUnavailable
from src.platforms.mymoment import parsers
from src.platforms.mymoment.cookies import CookieStore, restore_cookie_jar, serialize_cookie_jar
from src.platforms.types import ArticleContent, ArticleRef, PlatformAccount
from src.utils.url_sanitizer import is_url_malformed, sanitize_url

logger = logging.getLogger(__name__)

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5


@dataclass(frozen=True)
class _Page:
    status: int
    url: str
    text: str

    def soup(self) -> BeautifulSoup:
        return BeautifulSoup(self.text, 'html.parser')


class MyMomentAdapter:
    """Platform adapter for myMoment."""

    def __init__(
        self,
        cookie_store: CookieStore,
        *,
        rate_limit_delay: float = 0.0,
        timeout: float = 30,
        http_session_factory: Callable[..., Any] = aiohttp.ClientSession,
    ) -> None:
        self._cookie_store = cookie_store
        self._rate_limit_delay = rate_limit_delay
        self._timeout = timeout
        self._http_session_factory = http_session_factory

    @asynccontextmanager
    async def connect(self, account: PlatformAccount) -> AsyncIterator["MyMomentConnection"]:
        jar = aiohttp.CookieJar()
        http = self._http_session_factory(
            cookie_jar=jar,
            timeout=aiohttp.ClientTimeout(total=self._timeout),
            headers=_HEADERS,
        )
        connection = MyMomentConnection(account, http, jar, self._rate_limit_delay)
        try:
            await connection._open(self._cookie_store)
            yield connection
        finally:
            await http.close()


class MyMomentConnection:
    """An authenticated myMoment session for one platform account."""

    def __init__(
        self,
        account: PlatformAccount,
        http: Any,
        jar: aiohttp.CookieJar,
        rate_limit_delay: float,
    ) -> None:
        self._account = account
        self._base_url = account.base_url.rstrip('/')
        self._http = http
        self._jar = jar
        self._rate_limit_delay = rate_limit_delay
        self._last_request_time: Optional[float] = None
        self._rate_limit_lock = asyncio.Lock()
        self._csrf_token: Optional[str] = None

    async def fetch_article(self, ref: ArticleRef) -> ArticleContent:
        url = self._article_url(ref.id)
        page = await self._request('GET', url)
        if page.status != 200:
            raise PlatformRejected(f"myMoment answered {page.status} for article {ref.id}")

        data = parsers.parse_article_detail(page.soup(), ref.id)
        extra = {}
        if data['task_id'] is not None:
            extra['arrangement'] = str(data['task_id'])
        return ArticleContent(
            ref=ArticleRef(id=ref.id, url=url),
            title=data['title'],
            author=data['author'],
            body_html=data['full_html'],
            body_text=data['content'],
            category=str(data['category_id']) if data['category_id'] is not None else None,
            extra=extra,
        )

    def _article_url(self, article_id: str) -> str:
        return f"{self._base_url}/article/{article_id}/"

    async def _open(self, cookie_store: CookieStore) -> None:
        """Reuse stored cookies if myMoment still accepts them, else log in."""
        if await self._restore_session(cookie_store):
            logger.info(f"Restored myMoment session for account {self._account.id}")
        else:
            await self._login()
            logger.info(f"Logged in to myMoment for account {self._account.id}")

        # Saving renews the stored session; failures must not break the connection.
        try:
            await cookie_store.save(self._account.id, serialize_cookie_jar(self._jar, self._csrf_token))
        except Exception as e:
            logger.warning(f"Failed to persist myMoment cookies for account {self._account.id}: {e}")

    async def _restore_session(self, cookie_store: CookieStore) -> bool:
        # Like saving, loading is best-effort: without stored cookies we log in.
        try:
            data = await cookie_store.load(self._account.id)
        except Exception as e:
            logger.warning(f"Failed to load myMoment cookies for account {self._account.id}: {e}")
            return False

        try:
            if not restore_cookie_jar(self._jar, data, self._base_url):
                return False
        except (AttributeError, KeyError, TypeError, ValueError, CookieError) as e:
            logger.warning(f"Stored myMoment cookies of account {self._account.id} are corrupt: {e}")
            self._jar.clear()
            return False

        self._csrf_token = data.get('csrf_token') or None
        if await self._is_logged_in():
            return True

        logger.warning(f"Stored myMoment cookies expired for account {self._account.id}")
        self._jar.clear()
        return False

    async def _login(self) -> None:
        login_url = f"{self._base_url}/accounts/login/"
        page = await self._request('GET', login_url)
        csrf_token = parsers.extract_login_csrf_token(page.soup())
        if not csrf_token:
            raise PlatformUnavailable("Could not find CSRF token on myMoment login page")
        self._csrf_token = csrf_token

        await self._request(
            'POST',
            login_url,
            data={
                'csrfmiddlewaretoken': csrf_token,
                'username': self._account.username,
                'password': self._account.password,
                'next': ''
            },
            headers={
                'Referer': login_url,
                'Content-Type': 'application/x-www-form-urlencoded'
            },
        )
        if not await self._is_logged_in():
            raise PlatformAuthError(f"myMoment rejected the credentials of account {self._account.id}")

    async def _is_logged_in(self) -> bool:
        """Check the home page, wherever the login redirect landed."""
        page = await self._request('GET', f"{self._base_url}/")
        return page.status == 200 and parsers.is_logged_in(page.soup())

    async def _request(self, method: str, url: str, **kwargs: Any) -> _Page:
        """
        The single HTTP helper: rate limit, manual redirects, error mapping.

        myMoment sends Location headers with backslashes; every redirect is
        sanitized before it is followed. Network errors, timeouts and 5xx
        become PlatformUnavailable.
        """
        current_url = url
        request_method = method.upper()

        for _ in range(_MAX_REDIRECTS + 1):
            await self._rate_limit()
            try:
                async with self._http.request(
                    request_method, current_url, allow_redirects=False, **kwargs
                ) as response:
                    status = response.status
                    location = response.headers.get('Location')
                    text = '' if status in _REDIRECT_STATUSES else await response.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                raise PlatformUnavailable(f"myMoment not reachable ({request_method} {current_url}): {e}") from e

            if status >= 500:
                raise PlatformUnavailable(f"myMoment answered {status} for {request_method} {current_url}")
            if status not in _REDIRECT_STATUSES:
                return _Page(status=status, url=current_url, text=text)

            if not location:
                raise PlatformUnavailable(f"Redirect {status} without Location header from {current_url}")
            if is_url_malformed(location):
                location = sanitize_url(location)
            current_url = urljoin(current_url, location)

            # Redirects switch to GET, except 307/308 which preserve the method
            if status not in (307, 308):
                request_method = 'GET'
                kwargs.pop('data', None)

        raise PlatformUnavailable(f"Maximum redirects ({_MAX_REDIRECTS}) exceeded while accessing {url}")

    async def _rate_limit(self) -> None:
        # The lock makes concurrent requests on one connection wait in turn
        async with self._rate_limit_lock:
            loop = asyncio.get_running_loop()
            if self._last_request_time is not None:
                elapsed = loop.time() - self._last_request_time
                if elapsed < self._rate_limit_delay:
                    await asyncio.sleep(self._rate_limit_delay - elapsed)
            self._last_request_time = loop.time()
