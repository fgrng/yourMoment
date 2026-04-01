"""
Data Transfer Objects and Schemas for LLM services.

This module centralizes Pydantic models used for LLM interactions,
ensuring consistent data structures across llm_service.py and comment_service.py.
"""

import uuid
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class AICommentSchema(BaseModel):
    """
    Structured output schema for non-reasoning model comment generation.
    Includes a reasoning_content field to elicit chain-of-thought output
    from models that do not produce native reasoning tokens.
    Reasoning models skip this schema entirely and return plain text.
    """
    reasoning_content: str = Field(
        ...,
        description=(
            "Internal reasoning for comment generation on the myMoment platform. "
            "Think step-by-step. This is not visible by the author. "
            "Write your reasoning here."
        )
    )
    comment_content: str = Field(
        ...,
        description=(
            "Generated comment for publishing on the myMoment platform. "
            "This is visible by the author of the article commented upon. "
            "IMPORTANT: Wrap each paragraph in <p>...</p> tags. "
            "Do not use plain-text newlines for paragraph separation. "
            "Only use <p>, <strong>, <em> tags — no block-level HTML. "
            "Example: <p>First paragraph.</p><p>Second paragraph.</p>"
        )
    )


class GenerationResult(BaseModel):
    """
    Encapsulates the complete response from LiteLLM, including metadata.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    comment_content: str
    reasoning_content: Optional[str] = None

    # Metadata from LiteLLM response
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    model_used: str
    provider_used: str
    generation_time_ms: Optional[int] = None


class LLMGenerationConfig(BaseModel):
    """
    Lightweight DTO for LLM generation configuration.
    Eliminates strict dependency on SQLAlchemy models for background tasks.
    """
    provider_name: str
    model_name: str
    api_key: str  # Decrypted API key
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    
    @classmethod
    def from_model(cls, provider_config: Any, api_key: str) -> "LLMGenerationConfig":
        """
        Create DTO from LLMProviderConfiguration SQLAlchemy model.
        
        Args:
            provider_config: LLMProviderConfiguration instance
            api_key: Decrypted API key
        """
        return cls(
            provider_name=provider_config.provider_name,
            model_name=provider_config.model_name,
            api_key=api_key,
            max_tokens=provider_config.max_tokens,
            temperature=provider_config.temperature
        )
