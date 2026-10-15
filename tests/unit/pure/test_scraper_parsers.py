"""
Pure unit tests for scraper parsing logic.

Tests the parsing methods of ScraperService using static HTML fixtures
from tests/fixtures/myMoment_html/.
"""

import pytest
from bs4 import BeautifulSoup
from unittest.mock import MagicMock
from src.services.scraper_service import ScraperService
from tests.fixtures.loaders import load_html_fixture


@pytest.fixture
def scraper():
    """Return a ScraperService instance with a mocked DB session."""
    mock_db = MagicMock()
    return ScraperService(db_session=mock_db)


def test_parse_article_tabs(scraper):
    """Should extract tabs from articles_index.html fixture."""
    html = load_html_fixture("articles_index.html")
    soup = BeautifulSoup(html, "html.parser")
    
    tabs = scraper._parse_article_tabs(soup)
    
    assert len(tabs) >= 2
    # Expect "home" and "alle" tabs at least
    tab_ids = [t.id for t in tabs]
    assert "home" in tab_ids
    assert "alle" in tab_ids
    
    home_tab = next(t for t in tabs if t.id == "home")
    assert home_tab.tab_type == "home"
