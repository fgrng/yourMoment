"""Logging configuration built on the unified settings layer."""

import logging
import logging.handlers
from pathlib import Path
from typing import Any, Optional

from src.config.settings import LoggingSettings, get_settings


class _ServiceNameFilter(logging.Filter):
    """Ensure every record carries the configured service name."""

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "service"):
            record.service = self.service_name
        return True


def _resolve_log_level(level: Optional[Any], default_level_name: str) -> int:
    """Normalize logging levels from strings or integers."""
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        normalized = level.strip().upper()
        return getattr(logging, normalized, logging.INFO)
    return getattr(logging, default_level_name.upper(), logging.INFO)


def _build_formatter(environment: str) -> logging.Formatter:
    """Create a formatter tuned for the current environment."""
    if environment == "development":
        return logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(service)s | %(processName)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    return logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(service)s | %(processName)s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _reset_logger(logger: logging.Logger, *, propagate: bool) -> None:
    """Remove handlers from a logger so setup is idempotent."""
    for handler in list(logger.handlers):
        handler.close()
    logger.handlers.clear()
    logger.filters.clear()
    logger.propagate = propagate


def _build_rotating_file_handler(
    log_path: str,
    log_level: int,
    formatter: logging.Formatter,
    service_name: str,
    settings: LoggingSettings,
) -> logging.Handler:
    """Create a rotating file handler with the shared formatter."""
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        filename=path,
        maxBytes=settings.LOG_FILE_MAX_SIZE,
        backupCount=settings.LOG_FILE_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(log_level)
    handler.setFormatter(formatter)
    handler.addFilter(_ServiceNameFilter(service_name))
    return handler


def setup_logging(
    settings: Optional[LoggingSettings] = None,
    *,
    service_name: str = "app",
    log_level: Optional[Any] = None,
) -> LoggingSettings:
    """
    Initialize unified logging for a yourMoment runtime entrypoint.

    Args:
        settings: Optional logging settings instance.
        service_name: Logical service writing the logs (server, worker, scheduler, cli).
        log_level: Optional override for the root log level.

    Returns:
        LoggingSettings: The logging configuration used.
    """
    if settings is None:
        settings = get_settings().logging
    app_settings = get_settings().app
    resolved_level = _resolve_log_level(log_level, settings.LOG_LEVEL)
    formatter = _build_formatter(app_settings.ENVIRONMENT)

    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)
    _reset_logger(root_logger, propagate=True)

    if settings.LOG_CONSOLE_ENABLED:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(resolved_level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(_ServiceNameFilter(service_name))
        root_logger.addHandler(console_handler)

    if settings.LOG_FILE_ENABLED:
        root_logger.addHandler(
            _build_rotating_file_handler(
                settings.get_service_log_path(service_name),
                resolved_level,
                formatter,
                service_name,
                settings,
            )
        )

    llm_logger = logging.getLogger("yourmoment.llm")
    llm_logger.setLevel(resolved_level)
    _reset_logger(llm_logger, propagate=True)

    if settings.LOG_FILE_ENABLED:
        llm_logger.addHandler(
            _build_rotating_file_handler(
                settings.get_llm_log_path(),
                resolved_level,
                formatter,
                "llm",
                settings,
            )
        )

    logging.captureWarnings(True)

    logger = logging.getLogger(__name__)
    logger.info(
        "Logging system initialized for %s (level=%s, file=%s)",
        service_name,
        logging.getLevelName(resolved_level),
        settings.get_service_log_path(service_name) if settings.LOG_FILE_ENABLED else "disabled",
    )
    return settings


def format_log_context(**fields: Any) -> str:
    """Render compact key=value context fragments for log messages."""
    fragments = []
    for key, value in fields.items():
        if value is None or value == "":
            continue
        fragments.append(f"{key}={value}")
    return " ".join(fragments)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name."""
    return logging.getLogger(name)


__all__ = [
    "setup_logging",
    "format_log_context",
    "get_logger",
    "LoggingSettings",
]
