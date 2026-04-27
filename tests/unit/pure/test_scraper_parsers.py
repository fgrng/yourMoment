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


def test_parse_article_list_elements(scraper):
    """Should extract articles from an article list element."""
    html = load_html_fixture("articles_index.html")
    soup = BeautifulSoup(html, "html.parser")
    
    # Find the article list container
    article_list_element = soup.select_one('div[class*="article-list"]')
    assert article_list_element is not None
    
    articles = scraper._parse_article_list_elements(article_list_element, limit=5)
    
    assert len(articles) > 0
    assert len(articles) <= 5
    assert articles[0].id is not None
    assert articles[0].title is not None


def test_extract_article_metadata(scraper):
    """Should extract metadata from an article card."""
    html = load_html_fixture("articles_index.html")
    soup = BeautifulSoup(html, "html.parser")
    
    # Find the first article card
    card = soup.select_one('div[class*="article-list"] > div')
    assert card is not None
    
    metadata = scraper._extract_article_metadata(card)
    assert metadata is not None
    assert metadata.id is not None
    assert metadata.title is not None
    assert metadata.author is not None
    assert metadata.status in ["Entwurf", "Lehrpersonenkontrolle", "Publiziert", "Unknown"]


def test_extract_category_and_task_from_detail(scraper):
    """Should extract category and task IDs from articles_get.html fixture."""
    html = load_html_fixture("articles_get.html")
    soup = BeautifulSoup(html, "html.parser")
    
    category_id, task_id = scraper._extract_category_and_task_from_detail(soup)
    
    # Based on CATEGORY_MAPPING/TASK_MAPPING in scraper_service.py
    # and the content of articles_get.html
    # We expect these to be either None (if not found/mapped) or the correct ID.
    # articles_get.html typically has some category like "Erklären" (5) or "Anleiten" (4)
    assert category_id is not None or task_id is not None


def test_parse_article_detail(scraper):
    """Should extract article content and metadata from articles_get.html fixture."""
    html = load_html_fixture("articles_get.html")
    soup = BeautifulSoup(html, "html.parser")
    
    article_id = "3170"
    content = scraper._parse_article_detail(soup, article_id)
    
    assert content["id"] == article_id
    assert content["title"] != "Unknown Title"
    assert content["author"] != "Unknown Author"
    assert len(content["content"]) > 0
    assert "article" in content["full_html"]
    assert content["csrf_token"] is not None


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


def test_parse_article_table_elements(scraper):
    """Should extract articles from a teacher article table."""
    teacher_html = """
    <table>
        <tbody>
            <tr>
                <td><a href="/article/3170/">Title 1</a></td>
                <td>Author 1</td>
                <td>Class A</td>
                <td><ul><li>Category 1</li></ul></td>
                <td><ul><li>Task 1</li></ul></td>
                <td>Publiziert</td>
                <td>04.02.2026 um 18:04 Uhr</td>
            </tr>
        </tbody>
    </table>
    """
    soup = BeautifulSoup(teacher_html, "html.parser")
    table = soup.find('table')
    articles = scraper._parse_article_table_elements(table, limit=5)

    assert len(articles) == 1
    assert articles[0].id == "3170"
    assert articles[0].title == "Title 1"
    assert articles[0].author == "Author 1"
    assert articles[0].visibility == "Class A"
    assert articles[0].status == "Publiziert"
    assert articles[0].date == "04.02.2026 um 18:04 Uhr"
