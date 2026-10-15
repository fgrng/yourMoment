"""
yourMoment services package.

This package contains all business logic services for the yourMoment application,
including authentication, credential management, LLM integration,
monitoring, and prompt template management.
"""

from .auth_service import AuthService, AuthServiceValidationError
from .session_service import SessionService
from .mymoment_credentials_service import (
    MyMomentCredentialsService,
    MyMomentCredentialsServiceError,
)
from .llm_service import LLMProviderService, LLMProviderError
from .monitoring_service import MonitoringService
from .prompt_service import (
    PromptService,
    PromptServiceError,
    TemplateNotFoundError,
    TemplateValidationError,
    TemplateAccessError,
    TemplatePreviewRequest,
)
from .student_backup_service import (
    StudentBackupService,
    StudentBackupServiceError,
    StudentBackupValidationError,
    StudentBackupNotFoundError,
    StudentBackupDisabledError,
    StudentBackupLimitError,
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
    # LLM providers
    "LLMProviderService",
    "LLMProviderError",
    # Monitoring
    "MonitoringService",
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
    "StudentBackupLimitError",
]
