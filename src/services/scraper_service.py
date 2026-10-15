"""
Web scraping service for myMoment platform with multi-session support.

Multi-session web scraping for article discovery and comment generation.
Adapts the previous scraper implementation from https://github.com/fgrng/yourMoment_deprecated
to integrate with the yourMoment service architecture
while supporting concurrent sessions for multiple logins.
"""

import asyncio
import uuid
import aiohttp
import logging
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from http.cookies import SimpleCookie
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from yarl import URL

from src.services.mymoment_session_service import MyMomentSessionService
from src.services.mymoment_credentials_service import MyMomentCredentialsService
from src.config.settings import get_settings
from src.utils.url_sanitizer import sanitize_url, is_url_malformed
from src.platforms.mymoment import parsers

logger = logging.getLogger(__name__)


@dataclass
class ScrapingConfig:
    """
    Configuration for scraping operations.

    This class wraps settings from the unified configuration system
    to provide backward compatibility and a convenient API.
    """
    base_url: str
    request_timeout: int
    rate_limit_delay: float  # Seconds between requests
    max_concurrent_sessions: int
    session_timeout: int  # In seconds
    max_articles_per_request: int
    retry_attempts: int
    retry_delay: float

    @classmethod
    def from_settings(cls) -> 'ScrapingConfig':
        """
        Create ScrapingConfig from unified settings system.

        Returns:
            ScrapingConfig instance with values from settings
        """
        settings = get_settings()
        return cls(
            base_url=settings.scraper.MYMOMENT_BASE_URL,
            request_timeout=settings.scraper.MYMOMENT_TIMEOUT,
            rate_limit_delay=1.0 / settings.scraper.SCRAPING_RATE_LIMIT,  # Convert requests/sec to delay
            max_concurrent_sessions=settings.scraper.MAX_CONCURRENT_SESSIONS,
            session_timeout=settings.scraper.SESSION_TIMEOUT_MINUTES * 60,  # Convert to seconds
            max_articles_per_request=settings.scraper.MAX_ARTICLES_PER_REQUEST,
            retry_attempts=settings.scraper.RETRY_ATTEMPTS,
            retry_delay=settings.scraper.RETRY_DELAY
        )


@dataclass
class ArticleMetadata:
    """Article metadata extracted from myMoment."""
    id: str
    title: str
    author: str
    date: str
    status: str
    category_id: Optional[int]  # Category ID only, name can be looked up from parsers.CATEGORY_MAPPING
    task_id: Optional[int]  # Task ID only, name can be looked up from parsers.TASK_MAPPING
    visibility: str
    url: str
    content_preview: Optional[str] = None


@dataclass
class TabMetadata:
    """Tab/filter metadata extracted from myMoment articles page."""
    id: str  # Tab identifier (e.g., "home", "alle", "38")
    name: str  # Display name (e.g., "Meine", "Alle", "Dummy Klasse 01")
    tab_type: str  # Type: "home", "alle", or "class"


@dataclass
class SessionContext:
    """Context for an active myMoment session."""
    login_id: uuid.UUID
    session_id: uuid.UUID
    username: str
    aiohttp_session: aiohttp.ClientSession
    csrf_token: Optional[str] = None
    last_activity: datetime = None
    is_authenticated: bool = False


class ScrapingError(Exception):
    """Base exception for scraping operations."""
    pass


class SessionError(ScrapingError):
    """Raised when session operations fail."""
    pass


class AuthenticationError(ScrapingError):
    """Raised when authentication fails."""
    pass


