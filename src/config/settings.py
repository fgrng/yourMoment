"""
Unified application configuration using Pydantic BaseSettings.

This module provides environment-specific configuration management for:
- Development: Local development with verbose logging
- Testing: Automated tests with minimal logging
- Production: Production deployment with security hardening

All settings are loaded from environment variables with sensible defaults.
Settings are validated using Pydantic for type safety.
"""

import os
from typing import Literal, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Core application settings."""

    # Environment
    ENVIRONMENT: Literal["development", "testing", "production"] = Field(
        default="development",
        description="Application environment"
    )

    DEBUG: bool = Field(
        default=False,
        description="Enable debug mode"
    )

    # Application metadata
    APP_NAME: str = Field(
        default="yourMoment",
        description="Application name"
    )

    APP_VERSION: str = Field(
        default="0.1.0",
        description="Application version"
    )

    BASE_URL: str = Field(
        default="http://localhost:8000",
        description="Base URL for the application"
    )

    # Server configuration
    HOST: str = Field(
        default="0.0.0.0",
        description="Server host"
    )

    PORT: int = Field(
        default=8000,
        description="Server port"
    )

    # Security
    SECRET_KEY: str = Field(
        default="insecure-dev-key-change-in-production",
        description="Application secret key"
    )

    ALLOWED_HOSTS: str = Field(
        default="localhost,127.0.0.1",
        description="Comma-separated list of allowed hosts"
    )

    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:8000",
        description="Comma-separated CORS origins"
    )

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key_in_production(cls, v: str, info) -> str:
        """Ensure SECRET_KEY is not default in production."""
        environment = info.data.get("ENVIRONMENT", "development")
        if environment == "production" and v == "insecure-dev-key-change-in-production":
            raise ValueError("SECRET_KEY must be set to a secure value in production")
        return v

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        env_file=".env",
        extra="ignore"
    )


class DatabaseSettings(BaseSettings):
    """Database configuration settings."""

    DB_SQLITE_FILE: str = Field(
        default="yourmoment.db",
        description="SQLite database file path"
    )

    DB_ECHO: bool = Field(
        default=False,
        description="Enable SQL query logging"
    )

    model_config = SettingsConfigDict(
        env_prefix="DB_",
        case_sensitive=False,
        env_file=".env",
        extra="ignore"
    )


class SecuritySettings(BaseSettings):
    """Security and encryption settings."""

    # Encryption
    YOURMOMENT_ENCRYPTION_KEY: Optional[str] = Field(
        default=None,
        description="Fernet encryption key for sensitive data"
    )

    YOURMOMENT_KEY_FILE: str = Field(
        default=".encryption_key",
        description="File path for encryption key storage"
    )

    # JWT Authentication
    JWT_SECRET: str = Field(
        default="default-development-secret",
        description="JWT token secret"
    )

    JWT_ALGORITHM: str = Field(
        default="HS256",
        description="JWT algorithm"
    )

    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=30,
        description="JWT access token expiration in minutes"
    )

    # Password requirements
    PASSWORD_MIN_LENGTH: int = Field(default=8, ge=6, le=128)
    PASSWORD_MAX_LENGTH: int = Field(default=100, ge=20, le=256)
    PASSWORD_REQUIRE_UPPERCASE: bool = Field(default=True)
    PASSWORD_REQUIRE_LOWERCASE: bool = Field(default=True)
    PASSWORD_REQUIRE_DIGITS: bool = Field(default=True)
    PASSWORD_REQUIRE_SPECIAL: bool = Field(default=True)

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        env_file=".env",
        extra="ignore"
    )


class LoggingSettings(BaseSettings):
    """Logging configuration settings."""

    LOG_LEVEL: str = Field(default="INFO", description="Root log level")
    LOG_FILE_ENABLED: bool = Field(default=True, description="Enable rotating file handler")
    LOG_FILE_PATH: str = Field(default="logs/app.log", description="Path to log file")
    LOG_FILE_MAX_SIZE: int = Field(default=10 * 1024 * 1024, description="Log file max size in bytes")
    LOG_FILE_BACKUP_COUNT: int = Field(default=5, description="Log file backups to retain")
    LOG_CONSOLE_ENABLED: bool = Field(default=True, description="Enable console logging output")

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        env_file=".env",
        extra="ignore"
    )


class CelerySettings(BaseSettings):
    """Celery task queue settings."""

    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Celery broker URL"
    )

    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/0",
        description="Celery result backend URL"
    )

    CELERY_WORKER_CONCURRENCY: int = Field(
        default=4,
        description="Celery worker concurrency"
    )

    model_config = SettingsConfigDict(
        env_prefix="CELERY_",
        case_sensitive=False,
        env_file=".env",
        extra="ignore"
    )


class ScraperSettings(BaseSettings):
    """Web scraping and myMoment integration settings."""

    MYMOMENT_BASE_URL: str = Field(
        default="https://new.mymoment.ch",
        description="myMoment platform base URL"
    )

    MYMOMENT_LOGIN_URL: str = Field(
        default="https://new.mymoment.ch/accounts/login/",
        description="myMoment login URL"
    )

    MYMOMENT_TIMEOUT: int = Field(
        default=30,
        description="Request timeout in seconds"
    )

    SCRAPING_RATE_LIMIT: float = Field(
        default=2.0,
        description="Requests per second"
    )

    SCRAPING_BURST_LIMIT: int = Field(
        default=5,
        description="Burst limit for requests"
    )

    SESSION_TIMEOUT_MINUTES: int = Field(
        default=60,
        description="Session timeout in minutes"
    )

    SESSION_CLEANUP_INTERVAL_MINUTES: int = Field(
        default=30,
        description="Session cleanup interval in minutes"
    )

    MAX_CONCURRENT_SESSIONS: int = Field(
        default=5,
        description="Maximum concurrent scraping sessions"
    )

    MAX_ARTICLES_PER_REQUEST: int = Field(
        default=20,
        description="Maximum articles to fetch per request"
    )

    RETRY_ATTEMPTS: int = Field(
        default=3,
        description="Number of retry attempts for failed requests"
    )

    RETRY_DELAY: float = Field(
        default=5.0,
        description="Delay in seconds between retry attempts"
    )

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        env_file=".env",
        extra="ignore"
    )


class MonitoringSettings(BaseSettings):
    """Monitoring and comment generation settings."""

    DEFAULT_MONITORING_DURATION_MINUTES: int = Field(
        default=60,
        description="Default monitoring duration in minutes"
    )

    MAX_MONITORING_PROCESSES: int = Field(
        default=10,
        description="Maximum monitoring processes per user"
    )

    PROCESS_HEALTH_CHECK_INTERVAL_SECONDS: int = Field(
        default=30,
        description="Health check interval in seconds"
    )

    COMMENT_GENERATION_TIMEOUT_SECONDS: int = Field(
        default=60,
        description="Comment generation timeout in seconds"
    )

    COMMENT_RATE_LIMIT_SECONDS: int = Field(
        default=30,
        description="Minimum seconds between comments"
    )

    ARTICLE_DISCOVERY_INTERVAL_SECONDS: int = Field(
        default=60,
        description="Article discovery interval in seconds"
    )

    AI_COMMENT_PREFIX: str = Field(
        default="[Dieser Kommentar stammt von einem KI-ChatBot.]",
        description="Required prefix for AI-generated comments"
    )

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        env_file=".env",
        extra="ignore"
    )


class StudentBackupSettings(BaseSettings):
    """
    Student Backup feature settings.

    This feature allows backing up and versioning student texts from myMoment
    for tracking revision activity over time. Requires admin accounts on myMoment
    that have access to student dashboards.

    The feature is disabled by default and must be explicitly enabled per instance.
    """

    STUDENT_BACKUP_ENABLED: bool = Field(
        default=False,
        description="Enable the Student Backup feature (default: disabled)"
    )

    STUDENT_BACKUP_INTERVAL_MINUTES: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="Interval between backup runs in minutes"
    )

    STUDENT_BACKUP_MAX_TRACKED_STUDENTS_PER_USER: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of students a user can track"
    )

    STUDENT_BACKUP_MAX_VERSIONS_PER_ARTICLE: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Maximum number of versions to keep per article (oldest get soft-deleted)"
    )

    STUDENT_BACKUP_CONTENT_CHANGES_ONLY: bool = Field(
        default=True,
        description="Only create new version if content has changed (uses SHA-256 hash)"
    )

    model_config = SettingsConfigDict(
        env_prefix="",
        case_sensitive=False,
        env_file=".env",
        extra="ignore"
    )


class Settings:
    """
    Unified settings container with environment-specific defaults.

    Automatically loads appropriate configuration based on ENVIRONMENT variable.
    """

    def __init__(self):
        """Initialize settings with environment-specific defaults."""
        self.app = AppSettings()
        self.database = self._get_database_settings()
        self.security = self._get_security_settings()
        self.logging = LoggingSettings()
        self.celery = self._get_celery_settings()
        self.scraper = ScraperSettings()
        self.monitoring = MonitoringSettings()
        self.student_backup = StudentBackupSettings()

    def _get_database_settings(self) -> DatabaseSettings:
        """
        Get database settings with environment-specific defaults.

        Pydantic BaseSettings will automatically load from .env file and environment variables.
        Environment variables take precedence over .env file values.
        """
        # Load base settings from .env file (Pydantic handles this)
        base_settings = DatabaseSettings()

        # Apply environment-specific overrides only if not explicitly set
        if self.app.ENVIRONMENT == "testing":
            # Override with test-specific database if not explicitly configured
            if base_settings.DB_SQLITE_FILE == DatabaseSettings.model_fields["DB_SQLITE_FILE"].default:
                base_settings.DB_SQLITE_FILE = "yourMoment_testing.db"
            base_settings.DB_ECHO = False
        elif self.app.ENVIRONMENT == "production":
            # Production should explicitly set DB_SQLITE_FILE, use default if not
            base_settings.DB_ECHO = False
        else:  # development
            # In development, default to yourmoment_development.db if not set in .env
            if base_settings.DB_SQLITE_FILE == "yourmoment.db":
                # Only override if it's the hardcoded default, not from .env
                env_value = os.getenv("DB_SQLITE_FILE")
                if env_value:
                    base_settings.DB_SQLITE_FILE = env_value
                else:
                    base_settings.DB_SQLITE_FILE = "yourmoment_development.db"

        return base_settings

    def _get_security_settings(self) -> SecuritySettings:
        """Get security settings with environment-specific defaults."""
        if self.app.ENVIRONMENT == "testing":
            return SecuritySettings(
                YOURMOMENT_ENCRYPTION_KEY=os.getenv(
                    "YOURMOMENT_ENCRYPTION_KEY",
                    "test-encryption-key-not-for-production"
                ),
                YOURMOMENT_KEY_FILE=os.getenv("YOURMOMENT_KEY_FILE", ".encryption_key.test"),
                JWT_SECRET=os.getenv("JWT_SECRET", "test-jwt-secret"),
                SECRET_KEY=os.getenv("SECRET_KEY", "test-secret-key")
            )
        return SecuritySettings()

    def _get_celery_settings(self) -> CelerySettings:
        """Get Celery settings with environment-specific defaults."""
        if self.app.ENVIRONMENT == "testing":
            # Use separate Redis database for testing
            return CelerySettings(
                CELERY_BROKER_URL=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1"),
                CELERY_RESULT_BACKEND=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
            )
        return CelerySettings()

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.app.ENVIRONMENT == "development"

    @property
    def is_testing(self) -> bool:
        """Check if running in testing environment."""
        return self.app.ENVIRONMENT == "testing"


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Get the global settings instance.

    Creates the instance on first access with configuration loaded from environment.

    Returns:
        Settings: The global settings instance
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings():
    """Reset settings instance (useful for testing)."""
    global _settings
    _settings = None


# Convenience functions for backward compatibility
def get_app_settings() -> AppSettings:
    """Get application settings."""
    return get_settings().app


def get_database_settings() -> DatabaseSettings:
    """Get database settings."""
    return get_settings().database


def get_security_settings() -> SecuritySettings:
    """Get security settings."""
    return get_settings().security


def get_celery_settings() -> CelerySettings:
    """Get Celery settings."""
    return get_settings().celery


def get_scraper_settings() -> ScraperSettings:
    """Get scraper settings."""
    return get_settings().scraper


def get_monitoring_settings() -> MonitoringSettings:
    """Get monitoring settings."""
    return get_settings().monitoring


def get_student_backup_settings() -> StudentBackupSettings:
    """Get student backup settings."""
    return get_settings().student_backup
