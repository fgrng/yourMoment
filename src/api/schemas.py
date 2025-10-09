"""Pydantic request and response models shared across the API layer."""

import uuid
from datetime import datetime, timezone
from typing import Optional, List

from pydantic import BaseModel, EmailStr, Field, ConfigDict, field_validator
from src.validators.password import validate_password


# === Authentication Schemas ===

class UserRegisterRequest(BaseModel):
    """Request model for user registration."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")

    @field_validator('password')
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password meets security requirements."""
        errors = validate_password(v)
        if errors:
            raise ValueError("; ".join(errors))
        return v


class UserLoginRequest(BaseModel):
    """Request model for user login."""
    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class UserResponse(BaseModel):
    """Response model for user data."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="User unique identifier")
    email: str = Field(..., description="User email address")
    is_active: bool = Field(..., description="Whether user account is active")
    is_verified: bool = Field(..., description="Whether user email is verified")
    created_at: datetime = Field(..., description="Account creation timestamp")


class AuthResponse(BaseModel):
    """Response model for authentication endpoints."""
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiry in seconds")
    user: UserResponse = Field(..., description="Authenticated user information")


class LogoutResponse(BaseModel):
    """Response model for logout endpoint."""
    message: str = Field(default="Successfully logged out", description="Logout confirmation message")


# === Error Response Schemas ===

class ErrorResponse(BaseModel):
    """Standard error response model."""
    error: str = Field(..., description="Error type/code")
    message: str = Field(..., description="Human-readable error message")
    detail: Optional[dict] = Field(None, description="Additional error details")


class ValidationErrorResponse(BaseModel):
    """Validation error response model."""
    error: str = Field(default="validation_error", description="Error type")
    message: str = Field(..., description="Validation error message")
    detail: list = Field(..., description="List of validation errors")


# === MyMoment Credentials Schemas ===

class MyMomentCredentialsRequest(BaseModel):
    """Request model for myMoment credentials."""
    username: str = Field(..., min_length=1, max_length=100, description="myMoment username")
    password: str = Field(..., min_length=1, description="myMoment password")
    name: str = Field(..., min_length=1, max_length=100, description="Friendly name for this login")


class MyMomentCredentialsResponse(BaseModel):
    """Response model for myMoment credentials."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Credentials unique identifier")
    name: str = Field(..., description="Friendly name for this login")
    username: str = Field(..., description="myMoment username")
    is_active: bool = Field(..., description="Whether credentials are active")
    created_at: datetime = Field(..., description="Creation timestamp")
    last_used: Optional[datetime] = Field(None, description="Last time credentials were used")


# === LLM Provider Schemas ===

class LLMProviderCreate(BaseModel):
    """Request model for creating LLM provider configuration."""
    provider_name: str = Field(
        ...,
        description="LLM provider name",
        pattern="^(openai|mistral)$"
    )
    api_key: str = Field(..., min_length=1, description="API key for the provider")
    model_name: str = Field(..., min_length=1, max_length=100, description="Specific model to use")
    max_tokens: Optional[int] = Field(None, ge=1, description="Maximum tokens for responses")
    temperature: Optional[float] = Field(None, ge=0.0, le=1.0, description="Temperature for generation")


class LLMProviderUpdate(BaseModel):
    """Request model for updating LLM provider configuration."""
    api_key: Optional[str] = Field(None, min_length=1, description="API key for the provider")
    model_name: Optional[str] = Field(None, min_length=1, max_length=100, description="Specific model to use")
    max_tokens: Optional[int] = Field(None, ge=1, description="Maximum tokens for responses")
    temperature: Optional[float] = Field(None, ge=0.0, le=1.0, description="Temperature for generation")


