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
from typing import Any, AsyncIterator, Callable, Mapping, Optional
from urllib.parse import urlencode, urljoin

import aiohttp
from bs4 import BeautifulSoup

from src.platforms.errors import PlatformAuthError, PlatformRejected, PlatformUnavailable
from src.platforms.mymoment import parsers
from src.platforms.mymoment.cookies import CookieStore, restore_cookie_jar, serialize_cookie_jar
from src.platforms.types import (
    ArticleContent,
    ArticleRef,
    ArticleSummary,
    PlatformAccount,
    PostedComment,
    StudentRef,
)
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
_TARGET_KEYS = {'category', 'arrangement', 'classroom'}
_DEFAULT_CLASSROOM = 'alle'


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

    async def list_articles(self, target: Optional[Mapping[str, str]] = None) -> list[ArticleSummary]:
        """
        List the articles of a classroom, optionally narrowed by category and arrangement.

        myMoment filters by query parameters; the parsed category and
        arrangement are checked again, so a filter myMoment ignores still holds.
        Where a view does not show them, the filter value is what myMoment matched.
        """
        target = _validate_target(target or {})
        classroom = target.get('classroom', _DEFAULT_CLASSROOM)
        params = {'tab': classroom}
        if 'category' in target:
            params['kategorie'] = target['category']
        if 'arrangement' in target:
            params['aufgabe'] = target['arrangement']

        page = await self._request('GET', f"{self._base_url}/articles/?{urlencode(params)}")
        if page.status != 200:
            raise PlatformRejected(f"myMoment answered {page.status} for the article list")

        summaries = []
        for entry in parsers.parse_article_list(page.soup(), classroom):
            if _contradicts(entry['category_id'], target.get('category')) or _contradicts(
                entry['task_id'], target.get('arrangement')
            ):
                continue
            category = _shown_or_filtered(entry['category_id'], target.get('category'))
            arrangement = _shown_or_filtered(entry['task_id'], target.get('arrangement'))
            extra = {key: entry[key] for key in ('status', 'visibility', 'date')}
            if arrangement is not None:
                extra['arrangement'] = arrangement
            summaries.append(ArticleSummary(
                ref=ArticleRef(id=entry['id'], url=urljoin(f"{self._base_url}/", entry['href'])),
                title=entry['title'],
                author=entry['author'],
                category=category,
                extra=extra,
            ))
        return summaries

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

    async def post_comment(self, ref: ArticleRef, text: str, *, hidden: bool = False) -> PostedComment:
        """
        Fill in the article's comment form and submit it.

        The form's CSRF token comes from the article page. myMoment answers a
        successful post with 200 or 302; it reports no comment ID.
        """
        url = self._article_url(ref.id)
        page = await self._request('GET', url)
        if page.status != 200:
            raise PlatformRejected(f"myMoment answered {page.status} for article {ref.id}")
        csrf_token = parsers.extract_comment_csrf_token(page.soup(), ref.id)
        if not csrf_token:
            raise PlatformRejected(f"Article {ref.id} offers no comment form")

        form = {
            'csrfmiddlewaretoken': csrf_token,
            'text': text,
            'status': '20',  # Published
            'highlight': '',
        }
        if hidden:
            form['hide'] = 'on'

        response = await self._request(
            'POST',
            f"{url}comment/",
            follow_redirects=False,
            data=form,
            headers={
                'Referer': url,
                'Content-Type': 'application/x-www-form-urlencoded'
            },
        )
        if response.status not in (200, 302):
            raise PlatformRejected(f"myMoment answered {response.status} to the comment on article {ref.id}")
        logger.info(f"Posted comment to myMoment article {ref.id} (hidden={hidden})")
        return PostedComment()

    async def list_student_articles(self, student: StudentRef) -> list[ArticleSummary]:
        """
        List the articles on a student's dashboard, which only admin accounts may see.

        `category` is set where the dashboard shows exactly one known category;
        `extra` carries the categories as shown, status and visibility.
        """
        if not parsers.is_number(student.id):
            raise PlatformRejected(f"Unknown myMoment student: {student.id!r}")

        page = await self._request('GET', f"{self._base_url}/dashboard/user/{student.id}/")
        if page.status != 200:
            raise PlatformRejected(f"myMoment answered {page.status} for the dashboard of student {student.id}")

        summaries = []
        for entry in parsers.parse_student_articles(page.soup()):
            summaries.append(ArticleSummary(
                ref=ArticleRef(id=entry['id'], url=self._article_url(entry['id'])),
                title=entry['title'],
                author='',  # the dashboard belongs to one student and shows no author
                category=str(entry['category_id']) if entry['category_id'] is not None else None,
                edited_at=entry['last_modified'],
                extra={
                    'categories': ', '.join(entry['categories']),
                    'status': entry['status'],
                    'visibility': entry['visibility'],
                },
            ))
        return summaries

    def _article_url(self, article_id: str) -> str:
        return f"{self._base_url}/article/{article_id}/"

    async def _open(self, cookie_store: CookieStore) -> None:
        """Reuse stored cookies if myMoment still accepts them, else log in."""
        if await self._restore_session(cookie_store):
            logger.info(f"Restored myMoment session for account {self._account.id}")
        else:
            try:
                await self._login()
            except PlatformAuthError:
                await self._discard_session(cookie_store)
                raise
            logger.info(f"Logged in to myMoment for account {self._account.id}")

        # Saving renews the stored session; failures must not break the connection.
        try:
            await cookie_store.save(self._account.id, serialize_cookie_jar(self._jar, self._csrf_token))
        except Exception as e:
            logger.warning(f"Failed to persist myMoment cookies for account {self._account.id}: {e}")

    async def _discard_session(self, cookie_store: CookieStore) -> None:
        # Cookies of rejected credentials must not be reused; best-effort like saving.
        try:
            await cookie_store.discard(self._account.id)
        except Exception as e:
            logger.warning(f"Failed to discard myMoment cookies for account {self._account.id}: {e}")

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

    async def _request(self, method: str, url: str, *, follow_redirects: bool = True, **kwargs: Any) -> _Page:
        """
        The single HTTP helper: rate limit, manual redirects, error mapping.

        myMoment sends Location headers with backslashes; every redirect is
        sanitized before it is followed. Without `follow_redirects` a redirect
        is returned as the page. Network errors, timeouts and 5xx become
        PlatformUnavailable.
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
            if status not in _REDIRECT_STATUSES or not follow_redirects:
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


def _validate_target(target: Mapping[str, str]) -> dict[str, str]:
    """Reject targets myMoment cannot apply: unknown keys or malformed values."""
    unknown = set(target) - _TARGET_KEYS
    if unknown:
        raise PlatformRejected(f"Unknown myMoment target keys: {sorted(unknown)}")
    if not all(isinstance(value, str) for value in target.values()):
        raise PlatformRejected(f"myMoment target values must be strings: {dict(target)}")

    classroom = target.get('classroom')
    if classroom is not None and classroom not in ('home', 'alle') and not parsers.is_number(classroom):
        raise PlatformRejected(f"Unknown myMoment classroom: {classroom!r}")
    category = target.get('category')
    if category is not None and not (parsers.is_number(category) and int(category) in parsers.CATEGORY_MAPPING):
        raise PlatformRejected(f"Unknown myMoment category: {category!r}")
    arrangement = target.get('arrangement')
    if arrangement is not None and not parsers.is_number(arrangement):
        raise PlatformRejected(f"Unknown myMoment arrangement: {arrangement!r}")
    return dict(target)


def _contradicts(shown_id: Optional[int], wanted: Optional[str]) -> bool:
    """True if the list shows an ID that differs from the filter value."""
    return shown_id is not None and wanted is not None and str(shown_id) != wanted


def _shown_or_filtered(shown_id: Optional[int], wanted: Optional[str]) -> Optional[str]:
    """The ID the list shows, else the filter value myMoment matched."""
    return str(shown_id) if shown_id is not None else wanted
