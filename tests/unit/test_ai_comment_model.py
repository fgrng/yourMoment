"""
Unit tests for AIComment model.

Tests model creation, validation, business logic methods, and property accessors.
"""

import uuid
from datetime import datetime, timedelta

import pytest

from src.models.ai_comment import AIComment


class TestAICommentModel:
    """Test AIComment model creation and basic operations."""

    def test_create_ai_comment_minimal(self):
        """Test creating AIComment with minimal required fields."""
        user_id = uuid.uuid4()

        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=user_id,
            article_title="Test Article",
            article_author="Test Author",
            article_content="Test content",
            article_raw_html="<p>Test HTML</p>",
            article_url="https://new.mymoment.ch/article/12345/",
            article_scraped_at=datetime.utcnow(),
            comment_content="[Dieser Kommentar stammt von einem KI-ChatBot.] Test comment",
        )

        assert ai_comment.mymoment_article_id == "12345"
        assert ai_comment.user_id == user_id
        assert ai_comment.article_title == "Test Article"
        assert ai_comment.comment_content.startswith("[Dieser Kommentar stammt von einem KI-ChatBot.]")
        assert ai_comment.status == "generated"  # Default status
        assert ai_comment.is_active is True  # Default active

    def test_create_ai_comment_full(self):
        """Test creating AIComment with all fields populated."""
        user_id = uuid.uuid4()
        login_id = uuid.uuid4()
        process_id = uuid.uuid4()
        template_id = uuid.uuid4()
        provider_id = uuid.uuid4()

        now = datetime.utcnow()

        ai_comment = AIComment(
            # IDs
            mymoment_article_id="12345",
            mymoment_comment_id="67890",
            user_id=user_id,
            mymoment_login_id=login_id,
            monitoring_process_id=process_id,
            prompt_template_id=template_id,
            llm_provider_id=provider_id,

            # Article snapshot
            article_title="Full Article Title",
            article_author="Full Author",
            article_category=5,
            article_url="https://new.mymoment.ch/article/12345/",
            article_content="Full article content here",
            article_raw_html="<div><p>Full HTML</p></div>",
            article_published_at=now - timedelta(days=7),
            article_edited_at=now - timedelta(days=1),
            article_scraped_at=now,
            article_tags="tag1,tag2,tag3",
            article_metadata={"custom": "metadata"},

            # Comment
            comment_content="[Dieser Kommentar stammt von einem KI-ChatBot.] Full comment",
            status="posted",
            ai_model_name="gpt-4",
            ai_provider_name="openai",
            generation_tokens=150,
            generation_time_ms=1500,

            # Timestamps
            created_at=now,
            posted_at=now,

            # Status
            is_active=True
        )

        # Verify all fields
        assert ai_comment.mymoment_article_id == "12345"
        assert ai_comment.mymoment_comment_id == "67890"
        assert ai_comment.user_id == user_id
        assert ai_comment.article_category == 5
        assert ai_comment.article_tags == "tag1,tag2,tag3"
        assert ai_comment.article_metadata == {"custom": "metadata"}
        assert ai_comment.ai_model_name == "gpt-4"
        assert ai_comment.ai_provider_name == "openai"
        assert ai_comment.generation_tokens == 150
        assert ai_comment.generation_time_ms == 1500
        assert ai_comment.status == "posted"


