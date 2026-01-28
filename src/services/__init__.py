"""
yourMoment services package.

This package contains all business logic services for the yourMoment application,
including authentication, credential management, LLM integration, web scraping,
monitoring, and prompt template management.
"""

from .auth_service import AuthService, AuthServiceValidationError
from .session_service import SessionService
from .mymoment_credentials_service import (
    MyMomentCredentialsService,
    MyMomentCredentialsServiceError
)
from .mymoment_session_service import MyMomentSessionService
from .llm_service import LLMProviderService, LLMProviderError
from .scraper_service import ScraperService, ScrapingError, SessionContext
from .monitoring_service import MonitoringService
from .comment_service import CommentService, CommentGenerationError
from .prompt_service import (
    PromptService,
    PromptServiceError,
    TemplateNotFoundError,
    TemplateValidationError,
    TemplateAccessError,
    TemplatePreviewRequest
)
from .student_backup_service import (
    StudentBackupService,
    StudentBackupServiceError,
    StudentBackupValidationError,
    StudentBackupNotFoundError,
    StudentBackupDisabledError,
    StudentBackupLimitError
)

__all__ = [
    # Authentication
    "AuthService",
    "AuthServiceValidationError",

    # Session management
    "SessionService",

    # MyMoment credentials
    "MyMomentCredentialsService",
    "MyMomentCredentialsServiceError",

    # MyMoment sessions
    "MyMomentSessionService",

    # LLM providers
    "LLMProviderService",
    "LLMProviderError",

    # Web scraping
    "ScraperService",
    "ScrapingError",
    "SessionContext",

    # Monitoring
    "MonitoringService",

    # Comment generation
    "CommentService",
    "CommentGenerationError",

    # Prompt templates
    "PromptService",
    "PromptServiceError",
    "TemplateNotFoundError",
    "TemplateValidationError",
    "TemplateAccessError",
    "TemplatePreviewRequest",

    # Student Backup
    "StudentBackupService",
    "StudentBackupServiceError",
    "StudentBackupValidationError",
    "StudentBackupNotFoundError",
    "StudentBackupDisabledError",
    "StudentBackupLimitError"
]
