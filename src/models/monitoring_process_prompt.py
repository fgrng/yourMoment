"""
MonitoringProcessPrompt junction model for monitoring process and prompt template associations.

This junction table enables a many-to-many relationship between monitoring
processes and prompt templates, allowing each process to use multiple
prompts with weighted selection.
"""

import uuid

from sqlalchemy import Column, Float, Boolean, UUID, ForeignKey, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import relationship

from src.models.base import Base, BaseModel


class MonitoringProcessPrompt(BaseModel):
    """Junction table connecting monitoring processes with prompt templates."""

    __tablename__ = "monitoring_process_prompts"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)

    # Foreign keys
    monitoring_process_id = Column(
        UUID(as_uuid=True),
        ForeignKey("monitoring_processes.id", ondelete="CASCADE"),
        nullable=False
    )
    prompt_template_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prompt_templates.id", ondelete="CASCADE"),
        nullable=False
    )

    # Weighting for prompt selection
    weight = Column(Float, nullable=False, default=1.0)

    # Status
    is_active = Column(Boolean, nullable=False, default=True)

    # Relationships
    monitoring_process = relationship("MonitoringProcess", back_populates="monitoring_process_prompts")
    prompt_template = relationship("PromptTemplate", back_populates="monitoring_process_prompts")

    # Constraints
    __table_args__ = (
        UniqueConstraint(
            "monitoring_process_id", "prompt_template_id",
            name="uq_monitoring_process_prompt"
        ),
        CheckConstraint("weight > 0.0", name="check_positive_weight"),
    )

    def __repr__(self) -> str:
        return (
            f"<MonitoringProcessPrompt("
            f"id={self.id}, "
            f"monitoring_process_id={self.monitoring_process_id}, "
            f"prompt_template_id={self.prompt_template_id}, "
            f"weight={self.weight}, "
            f"is_active={self.is_active}"
            f")>"
        )

    @property
    def effective_weight(self) -> float:
        """Get the effective weight for prompt selection (0 if inactive)."""
        return self.weight if self.is_active else 0.0