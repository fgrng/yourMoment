# yourMoment Services Layer

Business logic layer for the yourMoment application, implementing domain-specific operations with async/await patterns, transaction management, and standardized error handling.

## Overview

The services layer provides a clean separation between API endpoints and data access, implementing:

- **Business Logic** – Domain-specific operations and validation
- **Transaction Management** – Automatic rollback on errors
- **Context Management** – Async context managers for resource cleanup
- **Access Control** – User ownership and permission validation
- **Error Handling** – Typed exceptions with standardized patterns
- **Logging** – Per-service structured logging

## Architecture

### Base Service Pattern

All services inherit from `BaseService` which provides:

```python
from src.services.base_service import BaseService

class MyService(BaseService):
    def __init__(self, db_session: AsyncSession):
        super().__init__(db_session)
        # self.db_session available
        # self.logger configured

    async def my_operation(self, user_id: uuid.UUID) -> Result:
        # Validate user
        user = await self.validate_user_exists(user_id)

        # Perform operation
        result = await self._do_work()

        # Commit handled by caller
        return result
```

**Key Features:**
- User validation helpers (`get_user_by_id`, `validate_user_exists`)
- Automatic logging setup per service
- Standard exception types (`ServiceValidationError`, `ServiceNotFoundError`, `ServiceAccessError`)
- Database session management

### Usage Pattern

Services are used as async context managers or direct instantiation:

```python
# Context manager (preferred for API routes)
async with MyService(session) as service:
    result = await service.do_something(user_id)
    # Session commit handled automatically

# Direct instantiation (for tasks/scripts)
service = MyService(session)
result = await service.do_something(user_id)
await session.commit()
```

## Core Services

### Authentication Services

#### `AuthService` (`auth_service.py`)

**Purpose**: User authentication, registration, and session management

**Key Methods:**
- `register_user(email, password)` – Create new user with bcrypt hashed password
- `authenticate_user(email, password)` – Verify credentials and return JWT token
- `create_access_token(user_id)` – Generate JWT access token
- `verify_token(token)` – Validate JWT and return user_id
- `create_user_session(user_id, token, metadata)` – Track active sessions
- `get_user_sessions(user_id)` – List active sessions
- `terminate_session(session_id)` – Expire session

**Exceptions:**
- `AuthServiceValidationError` – Invalid credentials or validation failure
- `AuthServiceNotFoundError` – User or session not found

**Security:**
- Bcrypt password hashing with configurable rounds
- JWT tokens with configurable expiration
- Session tracking for audit and revocation
- Password policy validation (length, complexity)

---

#### `UserService` (`user_service.py`)

**Purpose**: User account management and profile operations

**Key Methods:**
- `get_user(user_id)` – Fetch user by ID
- `update_user(user_id, updates)` – Update user profile
- `list_users(filters, limit, offset)` – Admin user listing
- `deactivate_user(user_id)` – Soft delete user account
- `validate_user_access(user_id, resource_owner_id)` – Check ownership

**Exceptions:**
- `UserNotFoundError` – User doesn't exist
- `UserAccessError` – Permission denied

---

#### `SessionService` (`session_service.py`)

**Purpose**: User session lifecycle management

**Key Methods:**
- `create_session(user_id, metadata)` – Create tracking session
- `get_active_sessions(user_id)` – List user's active sessions
- `terminate_session(session_id)` – End session
- `cleanup_expired_sessions()` – Remove old sessions (called by tasks)

---

### Monitoring Services

#### `MonitoringService` (`monitoring_service.py`)

**Purpose**: Complete lifecycle management for monitoring processes

**Key Methods:**
- `create_process(user_id, name, config)` – Create monitoring process with credentials/prompts
- `get_process(process_id, user_id)` – Fetch process with ownership check
- `list_processes(user_id, filters, limit)` – List user's processes
- `start_process(process_id, user_id)` – Initiate monitoring (dispatches Celery task)
- `stop_process(process_id, user_id)` – Terminate monitoring
- `update_process_status(process_id, status, metadata)` – Update execution state
- `delete_process(process_id, user_id)` – Remove process (soft delete)
- `get_process_statistics(process_id)` – Article/comment counts and runtime

**Process States:**
- `CREATED` – Process configured but not started
- `RUNNING` – Active monitoring and comment generation
- `STOPPED` – Manually stopped or completed duration
- `COMPLETED` – Finished successfully
- `FAILED` – Error during execution

**Validation:**
- Maximum processes per user (default: 10)
- Duration limits (max_duration_minutes)
- Credential and prompt existence
- User ownership for all operations

