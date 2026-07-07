"""
Base service class providing common functionality for all yourMoment services.

This module provides a standard foundation for all service classes with:
- Standardized database session handling
- Standard logging setup
- User validation utilities
"""

import uuid
import logging
from abc import ABC
from typing import Optional, Any, Dict
from datetime import datetime

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User

class BaseServiceError(Exception):
    """Base exception for all service operations."""
    pass


class ServiceValidationError(BaseServiceError):
    """Raised when service validation fails."""
    pass


class ServiceNotFoundError(BaseServiceError):
    """Raised when a requested resource is not found."""
    pass


class ServiceAccessError(BaseServiceError):
    """Raised when user lacks access to a resource."""
    pass


class BaseService(ABC):
    """
    Abstract base class for all yourMoment services.

    Provides common functionality:
    - Database session management
    - User validation and access control
    - Standardized logging
    """

    def __init__(self, db_session: AsyncSession):
        """
        Initialize base service.

        Args:
            db_session: Database session for operations
        """
        self.db_session = db_session
        self.logger = logging.getLogger(self.__class__.__name__)

    async def get_user_by_id(
        self,
        user_id: uuid.UUID,
        require_active: bool = True
    ) -> Optional[User]:
        """
        Get user by ID with optional active status validation.

        Args:
            user_id: User ID to lookup
            require_active: Whether to require user to be active

        Returns:
            User object if found and meets criteria, None otherwise
        """
        try:
            conditions = [User.id == user_id]
            if require_active:
                conditions.append(User.is_active.is_(True))

            stmt = select(User).where(and_(*conditions))
            result = await self.db_session.execute(stmt)
            return result.scalar_one_or_none()

        except Exception as e:
            self.logger.error(f"Failed to get user {user_id}: {e}")
            return None

    async def validate_user_exists(
        self,
        user_id: uuid.UUID,
        require_active: bool = True
    ) -> User:
        """
        Validate that a user exists and optionally is active.

        Args:
            user_id: User ID to validate
            require_active: Whether to require user to be active

        Returns:
            User object if validation passes

        Raises:
            ServiceNotFoundError: If user not found or not active when required
        """
        user = await self.get_user_by_id(user_id, require_active)
        if not user:
            status_msg = " and active" if require_active else ""
            raise ServiceNotFoundError(f"User {user_id} not found{status_msg}")
        return user

    async def validate_user_access(
        self,
        user_id: uuid.UUID,
        resource_user_id: Optional[uuid.UUID]
    ) -> bool:
        """
        Validate that a user has access to a resource owned by another user.

        Args:
            user_id: ID of user requesting access
            resource_user_id: ID of user who owns the resource (None for system resources)

        Returns:
            True if access is allowed

        Raises:
            ServiceAccessError: If access is denied
        """
        if resource_user_id is None:
            # System resource - accessible to all authenticated users
            await self.validate_user_exists(user_id)
            return True

        if user_id != resource_user_id:
            raise ServiceAccessError(
                f"User {user_id} does not have access to resource owned by {resource_user_id}"
            )

        return True

    def log_operation(
        self,
        operation: str,
        user_id: Optional[uuid.UUID] = None,
        resource_id: Optional[uuid.UUID] = None,
        additional_data: Optional[Dict[str, Any]] = None
    ):
        """
        Log service operations in a standardized format.

        Args:
            operation: Description of the operation
            user_id: User performing the operation (optional)
            resource_id: Resource being operated on (optional)
            additional_data: Additional data to log (optional)
        """
        log_data = {
            "operation": operation,
            "timestamp": datetime.utcnow().isoformat(),
            "service": self.__class__.__name__
        }

        if user_id:
            log_data["user_id"] = str(user_id)
        if resource_id:
            log_data["resource_id"] = str(resource_id)
        if additional_data:
            log_data.update(additional_data)

        self.logger.info(f"Service operation: {log_data}")

    def validate_uuid(self, value: str, field_name: str = "ID") -> uuid.UUID:
        """
        Validate and convert string to UUID.

        Args:
            value: String value to convert
            field_name: Name of the field for error messages

        Returns:
            UUID object

        Raises:
            ServiceValidationError: If value is not a valid UUID
        """
        try:
            return uuid.UUID(value)
        except (ValueError, TypeError):
            raise ServiceValidationError(f"Invalid {field_name}: must be a valid UUID")
