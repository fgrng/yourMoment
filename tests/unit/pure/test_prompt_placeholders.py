"""
Pure unit tests for prompt placeholder logic.

Tests placeholder extraction, validation, and rendering in PromptTemplate model
and placeholder definitions in src/services/prompt_placeholders.py.
"""

import pytest
from src.models.prompt_template import PromptTemplate
from src.services.prompt_placeholders import SUPPORTED_PLACEHOLDERS


def test_supported_placeholders_content():
    """Should have the expected core placeholders defined."""
    assert "article_title" in SUPPORTED_PLACEHOLDERS
    assert "article_content" in SUPPORTED_PLACEHOLDERS
    assert "article_author" in SUPPORTED_PLACEHOLDERS
    assert "article_raw_html" in SUPPORTED_PLACEHOLDERS


def test_extract_placeholders():
    """Should correctly extract placeholders from a template string."""
    template_text = "Hello {article_author}, welcome to {article_title}!"
    template = PromptTemplate(user_prompt_template=template_text)
    
    placeholders = template.extract_placeholders()
    assert set(placeholders) == {"article_author", "article_title"}


def test_extract_placeholders_empty():
    """Should return empty list if no placeholders are found."""
    template = PromptTemplate(user_prompt_template="No placeholders here.")
    assert template.extract_placeholders() == []


def test_validate_placeholders():
    """Should identify supported and unsupported placeholders."""
    template_text = "{article_title} by {article_author} and {unsupported_var}"
    template = PromptTemplate(user_prompt_template=template_text)
    
    validation = template.validate_placeholders()
    assert validation["article_title"] is True
    assert validation["article_author"] is True
    assert validation["unsupported_var"] is False


def test_render_prompt():
    """Should correctly replace placeholders with context values."""
    template_text = "Article: {article_title}\nAuthor: {article_author}"
    template = PromptTemplate(user_prompt_template=template_text)
    
    context = {
        "article_title": "My Test Article",
        "article_author": "Test Author"
    }
    
    rendered = template.render_prompt(context)
    assert rendered == "Article: My Test Article\nAuthor: Test Author"


def test_get_missing_context_keys():
    """Should identify which placeholders are missing from the context."""
    template_text = "{article_title} {article_author} {article_content}"
    template = PromptTemplate(user_prompt_template=template_text)
    
    context = {"article_title": "Title"}
    missing = template.get_missing_context_keys(context)
    
    assert set(missing) == {"article_author", "article_content"}


def test_is_valid_template():
    """Should validate a template based on content and placeholders."""
    # Valid template
    valid = PromptTemplate(
        system_prompt="System",
        user_prompt_template="Title: {article_title}",
        category="SYSTEM"
    )
    assert valid.is_valid_template() is True

    # Missing system prompt
    no_system = PromptTemplate(
        system_prompt="",
        user_prompt_template="{article_title}",
        category="SYSTEM"
    )
    assert no_system.is_valid_template() is False

    # Unsupported placeholder
    invalid_placeholder = PromptTemplate(
        system_prompt="System",
        user_prompt_template="{bogus_var}",
        category="SYSTEM"
    )
    assert invalid_placeholder.is_valid_template() is False