class TestAICommentProperties:
    """Test AIComment computed properties."""

    def test_is_posted_property(self):
        """Test is_posted property for different statuses."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Test",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Comment",
            status="posted"
        )
        assert ai_comment.is_posted is True

        ai_comment.status = "generated"
        assert ai_comment.is_posted is False

        ai_comment.status = "failed"
        assert ai_comment.is_posted is False

    def test_is_failed_property(self):
        """Test is_failed property."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Test",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Comment",
            status="failed"
        )
        assert ai_comment.is_failed is True

        ai_comment.status = "posted"
        assert ai_comment.is_failed is False

    def test_is_generated_property(self):
        """Test is_generated property."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Test",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Comment",
            status="generated"
        )
        assert ai_comment.is_generated is True

        ai_comment.status = "posted"
        assert ai_comment.is_generated is False

    def test_has_valid_ai_prefix(self):
        """Test has_valid_ai_prefix property."""
        # Valid prefix
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Test",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="[Dieser Kommentar stammt von einem KI-ChatBot.] This is valid"
        )
        assert ai_comment.has_valid_ai_prefix is True

        # Invalid - no prefix
        ai_comment.comment_content = "This has no prefix"
        assert ai_comment.has_valid_ai_prefix is False

        # Invalid - wrong prefix
        ai_comment.comment_content = "[This is wrong.] Comment"
        assert ai_comment.has_valid_ai_prefix is False

    def test_short_title(self):
        """Test short_title property."""
        # Short title (under 100 chars)
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Short Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Comment"
        )
        assert ai_comment.short_title == "Short Title"

        # Long title (over 100 chars)
        long_title = "A" * 150
        ai_comment.article_title = long_title
        assert ai_comment.short_title == "A" * 97 + "..."
        assert len(ai_comment.short_title) == 100

    def test_short_content(self):
        """Test short_content property."""
        # Short content
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Short comment"
        )
        assert ai_comment.short_content == "Short comment"

        # Long content
        long_content = "X" * 300
        ai_comment.comment_content = long_content
        assert ai_comment.short_content == "X" * 197 + "..."
        assert len(ai_comment.short_content) == 200

    def test_posting_status_display(self):
        """Test posting_status_display property."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Comment",
            status="generated"
        )
        assert ai_comment.posting_status_display == "Generated (not posted)"

        ai_comment.status = "posted"
        assert ai_comment.posting_status_display == "Posted to myMoment"

        ai_comment.status = "failed"
        assert ai_comment.posting_status_display == "Posting failed"

        ai_comment.status = "deleted"
        assert ai_comment.posting_status_display == "Deleted"

    def test_article_tag_list(self):
        """Test article_tag_list property."""
        # No tags
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Comment"
        )
        assert ai_comment.article_tag_list == []

        # With tags
        ai_comment.article_tags = "fiction,story,creative"
        assert ai_comment.article_tag_list == ["fiction", "story", "creative"]

        # With extra spaces
        ai_comment.article_tags = "tag1 , tag2, tag3"
        assert ai_comment.article_tag_list == ["tag1", "tag2", "tag3"]

        # Empty tags
        ai_comment.article_tags = "tag1,,tag2"
        tag_list = ai_comment.article_tag_list
        assert "tag1" in tag_list
        assert "tag2" in tag_list
        assert "" not in tag_list