**Exceptions:**
- `ProcessValidationError` – Invalid configuration or state
- `ProcessOperationError` – Failed to start/stop/update

---

### myMoment Integration Services

#### `MyMomentCredentialsService` (`mymoment_credentials_service.py`)

**Purpose**: Manage encrypted myMoment login credentials

**Key Methods:**
- `create_credentials(user_id, username, password, nickname)` – Store encrypted credentials
- `get_credentials(credential_id, user_id)` – Fetch with ownership check
- `list_credentials(user_id, limit)` – List user's credentials
- `test_credentials(credential_id, user_id)` – Validate by attempting login
- `update_credentials(credential_id, user_id, updates)` – Update username/password
- `delete_credentials(credential_id, user_id)` – Remove (checks if in use by processes)

**Security:**
- Passwords encrypted at rest with Fernet
- Decryption only during authentication
- Never returned in API responses (use separate test endpoint)

**Exceptions:**
- `MyMomentCredentialsValidationError` – Invalid format or test failed
- `MyMomentCredentialsNotFoundError` – Credential doesn't exist

---

#### `MyMomentSessionService` (`mymoment_session_service.py`)

**Purpose**: Manage active myMoment platform sessions

**Key Methods:**
- `create_session(login_id, session_data)` – Store session cookies/metadata
- `get_session(session_id)` – Fetch active session
- `get_sessions_by_login(login_id)` – List sessions for credential
- `refresh_session(session_id, new_data)` – Update session expiration/cookies
- `terminate_session(session_id)` – Close session
- `cleanup_expired_sessions()` – Remove expired (called by tasks)
- `validate_session(session_id)` – Check if still active

**Session Data:**
- Encrypted session cookies
- Expiration timestamps
- Last activity tracking
- Login credential association

---

#### `ScraperService` (`scraper_service.py`)

**Purpose**: Web scraping and myMoment platform interaction

**Key Methods:**
- `authenticate(username, password)` – Login to myMoment
- `fetch_articles(session, filters)` – Retrieve articles from tabs
- `fetch_article_details(session, article_id)` – Get full article content
- `post_comment(session, article_id, comment_text)` – Submit comment
- `fetch_tabs()` – Get available article categories/tabs
- `validate_session(session)` – Check if session still authenticated

**Configuration:**
- Rate limiting (requests per second)
- Timeout settings
- Retry attempts and delays
- User agent management

**Context Management:**
```python
async with ScraperService() as scraper:
    session = await scraper.authenticate(username, password)
    articles = await scraper.fetch_articles(session, filters)
    # Session automatically closed
```

**Exceptions:**
- `ScrapingError` – General scraping failure
- `SessionError` – Session invalid or expired
- `AuthenticationError` – Login failed

---

### LLM and Comment Services

#### `LLMProviderService` (`llm_service.py`)

**Purpose**: Manage LLM provider configurations and API key storage

**Key Methods:**
- `create_provider(user_id, provider_type, api_key, model, config)` – Store provider config
- `get_provider(provider_id, user_id)` – Fetch with ownership check
- `list_providers(user_id, limit)` – List user's providers
- `update_provider(provider_id, user_id, updates)` – Update config/API key
- `delete_provider(provider_id, user_id)` – Remove (checks if in use)
- `get_client(provider)` – Instantiate instructor-wrapped client for generation

**Supported Providers:**
- OpenAI (gpt-4, gpt-3.5-turbo)
- Mistral (mistral-small, mistral-medium, mistral-large)
- Extensible for additional providers

**Security:**
- API keys encrypted at rest with Fernet
- Decryption only during client instantiation
- Never returned in API responses

**Exceptions:**
- `LLMProviderNotFoundError` – Provider doesn't exist
- `LLMProviderValidationError` – Invalid configuration

---

#### `PromptService` (`prompt_service.py`)

**Purpose**: Template management and rendering with placeholder validation

**Key Methods:**
- `create_template(user_id, name, content, is_system)` – Create prompt template
- `get_template(template_id, user_id)` – Fetch with ownership check
- `list_templates(user_id, include_system, limit)` – List available templates
- `update_template(template_id, user_id, updates)` – Update content/metadata
- `delete_template(template_id, user_id)` – Remove (checks if in use)
- `validate_template(content)` – Check placeholders and AI prefix
- `render_template(template_id, context)` – Render with placeholder substitution
- `preview_template(template_id, sample_data)` – Test rendering without committing

**Required Features:**
- AI disclosure prefix: `[Dieser Kommentar stammt von einem KI-ChatBot.]`
- Placeholder validation (supported: `{article_title}`, `{article_author}`, `{article_content}`, etc.)
- System templates (admin-created, read-only for users)

