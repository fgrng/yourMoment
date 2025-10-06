"""
Encryption configuration and utilities for yourMoment application.

This module provides Fernet-based encryption/decryption for sensitive data including:
- LLM provider API keys (LLMProviderConfiguration.api_key)
- myMoment login credentials (myMomentLogin.username, password)
- myMoment session data (myMomentSession.session_data)

Security Requirements:
- Environment-based key management with fallback generation
- Proper error handling for encryption/decryption operations
- All sensitive fields encrypted before database storage (FR-017)
"""

import base64
import json
from typing import Union
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
import logging

from src.config.settings import get_settings


DEFAULT_KEY_ENV_VAR = "YOURMOMENT_ENCRYPTION_KEY"

# Configure logger for encryption operations
logger = logging.getLogger(__name__)


class EncryptionError(Exception):
    """Base exception for encryption-related errors."""
    pass


class DecryptionError(EncryptionError):
    """Raised when decryption fails."""
    pass


class EncryptionManager:
    """
    Manages Fernet encryption/decryption for sensitive application data.

    Features:
    - Environment-based key management with file fallback
    - Automatic key generation for development
    - Secure Fernet encryption/decryption
    """

    def __init__(self, *, key: str | None = None, key_file_path: str | None = None):
        """
        Initialize encryption manager.

        Args:
            key: Optional encryption key override (base64). If not provided, sourced from settings.
            key_file_path: Optional key file override. Defaults to settings-managed path.
        """
        security_settings = get_settings().security
        self.key_env_var = DEFAULT_KEY_ENV_VAR
        self._configured_key = key or security_settings.YOURMOMENT_ENCRYPTION_KEY
        self.key_file_path = key_file_path or security_settings.YOURMOMENT_KEY_FILE
        self._fernet = self._initialize_fernet()

    def _initialize_fernet(self) -> Fernet:
        """Initialize Fernet instance from environment, file, or generate new key."""
        key_b64 = self._configured_key
        if key_b64:
            try:
                return Fernet(key_b64.encode())
            except Exception as e:
                logger.warning(f"Invalid encryption key in environment variable: {e}")

        # Try loading from file
        if self.key_file_path:
            key_path = Path(self.key_file_path)
            if key_path.exists():
                try:
                    key_b64 = key_path.read_text().strip()
                    logger.info(f"Encryption key loaded from file: {self.key_file_path}")
                    return Fernet(key_b64.encode())
                except Exception as e:
                    logger.warning(f"Failed to load key from file {self.key_file_path}: {e}")

        # Generate new key and save to file
        return self._generate_new_key()

    def _generate_new_key(self) -> Fernet:
        """Generate new encryption key and save it to file."""
        key_b64 = Fernet.generate_key().decode()
        fernet = Fernet(key_b64.encode())

        # Save key to file for persistence
        if self.key_file_path:
            try:
                key_path = Path(self.key_file_path)
                key_path.write_text(key_b64)
                key_path.chmod(0o600)  # Restrict file permissions
                logger.info(f"New encryption key saved to: {self.key_file_path}")
            except Exception as e:
                logger.error(f"Failed to save encryption key to file: {e}")

        logger.warning(
            "Generated new encryption key. For production, set environment variable "
            f"{self.key_env_var} to the generated key and distribute securely."
        )
        return fernet

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext string.

        Args:
            plaintext: The string to encrypt

        Returns:
            Base64-encoded encrypted string

        Raises:
            EncryptionError: If encryption fails
        """
        if not plaintext:
            return ""

        try:
            # Convert string to bytes and encrypt
            plaintext_bytes = plaintext.encode('utf-8')
            encrypted_bytes = self._fernet.encrypt(plaintext_bytes)

            # Return base64-encoded result for database storage
            encrypted_b64 = base64.urlsafe_b64encode(encrypted_bytes).decode('utf-8')
            logger.debug(f"Successfully encrypted data (length: {len(plaintext)} chars)")
            return encrypted_b64

        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise EncryptionError(f"Failed to encrypt data: {e}")

    def decrypt(self, encrypted_data: str) -> str:
        """
        Decrypt encrypted string.

        Args:
            encrypted_data: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string

        Raises:
            DecryptionError: If decryption fails
        """
        if not encrypted_data:
            return ""

        try:
            # Decode base64 and decrypt
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode('utf-8'))
            plaintext_bytes = self._fernet.decrypt(encrypted_bytes)

            # Convert bytes back to string
            plaintext = plaintext_bytes.decode('utf-8')
            logger.debug(f"Successfully decrypted data (length: {len(plaintext)} chars)")
            return plaintext

        except InvalidToken:
            logger.error("Decryption failed: Invalid token (wrong key or corrupted data)")
            raise DecryptionError("Invalid encryption token - data may be corrupted or key is wrong")
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise DecryptionError(f"Failed to decrypt data: {e}")

    def is_encrypted(self, data: str) -> bool:
        """
        Check if data appears to be encrypted (basic heuristic).

        Args:
            data: String to check

        Returns:
            True if data appears encrypted, False otherwise
        """
        if not data:
            return False

        try:
            # Try to decode the double-base64 encoded data (our format)
            outer_decoded = base64.urlsafe_b64decode(data.encode('utf-8'))

            # Encrypted data should be at least Fernet minimum length
            if len(outer_decoded) < 60:  # Fernet tokens are typically 60+ bytes
                return False

            # Check if this looks like a Fernet token (starts with 'gAAAAA')
            # Fernet tokens are base64 encoded and start with version byte 0x80
            # which becomes 'gA' in base64
            fernet_token_str = outer_decoded.decode('utf-8')
            return fernet_token_str.startswith('gAAAAA')

        except Exception:
            # If we can't decode or convert, it's probably not our encrypted format
            return False


# Global encryption manager instance
_encryption_manager = None


def get_encryption_manager() -> EncryptionManager:
    """
    Get the global encryption manager instance.

    Creates instance on first access with default configuration.

    Returns:
        EncryptionManager instance
    """
    global _encryption_manager
    if _encryption_manager is None:
        security_settings = get_settings().security
        _encryption_manager = EncryptionManager(
            key=security_settings.YOURMOMENT_ENCRYPTION_KEY,
            key_file_path=security_settings.YOURMOMENT_KEY_FILE
        )
    return _encryption_manager


def encrypt_field(plaintext: str) -> str:
    """
    Convenience function to encrypt a field using the global encryption manager.

    Args:
        plaintext: The string to encrypt

    Returns:
        Encrypted string suitable for database storage
    """
    return get_encryption_manager().encrypt(plaintext)


def decrypt_field(encrypted_data: str) -> str:
    """
    Convenience function to decrypt a field using the global encryption manager.

    Args:
        encrypted_data: Encrypted string from database

    Returns:
        Decrypted plaintext string
    """
    return get_encryption_manager().decrypt(encrypted_data)


def is_field_encrypted(data: str) -> bool:
    """
    Convenience function to check if field data is encrypted.

    Args:
        data: String to check

    Returns:
        True if data appears encrypted
    """
    return get_encryption_manager().is_encrypted(data)


# Field-specific encryption functions for model usage

def encrypt_api_key(api_key: str) -> str:
    """
    Encrypt LLM provider API key for database storage.

    Used by: LLMProviderConfiguration.api_key

    Args:
        api_key: Plain API key

    Returns:
        Encrypted API key
    """
    if not api_key:
        return ""

    try:
        encrypted = encrypt_field(api_key)
        logger.info("API key encrypted for database storage")
        return encrypted
    except Exception as e:
        logger.error(f"Failed to encrypt API key: {e}")
        raise


def decrypt_api_key(encrypted_api_key: str) -> str:
    """
    Decrypt LLM provider API key from database.

    Used by: LLMProviderConfiguration.api_key

    Args:
        encrypted_api_key: Encrypted API key from database

    Returns:
        Plain API key
    """
    if not encrypted_api_key:
        return ""

    try:
        decrypted = decrypt_field(encrypted_api_key)
        logger.info("API key decrypted from database")
        return decrypted
    except Exception as e:
        logger.error(f"Failed to decrypt API key: {e}")
        raise


def encrypt_mymoment_credentials(username: str, password: str) -> tuple[str, str]:
    """
    Encrypt myMoment login credentials for database storage.

    Used by: myMomentLogin.username, myMomentLogin.password

    Args:
        username: Plain username
        password: Plain password

    Returns:
        Tuple of (encrypted_username, encrypted_password)
    """
    try:
        encrypted_username = encrypt_field(username) if username else ""
        encrypted_password = encrypt_field(password) if password else ""
        logger.info("myMoment credentials encrypted for database storage")
        return encrypted_username, encrypted_password
    except Exception as e:
        logger.error(f"Failed to encrypt myMoment credentials: {e}")
        raise


def decrypt_mymoment_credentials(encrypted_username: str, encrypted_password: str) -> tuple[str, str]:
    """
    Decrypt myMoment login credentials from database.

    Used by: myMomentLogin.username, myMomentLogin.password

    Args:
        encrypted_username: Encrypted username from database
        encrypted_password: Encrypted password from database

    Returns:
        Tuple of (plain_username, plain_password)
    """
    try:
        username = decrypt_field(encrypted_username) if encrypted_username else ""
        password = decrypt_field(encrypted_password) if encrypted_password else ""
        logger.info("myMoment credentials decrypted from database")
        return username, password
    except Exception as e:
        logger.error(f"Failed to decrypt myMoment credentials: {e}")
        raise


def encrypt_session_data(session_data: Union[str, dict]) -> str:
    """
    Encrypt myMoment session data for database storage.

    Used by: myMomentSession.session_data

    Args:
        session_data: Session data (JSON string or dict)

    Returns:
        Encrypted session data string
    """
    if not session_data:
        return ""

    try:
        # Convert dict to JSON string if needed
        if isinstance(session_data, dict):
            session_data = json.dumps(session_data)

        encrypted = encrypt_field(session_data)
        logger.info("Session data encrypted for database storage")
        return encrypted
    except Exception as e:
        logger.error(f"Failed to encrypt session data: {e}")
        raise


def decrypt_session_data(encrypted_session_data: str, as_dict: bool = True) -> Union[str, dict]:
    """
    Decrypt myMoment session data from database.

    Used by: myMomentSession.session_data

    Args:
        encrypted_session_data: Encrypted session data from database
        as_dict: If True, parse JSON and return dict; if False, return JSON string

    Returns:
        Decrypted session data (dict or string based on as_dict parameter)
    """
    if not encrypted_session_data:
        return {} if as_dict else ""

    try:
        decrypted = decrypt_field(encrypted_session_data)

        if as_dict and decrypted:
            return json.loads(decrypted)

        logger.info("Session data decrypted from database")
        return decrypted
    except Exception as e:
        logger.error(f"Failed to decrypt session data: {e}")
        raise


def get_encryption_key() -> str:
    """
    Get the raw encryption key for JWT and other purposes.

    Returns:
        Raw encryption key as string
    """
    manager = get_encryption_manager()
    # Extract the key from the Fernet instance
    return manager._fernet._encryption_key