class LLMProviderResponse(BaseModel):
    """Response model for LLM provider configuration."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Provider configuration unique identifier")
    provider_name: str = Field(..., description="LLM provider name")
    model_name: str = Field(..., description="Specific model being used")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens for responses")
    temperature: Optional[float] = Field(None, description="Temperature for generation")
    is_active: bool = Field(..., description="Whether provider is active")
    created_at: datetime = Field(..., description="Configuration creation timestamp")


# === Monitoring Process Schemas ===

class MonitoringProcessCreate(BaseModel):
    """Request model for monitoring process creation."""
    name: str = Field(..., min_length=1, max_length=100, description="Process name")
    description: Optional[str] = Field(None, max_length=500, description="Process description")
    max_duration_minutes: int = Field(..., ge=1, le=1440, description="Maximum duration in minutes (1-1440)")
    llm_provider_id: uuid.UUID = Field(..., description="LLM provider to use for comment generation")
    target_filters: Optional[dict] = Field(None, description="Article filtering configuration")
    prompt_template_ids: list[uuid.UUID] = Field(..., min_items=1, description="List of prompt template IDs to use")
    mymoment_login_ids: list[uuid.UUID] = Field(..., min_items=1, description="List of myMoment login IDs to use")
    generate_only: bool = Field(default=True, description="If true, only generate comments; if false, also post to myMoment")


class MonitoringProcessUpdate(BaseModel):
    """Request model for monitoring process updates."""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Process name")
    description: Optional[str] = Field(None, max_length=500, description="Process description")
    max_duration_minutes: Optional[int] = Field(None, ge=1, le=1440, description="Maximum duration in minutes (1-1440)")
    llm_provider_id: Optional[uuid.UUID] = Field(None, description="LLM provider to use for comment generation")
    target_filters: Optional[dict] = Field(None, description="Article filtering configuration")
    prompt_template_ids: Optional[list[uuid.UUID]] = Field(None, min_items=1, description="List of prompt template IDs to use")
    mymoment_login_ids: Optional[list[uuid.UUID]] = Field(None, min_items=1, description="List of myMoment login IDs to use")
    generate_only: Optional[bool] = Field(None, description="If true, only generate comments; if false, also post to myMoment")


class MonitoringProcessResponse(BaseModel):
    """Response model for monitoring process."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Process unique identifier")
    name: str = Field(..., description="Process name")
    description: Optional[str] = Field(None, description="Process description")
    is_running: bool = Field(..., description="Whether process is currently running")
    error_message: Optional[str] = Field(None, description="Error message if process failed")
    max_duration_minutes: int = Field(..., description="Maximum duration in minutes")
    started_at: Optional[datetime] = Field(None, description="When process was started")
    stopped_at: Optional[datetime] = Field(None, description="When process was stopped")
    expires_at: Optional[datetime] = Field(None, description="When process will automatically stop")
    llm_provider_id: Optional[uuid.UUID] = Field(None, description="LLM provider used for comment generation")
    target_filters: Optional[dict] = Field(None, description="Article filtering configuration")
    prompt_template_ids: list[uuid.UUID] = Field(..., description="List of prompt template IDs")
    mymoment_login_ids: list[uuid.UUID] = Field(..., description="List of myMoment login IDs")
    generate_only: bool = Field(..., description="If true, only generate comments; if false, also post to myMoment")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    @field_validator(
        'started_at',
        'stopped_at',
        'expires_at',
        'created_at',
        'updated_at',
        mode='before'
    )
    @classmethod
    def _ensure_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        """Normalize naive datetimes to UTC for consistent client handling."""
        if value is None:
            return value
        if isinstance(value, str):
            # Let pydantic handle string parsing after this validator
            return value
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class ProcessStartRequest(BaseModel):
    """Request model for starting a monitoring process."""
    force_restart: bool = Field(default=False, description="Force restart if already running")


class ProcessControlResponse(BaseModel):
    """Response model for process control operations."""
    process_id: uuid.UUID = Field(..., description="Process unique identifier")
    action: str = Field(..., description="Action performed (start/stop)")
    status: str = Field(..., description="Current process status")
    message: str = Field(..., description="Operation result message")


