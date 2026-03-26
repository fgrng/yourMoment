"""
MyMoment credentials service for yourMoment application.

Implements secure storage, retrieval, and management of myMoment login credentials
using Fernet encryption according to FR-017 (encrypted storage requirements).
"""

import uuid
from typing import List, Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from src.models.mymoment_login import MyMomentLogin
from src.services.base_service import BaseService


class MyMomentCredentialsServiceError(Exception):
    """Base exception for MyMoment credentials service operations."""
    pass


class MyMomentCredentialsValidationError(MyMomentCredentialsServiceError):
    """Raised when credentials validation fails."""
    pass


class MyMomentCredentialsNotFoundError(MyMomentCredentialsServiceError):
    """Raised when credentials are not found."""
    pass


class MyMomentCredentialsService(BaseService):
    """
    Service for handling myMoment credentials operations.

    Implements:
    - Secure credential storage with Fernet encryption
    - Credential retrieval and decryption
    - User-scoped credential management
    - Active credential filtering
    """

    def __init__(self, db_session: AsyncSession):
        """
        Initialize credentials service.

        Args:
            db_session: Database session for operations
        """
        super().__init__(db_session)

    async def create_credentials(
        self,
        user_id: uuid.UUID,
        username: str,
        password: str,
        name: str,
        is_admin: bool = False
    ) -> MyMomentLogin:
        """
        Create new myMoment credentials for a user.

        Args:
            user_id: ID of the user creating credentials
            username: myMoment username
            password: myMoment password (will be encrypted)
            name: Friendly name for these credentials
            is_admin: Whether this is an admin account (for Student Backup feature)

        Returns:
            Created MyMomentLogin object

        Raises:
            MyMomentCredentialsValidationError: If creation fails
        """
        # Validate inputs
        if not username.strip():
            raise MyMomentCredentialsValidationError("Username cannot be empty")
        if not password.strip():
            raise MyMomentCredentialsValidationError("Password cannot be empty")
        if not name.strip():
            raise MyMomentCredentialsValidationError("Name cannot be empty")

        # Check for duplicate name within user's credentials
        stmt = select(MyMomentLogin).where(
            and_(
                MyMomentLogin.user_id == user_id,
                MyMomentLogin.name == name.strip(),
                MyMomentLogin.is_active == True
            )
        )
        result = await self.db_session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            raise MyMomentCredentialsValidationError(f"Credentials with name '{name}' already exist")

        # Create credentials with automatic encryption
        credentials = MyMomentLogin(
            user_id=user_id,
            name=name.strip(),
            is_active=True,
            is_admin=is_admin
        )

        # Set both username and password using the model's encryption method
        credentials.set_credentials(username.strip(), password)

        try:
            self.db_session.add(credentials)
            await self.db_session.commit()
            await self.db_session.refresh(credentials)
        except IntegrityError as e:
            await self.db_session.rollback()
            raise MyMomentCredentialsValidationError("Failed to create credentials")

        return credentials

    async def get_credentials_by_id(
        self,
        credentials_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None
    ) -> Optional[MyMomentLogin]:
        """
        Get specific credentials by ID for a user.

        Args:
            credentials_id: ID of the credentials to retrieve
            user_id: ID of the user owning the credentials (optional, for security validation)

        Returns:
            MyMomentLogin object if found and active, None otherwise

        Note:
            If user_id is provided, validates that credentials belong to that user.
            If user_id is None, skips user validation (used in trusted internal contexts).
        """
        conditions = [
            MyMomentLogin.id == credentials_id,
            MyMomentLogin.is_active == True
        ]

        if user_id is not None:
            conditions.append(MyMomentLogin.user_id == user_id)

        stmt = select(MyMomentLogin).where(and_(*conditions))
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_credentials(
        self,
        user_id: uuid.UUID,
        is_admin: Optional[bool] = None
    ) -> List[MyMomentLogin]:
        """
        Get all active credentials for a user.

        Args:
            user_id: ID of the user whose credentials to retrieve
            is_admin: Optional filter for admin status.
                      True = only admin logins (for Student Backup)
                      False = only non-admin logins (for Monitoring)
                      None = all logins

        Returns:
            List of active MyMomentLogin objects
        """
        conditions = [
            MyMomentLogin.user_id == user_id,
            MyMomentLogin.is_active == True
        ]

        # Add is_admin filter if specified
        if is_admin is not None:
            conditions.append(MyMomentLogin.is_admin == is_admin)

        stmt = select(MyMomentLogin).where(
            and_(*conditions)
        ).order_by(MyMomentLogin.created_at)

        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def update_credentials(
        self,
        credentials_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        name: Optional[str] = None,
        is_admin: Optional[bool] = None
    ) -> Optional[MyMomentLogin]:
        """
        Update existing credentials.

        Args:
            credentials_id: ID of the credentials to update
            user_id: ID of the user owning the credentials (optional, for security validation)
            username: New username (optional)
            password: New password (optional, will be encrypted)
            name: New friendly name (optional)
            is_admin: New admin status (optional)

        Returns:
            Updated MyMomentLogin object if successful, None if not found

        Raises:
            MyMomentCredentialsValidationError: If update fails validation
        """
        # Get existing credentials
        credentials = await self.get_credentials_by_id(credentials_id, user_id)
        if not credentials:
            return None

        # Update credentials if username or password provided
        if username is not None or password is not None:
            current_username, current_password = credentials.get_credentials()
            new_username = username.strip() if username is not None else current_username
            new_password = password if password is not None else current_password

            if not new_username or not new_password:
                raise MyMomentCredentialsValidationError("Username and password cannot be empty")

            credentials.set_credentials(new_username, new_password)

        if name is not None:
            if not name.strip():
                raise MyMomentCredentialsValidationError("Name cannot be empty")

            # Check for duplicate name (excluding current credentials)
            stmt = select(MyMomentLogin).where(
                and_(
                    MyMomentLogin.user_id == credentials.user_id,
                    MyMomentLogin.name == name.strip(),
                    MyMomentLogin.is_active == True,
                    MyMomentLogin.id != credentials_id
                )
            )
            result = await self.db_session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                raise MyMomentCredentialsValidationError(f"Credentials with name '{name}' already exist")

            credentials.name = name.strip()

        # Update is_admin if provided
        if is_admin is not None:
            credentials.is_admin = is_admin

        try:
            await self.db_session.commit()
            await self.db_session.refresh(credentials)
        except IntegrityError:
            await self.db_session.rollback()
            raise MyMomentCredentialsValidationError("Failed to update credentials")

        return credentials

    async def delete_credentials(
        self,
        credentials_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None
    ) -> bool:
        """
        Delete (deactivate) credentials.

        Args:
            credentials_id: ID of the credentials to delete
            user_id: ID of the user owning the credentials (optional, for security validation)

        Returns:
            True if deletion was successful, False if not found
        """
        credentials = await self.get_credentials_by_id(credentials_id, user_id)
        if not credentials:
            return False

        # Soft delete by marking as inactive
        credentials.is_active = False

        try:
            await self.db_session.commit()
            return True
        except Exception:
            await self.db_session.rollback()
            return False

    async def get_decrypted_credentials(
        self,
        credentials_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None
    ) -> Optional[tuple[str, str]]:
        """
        Get decrypted username and password for authentication.

        This method should only be used internally by services that need
        to authenticate with myMoment on behalf of the user.

        Args:
            credentials_id: ID of the credentials to decrypt
            user_id: ID of the user owning the credentials (optional)

        Returns:
            Tuple of (username, password) if successful, None otherwise
        """
        credentials = await self.get_credentials_by_id(credentials_id, user_id)
        if not credentials:
            return None

        try:
            username, password = credentials.get_credentials()
            if username is None or password is None:
                return None
            return username, password
        except Exception:
            return None

    async def validate_credentials(
        self,
        credentials_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Validate myMoment credentials by attempting to decrypt.

        Args:
            credentials_id: ID of the credentials to validate
            user_id: ID of the user owning the credentials (optional)

        Returns:
            Tuple of (is_valid, error_message)
        """
        result = await self.get_decrypted_credentials(credentials_id, user_id)

        if result is None:
            credentials = await self.get_credentials_by_id(credentials_id, user_id)
            if not credentials:
                return False, "Credentials not found"
            return False, "Failed to decrypt credentials"

        return True, None