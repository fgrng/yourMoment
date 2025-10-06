"""Logging configuration built on the unified settings layer."""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional

from src.config.settings import LoggingSettings, get_settings


def setup_logging(settings: Optional[LoggingSettings] = None) -> LoggingSettings:
    """
    Initialize basic logging for the yourMoment application.

    This function sets up:
    - Console logging for development
    - File-based logging with rotation
    - Simple formatting for readability

    Args:
        settings: Optional LoggingSettings instance. If not provided,
                 settings will be loaded from environment variables.

    Returns:
        LoggingSettings: The logging configuration used.
    """
    if settings is None:
        settings = get_settings().logging
    app_settings = get_settings().app

    # Convert string log level to logging constant
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Clear any existing handlers
    root_logger.handlers.clear()

    # Create formatter
    if app_settings.ENVIRONMENT == "development":
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )

    # Console handler
    if settings.LOG_CONSOLE_ENABLED:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handler with rotation
    if settings.LOG_FILE_ENABLED:
        # Ensure log directory exists
        log_dir = Path(settings.LOG_FILE_PATH).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            filename=settings.LOG_FILE_PATH,
            maxBytes=settings.LOG_FILE_MAX_SIZE,
            backupCount=settings.LOG_FILE_BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Log initialization
    logger = logging.getLogger(__name__)
    logger.info(
        "Logging system initialized",
        extra={
            "log_level": settings.LOG_LEVEL,
            "environment": app_settings.ENVIRONMENT,
        }
    )

    return settings


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name."""
    return logging.getLogger(name)


# Export main interfaces
__all__ = [
    "setup_logging",
    "get_logger",
    "LoggingSettings",
]
