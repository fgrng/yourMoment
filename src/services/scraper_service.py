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

logger = logging.getLogger(__name__)


# Category mapping: image keyword -> (category_id, category_name)
# Based on myMoment platform category options
CATEGORY_MAPPING = {
    "unterhalten": (9, "Unterhalten"),
    "informieren": (7, "Informieren"),
    "anleiten": (4, "Anleiten"),
    "berichten": (14, "Berichten"),
    "erklaeren": (5, "Erklären"),
    "fragen": (6, "Fragen"),
    "ueberzeugen": (8, "Überzeugen"),
    "sa-schaltplan": (12, "Schreibaufgabe: Schaltplan"),
    "sa-wegbeschreibung": (11, "Schreibaufgabe: Wegbeschreibung"),
    "sa-fiktionaler_dialog": (10, "Schreibaufgabe: Fiktionaler Dialog"),
    "sa-reisebericht": (13, "Schreibaufgabe: Reisebericht"),
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
    category_id: Optional[int]  # Changed from str to int
    category_name: Optional[str]
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
            connector = aiohttp.TCPConnector(limit=10)
            timeout = aiohttp.ClientTimeout(total=self.config.request_timeout)
            http_session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
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

            await self._rate_limit()
            async with context.aiohttp_session.get(login_url) as response:
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

            # Perform login
            await self._rate_limit()
            async with context.aiohttp_session.post(
                login_url,
                data=login_data,
                headers={
                    'Referer': login_url,
                    'Content-Type': 'application/x-www-form-urlencoded'
                }
            ) as response:
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

    async def _check_authentication_status(self, context: SessionContext) -> bool:
        """
        Check if a session is currently authenticated.

        Args:
            context: Session context to check

        Returns:
            True if authenticated
        """
        try:
            await self._rate_limit()
            async with context.aiohttp_session.get(f"{self.config.base_url}/") as response:
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
        limit: int = 20
    ) -> List[ArticleMetadata]:
        """
        Discover new articles from myMoment platform.

        Returns article metadata only (no full content). This method performs
        HTTP requests only and does NOT use the database session.

        Args:
            context: Authenticated session context
            tab: Which tab to scrape ('home', 'alle', or classroom ID)
            category: Optional category filter
            limit: Maximum number of articles to retrieve

        Returns:
            List of discovered articles (metadata only, no content)

        Raises:
            ScrapingError: If article discovery fails
        """
        try:
            if not context.is_authenticated:
                raise ScrapingError(f"Session not authenticated for login {context.login_id}")

            articles_url = f"{self.config.base_url}/articles/"

            logger.debug(f"Starting HTTP request to discover articles (login {context.login_id}, tab={tab})")
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
                post_cards = article_list.find_all('div', recursive=False)[:limit]

                for card in post_cards:
                    try:
                        article = self._extract_article_metadata(card)
                        if article:
                            articles.append(article)
                    except Exception as e:
                        logger.warning(f"Failed to extract article metadata: {e}")
                        continue

            context.last_activity = datetime.utcnow()
            logger.debug(f"HTTP request completed for article discovery (login {context.login_id})")
            logger.info(f"Discovered {len(articles)} articles for login {context.login_id}")

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

            # Extract category from image filename
            img_element = card_element.find('div', class_='card-body')
            img_element = img_element.find('img') if img_element else None
            img_url = img_element.get('src') if img_element else None

            # Not implemented yet
            category_id = None
            category_name = None

            if img_url:
                category_id, category_name = self._extract_category_from_image(img_url)

            return ArticleMetadata(
                id=post_id,
                title=title,
                author=author,
                date=date,
                status=status,
                category_id=category_id,
                category_name=category_name,
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
        highlight: Optional[str] = None
    ) -> bool:
        """
        Post a comment to an article.

        Args:
            context: Authenticated session context
            article_id: Article ID to comment on
            comment_content: Comment text (should include German AI prefix)
            highlight: Optional text to highlight in article

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
                    logger.info(f"Successfully posted comment to article {article_id} via login {context.login_id}")
                else:
                    logger.warning(f"Comment posting failed with status {response.status}")

                return success

        except Exception as e:
            logger.error(f"Failed to post comment to article {article_id}: {e}")
            raise ScrapingError(f"Comment posting failed: {e}")

    def _extract_category_from_image(self, img_url: str) -> Tuple[Optional[int], Optional[str]]:
        """
        Extract category ID and name from article image URL.

        The myMoment platform uses category keywords in image filenames
        to indicate the article category. For example:
        - /media/2025/2/14/unterhalten.png.1500x1500_q85_upscale.png -> (9, "Unterhalten")
        - /media/2025/2/14/sa-fiktionaler_dialog.png.1500x1500_q85_upscale.png -> (10, "Schreibaufgabe: Fiktionaler Dialog")

        Args:
            img_url: Image URL/path from article card

        Returns:
            Tuple of (category_id, category_name) or (None, None) if not found
        """
        if not img_url:
            return None, None

        # Extract filename from URL (handle both relative and absolute paths)
        # Example: /media/2025/2/14/unterhalten.png.1500x1500_q85_upscale.png
        filename = img_url.split('/')[-1]

        # Remove image processing suffixes (e.g., .1500x1500_q85_upscale.png)
        # Extract the base keyword (e.g., unterhalten, sa-fiktionaler_dialog)
        for keyword in CATEGORY_MAPPING.keys():
            if keyword in filename.lower():
                category_id, category_name = CATEGORY_MAPPING[keyword]
                logger.debug(f"Extracted category from image: {keyword} -> {category_id}: {category_name}")
                return category_id, category_name

        logger.debug(f"No category keyword found in image URL: {img_url}")
        return None, None

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
