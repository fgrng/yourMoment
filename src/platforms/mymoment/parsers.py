"""HTML parsers for myMoment pages."""

from __future__ import annotations

import copy
import logging
import re
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from src.utils.ids import is_number

logger = logging.getLogger(__name__)

# myMoment shows times as local wall-clock time without an offset.
MYMOMENT_TIMEZONE = ZoneInfo("Europe/Zurich")


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


def is_logged_in(soup: BeautifulSoup) -> bool:
    """Return True if the page shows the logout form of an authenticated user."""
    return soup.find("form", attrs={"action": "/accounts/logout/"}) is not None


def extract_login_csrf_token(soup: BeautifulSoup) -> Optional[str]:
    """Return the CSRF token of the login form, or None."""
    csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
    return csrf_input.get("value") if csrf_input else None


def parse_classroom_tabs(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    """
    Read the classroom tabs of the article index as (value, label) pairs.

    The value is the tab ID used as `?tab=`: "home" (own articles), "alle"
    or a numeric classroom ID.
    """
    tabs_nav = soup.find("ul", {"id": "pills-tab"})
    if not tabs_nav:
        logger.warning("No tabs navigation found on articles page")
        return []

    tabs = []
    for button in tabs_nav.find_all("button", {"role": "tab"}):
        target = button.get("data-bs-target", "")
        if target.startswith("#pills-"):
            tabs.append((target.removeprefix("#pills-"), button.get_text(strip=True)))
    return tabs


def parse_arrangement_options(soup: BeautifulSoup) -> List[Tuple[str, str]]:
    """
    Read the arrangements (Schreibaufgaben) of the article index filter as (value, label) pairs.

    The value is the arrangement ID used as `?aufgabe=`; the empty "Alle Aufgaben" entry is skipped.
    """
    select = soup.find("select", {"name": "aufgabe"})
    if not select:
        logger.warning("No arrangement filter found on articles page")
        return []

    return [
        (option["value"], option.get_text(strip=True))
        for option in select.find_all("option")
        if option.get("value")
    ]


def parse_article_list(soup: BeautifulSoup, classroom: str) -> List[Dict[str, Any]]:
    """
    Parse the article index for one classroom tab.

    Students see article cards, teachers a table. Each entry has `id`, `href`
    (as on the page, usually relative), `title`, `author`, `date`, `status`,
    `visibility`, `category_id` and `task_id` (None where the view lacks them).
    """
    tab_content = soup.find("div", {"id": f"pills-{classroom}"})
    if not tab_content:
        logger.warning(f"Tab '{classroom}' not found, falling back to whole page")
        tab_content = soup

    article_list = tab_content.select_one(':scope > div[class*="article-list"]')
    if article_list:
        entries = [
            _parse_article_card(card)
            for card in article_list.find_all("div", recursive=False)
        ]
    else:
        table = tab_content.find("table")
        rows = table.select("tbody tr") if table else []
        entries = [_parse_article_row(row) for row in rows]
    return [entry for entry in entries if entry is not None]


def _parse_article_card(card: Any) -> Optional[Dict[str, Any]]:
    """Parse one article card of the student view."""
    link = card.find("a")
    href = link.get("href", "") if link else ""
    article_id = _article_id_from_href(href)
    if not article_id:
        return None

    status = "Unknown"
    header = card.find("div", class_=re.compile(r"card-header\s+\w+"))
    if header:
        for class_name in header.get("class", []):
            if class_name in ["entwurf", "lehrpersonenkontrolle", "publiziert"]:
                status = class_name.capitalize()
                break

    # The card shows the category only as an image named after it (e.g. ueberzeugen.png)
    category_id = None
    image = card.select_one(".card-body img")
    if image and image.get("src"):
        slug = image["src"].rsplit("/", 1)[-1].split(".", 1)[0]
        category_id = _category_id_from_slug(slug)

    return {
        "id": article_id,
        "href": href,
        "title": _text(card.find("div", class_="article-title"), "Unknown Title"),
        "author": _text(card.find("div", class_="article-author"), "Unknown Author"),
        "date": _text(card.find("div", class_="article-date"), "Unknown Date"),
        "status": status,
        "visibility": _text(card.find("div", class_="article-classroom"), "Unknown"),
        "category_id": category_id,
        "task_id": None,
    }


def _parse_article_row(row: Any) -> Optional[Dict[str, Any]]:
    """Parse one table row of the teacher view: title, author, visibility, category, task, status, date."""
    cells = row.find_all("td")
    if len(cells) < 7:
        return None
    link = cells[0].find("a")
    href = link.get("href", "") if link else ""
    article_id = _article_id_from_href(href)
    if not article_id:
        return None

    return {
        "id": article_id,
        "href": href,
        "title": link.get_text(strip=True),
        "author": cells[1].get_text(strip=True),
        "date": cells[6].get_text(strip=True),
        "status": cells[5].get_text(strip=True),
        "visibility": cells[2].get_text(strip=True),
        "category_id": _lookup_id(CATEGORY_MAPPING, cells[3].get_text(strip=True)),
        "task_id": _lookup_id(TASK_MAPPING, cells[4].get_text(strip=True)),
    }


def parse_student_articles(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """
    Parse the article table of a student's dashboard.

    Each entry has `id`, `title`, `visibility`, `categories` (names as shown,
    an article may have several), `category_id` (only for exactly one known
    category), `status` and `last_modified` (None if the date cannot be read).
    The rows link to the edit page of the article.
    """
    articles_tab = soup.select_one("#pills-articles") or soup
    entries = []
    for row in articles_tab.select("table tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        link = cells[0].find("a")
        article_id = _article_id_from_href(link.get("href", "")) if link else None
        if not article_id:
            continue

        category_items = cells[2].find_all("li")
        if category_items:
            categories = [item.get_text(strip=True) for item in category_items]
        else:
            categories = (
                [cells[2].get_text(strip=True)] if cells[2].get_text(strip=True) else []
            )

        entries.append(
            {
                "id": article_id,
                "title": link.get_text(strip=True),
                "visibility": cells[1].get_text(strip=True),
                "categories": categories,
                "category_id": _lookup_id(CATEGORY_MAPPING, categories[0])
                if len(categories) == 1
                else None,
                "status": cells[3].get_text(strip=True),
                "last_modified": _parse_german_datetime(cells[4].get_text(strip=True)),
            }
        )
    return entries


def _parse_german_datetime(value: str) -> Optional[datetime]:
    """Parse "28.01.2026 um 09:24 Uhr" (myMoment local time) as UTC; None if the text has another form."""
    try:
        text = value.replace(" um ", " ").replace(" Uhr", "")
        local = datetime.strptime(text, "%d.%m.%Y %H:%M")  # noqa: DTZ007
    except ValueError:
        logger.debug(f"Could not parse myMoment date '{value}'")
        return None
    return local.replace(tzinfo=MYMOMENT_TIMEZONE).astimezone(UTC)


def _article_id_from_href(href: str) -> Optional[str]:
    """The numeric segment after /article/: links point to /article/<id>/, /article/<id>/edit/ or /article/edit/<id>/."""
    if "/article/" not in href:
        return None
    segments = href.split("/article/", 1)[1].split("/")
    return next((segment for segment in segments if is_number(segment)), None)


def _text(element: Any, default: str) -> str:
    return element.text.strip() if element else default


def _category_id_from_slug(slug: str) -> Optional[int]:
    """Category ID for an image file name: lower case, umlauts transcribed."""
    for category_id, name in CATEGORY_MAPPING.items():
        name = name.lower()
        for umlaut, transcription in (("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
            name = name.replace(umlaut, transcription)
        if name == slug:
            return category_id
    logger.debug(f"Category image '{slug}' not found in mapping")
    return None


def parse_article_detail(soup: BeautifulSoup, article_id: str) -> Dict[str, Any]:
    """
    Parse article detail page HTML.

    Args:
        soup: BeautifulSoup object of the article detail page
        article_id: Article ID

    Returns:
        Dictionary with extracted article content
    """
    # Extract title
    title = "Unknown Title"
    title_element = soup.find("h1")
    if title_element:
        title_text = title_element.text.strip()
        if " von " in title_text:
            title = title_text.split(" von ")[0].strip()
        else:
            title = title_text

    # Extract author
    author = "Unknown Author"
    if title_element and " von " in title_element.text:
        author = title_element.text.split(" von ")[1].strip()

    # Extract content
    content = ""
    content_elements = soup.select(".article .highlight-target p")
    if content_elements:
        content = "\n".join([el.text.strip() for el in content_elements])
    else:
        # Alternative: try text-to-speech area
        tts_element = soup.find("textarea", {"id": "text-to-speech"})
        if tts_element:
            content = tts_element.text.strip()

    # Extract full HTML content
    full_article_html_element = soup.find("div", class_="article")
    if full_article_html_element:
        # Create a copy to avoid modifying the original soup
        full_article_html_copy = copy.copy(full_article_html_element)
        # Remove textarea elements
        for textarea in full_article_html_copy.find_all("textarea"):
            textarea.decompose()
        full_article_html = str(full_article_html_copy)
    else:
        full_article_html = ""

    # Extract category and task IDs from detail page
    category_id, task_id = extract_category_and_task(soup)

    return {
        "id": article_id,
        "title": title,
        "author": author,
        "content": content,
        "full_html": full_article_html,
        "category_id": category_id,
        "task_id": task_id,
        "csrf_token": extract_comment_csrf_token(soup, article_id),
    }


def extract_comment_csrf_token(soup: BeautifulSoup, article_id: str) -> Optional[str]:
    """CSRF token of the article's comment form; None if the page offers no comment form."""
    comment_form = soup.find(
        "form", {"action": re.compile(f"/article/{re.escape(article_id)}/comment/")}
    )
    if not comment_form:
        # Try a more generic match if exact article_id doesn't match
        comment_form = soup.find(
            "form", {"action": re.compile(r"/article/\d+/comment/")}
        )
    if not comment_form:
        return None
    csrf_input = comment_form.find("input", {"name": "csrfmiddlewaretoken"})
    return csrf_input.get("value") if csrf_input else None


def extract_category_and_task(
    soup: BeautifulSoup,
) -> Tuple[Optional[int], Optional[int]]:
    """
    Extract category and task IDs from article detail page HTML.

    Looks for the social list items containing "Kategorie:" and "Aufgabe:".

    Example HTML:
    <ul class="social list-group list-group-horizontal">
        <li class="list-group-item">Kategorie: Anleiten</li>
        <li class="list-group-item">Aufgabe: Wo ist Hugo? (Anleitung schreiben)</li>
    </ul>

    Returns:
        Tuple of (category_id, task_id) or (None, None) if not found
    """
    category_id = None
    task_id = None

    for item in soup.find_all("li", class_="list-group-item"):
        text = item.get_text(strip=True)

        if text.startswith("Kategorie:"):
            category_name = text.replace("Kategorie:", "").strip()
            category_id = _lookup_id(CATEGORY_MAPPING, category_name)
        elif text.startswith("Aufgabe:"):
            task_name = text.replace("Aufgabe:", "").strip()
            task_id = _lookup_id(TASK_MAPPING, task_name)

    return category_id, task_id


def _lookup_id(mapping: Dict[int, str], name: str) -> Optional[int]:
    for mapped_id, mapped_name in mapping.items():
        if mapped_name == name:
            return mapped_id
    logger.debug(f"'{name}' not found in mapping")
    return None
