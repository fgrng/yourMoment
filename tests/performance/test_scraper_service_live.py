"""
Performance tests for ScraperService with live myMoment platform integration.

These tests require:
1. ENABLE_LIVE_SCRAPER_TESTS=1 environment variable
2. Valid myMoment credentials (MYMOMENT_TEST_USERNAME/MYMOMENT_TEST_PASSWORD)
3. Network access to myMoment platform

Run with: ENABLE_LIVE_SCRAPER_TESTS=1 pytest tests/performance/test_scraper_service_live.py -v
"""

import os
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import aiohttp
import pytest

from src.services.scraper_service import ScraperService, SessionContext


class FakeCredentials:
    """Mock credentials object matching myMomentLogin interface."""

    def __init__(self, username: str, password: str):
        self.username = username
        self._password = password

    def get_credentials(self) -> tuple[str, str]:
        """Return decrypted credentials tuple."""
        return self.username, self._password


@pytest.mark.asyncio
@pytest.mark.performance
@pytest.mark.external_api
@pytest.mark.web_scraping
async def test_scraper_service_live_performance(
    mymoment_test_credentials: dict,
    venv_dir: Path,
    test_env_override: dict,
):
    """
    Test scraper service performance with real myMoment platform.

    This test:
    1. Authenticates with myMoment using real credentials
    2. Discovers articles from the platform
    3. Fetches article content
    4. Validates performance (< 15 seconds for all operations)

    Requirements:
    - ENABLE_LIVE_SCRAPER_TESTS=1
    - MYMOMENT_TEST_USERNAME and MYMOMENT_TEST_PASSWORD
    - Active internet connection
    """
    if os.getenv("ENABLE_LIVE_SCRAPER_TESTS") != "1":
        pytest.skip(
            "Live scraper tests disabled. Set ENABLE_LIVE_SCRAPER_TESTS=1 to enable. "
            "Also requires MYMOMENT_TEST_USERNAME and MYMOMENT_TEST_PASSWORD."
        )

    # Override environment for live testing
    test_env_override["MYMOMENT_BASE_URL"] = "https://new.mymoment.ch"
    test_env_override["MYMOMENT_TIMEOUT"] = "30"
    test_env_override["SCRAPING_RATE_LIMIT"] = "0.5"

    username = mymoment_test_credentials["username"]
    password = mymoment_test_credentials["password"]

    # Initialize scraper service
    service = ScraperService(db_session=None)
    service.config.rate_limit_delay = 0.5

    # Mock credential and session services
    credentials = FakeCredentials(username, password)
    service.credentials_service.get_credentials_by_id = AsyncMock(return_value=credentials)
    service.session_service.get_or_create_session = AsyncMock(
        return_value=type("Session", (), {"id": uuid.uuid4()})()
    )
    service.session_service.touch_session = AsyncMock()

    # Configure HTTP session with reasonable timeouts
    connector = aiohttp.TCPConnector(limit=10)
    timeout = aiohttp.ClientTimeout(total=service.config.request_timeout)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as http_session:
        context = SessionContext(
            login_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            username=username,
            aiohttp_session=http_session,
            csrf_token=None,
            last_activity=None,
            is_authenticated=False,
        )

        # Start performance measurement
        start_time = time.perf_counter()

        # Test 1: Authentication
        auth_start = time.perf_counter()
        auth_ok = await service._authenticate_session(context)
        auth_elapsed = time.perf_counter() - auth_start

        assert auth_ok is True, "Authentication with myMoment failed"
        assert auth_elapsed < 10, f"Authentication took too long: {auth_elapsed:.2f}s"

        # Test 2: Article Discovery
        discover_start = time.perf_counter()
        articles = await service.discover_new_articles(context, tab="alle", limit=10)
        discover_elapsed = time.perf_counter() - discover_start

        assert articles, "No articles discovered from myMoment"
        assert len(articles) > 0, "Expected at least 1 article"
        assert discover_elapsed < 8, f"Article discovery took too long: {discover_elapsed:.2f}s"

        # Test 3: Article Content Fetch
        fetch_start = time.perf_counter()
        article = await service.get_article_content(context, article_id=articles[0].id)
        fetch_elapsed = time.perf_counter() - fetch_start

        assert article, "Failed to fetch article content"
        assert article["title"], "Article has no title"
        assert article["content"], "Article has no content"
        assert article["csrf_token"], "Article has no CSRF token"
        assert fetch_elapsed < 5, f"Article fetch took too long: {fetch_elapsed:.2f}s"

        # Overall performance check
        total_elapsed = time.perf_counter() - start_time

        assert total_elapsed < 15, (
            f"Total scraper operations took too long: {total_elapsed:.2f}s "
            f"(auth: {auth_elapsed:.2f}s, discover: {discover_elapsed:.2f}s, "
            f"fetch: {fetch_elapsed:.2f}s)"
        )

        # Log performance metrics for monitoring
        print(f"\n✓ Performance metrics:")
        print(f"  Authentication: {auth_elapsed:.2f}s")
        print(f"  Article discovery: {discover_elapsed:.2f}s ({len(articles)} articles)")
        print(f"  Article fetch: {fetch_elapsed:.2f}s")
        print(f"  Total: {total_elapsed:.2f}s")

    # Cleanup
    await service.cleanup_all_sessions()
