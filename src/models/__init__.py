"""
Database models for yourMoment application.

This module imports all database models to ensure proper relationship setup
and provides easy access to all model classes.
"""

from src.models.base import Base, BaseModel
from src.models.user import User
from src.models.mymoment_login import MyMomentLogin
from src.models.mymoment_session import MyMomentSession
from src.models.llm_provider import LLMProviderConfiguration
from src.models.monitoring_process import MonitoringProcess
from src.models.monitoring_process_login import MonitoringProcessLogin
from src.models.prompt_template import PromptTemplate
from src.models.monitoring_process_prompt import MonitoringProcessPrompt
from src.models.user_session import UserSession
from src.models.ai_comment import AIComment

# Export all models for easy importing
__all__ = [
    "Base",
    "BaseModel",
    "User",
    "MyMomentLogin",
    "MyMomentSession",
    "LLMProviderConfiguration",
    "MonitoringProcess",
    "MonitoringProcessLogin",
    "PromptTemplate",
    "MonitoringProcessPrompt",
    "UserSession",
    "AIComment",
]