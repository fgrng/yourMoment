"""HTML parsers for myMoment pages."""

from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, Optional, Tuple

from bs4 import BeautifulSoup

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


def is_logged_in(soup: BeautifulSoup) -> bool:
    """Return True if the page shows the logout form of an authenticated user."""
    return soup.find('form', attrs={'action': '/accounts/logout/'}) is not None


def extract_login_csrf_token(soup: BeautifulSoup) -> Optional[str]:
    """Return the CSRF token of the login form, or None."""
    csrf_input = soup.find('input', {'name': 'csrfmiddlewaretoken'})
    return csrf_input.get('value') if csrf_input else None


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
    full_article_html_element = soup.find('div', class_='article')
    if full_article_html_element:
        # Create a copy to avoid modifying the original soup
        full_article_html_copy = copy.copy(full_article_html_element)
        # Remove textarea elements
        for textarea in full_article_html_copy.find_all('textarea'):
            textarea.decompose()
        full_article_html = str(full_article_html_copy)
    else:
        full_article_html = ''

    # Extract category and task IDs from detail page
    category_id, task_id = extract_category_and_task(soup)

    # Extract CSRF token for commenting
    csrf_token = None
    comment_form = soup.find('form', {'action': re.compile(f'/article/{article_id}/comment/')})
    if not comment_form:
        # Try a more generic match if exact article_id doesn't match
        comment_form = soup.find('form', {'action': re.compile(r'/article/\d+/comment/')})

    if comment_form:
        csrf_input = comment_form.find('input', {'name': 'csrfmiddlewaretoken'})
        if csrf_input:
            csrf_token = csrf_input.get('value')

    return {
        'id': article_id,
        'title': title,
        'author': author,
        'content': content,
        'full_html': full_article_html,
        'category_id': category_id,
        'task_id': task_id,
        'csrf_token': csrf_token
    }


def extract_category_and_task(soup: BeautifulSoup) -> Tuple[Optional[int], Optional[int]]:
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

    for item in soup.find_all('li', class_='list-group-item'):
        text = item.get_text(strip=True)

        if text.startswith('Kategorie:'):
            category_name = text.replace('Kategorie:', '').strip()
            category_id = _lookup_id(CATEGORY_MAPPING, category_name)
        elif text.startswith('Aufgabe:'):
            task_name = text.replace('Aufgabe:', '').strip()
            task_id = _lookup_id(TASK_MAPPING, task_name)

    return category_id, task_id


def _lookup_id(mapping: Dict[int, str], name: str) -> Optional[int]:
    for mapped_id, mapped_name in mapping.items():
        if mapped_name == name:
            return mapped_id
    logger.debug(f"'{name}' not found in mapping")
    return None
