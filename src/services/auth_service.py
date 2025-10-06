"""
Authentication service for yourMoment application.

Implements secure user authentication, registration, and session management
according to FR-001 (email/password authentication) and security requirements.
"""

import hashlib
import os
import uuid
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

import bcrypt
import jwt
from pydantic import EmailStr, ValidationError
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from src.models.user import User
from src.models.user_session import UserSession
from src.services.base_service import BaseService
from src.config.settings import get_settings

class AuthServiceError(Exception):
    """Base exception for authentication service operations."""
    pass


class AuthServiceValidationError(AuthServiceError):
    """Raised when authentication validation fails."""
    pass


class AuthServiceNotFoundError(AuthServiceError):
    """Raised when user or session is not found."""
    pass


class AuthService(BaseService):
    """
    Service for handling user authentication operations.

    Implements:
    - User registration with secure password hashing
    - User authentication with bcrypt verification
    - JWT token generation and validation
    - Session management and tracking
    """

    def __init__(self, db_session: AsyncSession, jwt_secret: str = None, jwt_algorithm: str = None):
        """
        Initialize authentication service.

        Args:
            db_session: Database session for operations
            jwt_secret: Secret key for JWT token signing (defaults to settings)
            jwt_algorithm: Algorithm to use for JWT signing (defaults to settings)
        """
        super().__init__(db_session)
        settings = get_settings()
        self.jwt_secret = jwt_secret or settings.security.JWT_SECRET
        self.jwt_algorithm = jwt_algorithm or settings.security.JWT_ALGORITHM

        # JWT token expiry configuration
        self.token_expiry_minutes = settings.security.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        self.token_expiry_hours = self.token_expiry_minutes / 60

    async def register_user(
        self,
        email: str,
        password: str
    ) -> Tuple[User, str]:
        """
        Register a new user with email and password.

        Args:
            email: User email address
            password: Plain text password (will be hashed)

        Returns:
            Tuple of (User object, JWT access token)

        Raises:
            RegistrationError: If registration fails
        """
        # Hash password securely
        password_hash = self._hash_password(password)

        # Create user
        user = User(
            email=email,
            password_hash=password_hash,
            is_active=True,
            is_verified=False
        )

        try:
            self.db_session.add(user)
            await self.db_session.commit()
            await self.db_session.refresh(user)
        except IntegrityError:
            await self.db_session.rollback()
            raise AuthServiceValidationError("User with this email already exists")

        access_token = await self._create_user_session(user_id=user.id)
        return user, access_token

    async def authenticate_user(
        self,
        email: str,
        password: str
    ) -> Tuple[User, str]:
        """
        Authenticate user with email and password.

        Args:
            email: User email address
            password: Plain text password

        Returns:
            Tuple of (User object, JWT access token)

        Raises:
            AuthServiceValidationError: If authentication fails
        """
        # Find user by email
        stmt = select(User).where(User.email == email)
        result = await self.db_session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise AuthServiceValidationError("Invalid credentials")

        # Check if user is active
        if not user.is_active:
            raise AuthServiceValidationError("User account is inactive")

        # Check if user is verified
        if not user.is_verified:
            raise AuthServiceValidationError("User account is not verified")

        # Verify password
        if not self._verify_password(password, user.password_hash):
            raise AuthServiceValidationError("Invalid credentials")

        # Extract user data while session is active
        user_id = user.id
        user_email = user.email
        user_is_active = user.is_active
        user_is_verified = user.is_verified

        # Generate JWT token and create session using extracted data
        access_token = await self._create_user_session(user_id=user_id)

        return user, access_token

    async def validate_token(self, token: str) -> Optional[User]:
        """
        Validate JWT token and return associated user.

        Args:
            token: JWT token to validate

        Returns:
            User object if token is valid, None otherwise
        """
        try:
            # Decode JWT token
            payload = jwt.decode(token, self.jwt_secret, algorithms=[self.jwt_algorithm])
            user_id = uuid.UUID(payload.get("sub"))

            # Check token hash in database
            token_hash = self._hash_token(token)
            stmt = select(UserSession).where(
                and_(
                    UserSession.token_hash == token_hash,
                    UserSession.is_active == True
                )
            )
            result = await self.db_session.execute(stmt)
            session = result.scalar_one_or_none()

            if not session or session.is_expired:
                return None

            # Get user
            stmt = select(User).where(User.id == user_id)
            result = await self.db_session.execute(stmt)
            user = result.scalar_one_or_none()

            if not user or not user.is_active:
                return None

            # Update session activity
            session.update_last_activity()
            await self.db_session.commit()

            return user

        except (jwt.InvalidTokenError, ValueError):
            return None

    async def logout_user(self, token: str) -> bool:
        """
        Logout user by revoking their session.

        Args:
            token: JWT token to revoke

        Returns:
            True if logout was successful, False otherwise
        """
        try:
            token_hash = self._hash_token(token)
            stmt = select(UserSession).where(
                and_(
                    UserSession.token_hash == token_hash,
                    UserSession.is_active == True
                )
            )
            result = await self.db_session.execute(stmt)
            session = result.scalar_one_or_none()

            if session:
                session.revoke()
                await self.db_session.commit()
                return True

        except Exception:
            pass

        return False

    async def get_user_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        """
        Get user by ID.

        Args:
            user_id: User ID to lookup

        Returns:
            User object if found and active, None otherwise
        """
        stmt = select(User).where(
            and_(
                User.id == user_id,
                User.is_active == True
            )
        )
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired user sessions.

        Returns:
            Number of sessions cleaned up
        """
        from sqlalchemy import delete

        stmt = delete(UserSession).where(
            UserSession.expires_at < datetime.utcnow()
        )
        result = await self.db_session.execute(stmt)
        await self.db_session.commit()

        return result.rowcount


    def _hash_password(self, password: str) -> str:
        """
        Hash password using bcrypt.

        Args:
            password: Plain text password

        Returns:
            Bcrypt hash as string
        """
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """
        Verify password against bcrypt hash.

        Args:
            password: Plain text password
            password_hash: Bcrypt hash to verify against

        Returns:
            True if password matches, False otherwise
        """
        try:
            # bcrypt.checkpw expects the hash as bytes, not string
            # The hash is stored as string in database, so we need to convert it back to bytes
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        except (ValueError, TypeError):
            return False

    def _hash_token(self, token: str) -> str:
        """
        Create a hash of JWT token for database storage.

        Args:
            token: JWT token to hash

        Returns:
            SHA-256 hash of token
        """
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    async def _create_user_session(
        self,
        user_id: uuid.UUID
    ) -> str:
        """
        Create a user session and corresponding JWT token.

        Args:
            user_id: User ID to create a session for (must be a UUID)

        Returns:
            JWT access token
        """
        # Generate JWT token
        now = datetime.utcnow()
        expires_at = now + timedelta(minutes=self.token_expiry_minutes)

        # Get user (user_id is already a UUID object)
        stmt = select(User).where(User.id == user_id)
        result = await self.db_session.execute(stmt)
        user = result.scalar_one_or_none()

        payload = {
            "sub": str(user.id),
            "email": user.email,
            "iat": now,
            "exp": expires_at,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "jti": str(uuid.uuid4())  # Add unique identifier to prevent duplicate token hashes
        }

        access_token = jwt.encode(payload, self.jwt_secret, algorithm=self.jwt_algorithm)

        # Create session record
        token_hash = self._hash_token(access_token)
        session = UserSession.create_session(
            user_id=user_id,
            token_hash=token_hash,
            session_duration=timedelta(minutes=self.token_expiry_minutes)
        )

        self.db_session.add(session)
        await self.db_session.commit()

        return access_token

    def create_auth_response(self, user: User, access_token: str) -> Dict[str, Any]:
        """
        Create standardized authentication response.

        Args:
            user: Authenticated user
            access_token: JWT access token

        Returns:
            Dictionary containing auth response data compatible with AuthResponse schema
        """
        from src.api.schemas import UserResponse

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": self.token_expiry_minutes * 60,  # Convert to seconds
            "user": UserResponse.model_validate(user)
        }