class TestAICommentMethods:
    """Test AIComment business logic methods."""

    def test_mark_as_posted(self):
        """Test mark_as_posted method."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="[Dieser Kommentar stammt von einem KI-ChatBot.] Comment",
            status="generated"
        )

        assert ai_comment.status == "generated"
        assert ai_comment.mymoment_comment_id is None
        assert ai_comment.posted_at is None

        # Mark as posted
        posted_time = datetime.utcnow()
        ai_comment.mark_as_posted("comment_67890", posted_time)

        assert ai_comment.status == "posted"
        assert ai_comment.mymoment_comment_id == "comment_67890"
        assert ai_comment.posted_at == posted_time
        assert ai_comment.error_message is None  # Cleared on success

    def test_mark_as_posted_default_timestamp(self):
        """Test mark_as_posted with default timestamp."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Comment",
            status="generated"
        )

        before = datetime.utcnow()
        ai_comment.mark_as_posted("comment_123")
        after = datetime.utcnow()

        assert ai_comment.status == "posted"
        assert ai_comment.posted_at is not None
        assert before <= ai_comment.posted_at <= after

    def test_mark_as_failed(self):
        """Test mark_as_failed method."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Comment",
            status="generated",
            retry_count=0
        )

        assert ai_comment.status == "generated"
        assert ai_comment.error_message is None
        assert ai_comment.retry_count == 0

        # Mark as failed
        failed_time = datetime.utcnow()
        ai_comment.mark_as_failed("Network timeout", failed_time)

        assert ai_comment.status == "failed"
        assert ai_comment.error_message == "Network timeout"
        assert ai_comment.failed_at == failed_time
        assert ai_comment.retry_count == 1

    def test_mark_as_failed_increments_retry_count(self):
        """Test that mark_as_failed increments retry counter."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Comment",
            retry_count=0
        )

        # First failure
        ai_comment.mark_as_failed("Error 1")
        assert ai_comment.retry_count == 1

        # Second failure
        ai_comment.mark_as_failed("Error 2")
        assert ai_comment.retry_count == 2

        # Third failure
        ai_comment.mark_as_failed("Error 3")
        assert ai_comment.retry_count == 3

    def test_validate_requirements_valid(self):
        """Test validate_requirements with valid comment."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            mymoment_login_id=uuid.uuid4(),
            monitoring_process_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="[Dieser Kommentar stammt von einem KI-ChatBot.] Valid comment",
            status="generated"
        )

        validation = ai_comment.validate_requirements()

        assert validation["is_valid"] is True
        assert validation["has_required_prefix"] is True
        assert validation["has_monitoring_process"] is True
        assert validation["content_not_empty"] is True
        assert validation["article_content_not_empty"] is True
        assert validation["article_title_not_empty"] is True

    def test_validate_requirements_missing_prefix(self):
        """Test validate_requirements with missing AI prefix."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            monitoring_process_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Missing prefix comment"
        )

        validation = ai_comment.validate_requirements()

        assert validation["is_valid"] is False
        assert validation["has_required_prefix"] is False

    def test_validate_requirements_missing_process(self):
        """Test validate_requirements with missing monitoring process."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="[Dieser Kommentar stammt von einem KI-ChatBot.] Comment"
        )

        validation = ai_comment.validate_requirements()

        assert validation["is_valid"] is False
        assert validation["has_monitoring_process"] is False

    def test_validate_requirements_posted_without_comment_id(self):
        """Test validate_requirements for posted comment without mymoment_comment_id."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            monitoring_process_id=uuid.uuid4(),
            mymoment_login_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="[Dieser Kommentar stammt von einem KI-ChatBot.] Comment",
            status="posted"
            # Missing mymoment_comment_id
        )

        validation = ai_comment.validate_requirements()

        assert validation["is_valid"] is False
        assert validation["has_comment_id_if_posted"] is False

    def test_to_article_snapshot_dict(self):
        """Test to_article_snapshot_dict method."""
        now = datetime.utcnow()

        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="Article Title",
            article_author="Article Author",
            article_category=5,
            article_url="https://new.mymoment.ch/article/12345/",
            article_content="Article content here",
            article_raw_html="<p>HTML</p>",
            article_published_at=now - timedelta(days=7),
            article_edited_at=now - timedelta(days=1),
            article_scraped_at=now,
            article_tags="tag1,tag2",
            comment_content="Comment"
        )

        snapshot = ai_comment.to_article_snapshot_dict()

        assert snapshot["mymoment_article_id"] == "12345"
        assert snapshot["title"] == "Article Title"
        assert snapshot["author"] == "Article Author"
        assert snapshot["category"] == 5
        assert snapshot["url"] == "https://new.mymoment.ch/article/12345/"
        assert snapshot["content"] == "Article content here"
        assert snapshot["raw_html"] == "<p>HTML</p>"
        assert snapshot["published_at"] == now - timedelta(days=7)
        assert snapshot["edited_at"] == now - timedelta(days=1)
        assert snapshot["scraped_at"] == now
        assert snapshot["tags"] == ["tag1", "tag2"]

    def test_to_comment_dict(self):
        """Test to_comment_dict method."""
        now = datetime.utcnow()

        ai_comment = AIComment(
            id=uuid.uuid4(),
            mymoment_article_id="12345",
            mymoment_comment_id="67890",
            user_id=uuid.uuid4(),
            article_title="Title",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=now,
            comment_content="[Dieser Kommentar stammt von einem KI-ChatBot.] Comment",
            status="posted",
            ai_model_name="gpt-4",
            ai_provider_name="openai",
            created_at=now - timedelta(minutes=5),
            posted_at=now
        )

        comment_dict = ai_comment.to_comment_dict()

        assert comment_dict["id"] == ai_comment.id
        assert comment_dict["mymoment_comment_id"] == "67890"
        assert comment_dict["content"] == ai_comment.comment_content
        assert comment_dict["status"] == "posted"
        assert comment_dict["is_posted"] is True
        assert comment_dict["created_at"] == now - timedelta(minutes=5)
        assert comment_dict["posted_at"] == now
        assert comment_dict["ai_model_name"] == "gpt-4"
        assert comment_dict["ai_provider_name"] == "openai"


class TestAICommentRepr:
    """Test AIComment string representation."""

    def test_repr(self):
        """Test __repr__ method."""
        ai_comment = AIComment(
            mymoment_article_id="12345",
            user_id=uuid.uuid4(),
            article_title="A Very Long Article Title That Should Be Truncated In The Repr",
            article_author="Author",
            article_content="Content",
            article_raw_html="HTML",
            article_url="https://...",
            article_scraped_at=datetime.utcnow(),
            comment_content="Comment",
            status="posted"
        )

        repr_str = repr(ai_comment)

        assert "AIComment" in repr_str
        assert "12345" in repr_str
        assert "posted" in repr_str
        assert "A Very Long Article Title" in repr_str