class ScraperService:
    """
    Multi-session web scraping service for myMoment platform.

    Features:
    - Concurrent session management for multiple myMoment logins
    - Session isolation and coordination
    - Article discovery with filtering
    - Comment generation integration
    - Rate limiting and error recovery

    Database Session Lifecycle:
    - DB session is required for initialization (reading credentials, session records)
    - Once SessionContext is created, HTTP operations do NOT use the DB session
    - Callers should close DB session after initialization, before HTTP operations
    - Pattern: Open DB → Init session → Close DB → HTTP scraping → Open DB → Update
    """

    def __init__(self, db_session: AsyncSession, config: Optional[ScrapingConfig] = None):
        """
        Initialize scraper service.

        Args:
            db_session: Database session for operations
            config: Scraping configuration (optional, defaults to settings-based config)
        """
        self.db_session = db_session
        self.config = config or ScrapingConfig.from_settings()

        # Session management
        self.active_sessions: Dict[uuid.UUID, SessionContext] = {}
        self.session_lock = asyncio.Lock()

        # Services
        self.session_service = MyMomentSessionService(db_session)
        self.credentials_service = MyMomentCredentialsService(db_session)

        # Rate limiting
        self._last_request_time = 0.0
        self._request_lock = asyncio.Lock()

        logger.debug(f"ScraperService initialized with DB session {id(db_session)}")

    async def __aenter__(self):
        """Async context manager entry."""
        logger.debug(f"ScraperService context entered (DB session {id(self.db_session)})")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup all sessions."""
        logger.debug(f"ScraperService context exiting (DB session {id(self.db_session)})")
        await self.cleanup_all_sessions()
        logger.debug("ScraperService context exited, all sessions cleaned up")

    async def initialize_session_for_login(
        self,
        login_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> SessionContext:
        """
        Initialize a single scraping session for a myMoment login (direct API call).

        Args:
            login_id: MyMoment login ID
            user_id: User ID for validation

        Returns:
            Initialized session context

        Raises:
            ScrapingError: If session initialization fails
        """
        try:
            logger.info(f"Initializing scraping session for login {login_id}")
            context = await self._initialize_single_session(login_id, user_id)
            return context
        except SessionError as e:
            logger.error(f"Failed to initialize session for login {login_id}: {e}")
            raise ScrapingError(f"Failed to authenticate with myMoment: {e}")

    async def _initialize_single_session(
        self,
        login_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> SessionContext:
        """
        Initialize a single myMoment session.

        Args:
            login_id: MyMoment login ID
            user_id: User ID for validation

        Returns:
            Initialized session context

        Raises:
            SessionError: If session initialization fails
        """
        try:
            # Get login credentials
            credentials = await self.credentials_service.get_credentials_by_id(login_id, user_id)

            # Get or create session
            session_record = await self.session_service.get_or_create_session(
                login_id=login_id,
                user_id=user_id
            )

            # Create HTTP session
            # Important: We will handle redirects manually for ALL requests to sanitize
            # malformed Location headers that myMoment returns (containing backslashes)
            connector = aiohttp.TCPConnector(limit=10)
            timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
            http_session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }
            )

            # Create session context
            context = SessionContext(
                login_id=login_id,
                session_id=session_record.id,
                username=credentials.username,
                aiohttp_session=http_session,
                last_activity=datetime.utcnow(),
                is_authenticated=False
            )

            # Store in active sessions
            async with self.session_lock:
                self.active_sessions[login_id] = context

            session_data = None

            try:
                session_data = session_record.get_session_data(as_dict=True)
            except Exception as e:
                logger.warning(f"Failed to load stored session data for login {login_id}: {e}")

            cookies = session_data.get('cookies') if isinstance(session_data, dict) else None

            auth_needed = True
            if isinstance(cookies, list) and cookies:
                try:
                    logger.info(f"Attempting cookie restore for login {login_id}")
                    csrf_token = self._restore_cookies_to_session(http_session, session_data)
                    if csrf_token is not None:
                        context.csrf_token = csrf_token

                    if await self._check_authentication_status(context):
                        context.is_authenticated = True
                        await self.session_service.renew_session(context.session_id)
                        logger.info(f"Restored session for login {login_id}")
                        auth_needed = False
                    else:
                        logger.warning(f"Restored cookies expired for login {login_id}")
                except Exception as e:
                    logger.warning(f"Cookie restore failed for login {login_id}: {e}")

            if auth_needed:
                # Full login path — only called once
                await self._authenticate_session(context)

            return context

        except Exception as e:
            logger.error(f"Failed to initialize session for login {login_id}: {e}")
            raise SessionError(f"Session initialization failed: {e}")

    def _serialize_cookie_jar(
        self,
        http_session: aiohttp.ClientSession,
        csrf_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Serialize the aiohttp cookie jar into a persistable dictionary.
        """
        cookies = []

        for cookie in http_session.cookie_jar:
            expires = None
            expires_value = cookie['expires']
            if expires_value:
                try:
                    expires = parsedate_to_datetime(expires_value).isoformat()
                except (TypeError, ValueError, IndexError):
                    expires = None

            cookies.append({
                'name': cookie.key,
                'value': cookie.value,
                'domain': cookie['domain'] or None,
                'path': cookie['path'] or '/',
                'expires': expires
            })

        return {
            'cookies': cookies,
            'csrf_token': csrf_token,
            'saved_at': datetime.utcnow().isoformat()
        }

    def _restore_cookies_to_session(
        self,
        http_session: aiohttp.ClientSession,
        session_data: Dict[str, Any]
    ) -> Optional[str]:
        """
        Restore persisted cookies into an aiohttp session cookie jar.
        """
        try:
            cookies = session_data.get('cookies') if isinstance(session_data, dict) else None
            if not isinstance(cookies, list) or not cookies:
                return None

            base_url = URL(self.config.base_url)

            for cookie_data in cookies:
                simple_cookie = SimpleCookie()
                simple_cookie[cookie_data['name']] = cookie_data['value']
                morsel = simple_cookie[cookie_data['name']]

                domain = cookie_data.get('domain')
                if domain:
                    morsel['domain'] = domain

                path = cookie_data.get('path') or '/'
                morsel['path'] = path

                expires = cookie_data.get('expires')
                if expires:
                    expires_dt = datetime.fromisoformat(expires)
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)
                    else:
                        expires_dt = expires_dt.astimezone(timezone.utc)
                    morsel['expires'] = format_datetime(expires_dt, usegmt=True)

                cookie_domain = (domain or base_url.host or '').lstrip('.')
                cookie_path = path if path.startswith('/') else f'/{path}'
                if cookie_domain:
                    response_url = URL.build(
                        scheme=base_url.scheme or 'https',
                        host=cookie_domain,
                        path=cookie_path
                    )
                else:
                    response_url = base_url.with_path(cookie_path)

                http_session.cookie_jar.update_cookies(
                    simple_cookie,
                    response_url=response_url
                )

            return session_data.get('csrf_token') or None
        except Exception as e:
            logger.warning(f"Failed to restore cookies to session: {e}")
            return None

    async def _authenticate_session(self, context: SessionContext) -> bool:
        """
        Authenticate a session with myMoment platform.

        Args:
            context: Session context to authenticate

        Returns:
            True if authentication successful

        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            # Check if already authenticated
            if await self._check_authentication_status(context):
                context.is_authenticated = True
                return True

            # Get credentials for login
            credentials = await self.credentials_service.get_credentials_by_id(
                context.login_id,
                None  # Skip user validation since we're already in a trusted context
            )

            username, password = credentials.get_credentials()

            # Load login page to get CSRF token
            login_url = f"{self.config.base_url}/accounts/login/"
            logger.info(f"Try auth using base url: {self.config.base_url}")
            logger.info(f"Resulting in login url: {login_url}")

            # Use redirect handler to sanitize any malformed Location headers
            response = await self._get_with_redirect_handling(context, login_url)
            login_html = await response.text()

            soup = BeautifulSoup(login_html, 'html.parser')
            csrf_input = soup.find('input', {'name': 'csrfmiddlewaretoken'})

            if not csrf_input:
                raise AuthenticationError("Could not find CSRF token on login page")

            csrf_token = csrf_input.get('value')
            context.csrf_token = csrf_token

            # Prepare login data
            login_data = {
                'csrfmiddlewaretoken': csrf_token,
                'username': username,
                'password': password,
                'next': ''
            }

            # Perform login with redirect handling
            response = await self._request_with_redirect_handling(
                context,
                'POST',
                login_url,
                data=login_data,
                headers={
                    'Referer': login_url,
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            )
            response.close()

            # Check authentication success
            if await self._check_authentication_status(context):
                context.is_authenticated = True
                context.last_activity = datetime.utcnow()

                # Persist cookies for future restore (best-effort — must not break auth on failure)
                try:
                    await self.session_service.touch_session(context.session_id)
                    data = self._serialize_cookie_jar(
                        context.aiohttp_session,
                        context.csrf_token
                    )
                    await self.session_service.update_session_data(context.session_id, data)
                    logger.info(f"Persisted cookie jar for login {context.login_id}")
                except Exception as e:
                    logger.warning(f"Failed to persist session data for login {context.login_id}: {e}")

                logger.info(f"Successfully authenticated session for login {context.login_id}")
                return True
            else:
                raise AuthenticationError(f"Login failed for {username}")

        except Exception as e:
            logger.error(f"Authentication failed for login {context.login_id}: {e}")
            context.is_authenticated = False
            raise AuthenticationError(f"Authentication failed: {e}")

    async def _request_with_redirect_handling(
        self,
        context: SessionContext,
        method: str,
        url: str,
        max_redirects: int = 5,
        **kwargs
    ) -> aiohttp.ClientResponse:
        """
        Perform an HTTP request with manual redirect handling to sanitize malformed URLs.

        This handles the myMoment server bug where Location headers contain backslashes.
        Works for both GET and POST requests.

        Args:
            context: Session context for HTTP operations
            method: HTTP method ('GET', 'POST', etc.)
            url: URL to request
            max_redirects: Maximum number of redirects to follow (default: 5)
            **kwargs: Additional arguments to pass to the request method

        Returns:
            Final response object with proper status

        Raises:
            AuthenticationError: If max redirects exceeded or request fails
        """
        current_url = url
        redirect_count = 0
        request_method = method.upper()

        while redirect_count < max_redirects:
            logger.debug(f"Request: {request_method} {current_url}")
            await self._rate_limit()

            # Make the request with redirects disabled
            response = await context.aiohttp_session.request(
                request_method,
                current_url,
                allow_redirects=False,  # Disable auto-redirects
                **kwargs
            )

            # Check for redirect status codes
            if response.status in [301, 302, 303, 307, 308]:
                location = response.headers.get('Location')

                # Must close the response when we're following the redirect
                response.close()

                if not location:
                    logger.warning(f"Redirect response {response.status} but no Location header")
                    raise AuthenticationError(f"Redirect response {response.status} but no Location header")

                # Check if Location header is malformed
                if is_url_malformed(location):
                    logger.warning(
                        f"Detected malformed Location header (contains backslash): {repr(location)}"
                    )
                    location = sanitize_url(location)
                    logger.info(f"Sanitized to: {repr(location)}")

                # Handle relative redirects
                if location.startswith('/'):
                    # Relative redirect - build absolute URL from current URL
                    from urllib.parse import urlparse, urlunparse
                    parsed = urlparse(current_url)
                    location = urlunparse((
                        parsed.scheme,
                        parsed.netloc,
                        location,
                        '',
                        '',
                        ''
                    ))

                current_url = location
                redirect_count += 1
                logger.debug(f"Following redirect ({redirect_count}/{max_redirects}) to: {current_url}")

                # For redirects, switch to GET method (except for 307/308 which preserve method)
                if response.status not in [307, 308]:
                    request_method = 'GET'
                    kwargs.pop('data', None)  # Remove POST data for GET requests

                continue
            else:
                # Not a redirect, return the response
                logger.debug(f"Final response status: {response.status}")
                return response

        # Max redirects exceeded
        raise AuthenticationError(
            f"Maximum redirects ({max_redirects}) exceeded while accessing {url}"
        )

    async def _get_with_redirect_handling(
        self,
        context: SessionContext,
        url: str,
        max_redirects: int = 5
    ) -> aiohttp.ClientResponse:
        """
        Perform a GET request with manual redirect handling.

        Convenience wrapper around _request_with_redirect_handling.
        """
        return await self._request_with_redirect_handling(context, 'GET', url, max_redirects)

    async def _check_authentication_status(self, context: SessionContext) -> bool:
        """
        Check if a session is currently authenticated.

        Args:
            context: Session context to check

        Returns:
            True if authenticated
        """
        try:
            # Use redirect handler to sanitize any malformed Location headers
            response = await self._get_with_redirect_handling(
                context,
                f"{self.config.base_url}/"
            )

            if response.status == 200:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                # Look for logout form (indicates authenticated user)
                logout_form = soup.find('form', attrs={'action': '/accounts/logout/'})
                return logout_form is not None
            return False
        except Exception as e:
            logger.warning(f"Failed to check authentication status: {e}")
            return False

    async def discover_new_articles(
        self,
        context: SessionContext,
        tab: str = "alle",
        category: Optional[str] = None,
        task: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 20
    ) -> List[ArticleMetadata]:
        """
        Discover new articles from myMoment platform.

        Returns article metadata only (no full content). This method performs
        HTTP requests only and does NOT use the database session.

        Args:
            context: Authenticated session context
            tab: Which tab to scrape ('home', 'alle', or classroom ID)
            category: Optional category filter (by category ID)
            task: Optional task filter (by task ID)
            search: Optional search string to filter articles by title
            limit: Maximum number of articles to retrieve

        Returns:
            List of discovered articles (metadata only, no content)

        Raises:
            ScrapingError: If article discovery fails
        """
        try:
            if not context.is_authenticated:
                raise ScrapingError(f"Session not authenticated for login {context.login_id}")

            # Build URL with query parameters for filtering
            articles_url = f"{self.config.base_url}/articles/?tab={tab}"

            # Add category filter if specified
            if category:
                articles_url += f"&kategorie={category}"

            # Add task filter if specified
            if task:
                articles_url += f"&aufgabe={task}"

            logger.debug(f"Starting HTTP request to discover articles (login {context.login_id}, tab={tab}, category={category}, task={task})")
            await self._rate_limit()
            async with context.aiohttp_session.get(articles_url) as response:
                if response.status != 200:
                    raise ScrapingError(f"Failed to load articles page: {response.status}")

                html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')
            articles = []
            for entry in parsers.parse_article_list(soup, tab):
                if len(articles) >= limit:
                    break
                if search and search.lower() not in entry['title'].lower():
                    continue
                href = entry['href']
                articles.append(ArticleMetadata(
                    id=entry['id'],
                    title=entry['title'],
                    author=entry['author'],
                    date=entry['date'],
                    status=entry['status'],
                    category_id=entry['category_id'],
                    task_id=entry['task_id'],
                    visibility=entry['visibility'],
                    url=f"{self.config.base_url}{href}" if href.startswith('/') else href,
                ))

            context.last_activity = datetime.utcnow()
            logger.debug(f"HTTP request completed for article discovery (login {context.login_id})")
            logger.info(f"Discovered {len(articles)} articles for login {context.login_id} (tab: {tab}, category: {category}, task: {task}, search: {search})")

            return articles

        except Exception as e:
            logger.error(f"Failed to discover articles for login {context.login_id}: {e}")
            raise ScrapingError(f"Article discovery failed: {e}")

    async def discover_available_tabs(self, context: SessionContext) -> List[TabMetadata]:
        """
        Discover available tabs for the authenticated session.

        Tabs represent article filters on myMoment platform:
        - "home": User's own articles ("Meine")
        - "alle": All publicly visible articles ("Alle")
        - Class IDs: Articles visible to specific classes (e.g., "38", "82")

        Args:
            context: Active session context

        Returns:
            List of available tabs

        Raises:
            ScrapingError: If tab discovery fails
        """
        try:
            if not context.is_authenticated:
                raise ScrapingError(f"Session not authenticated for login {context.login_id}")

            articles_url = f"{self.config.base_url}/articles/"

            await self._rate_limit()
            async with context.aiohttp_session.get(articles_url) as response:
                if response.status != 200:
                    raise ScrapingError(f"Failed to load articles page: {response.status}")

                html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')
            tabs = self._parse_article_tabs(soup)

            context.last_activity = datetime.utcnow()
            logger.info(f"Discovered {len(tabs)} tabs for login {context.login_id}")

            return tabs

        except Exception as e:
            logger.error(f"Failed to discover tabs for login {context.login_id}: {e}")
            raise ScrapingError(f"Tab discovery failed: {e}")

    def _parse_article_tabs(self, soup: BeautifulSoup) -> List[TabMetadata]:
        """
        Parse available tabs from articles page HTML.

        Args:
            soup: BeautifulSoup object of the articles page

        Returns:
            List of TabMetadata objects
        """
        # Find the tab navigation (<ul class="nav nav-pills" id="pills-tab">)
        tabs_nav = soup.find('ul', {'id': 'pills-tab'})
        if not tabs_nav:
            logger.warning("No tabs navigation found on articles page")
            return []

        tabs = []

        # Extract all tab buttons
        for tab_button in tabs_nav.find_all('button', {'role': 'tab'}):
            try:
                # Extract tab ID from data-bs-target (e.g., "#pills-home" -> "home")
                target = tab_button.get('data-bs-target', '')
                if not target.startswith('#pills-'):
                    continue

                tab_id = target.replace('#pills-', '')
                tab_name = tab_button.text.strip()

                # Determine tab type
                if tab_id == 'home':
                    tab_type = 'home'
                elif tab_id == 'alle':
                    tab_type = 'alle'
                else:
                    # Numeric ID = class tab
                    tab_type = 'class'

                tabs.append(TabMetadata(
                    id=tab_id,
                    name=tab_name,
                    tab_type=tab_type
                ))

            except Exception as e:
                logger.warning(f"Failed to extract tab metadata: {e}")
                continue

        return tabs

    async def get_article_content(
        self,
        context: SessionContext,
        article_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get full content of a specific article.

        This method performs HTTP requests only and does NOT use the database session.

        Args:
            context: Authenticated session context
            article_id: Article ID to retrieve

        Returns:
            Article content dictionary or None if failed

        Raises:
            ScrapingError: If content retrieval fails
        """
        try:
            if not context.is_authenticated:
                raise ScrapingError(f"Session not authenticated for login {context.login_id}")

            article_url = f"{self.config.base_url}/article/{article_id}/"

            logger.debug(f"Starting HTTP request to fetch article content (article_id={article_id}, login={context.login_id})")
            await self._rate_limit()
            async with context.aiohttp_session.get(article_url) as response:
                if response.status != 200:
                    raise ScrapingError(f"Failed to load article {article_id}: {response.status}")

                html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')
            article_content = parsers.parse_article_detail(soup, article_id)
            article_content['url'] = article_url

            context.last_activity = datetime.utcnow()
            logger.debug(f"HTTP request completed for article content (article_id={article_id}, login={context.login_id})")

            return article_content

        except Exception as e:
            logger.error(f"Failed to get article content for {article_id}: {e}")
            raise ScrapingError(f"Article content retrieval failed: {e}")

    async def _rate_limit(self):
        """Apply rate limiting to requests."""
        async with self._request_lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request_time

            if elapsed < self.config.rate_limit_delay:
                sleep_time = self.config.rate_limit_delay - elapsed
                await asyncio.sleep(sleep_time)

            self._last_request_time = asyncio.get_event_loop().time()

    async def cleanup_session(self, login_id: uuid.UUID):
        """
        Cleanup a specific session.

        Args:
            login_id: Login ID of session to cleanup
        """
        async with self.session_lock:
            context = self.active_sessions.get(login_id)
            if context:
                try:
                    await context.aiohttp_session.close()
                except Exception as e:
                    logger.warning(f"Error closing HTTP session for login {login_id}: {e}")

                del self.active_sessions[login_id]
                logger.info(f"Cleaned up session for login {login_id}")

    async def cleanup_all_sessions(self):
        """Cleanup all active sessions."""
        async with self.session_lock:
            for login_id in list(self.active_sessions.keys()):
                context = self.active_sessions[login_id]
                try:
                    await context.aiohttp_session.close()
                except Exception as e:
                    logger.warning(f"Error closing HTTP session for login {login_id}: {e}")

            self.active_sessions.clear()
            logger.info("Cleaned up all active scraping sessions")