**Validation:**
- Ensures AI prefix is present
- Validates placeholder syntax
- Checks for unknown placeholders

**Exceptions:**
- `TemplateNotFoundError` – Template doesn't exist
- `TemplateValidationError` – Invalid placeholders or missing prefix
- `TemplateAccessError` – User can't modify system template

---

#### `CommentService` (`comment_service.py`)

**Purpose**: End-to-end AI comment generation and posting workflow

**Key Methods:**
- `generate_comment(article_id, prompt_template, llm_provider, context)` – Generate using LLM
- `post_comment(article_id, comment_text, session)` – Publish to myMoment
- `get_comments_for_article(article_id, limit)` – List generated comments
- `validate_comment(comment_text)` – Check length, profanity, AI prefix
- `retry_failed_comment(comment_id)` – Regenerate failed comment

**Generation Flow:**
1. Fetch article details
2. Render prompt template with article context
3. Call LLM provider via instructor
4. Validate generated comment (length, prefix, content)
5. Store in database with metadata
6. Post to myMoment (if enabled)
7. Update comment status

**Configuration:**
- Max/min comment length
- Generation timeout
- Retry attempts
- Content validation rules
- Fallback provider support

**Exceptions:**
- `CommentGenerationError` – LLM generation failed
- `CommentValidationError` – Generated comment doesn't meet requirements
- `ProviderExhaustionError` – All configured providers failed

---

### Placeholder Management

#### `prompt_placeholders.py`

**Purpose**: Define available placeholders for prompt templates

**Available Placeholders:**
```python
{article_title}        # Article headline
{article_author}       # Author username
{article_content}      # Full article text
{article_excerpt}      # First 200 chars
{article_category}     # Category/tab name
{article_published_at} # Publication date
{current_date}         # Current date
{current_time}         # Current time
{user_nickname}        # User's display name
```

**Methods:**
- `get_available_placeholders()` – List all placeholders with descriptions
- `validate_placeholders(template)` – Check template uses valid placeholders
- `extract_placeholders(template)` – Parse placeholders from template
- `render_with_context(template, context)` – Substitute values

---

## Service Dependencies

### Dependency Graph

```
API Routes
    ↓
AuthService
    ↓
UserService → SessionService
    ↓
MonitoringService ──────────────┐
    ↓                           ↓
MyMomentCredentialsService  PromptService
    ↓                           ↓
MyMomentSessionService      LLMProviderService
    ↓                           ↓
ScraperService ←────────────────┘
    ↓
CommentService
```

### Service Interactions

**Monitoring Process Start:**
```
MonitoringService.start_process()
  → Validates credentials via MyMomentCredentialsService
  → Validates prompts via PromptService
  → Validates LLM provider via LLMProviderService
  → Dispatches Celery task

Celery Task
  → MyMomentSessionService.create_session()
  → ScraperService.authenticate()
  → ScraperService.fetch_articles()
  → CommentService.generate_comment()
  → ScraperService.post_comment()
```

## Error Handling

### Exception Hierarchy

```
BaseServiceError
├── ServiceValidationError
│   ├── AuthServiceValidationError
│   ├── MyMomentCredentialsValidationError
│   ├── TemplateValidationError
│   └── ProcessValidationError
├── ServiceNotFoundError
│   ├── AuthServiceNotFoundError
│   ├── UserNotFoundError
│   ├── TemplateNotFoundError
│   ├── MyMomentCredentialsNotFoundError
│   └── LLMProviderNotFoundError
└── ServiceAccessError
    ├── UserAccessError
    └── TemplateAccessError

ScrapingError (independent hierarchy)
├── SessionError
└── AuthenticationError

CommentGenerationError (independent hierarchy)
├── CommentValidationError
└── ProviderExhaustionError
```

### Exception Handling Pattern

```python
from src.services.base_service import (
    ServiceValidationError,
    ServiceNotFoundError,
    ServiceAccessError
)

try:
    result = await service.do_operation(user_id, resource_id)
except ServiceValidationError as e:
    # 400 Bad Request - invalid input
    raise HTTPException(400, str(e))
except ServiceNotFoundError as e:
    # 404 Not Found - resource doesn't exist
    raise HTTPException(404, str(e))
except ServiceAccessError as e:
    # 403 Forbidden - user doesn't own resource
    raise HTTPException(403, str(e))
except Exception as e:
    # 500 Internal Server Error
    logger.error(f"Unexpected error: {e}")
    raise HTTPException(500, "Internal server error")
```