class PipelineStatusResponse(BaseModel):
    """Response model for pipeline status with AIComment counts by stage."""
    process_id: str = Field(..., description="Process unique identifier")
    discovered: int = Field(..., ge=0, description="Number of articles discovered")
    prepared: int = Field(..., ge=0, description="Number of articles with content prepared")
    generated: int = Field(..., ge=0, description="Number of AI comments generated")
    posted: int = Field(..., ge=0, description="Number of comments posted to myMoment")
    failed: int = Field(..., ge=0, description="Number of failed comments")
    total: int = Field(..., ge=0, description="Total number of AIComment records")


# === Prompt Template Schemas ===

class PromptTemplateCreate(BaseModel):
    """Request model for prompt template creation."""
    name: str = Field(..., min_length=1, max_length=100, description="Template name")
    description: Optional[str] = Field(None, max_length=500, description="Template description")
    system_prompt: str = Field(..., min_length=10, description="System prompt template")
    user_prompt_template: str = Field(..., min_length=10, description="User prompt template")

    @field_validator('system_prompt')
    @classmethod
    def validate_system_prompt(cls, v: str) -> str:
        """Validate system prompt length and content."""
        if len(v.strip()) < 10:
            raise ValueError('System prompt must be at least 10 characters')
        return v.strip()

    @field_validator('user_prompt_template')
    @classmethod
    def validate_user_prompt(cls, v: str) -> str:
        """Validate user prompt template length."""
        if len(v.strip()) < 10:
            raise ValueError('User prompt template must be at least 10 characters')
        return v.strip()

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate name is not empty after stripping."""
        if not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip()


class PromptTemplateUpdate(BaseModel):
    """Request model for prompt template updates."""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Template name")
    description: Optional[str] = Field(None, max_length=500, description="Template description")
    system_prompt: Optional[str] = Field(None, min_length=10, description="System prompt template")
    user_prompt_template: Optional[str] = Field(None, min_length=10, description="User prompt template")
    is_active: Optional[bool] = Field(None, description="Whether template is active")

    @field_validator('system_prompt')
    @classmethod
    def validate_system_prompt(cls, v: Optional[str]) -> Optional[str]:
        """Validate system prompt length and content if provided."""
        if v is not None and len(v.strip()) < 10:
            raise ValueError('System prompt must be at least 10 characters')
        return v.strip() if v is not None else None

    @field_validator('user_prompt_template')
    @classmethod
    def validate_user_prompt(cls, v: Optional[str]) -> Optional[str]:
        """Validate user prompt template length if provided."""
        if v is not None and len(v.strip()) < 10:
            raise ValueError('User prompt template must be at least 10 characters')
        return v.strip() if v is not None else None

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        """Validate name is not empty after stripping if provided."""
        if v is not None and not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip() if v is not None else None


class PromptTemplateResponse(BaseModel):
    """Response model for prompt template."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Template unique identifier")
    name: str = Field(..., description="Template name")
    description: Optional[str] = Field(None, description="Template description")
    system_prompt: str = Field(..., description="System prompt template")
    user_prompt_template: str = Field(..., description="User prompt template")
    category: str = Field(..., description="Template category (SYSTEM or USER)")
    is_active: bool = Field(..., description="Whether template is active")
    created_at: datetime = Field(..., description="Creation timestamp")


class PlaceholderInfoResponse(BaseModel):
    """Response model for supported prompt placeholder details."""

    name: str = Field(..., description="Placeholder identifier")
    is_required: bool = Field(..., description="Whether placeholder is required")
    description: str = Field(..., description="Explanation of placeholder usage")
    example_value: str = Field(..., description="Example value for this placeholder")


class PlaceholderListResponse(BaseModel):
    """Response model for supported placeholder list."""

    items: list[PlaceholderInfoResponse] = Field(..., description="Supported placeholders")


# === Article Schemas ===

