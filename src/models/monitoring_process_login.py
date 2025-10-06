"""
MonitoringProcessLogin junction model for monitoring process and myMoment login associations.

This junction table enables a many-to-many relationship between monitoring
processes and myMoment login credentials, allowing each process to use
multiple logins simultaneously for commenting.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, Boolean, DateTime, UUID, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from src.models.base import Base, BaseModel


class MonitoringProcessLogin(BaseModel):
    """Junction table connecting monitoring processes with myMoment login credentials."""

    __tablename__ = "monitoring_process_logins"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)

    # Foreign keys
    monitoring_process_id = Column(
        UUID(as_uuid=True),
        ForeignKey("monitoring_processes.id", ondelete="CASCADE"),
        nullable=False
    )
    mymoment_login_id = Column(
        UUID(as_uuid=True),
        ForeignKey("mymoment_logins.id", ondelete="CASCADE"),
        nullable=False
    )

    # Status and metadata
    is_active = Column(Boolean, nullable=False, default=True)

    # Relationships
    monitoring_process = relationship("MonitoringProcess", back_populates="monitoring_process_logins")
    mymoment_login = relationship("MyMomentLogin", back_populates="monitoring_process_logins")

    # Constraints
    __table_args__ = (
        UniqueConstraint(
            "monitoring_process_id", "mymoment_login_id",
            name="uq_monitoring_process_login"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MonitoringProcessLogin("
            f"id={self.id}, "
            f"monitoring_process_id={self.monitoring_process_id}, "
            f"mymoment_login_id={self.mymoment_login_id}, "
            f"is_active={self.is_active}"
            f")>"
        )

    @property
    def is_valid_association(self) -> bool:
        """
        Validate that the associated login belongs to the same user as the monitoring process.

        This enforces the business rule that monitoring processes can only use
        myMoment logins belonging to the same user.
        """
        if not self.monitoring_process or not self.mymoment_login:
            return False

        return self.monitoring_process.user_id == self.mymoment_login.user_id