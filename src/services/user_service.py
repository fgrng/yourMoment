"""
User management utility service for yourMoment application.

Provides centralized user validation, lookup, and access control utilities
that can be shared across all services for consistent user handling.
"""

import uuid
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.services.base_service import (
    BaseService,
    ServiceNotFoundError,
    ServiceValidationError,
    ServiceAccessError,
)


class UserServiceError(ServiceValidationError):
    """Base exception for user service operations."""
    pass


class UserNotFoundError(ServiceNotFoundError):
    """Raised when a user is not found."""
    pass


class UserAccessError(ServiceAccessError):
    """Raised when user access is denied."""
    pass


class UserService(BaseService):
    """
    Centralized user management and validation service.

    Provides utilities for:
    - User lookup and validation
    - Access control verification
    - User statistics and management
    - Dependency injection for other services
    """

    def __init__(self, db_session: AsyncSession):
        """
        Initialize user service.

        Args:
            db_session: Database session for operations
        """
        super().__init__(db_session)

    async def get_current_user(
        self,
        user_id: uuid.UUID,
        require_active: bool = True,
        require_verified: bool = False
    ) -> User:
        """
        Get current user with validation (primary method for dependency injection).

        This is the main method that other services should use to get and validate
        the current user making a request.

        Args:
            user_id: User ID to validate
            require_active: Whether to require user to be active (default: True)
            require_verified: Whether to require user to be verified (default: False)

        Returns:
            User object if validation passes

        Raises:
            UserNotFoundError: If user not found or doesn't meet requirements
        """
        try:
            user = await self.validate_user_exists(
                user_id=user_id,
                require_active=require_active
            )

            if require_verified and not user.is_verified:
                raise UserNotFoundError(
                    f"User {user_id} not found (verified)"
                )

            return user

        except ServiceNotFoundError as exc:
            raise UserNotFoundError(str(exc)) from exc
        except Exception as exc:
            self.logger.error(f"Failed to get current user {user_id}: {exc}")
            raise UserServiceError(f"User lookup failed: {exc}")

    async def validate_user_owns_resource(
        self,
        user_id: uuid.UUID,
        resource_user_id: Optional[uuid.UUID],
        resource_type: str = "resource"
    ) -> User:
        """
        Validate that a user owns a specific resource.

        Args:
            user_id: ID of user requesting access
            resource_user_id: ID of user who owns the resource (None for system resources)
            resource_type: Type of resource for error messages

        Returns:
            User object if validation passes

        Raises:
            UserNotFoundError: If user not found
            UserAccessError: If user doesn't own the resource
        """
        user = await self.get_current_user(user_id)

        try:
            await self.validate_user_access(user_id, resource_user_id)
        except ServiceAccessError as exc:
            raise UserAccessError(
                f"User {user_id} does not have access to {resource_type} "
                f"owned by {resource_user_id}"
            ) from exc

        return user

    async def get_user_by_email(
        self,
        email: str,
        require_active: bool = True
    ) -> Optional[User]:
        """
        Get user by email address.

        Args:
            email: Email address to lookup
            require_active: Whether to require user to be active

        Returns:
            User object if found, None otherwise
        """
        try:
            conditions = [User.email == email.lower().strip()]

            if require_active:
                conditions.append(User.is_active.is_(True))

            stmt = select(User).where(and_(*conditions))
            result = await self.db_session.execute(stmt)
            return result.scalar_one_or_none()

        except Exception as e:
            self.logger.error(f"Failed to get user by email {email}: {e}")
            return None

    async def check_user_exists(
        self,
        user_id: uuid.UUID,
        require_active: bool = True
    ) -> bool:
        """
        Check if a user exists without returning the user object.

        Args:
            user_id: User ID to check
            require_active: Whether to require user to be active

        Returns:
            True if user exists and meets criteria, False otherwise
        """
        try:
            user = await self.get_user_by_id(user_id, require_active)
            return user is not None
        except Exception:
            return False

    async def get_users_by_ids(
        self,
        user_ids: List[uuid.UUID],
        require_active: bool = True
    ) -> List[User]:
        """
        Get multiple users by their IDs.

        Args:
            user_ids: List of user IDs to lookup
            require_active: Whether to require users to be active

        Returns:
            List of User objects (may be shorter than input list if some not found)
        """
        try:
            if not user_ids:
                return []

            conditions = [User.id.in_(user_ids)]

            if require_active:
                conditions.append(User.is_active.is_(True))

            stmt = select(User).where(and_(*conditions))
            result = await self.db_session.execute(stmt)
            return list(result.scalars().all())

        except Exception as e:
            self.logger.error(f"Failed to get users by IDs: {e}")
            return []

    async def get_user_statistics(self, user_id: uuid.UUID) -> Dict[str, Any]:
        """
        Get comprehensive statistics for a user.

        Args:
            user_id: User ID to get statistics for

        Returns:
            Dictionary with user statistics
        """
        try:
            user = await self.get_current_user(user_id)

            # Basic user info
            stats = {
                "user_id": str(user.id),
                "email": user.email,
                "is_active": user.is_active,
                "is_verified": user.is_verified,
                "created_at": user.created_at.isoformat() if hasattr(user, 'created_at') else None,
                "last_login": None  # Would need session tracking
            }

            # Additional statistics would be added here
            # For example: number of processes, sessions, credentials, etc.
            # This would require joining with other tables

            return stats

        except Exception as e:
            self.logger.error(f"Failed to get user statistics for {user_id}: {e}")
            return {"error": str(e)}

    async def validate_multiple_users(
        self,
        user_ids: List[uuid.UUID],
        require_active: bool = True
    ) -> Dict[uuid.UUID, bool]:
        """
        Validate multiple users and return validation results.

        Args:
            user_ids: List of user IDs to validate
            require_active: Whether to require users to be active

        Returns:
            Dictionary mapping user_id to validation result (True/False)
        """
        try:
            if not user_ids:
                return {}

            existing_users = await self.get_users_by_ids(user_ids, require_active)
            existing_ids = {user.id for user in existing_users}

            return {
                user_id: user_id in existing_ids
                for user_id in user_ids
            }

        except Exception as e:
            self.logger.error(f"Failed to validate multiple users: {e}")
            return {user_id: False for user_id in user_ids}

    async def get_active_users_count(self) -> int:
        """
        Get count of active users in the system.

        Returns:
            Number of active users
        """
        try:
            stmt = select(func.count(User.id)).where(User.is_active.is_(True))
            result = await self.db_session.execute(stmt)
            return result.scalar() or 0

        except Exception as e:
            self.logger.error(f"Failed to get active users count: {e}")
            return 0

    async def search_users(
        self,
        search_term: str,
        limit: int = 20,
        require_active: bool = True
    ) -> List[User]:
        """
        Search users by email or other criteria.

        Args:
            search_term: Term to search for
            limit: Maximum number of results
            require_active: Whether to require users to be active

        Returns:
            List of matching User objects
        """
        try:
            search_term = search_term.strip().lower()
            if not search_term:
                return []

            conditions = [User.email.ilike(f"%{search_term}%")]

            if require_active:
                conditions.append(User.is_active.is_(True))

            stmt = select(User).where(and_(*conditions)).limit(limit)
            result = await self.db_session.execute(stmt)
            return list(result.scalars().all())

        except Exception as e:
            self.logger.error(f"Failed to search users with term '{search_term}': {e}")
            return []

    def create_user_context(self, user: User) -> Dict[str, Any]:
        """
        Create a standardized user context dictionary for use in other services.

        Args:
            user: User object

        Returns:
            Dictionary with user context information
        """
        return {
            "user_id": user.id,
            "email": user.email,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def ensure_user_access(
        self,
        user_id: uuid.UUID,
        resource_user_id: Optional[uuid.UUID] = None,
        require_verified: bool = False
    ) -> Dict[str, Any]:
        """
        Comprehensive user access validation with context creation.

        This is a convenience method that combines user validation and context creation
        for use in service operations.

        Args:
            user_id: User ID requesting access
            resource_user_id: User ID that owns the resource (None for system resources)
            require_verified: Whether to require user verification

        Returns:
            User context dictionary

        Raises:
            UserNotFoundError: If user not found
            UserAccessError: If access is denied
        """
        # Validate user exists and meets requirements
        user = await self.get_current_user(
            user_id,
            require_active=True,
            require_verified=require_verified
        )

        # Validate resource access if needed
        if resource_user_id is not None:
            await self.validate_user_owns_resource(
                user_id,
                resource_user_id,
                "resource"
            )

        # Create and return user context
        return self.create_user_context(user)