class ArticleResponse(BaseModel):
    """Response model for article data."""
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="MyMoment article ID")
    title: str = Field(..., description="Article title")
    author: str = Field(..., description="Article author name")
    published_at: Optional[datetime] = Field(None, description="Article publication timestamp")
    edited_at: Optional[str] = Field(None, description="Article last edit date (as displayed on myMoment)")
    scraped_at: datetime = Field(..., description="When article was scraped")
    mymoment_url: str = Field(..., description="URL to original myMoment article")
    visibility: str = Field(..., description="Article visibility setting")
    ai_comments_count: int = Field(default=0, description="Number of AI comments generated")
    accessible_by_login_ids: list[uuid.UUID] = Field(..., description="Login IDs that can access this article")


class ArticleDetailResponse(ArticleResponse):
    """Response model for detailed article data."""
    content: str = Field(..., description="Article text content")
    raw_html: str = Field(..., description="Original HTML content for reference")
    comment_ids: list[uuid.UUID] = Field(default_factory=list, description="List of comment IDs for this article")


class ArticleListResponse(BaseModel):
    """Response model for article list with pagination."""
    items: list[ArticleResponse] = Field(..., description="List of articles")
    total: int = Field(..., description="Total number of articles")
    limit: int = Field(..., description="Number of articles per page")
    offset: int = Field(..., description="Number of articles skipped")


class TabResponse(BaseModel):
    """Response model for article tab/filter data."""
    id: str = Field(..., description="Tab identifier (e.g., 'home', 'alle', '38')")
    name: str = Field(..., description="Display name (e.g., 'Meine', 'Alle', 'Dummy Klasse 01')")
    tab_type: str = Field(..., description="Tab type: 'home', 'alle', or 'class'")


class TabListResponse(BaseModel):
    """Response model for available tabs list."""
    items: list[TabResponse] = Field(..., description="List of available tabs")
    total: int = Field(..., description="Total number of tabs")


# === Comment Schemas ===

class CommentResponse(BaseModel):
    """Response model for comment data."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Comment unique identifier")
    mymoment_comment_id: Optional[str] = Field(None, description="External comment ID from myMoment (if exists)")
    content: str = Field(..., description="Comment content")
    is_ai_generated: bool = Field(..., description="Whether comment is AI-generated")
    is_posted: bool = Field(..., description="Whether comment has been posted to myMoment")
    posted_by_login_id: Optional[uuid.UUID] = Field(None, description="myMoment login ID used to post this comment")
    posted_at: Optional[datetime] = Field(None, description="When comment was posted")
    scraped_at: Optional[datetime] = Field(None, description="When comment was scraped from myMoment")
    created_at: datetime = Field(..., description="When comment was created")


class AICommentResponse(BaseModel):
    """Response model for AI-generated comment with article snapshot."""
    model_config = ConfigDict(from_attributes=True)

    # Comment identification
    id: uuid.UUID = Field(..., description="AI comment unique identifier")
    mymoment_article_id: str = Field(..., description="myMoment article ID")
    mymoment_comment_id: Optional[str] = Field(None, description="myMoment comment ID (after posting)")

    # Article snapshot fields
    article_title: str = Field(..., description="Article title at comment time")
    article_author: str = Field(..., description="Article author at comment time")
    article_content: Optional[str] = Field(..., description="Article content at comment time")
    article_raw_html: Optional[str] = Field(None, description="Raw HTML content")
    article_url: str = Field(..., description="myMoment article URL")
    article_category: Optional[int] = Field(None, description="myMoment category ID")
    article_published_at: Optional[datetime] = Field(None, description="Article publication date")
    article_scraped_at: datetime = Field(..., description="When article snapshot was captured")

    # AI comment fields
    comment_content: Optional[str] = Field(..., description="AI-generated comment content")
    status: str = Field(..., description="Comment status: generated, posted, failed, deleted")
    ai_model_name: Optional[str] = Field(None, description="LLM model used")
    ai_provider_name: Optional[str] = Field(None, description="LLM provider used")
    generation_time_ms: Optional[int] = Field(None, description="Time taken to generate (ms)")

    # Timestamps
    created_at: datetime = Field(..., description="When comment was generated")
    posted_at: Optional[datetime] = Field(None, description="When comment was posted to myMoment")

    # Relations
    user_id: uuid.UUID = Field(..., description="User who owns this comment")
    mymoment_login_id: Optional[uuid.UUID] = Field(None, description="Login used to post")
    monitoring_process_id: Optional[uuid.UUID] = Field(None, description="Monitoring process that generated this")


class AICommentListResponse(BaseModel):
    """Response model for list of AI comments."""
    items: List[AICommentResponse] = Field(..., description="List of AI comments")
    total: int = Field(..., description="Total number of AI comments")
    limit: int = Field(..., description="Page size limit")
    offset: int = Field(0, description="Page offset")


class AICommentSummaryResponse(BaseModel):
    """Lightweight summary of an AI comment (for lists/tables)."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="AI comment unique identifier")
    mymoment_article_id: str = Field(..., description="myMoment article ID")
    article_title: str = Field(..., description="Article title")
    article_author: str = Field(..., description="Article author")
    status: str = Field(..., description="Comment status")
    created_at: datetime = Field(..., description="When comment was generated")
    posted_at: Optional[datetime] = Field(None, description="When posted")


