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


def test_extract_article_id_from_url(scraper):
    """Should correctly extract article ID from various myMoment URLs."""
    assert scraper._extract_article_id_from_url("/article/edit/2695/") == 2695
    assert scraper._extract_article_id_from_url("/article/1234/") == 1234
    assert scraper._extract_article_id_from_url("https://host/article/999/") == 999
    assert scraper._extract_article_id_from_url("/invalid/url/") is None


def test_parse_german_datetime(scraper):
    """Should correctly parse German datetime strings from myMoment."""
    dt_str = "28.01.2026 um 09:24 Uhr"
    dt = scraper._parse_german_datetime(dt_str)
    assert dt.day == 28
    assert dt.month == 1
    assert dt.year == 2026
    assert dt.hour == 9
    assert dt.minute == 24


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


def test_parse_student_dashboard_articles(scraper):
    """Should parse articles from a student dashboard."""
    # The tracked HTML corpus does not currently include a dedicated student
    # dashboard page, so this parser contract uses a minimal inline fixture.
    minimal_dashboard_html = """
    <div id="pills-articles">
        <table>
            <tbody>
                <tr>
                    <td><a href="/article/edit/2695/">Test Article</a></td>
                    <td>3. Klasse</td>
                    <td><li>Unterhalten</li></td>
                    <td>Publiziert</td>
                    <td>28.01.2026 um 09:24 Uhr</td>
                </tr>
            </tbody>
        </table>
    </div>
    """
    soup = BeautifulSoup(minimal_dashboard_html, "html.parser")
    articles = scraper._parse_student_dashboard_articles(soup, student_id=123)
    
    assert len(articles) == 1
    assert articles[0].article_id == 2695
    assert articles[0].title == "Test Article"
    assert articles[0].status == "Publiziert"
    assert articles[0].category == "Unterhalten"
