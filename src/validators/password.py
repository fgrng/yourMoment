"""
Password validation utilities for yourMoment application.

Centralized password validation logic that can be used across
API schemas, services, and business logic layers.
"""

import re
from typing import List
from src.config.settings import get_settings


class PasswordValidator:
    """
    Centralized password validation with configurable requirements.

    Reads configuration from environment variables to maintain
    consistency across the application.
    """

    def __init__(self):
        """Initialize validator with settings configuration."""
        settings = get_settings()
        self.min_length = settings.security.PASSWORD_MIN_LENGTH
        self.max_length = settings.security.PASSWORD_MAX_LENGTH
        self.require_uppercase = settings.security.PASSWORD_REQUIRE_UPPERCASE
        self.require_lowercase = settings.security.PASSWORD_REQUIRE_LOWERCASE
        self.require_digits = settings.security.PASSWORD_REQUIRE_DIGITS
        self.require_special = settings.security.PASSWORD_REQUIRE_SPECIAL
        self.special_chars = r'[!@#$%^&*(),.?":{}|<>]'

    def validate(self, password: str) -> List[str]:
        """
        Validate password against configured requirements.

        Args:
            password: Plain text password to validate

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check length requirements
        if len(password) < self.min_length:
            errors.append(f"Password must be at least {self.min_length} characters long")

        if len(password) > self.max_length:
            errors.append(f"Password must be no more than {self.max_length} characters long")

        # Check character requirements
        if self.require_uppercase and not re.search(r'[A-Z]', password):
            errors.append("Password must contain at least one uppercase letter")

        if self.require_lowercase and not re.search(r'[a-z]', password):
            errors.append("Password must contain at least one lowercase letter")

        if self.require_digits and not re.search(r'\d', password):
            errors.append("Password must contain at least one digit")

        if self.require_special and not re.search(self.special_chars, password):
            errors.append("Password must contain at least one special character")

        return errors

    def is_valid(self, password: str) -> bool:
        """
        Check if password is valid.

        Args:
            password: Plain text password to validate

        Returns:
            True if password meets all requirements, False otherwise
        """
        return len(self.validate(password)) == 0

    def get_requirements(self) -> dict:
        """
        Get current password requirements as a dictionary.

        Useful for API documentation and client-side validation.

        Returns:
            Dictionary of password requirements
        """
        return {
            "min_length": self.min_length,
            "max_length": self.max_length,
            "require_uppercase": self.require_uppercase,
            "require_lowercase": self.require_lowercase,
            "require_digits": self.require_digits,
            "require_special": self.require_special,
        }


# Global validator instance
_validator = None


def get_password_validator() -> PasswordValidator:
    """
    Get singleton password validator instance.

    Returns:
        Shared PasswordValidator instance
    """
    global _validator
    if _validator is None:
        _validator = PasswordValidator()
    return _validator


def validate_password(password: str) -> List[str]:
    """
    Convenience function to validate password.

    Args:
        password: Plain text password to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    return get_password_validator().validate(password)


def is_password_valid(password: str) -> bool:
    """
    Convenience function to check if password is valid.

    Args:
        password: Plain text password to validate

    Returns:
        True if password meets all requirements, False otherwise
    """
    return get_password_validator().is_valid(password)