class AICommentCreateRequest(BaseModel):
    """Request model for creating an AI comment (internal use by monitoring processes)."""

    # Article data (from scraping)
    mymoment_article_id: str = Field(..., description="myMoment article ID", min_length=1)
    article_title: str = Field(..., description="Article title", min_length=1, max_length=500)
    article_author: str = Field(..., description="Article author", min_length=1, max_length=200)
    article_content: str = Field(..., description="Article content", min_length=1)
    article_url: str = Field(..., description="myMoment article URL", min_length=1, max_length=500)
    article_raw_html: Optional[str] = Field(None, description="Raw HTML content")
    article_category: Optional[int] = Field(None, description="myMoment category ID", ge=0)
    article_published_at: Optional[datetime] = Field(None, description="Article publication date")
    article_edited_at: Optional[datetime] = Field(None, description="Article last edit date")

    # Comment generation parameters
    prompt_template_id: Optional[uuid.UUID] = Field(None, description="Prompt template to use")
    llm_provider_id: Optional[uuid.UUID] = Field(None, description="LLM provider to use")
    highlight_text: Optional[str] = Field(None, description="Text to highlight when commenting", max_length=1000)
    mymoment_username: Optional[str] = Field(None, description="myMoment username context", max_length=100)


class AICommentUpdateRequest(BaseModel):
    """Request model for updating AI comment status (after posting)."""

    mymoment_comment_id: Optional[str] = Field(None, description="Comment ID from myMoment")
    status: Optional[str] = Field(None, description="New status: posted, failed, deleted")
    error_message: Optional[str] = Field(None, description="Error message if failed", max_length=1000)

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v and v not in ['posted', 'failed', 'deleted']:
            raise ValueError('Status must be: posted, failed, or deleted')
        return v


class AICommentStatisticsResponse(BaseModel):
    """Response model for AI comment statistics."""

    total_comments: int = Field(..., description="Total AI comments")
    posted_comments: int = Field(..., description="Successfully posted comments")
    failed_comments: int = Field(..., description="Failed posting attempts")
    generated_comments: int = Field(..., description="Generated but not yet posted")
    success_rate: float = Field(..., description="Success rate percentage", ge=0, le=100)
    avg_generation_time_ms: float = Field(..., description="Average generation time in ms", ge=0)
    total_articles_commented: int = Field(..., description="Unique articles commented on", ge=0)

    # Breakdown by provider
    by_provider: Optional[dict] = Field(None, description="Statistics by LLM provider")

    # Breakdown by status
    by_status: Optional[dict] = Field(None, description="Count by status")

    # Recent activity
    last_comment_at: Optional[datetime] = Field(None, description="Most recent comment timestamp")
    last_posted_at: Optional[datetime] = Field(None, description="Most recent successful posting")
