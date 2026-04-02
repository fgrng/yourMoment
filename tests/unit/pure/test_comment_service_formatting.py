"""
Pure unit tests for comment service formatting logic.

Tests ensure_html_paragraphs and validate_comment functions from
src/services/comment_service.py.
"""

import pytest
from src.services.comment_service import ensure_html_paragraphs, validate_comment
from unittest.mock import MagicMock, patch


def test_ensure_html_paragraphs_already_has_p():
    """Should return text as-is if it already contains <p> tags."""
    text = "<p>Existing paragraph.</p>"
    assert ensure_html_paragraphs(text) == text

    text_mixed_case = "<P>Mixed case paragraph.</P>"
    assert ensure_html_paragraphs(text_mixed_case) == text_mixed_case


def test_ensure_html_paragraphs_converts_newlines():
    """Should wrap blocks of text in <p> tags."""
    text = "First paragraph.\n\nSecond paragraph."
    expected = "<p>First paragraph.</p><p>Second paragraph.</p>"
    assert ensure_html_paragraphs(text) == expected


def test_ensure_html_paragraphs_single_newline():
    """Should treat single newlines as paragraph breaks (current implementation)."""
    text = "Line 1.\nLine 2."
    expected = "<p>Line 1.</p><p>Line 2.</p>"
    assert ensure_html_paragraphs(text) == expected


def test_ensure_html_paragraphs_trims_whitespace():
    """Should trim leading/trailing whitespace before wrapping."""
    text = "  Leading and trailing.  "
    expected = "<p>Leading and trailing.</p>"
    assert ensure_html_paragraphs(text) == expected


def test_ensure_html_paragraphs_empty_input():
    """Should return empty input as-is."""
    assert ensure_html_paragraphs("") == ""
    assert ensure_html_paragraphs(None) is None


@patch("src.services.comment_service.get_settings")
def test_validate_comment_valid(mock_get_settings):
    """Should validate a correct comment with prefix and length."""
    mock_settings = MagicMock()
    mock_settings.monitoring.AI_COMMENT_PREFIX = "[KI]"
    mock_settings.monitoring.COMMENT_MIN_LENGTH = 10
    mock_settings.monitoring.COMMENT_MAX_LENGTH = 100
    mock_get_settings.return_value = mock_settings

    comment = "[KI] This is a valid comment with enough length."
    result = validate_comment(comment)

    assert result["is_valid"] is True
    assert result["has_ai_prefix"] is True
    assert not result["errors"]
    assert result["content_length"] > 10


@patch("src.services.comment_service.get_settings")
def test_validate_comment_missing_prefix(mock_get_settings):
    """Should fail if the AI prefix is missing."""
    mock_settings = MagicMock()
    mock_settings.monitoring.AI_COMMENT_PREFIX = "[KI]"
    mock_settings.monitoring.COMMENT_MIN_LENGTH = 5
    mock_settings.monitoring.COMMENT_MAX_LENGTH = 100
    mock_get_settings.return_value = mock_settings

    comment = "This comment has no prefix."
    result = validate_comment(comment)

    assert result["is_valid"] is False
    assert result["has_ai_prefix"] is False
    assert "Missing required German AI prefix" in result["errors"]


@patch("src.services.comment_service.get_settings")
def test_validate_comment_too_short(mock_get_settings):
    """Should fail if the comment content is too short."""
    mock_settings = MagicMock()
    mock_settings.monitoring.AI_COMMENT_PREFIX = "[KI]"
    mock_settings.monitoring.COMMENT_MIN_LENGTH = 50
    mock_settings.monitoring.COMMENT_MAX_LENGTH = 100
    mock_get_settings.return_value = mock_settings

    comment = "[KI] Too short."
    result = validate_comment(comment)

    assert result["is_valid"] is False
    assert any("too short" in e.lower() for e in result["errors"])


@patch("src.services.comment_service.get_settings")
def test_validate_comment_repetitive(mock_get_settings):
    """Should fail if the comment is repetitive (if content validation enabled)."""
    mock_settings = MagicMock()
    mock_settings.monitoring.AI_COMMENT_PREFIX = "[KI]"
    mock_settings.monitoring.COMMENT_MIN_LENGTH = 5
    mock_settings.monitoring.COMMENT_MAX_LENGTH = 500
    mock_get_settings.return_value = mock_settings

    # Repetitive comment: more than 5 words and unique words < 50%
    comment = "[KI] Word word word word word word word word word word."
    result = validate_comment(comment, enable_content_validation=True)

    assert result["is_valid"] is False
    assert "Comment appears to be repetitive" in result["errors"]


@patch("src.services.comment_service.get_settings")
def test_validate_comment_unresolved_placeholders(mock_get_settings):
    """Should fail if the comment contains unresolved placeholders."""
    mock_settings = MagicMock()
    mock_settings.monitoring.AI_COMMENT_PREFIX = "[KI]"
    mock_settings.monitoring.COMMENT_MIN_LENGTH = 5
    mock_settings.monitoring.COMMENT_MAX_LENGTH = 500
    mock_get_settings.return_value = mock_settings

    comment = "[KI] Hello {article_author}, great article!"
    result = validate_comment(comment, enable_content_validation=True)

    assert result["is_valid"] is False
    assert "Comment contains unresolved placeholders" in result["errors"]