## Best Practices

### Service Design

✅ **Do:**
- Inherit from `BaseService` for common functionality
- Use async/await for all database operations
- Validate user ownership before operations
- Use typed exceptions for different error cases
- Log operations with structured data
- Keep services focused on single responsibility

❌ **Don't:**
- Access database directly from API routes
- Mix multiple concerns in one service
- Return raw SQLAlchemy models (use Pydantic schemas)
- Perform long-running operations synchronously
- Expose encrypted fields in responses

### Transaction Management

```python
# ✅ Correct: Commit in route, rollback on exception
@router.post("/resources")
async def create_resource(data: CreateRequest, session: AsyncSession):
    try:
        service = MyService(session)
        result = await service.create_resource(data)
        await session.commit()  # Explicit commit
        return result
    except ServiceValidationError as e:
        await session.rollback()  # Rollback on error
        raise HTTPException(400, str(e))

# ❌ Wrong: Service commits internally
class MyService(BaseService):
    async def create_resource(self, data):
        resource = Resource(**data)
        self.db_session.add(resource)
        await self.db_session.commit()  # Don't do this!
        return resource
```

### Encryption Handling

```python
# ✅ Correct: Use model helper methods
provider = await session.get(LLMProviderConfiguration, provider_id)
provider.set_api_key("sk-...")  # Encrypts automatically
api_key = provider.get_api_key()  # Decrypts on access

# ❌ Wrong: Direct column access
provider.api_key = "sk-..."  # Stored in plaintext!
api_key = provider.api_key  # Returns encrypted blob
```

### Context Manager Usage

```python
# ✅ Correct: Context manager for resources
async with ScraperService() as scraper:
    session = await scraper.authenticate(user, pass)
    articles = await scraper.fetch_articles(session)
    # Session automatically closed

# ✅ Also correct: Manual cleanup
scraper = ScraperService()
try:
    session = await scraper.authenticate(user, pass)
    articles = await scraper.fetch_articles(session)
finally:
    await scraper.close_session(session)
```

## Testing Services

### Unit Testing

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.asyncio
async def test_create_process(db_session: AsyncSession, test_user):
    service = MonitoringService(db_session)

    process = await service.create_process(
        user_id=test_user.id,
        name="Test Process",
        config={...}
    )

    assert process.name == "Test Process"
    assert process.user_id == test_user.id
    await db_session.commit()
```

### Integration Testing

```python
@pytest.mark.asyncio
async def test_monitoring_workflow(db_session: AsyncSession, test_user):
    # Create credentials
    creds_service = MyMomentCredentialsService(db_session)
    creds = await creds_service.create_credentials(
        test_user.id, "user@example.com", "password", "nickname"
    )

    # Create process
    monitoring_service = MonitoringService(db_session)
    process = await monitoring_service.create_process(
        user_id=test_user.id,
        name="Integration Test",
        login_ids=[creds.id],
        prompt_ids=[],
        llm_provider_id=None
    )

    # Start process
    await monitoring_service.start_process(process.id, test_user.id)
    await db_session.commit()

    # Verify state
    updated = await monitoring_service.get_process(process.id, test_user.id)
    assert updated.status == "running"
```

## Performance Considerations

### Query Optimization

Services use eager loading for relationships:

```python
# Optimized query with joinedload
stmt = (
    select(MonitoringProcess)
    .options(
        selectinload(MonitoringProcess.logins),
        selectinload(MonitoringProcess.prompts),
        selectinload(MonitoringProcess.llm_provider)
    )
    .where(MonitoringProcess.id == process_id)
)
```

### Caching Opportunities

Consider caching for:
- System prompt templates (rarely change)
- LLM provider configurations (per request)
- Available placeholders (static)

### Async Operations

All services use async/await:
- Database queries are non-blocking
- External API calls (LLM, scraping) are async
- Session management is async

## Migration Notes

When adding new services:

1. **Inherit from BaseService**
   ```python
   from src.services.base_service import BaseService

   class NewService(BaseService):
       pass
   ```

2. **Define custom exceptions**
   ```python
   class NewServiceError(BaseServiceError):
       pass
   ```

3. **Use async patterns**
   ```python
   async def my_method(self, user_id: uuid.UUID):
       user = await self.validate_user_exists(user_id)
       # ... operation
   ```

4. **Add to `__init__.py`** for easy imports
   ```python
   from .new_service import NewService
   ```

5. **Write tests** in `tests/unit/services/`

---

**Service Layer Total**: ~6,880 lines across 13 service modules

For implementation details, see source files in `src/services/`.
