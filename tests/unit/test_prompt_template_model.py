"""Unit tests for PromptTemplate model behavior."""

import uuid

from src.models.prompt_template import PromptTemplate


class TestPromptTemplate:
    """Tests covering placeholder utilities."""

    def _create_template(self, **overrides) -> PromptTemplate:
        defaults = {
            "id": uuid.uuid4(),
            "name": "Friendly",
            "system_prompt": "You are helpful.",
            "user_prompt_template": "Hello {article_title}",
            "category": "USER",
            "user_id": uuid.uuid4(),
            "is_active": True,
        }
        defaults.update(overrides)
        return PromptTemplate(**defaults)

    def test_category_helpers(self):
        system_template = self._create_template(category="SYSTEM", user_id=None)
        user_template = self._create_template(category="USER")

        assert system_template.is_system_template is True
        assert system_template.is_user_template is False
        assert user_template.is_system_template is False
        assert user_template.is_user_template is True

    def test_extract_placeholders_deduplicates(self):
        template = self._create_template(user_prompt_template="Title: {article_title} and {article_title}")

        placeholders = template.extract_placeholders()

        assert placeholders == ["article_title"]

    def test_validate_placeholders_marks_supported_and_unknown(self):
        template = self._create_template(user_prompt_template="{article_title} {unknown_placeholder}")

        validation = template.validate_placeholders()

        assert validation["article_title"] is True
        assert validation["unknown_placeholder"] is False

    def test_is_valid_template_checks_content_and_placeholders(self):
        template = self._create_template(user_prompt_template="{article_title}")
        assert template.is_valid_template() is True

        invalid = self._create_template(user_prompt_template="{unsupported}")
        assert invalid.is_valid_template() is False

        missing_content = self._create_template(system_prompt="", user_prompt_template="{article_title}")
        assert missing_content.is_valid_template() is False

    def test_render_prompt_substitutes_values(self):
        template = self._create_template(user_prompt_template="Article: {article_title} by {article_author}")

        rendered = template.render_prompt({
            "article_title": "Example",
            "article_author": "Author",
        })

        assert rendered == "Article: Example by Author"

    def test_get_missing_context_keys(self):
        template = self._create_template(user_prompt_template="{article_title} {article_author}")

        missing = template.get_missing_context_keys({"article_title": "Example"})

        assert missing == ["article_author"]
