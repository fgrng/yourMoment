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
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass
from contextlib import asynccontextmanager

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from src.models.mymoment_login import MyMomentLogin
from src.models.mymoment_session import MyMomentSession
from src.models.monitoring_process import MonitoringProcess
from src.services.mymoment_session_service import MyMomentSessionService
from src.services.mymoment_credentials_service import MyMomentCredentialsService
from src.config.settings import get_settings
from src.utils.url_sanitizer import sanitize_url, is_url_malformed

logger = logging.getLogger(__name__)


# Category mapping: category_id -> category_name
# Based on myMoment platform category options (7 core communication functions)
CATEGORY_MAPPING = {
    4: "Anleiten",
    14: "Berichten",
    5: "Erklären",
    6: "Fragen",
    7: "Informieren",
    8: "Überzeugen",
    9: "Unterhalten",
}

# Task mapping: task_id -> task_name
# Separate from categories in the new myMoment platform structure
# Tasks are writing assignments (Schreibaufgaben) that can be filtered independently
TASK_MAPPING = {
    4: "Fiktionaler Dialog zwischen zwei Gegenständen",
    10: "Wo ist Hugo? (Anleitung schreiben)",
    # Additional tasks will be added as they are discovered
}


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
    category_id: Optional[int]  # Category ID only, name can be looked up from CATEGORY_MAPPING
    task_id: Optional[int]  # Task ID only, name can be looked up from TASK_MAPPING
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

    async def initialize_sessions_for_process(
        self,
        process_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> List[SessionContext]:
        """
        Initialize scraping sessions for all logins associated with a monitoring process.

        Args:
            process_id: Monitoring process ID
            user_id: User ID for validation

        Returns:
            List of initialized session contexts

        Raises:
            ScrapingError: If session initialization fails
        """
        try:
            from src.models.monitoring_process_login import MonitoringProcessLogin

            # Get monitoring process to verify it exists and belongs to user
            stmt = select(MonitoringProcess).where(
                and_(
                    MonitoringProcess.id == process_id,
                    MonitoringProcess.user_id == user_id
                )
            )
            result = await self.db_session.execute(stmt)
            process = result.scalar_one_or_none()

            if not process:
                raise ScrapingError(f"Monitoring process {process_id} not found for user {user_id}")

            # Query junction table directly to get login IDs (avoid lazy loading)
            login_stmt = select(MonitoringProcessLogin.mymoment_login_id).where(
                and_(
                    MonitoringProcessLogin.monitoring_process_id == process_id,
                    MonitoringProcessLogin.is_active == True
                )
            )
            login_result = await self.db_session.execute(login_stmt)
            login_ids = [row[0] for row in login_result.all()]

            if not login_ids:
                raise ScrapingError(f"No active myMoment logins configured for process {process_id}")

            logger.info(f"Initializing {len(login_ids)} sessions for process {process_id}")

            # Initialize sessions for each login
            session_contexts = []
            for login_id in login_ids:
                try:
                    context = await self._initialize_single_session(login_id, user_id)
                    session_contexts.append(context)
                    logger.info(f"Initialized session for login {login_id}")
                except Exception as e:
                    logger.error(f"Failed to initialize session for login {login_id}: {e}")
                    # Continue with other sessions - partial success is acceptable

            if not session_contexts:
                raise ScrapingError("Failed to initialize any sessions for the monitoring process")

            logger.info(f"Successfully initialized {len(session_contexts)} sessions for process {process_id}")
            return session_contexts

        except Exception as e:
            logger.error(f"Failed to initialize sessions for process {process_id}: {e}")
            # Cleanup any partially created sessions
            await self.cleanup_all_sessions()
            raise ScrapingError(f"Session initialization failed: {e}")

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

            # Attempt authentication
            await self._authenticate_session(context)

            return context

        except Exception as e:
            logger.error(f"Failed to initialize session for login {login_id}: {e}")
            raise SessionError(f"Session initialization failed: {e}")

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

                # Update session record
                await self.session_service.touch_session(context.session_id)

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

            # Find the specified tab
            tab_id = f"pills-{tab}"
            tab_content = soup.find('div', {'id': tab_id})

            if not tab_content:
                logger.warning(f"Tab '{tab}' not found, falling back to default")
                tab_content = soup

            articles = []

            # Extract article cards
            article_list = tab_content.select_one(':scope > div[class*="article-list"]')
            if article_list:
                post_cards = article_list.find_all('div', recursive=False)

                for card in post_cards:
                    # Stop when we reach the limit
                    if len(articles) >= limit:
                        break

                    try:
                        article = self._extract_article_metadata(card)
                        if article:
                            # Server-side filtering via URL params handles category and task filters
                            # We only apply client-side search filter if specified
                            should_include = True

                            # Apply search filter if specified
                            if search:
                                search_lower = search.lower()
                                title_lower = article.title.lower() if article.title else ""
                                if search_lower not in title_lower:
                                    should_include = False

                            if should_include:
                                articles.append(article)
                                logger.debug(f"Article {article.id} ('{article.title}') included in results")
                            else:
                                logger.debug(f"Article {article.id} ('{article.title}') filtered out (search filter)")

                    except Exception as e:
                        logger.warning(f"Failed to extract article metadata: {e}")
                        continue

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

            context.last_activity = datetime.utcnow()
            logger.info(f"Discovered {len(tabs)} tabs for login {context.login_id}")

            return tabs

        except Exception as e:
            logger.error(f"Failed to discover tabs for login {context.login_id}: {e}")
            raise ScrapingError(f"Tab discovery failed: {e}")

    def _extract_article_metadata(self, card_element) -> Optional[ArticleMetadata]:
        """
        Extract article metadata from HTML card element.

        Args:
            card_element: BeautifulSoup element containing article card

        Returns:
            ArticleMetadata object or None if extraction fails
        """
        try:
            # Extract link and ID
            link_element = card_element.find('a')
            if not link_element:
                return None

            href = link_element.get('href', '')
            post_id = None

            if '/article/' in href:
                post_id = href.strip('/').split('/')[-1]
            elif '/article/edit/' in href:
                post_id = href.strip('/').split('/')[-1]

            if not post_id:
                return None

            # Extract title
            title_element = card_element.find('div', class_='article-title')
            title = title_element.text.strip() if title_element else 'Unknown Title'

            # Extract author
            author_element = card_element.find('div', class_='article-author')
            author = author_element.text.strip() if author_element else 'Unknown Author'

            # Extract date
            date_element = card_element.find('div', class_='article-date')
            date = date_element.text.strip() if date_element else 'Unknown Date'

            # Extract status
            status_element = card_element.find('div', class_=re.compile(r'card-header\s+\w+'))
            status = 'Unknown'
            if status_element:
                for class_name in status_element.get('class', []):
                    if class_name in ['entwurf', 'lehrpersonenkontrolle', 'publiziert']:
                        status = class_name.capitalize()
                        break

            # Extract visibility
            visibility_element = card_element.find('div', class_='article-classroom')
            visibility = visibility_element.text.strip() if visibility_element else 'Unknown'

            # Category and Task IDs cannot be reliably extracted from article cards in the index view
            # We rely on server-side filtering via URL parameters (?kategorie=X&aufgabe=Y)
            # Image-based category extraction is deprecated and inconsistent with task behavior
            # Both remain None here and are determined via server-side filtering
            category_id = None
            task_id = None

            return ArticleMetadata(
                id=post_id,
                title=title,
                author=author,
                date=date,
                status=status,
                category_id=category_id,
                task_id=task_id,
                visibility=visibility,
                url=f"{self.config.base_url}{href}" if href.startswith('/') else href
            )

        except Exception as e:
            logger.warning(f"Failed to extract article metadata: {e}")
            return None

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

            # Extract title
            title = 'Unknown Title'
            title_element = soup.find('h1')
            if title_element:
                title_text = title_element.text.strip()
                if ' von ' in title_text:
                    title = title_text.split(' von ')[0].strip()
                else:
                    title = title_text

            # Extract author
            author = 'Unknown Author'
            if title_element and ' von ' in title_element.text:
                author = title_element.text.split(' von ')[1].strip()

            # Extract content
            content = ''
            content_elements = soup.select('.article .highlight-target p')
            if content_elements:
                content = '\n'.join([el.text.strip() for el in content_elements])
            else:
                # Alternative: try text-to-speech area
                tts_element = soup.find('textarea', {'id': 'text-to-speech'})
                if tts_element:
                    content = tts_element.text.strip()

            # Extract full HTML content
            full_article_html = soup.find('div', class_='article')
            if full_article_html:
                # Remove textarea elements
                for textarea in full_article_html.find_all('textarea'):
                    textarea.decompose()
                full_article_html = str(full_article_html)
            else:
                full_article_html = ''

            # Extract category and task IDs from detail page
            category_id, task_id = self._extract_category_and_task_from_detail(soup)

            # Extract CSRF token for commenting
            csrf_token = None
            comment_form = soup.find('form', {'action': re.compile(r'/article/\d+/comment/')})
            if comment_form:
                csrf_input = comment_form.find('input', {'name': 'csrfmiddlewaretoken'})
                if csrf_input:
                    csrf_token = csrf_input.get('value')

            context.last_activity = datetime.utcnow()
            logger.debug(f"HTTP request completed for article content (article_id={article_id}, login={context.login_id})")

            return {
                'id': article_id,
                'title': title,
                'author': author,
                'content': content,
                'full_html': full_article_html,
                'category_id': category_id,
                'task_id': task_id,
                'csrf_token': csrf_token,
                'url': article_url
            }

        except Exception as e:
            logger.error(f"Failed to get article content for {article_id}: {e}")
            raise ScrapingError(f"Article content retrieval failed: {e}")

    async def post_comment(
        self,
        context: SessionContext,
        article_id: str,
        comment_content: str,
        highlight: Optional[str] = None,
        hide_comment: bool = False
    ) -> bool:
        """
        Post a comment to an article.

        Args:
            context: Authenticated session context
            article_id: Article ID to comment on
            comment_content: Comment text (should include German AI prefix)
            highlight: Optional text to highlight in article
            hide_comment: Whether to hide the comment on myMoment (default: False)

        Returns:
            True if comment posted successfully

        Raises:
            ScrapingError: If comment posting fails
        """
        try:
            if not context.is_authenticated:
                raise ScrapingError(f"Session not authenticated for login {context.login_id}")

            # Ensure German AI prefix is included (FR-006)
            settings = get_settings()
            ai_prefix = settings.monitoring.AI_COMMENT_PREFIX
            if not comment_content.startswith(ai_prefix):
                comment_content = f"{ai_prefix} {comment_content}"

            # Get article to obtain CSRF token
            article_content = await self.get_article_content(context, article_id)
            if not article_content or not article_content.get('csrf_token'):
                raise ScrapingError(f"Could not get CSRF token for article {article_id}")

            comment_url = f"{self.config.base_url}/article/{article_id}/comment/"

            comment_data = {
                'csrfmiddlewaretoken': article_content['csrf_token'],
                'text': comment_content,
                'status': '20',  # Published
                'highlight': highlight or ''
            }

            # Add hide parameter if requested
            if hide_comment:
                comment_data['hide'] = 'on'

            logger.debug(f"Starting HTTP request to post comment (article_id={article_id}, login={context.login_id})")
            await self._rate_limit()
            async with context.aiohttp_session.post(
                comment_url,
                data=comment_data,
                headers={
                    'Referer': article_content['url'],
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            ) as response:
                success = response.status in [200, 302]

                logger.debug(f"HTTP request completed for post comment (article_id={article_id}, login={context.login_id}, status={response.status})")
                if success:
                    context.last_activity = datetime.utcnow()
                    logger.info(f"Successfully posted comment to article {article_id} via login {context.login_id} (hidden={hide_comment})")
                else:
                    logger.warning(f"Comment posting failed with status {response.status}")

                return success

        except Exception as e:
            logger.error(f"Failed to post comment to article {article_id}: {e}")
            raise ScrapingError(f"Comment posting failed: {e}")

    def _lookup_category_id(self, category_name: str) -> Optional[int]:
        """
        Look up category ID by name from CATEGORY_MAPPING.

        Args:
            category_name: Category name extracted from HTML (e.g., "Anleiten")

        Returns:
            Category ID or None if not found
        """
        for cat_id, cat_name in CATEGORY_MAPPING.items():
            if cat_name == category_name:
                return cat_id
        logger.debug(f"Category '{category_name}' not found in CATEGORY_MAPPING")
        return None

    def _lookup_task_id(self, task_name: str) -> Optional[int]:
        """
        Look up task ID by name from TASK_MAPPING.

        Args:
            task_name: Task name extracted from HTML (e.g., "Wo ist Hugo? (Anleitung schreiben)")

        Returns:
            Task ID or None if not found
        """
        for task_id, t_name in TASK_MAPPING.items():
            if t_name == task_name:
                return task_id
        logger.debug(f"Task '{task_name}' not found in TASK_MAPPING")
        return None

    def _extract_category_and_task_from_detail(self, soup: BeautifulSoup) -> Tuple[Optional[int], Optional[int]]:
        """
        Extract category and task IDs from article detail page HTML.

        Looks for the social list items containing "Kategorie:" and "Aufgabe:".

        Example HTML:
        <ul class="social list-group list-group-horizontal">
            <li class="list-group-item">Kategorie: Anleiten</li>
            <li class="list-group-item">Aufgabe: Wo ist Hugo? (Anleitung schreiben)</li>
        </ul>

        Args:
            soup: BeautifulSoup object of the article detail page

        Returns:
            Tuple of (category_id, task_id) or (None, None) if not found
        """
        category_id = None
        task_id = None

        # Find all list items in social list groups
        list_items = soup.find_all('li', class_='list-group-item')

        for item in list_items:
            text = item.get_text(strip=True)

            # Extract category
            if text.startswith('Kategorie:'):
                category_name = text.replace('Kategorie:', '').strip()
                category_id = self._lookup_category_id(category_name)
                if category_id:
                    logger.debug(f"Extracted category from detail: {category_name} -> {category_id}")

            # Extract task
            elif text.startswith('Aufgabe:'):
                task_name = text.replace('Aufgabe:', '').strip()
                task_id = self._lookup_task_id(task_name)
                if task_id:
                    logger.debug(f"Extracted task from detail: {task_name} -> {task_id}")

        return category_id, task_id

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

    async def get_session_status(self) -> Dict[str, Any]:
        """
        Get status of all active sessions.

        Returns:
            Dictionary with session status information
        """
        async with self.session_lock:
            status = {
                'total_sessions': len(self.active_sessions),
                'authenticated_sessions': sum(1 for ctx in self.active_sessions.values() if ctx.is_authenticated),
                'sessions': []
            }

            for login_id, context in self.active_sessions.items():
                session_info = {
                    'login_id': str(login_id),
                    'session_id': str(context.session_id),
                    'username': context.username,
                    'is_authenticated': context.is_authenticated,
                    'last_activity': context.last_activity.isoformat() if context.last_activity else None
                }
                status['sessions'].append(session_info)

            return status
