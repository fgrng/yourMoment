"""
PromptTemplate model for managing AI comment generation templates.

This model stores both system-defined and user-defined prompt templates
that are used to generate contextual AI comments on myMoment articles.
"""

import re
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import Column, String, Text, Boolean, UUID, ForeignKey, CheckConstraint, DateTime
from sqlalchemy.orm import relationship

from src.models.base import Base, BaseModel


class PromptTemplate(BaseModel):
    """PromptTemplate manages templates for AI comment generation."""

    __tablename__ = "prompt_templates"

    # Primary fields
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    # Template content
    system_prompt = Column(Text, nullable=False)
    user_prompt_template = Column(Text, nullable=False)

    # Template categorization
    category = Column(String(20), nullable=False)  # SYSTEM or USER
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)

    # Status
    is_active = Column(Boolean, nullable=False, default=True)

    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="prompt_templates")
    monitoring_process_prompts = relationship(
        "MonitoringProcessPrompt",
        back_populates="prompt_template",
        cascade="all, delete-orphan"
    )
    ai_comments = relationship("AIComment", back_populates="prompt_template")

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "category IN ('SYSTEM', 'USER')",
            name="check_prompt_template_category"
        ),
        CheckConstraint(
            "(category = 'SYSTEM' AND user_id IS NULL) OR (category = 'USER' AND user_id IS NOT NULL)",
            name="check_prompt_template_user_consistency"
        ),
    )

    def __repr__(self) -> str:
        return f"<PromptTemplate(id={self.id}, name='{self.name}', category='{self.category}', user_id={self.user_id})>"

    @property
    def is_system_template(self) -> bool:
        """Check if this is a system-defined template."""
        return self.category == "SYSTEM"

    @property
    def is_user_template(self) -> bool:
        """Check if this is a user-defined template."""
        return self.category == "USER"

    def extract_placeholders(self) -> List[str]:
        """
        Extract placeholder variables from the user prompt template.

        Returns a list of placeholder names found in the template (without braces).
        Example: "{article_title}" -> "article_title"
        """
        placeholders = re.findall(r'\{([^}]+)\}', self.user_prompt_template)
        return list(set(placeholders))  # Remove duplicates

    def validate_placeholders(self) -> Dict[str, bool]:
        """
        Validate that the template contains supported placeholders.

        Returns a dictionary mapping placeholder names to validation status.
        """
        supported_placeholders = {
            'article_title', 'article_content', 'article_author',
            'article_category', 'article_published_at', 'article_url',
            'mymoment_username'
        }

        placeholders = self.extract_placeholders()
        return {
            placeholder: placeholder in supported_placeholders
            for placeholder in placeholders
        }

    def is_valid_template(self) -> bool:
        """Check if the template has valid placeholders and content."""
        if not self.system_prompt or not self.user_prompt_template:
            return False

        # Check that all placeholders are supported
        validation_results = self.validate_placeholders()
        return all(validation_results.values())

    def render_prompt(self, context: Dict[str, str]) -> str:
        """
        Render the user prompt template with provided context values.

        Args:
            context: Dictionary mapping placeholder names to values

        Returns:
            Rendered prompt string with placeholders replaced
        """
        rendered_prompt = self.user_prompt_template
        for placeholder, value in context.items():
            rendered_prompt = rendered_prompt.replace(f"{{{placeholder}}}", str(value))

        return rendered_prompt

    def get_missing_context_keys(self, context: Dict[str, str]) -> List[str]:
        """
        Get list of placeholder keys that are missing from the provided context.

        Args:
            context: Dictionary with context values

        Returns:
            List of placeholder names that are in the template but not in context
        """
        placeholders = set(self.extract_placeholders())
        context_keys = set(context.keys())
        return list(placeholders - context_keys)