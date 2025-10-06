# yourMoment API Documentation

REST API for the yourMoment platform providing authentication, monitoring workflow management, LLM integration, and automated comment generation.

## Overview

The yourMoment API is built with FastAPI and provides:

- **RESTful Architecture** – Resource-based URLs with standard HTTP methods
- **JWT Authentication** – Secure token-based authentication with Bearer tokens
- **Async Operations** – Non-blocking request handling for high concurrency
- **Request Validation** – Automatic Pydantic-based validation with detailed errors
- **OpenAPI Documentation** – Interactive API docs at `/docs` (development mode)
- **Type Safety** – Full type hints and Pydantic schemas for all endpoints
- **Error Handling** – Standardized error responses with appropriate HTTP status codes

**Base URL**: `http://localhost:8000/api/v1` (development)

**API Version**: 1.0.0

## Interactive Documentation

For detailed endpoint documentation, schema definitions, and interactive testing:

🔗 **OpenAPI (Swagger) UI**: http://localhost:8000/docs
🔗 **ReDoc UI**: http://localhost:8000/redoc

*Note: Interactive docs are only available in development and testing environments for security reasons.*

## Quick Start

### Authentication Flow

```bash
# 1. Register a new user
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"SecurePass123!"}'

# 2. Login and get access token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"SecurePass123!"}'

# Response includes access_token
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user": {...}
}

# 3. Use token for authenticated requests
curl http://localhost:8000/api/v1/llm-providers/index \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..."
```

### Typical Workflow

```bash
# 1. Authenticate (get JWT token)
POST /api/v1/auth/login

# 2. Configure LLM provider
POST /api/v1/llm-providers/create

# 3. Add myMoment credentials
POST /api/v1/mymoment-credentials/create

# 4. Create prompt template
POST /api/v1/prompt-templates/create

# 5. Create monitoring process
POST /api/v1/monitoring-processes/create

# 6. Start monitoring
POST /api/v1/monitoring-processes/{id}/start

# 7. Monitor progress
GET /api/v1/monitoring-processes/{id}
GET /api/v1/articles/index
GET /api/v1/comments/index
```

## API Structure

### Endpoint Organization

The API is organized into 8 functional domains:

```
/api/v1
├── /auth                      # Authentication & user management
├── /mymoment-credentials      # myMoment login credentials
├── /llm-providers             # LLM provider configurations
├── /prompt-templates          # Comment templates
├── /monitoring-processes      # Process orchestration
├── /articles                  # Article discovery results
├── /comments                  # Generated comments
└── /dev                       # Development utilities (dev mode only)
```

**Total Endpoints**: ~73 routes across 9 routers

## API Domains

### 1. Authentication (`/auth`)

**Purpose**: User registration, login, session management

**Endpoints**:
- `POST /auth/register` – Create new user account
- `POST /auth/login` – Authenticate and receive JWT token
- `POST /auth/logout` – Terminate current session
- `GET /auth/me` – Get current user profile (authenticated)

**Authentication Methods**:
1. **Bearer Token** (API clients): `Authorization: Bearer <token>`
2. **Cookie** (web UI): `access_token` cookie set on login

**Token Details**:
- Type: JWT (JSON Web Token)
- Expiration: Configurable (default: 30 minutes)
- Algorithm: HS256
- Payload: User ID, issued/expiry timestamps

**Security Features**:
- Bcrypt password hashing
- Configurable password policies (length, complexity)
- Session tracking for audit
- Token expiration and validation

---

### 2. myMoment Credentials (`/mymoment-credentials`)

**Purpose**: Manage encrypted myMoment platform login credentials

**Endpoints**:
- `POST /create` – Store new myMoment credentials (encrypted)
- `GET /index` – List user's credentials (limit, offset)
- `GET /{id}` – Get specific credential (without password)
- `POST /{id}/test` – Validate credential by attempting login
- `DELETE /{id}` – Remove credential (fails if in use by process)

**Data Model**:
```json
{
  "id": "uuid",
  "name": "Friendly name",
  "username": "mymoment_user",
  "is_active": true,
  "created_at": "2025-01-15T10:00:00Z",
  "last_used": "2025-01-15T15:30:00Z"
}
```

**Security**:
- Passwords encrypted at rest (Fernet)
- Never returned in API responses
- Decrypted only during authentication
- Test endpoint validates without exposing password

---

### 3. LLM Providers (`/llm-providers`)

**Purpose**: Configure LLM provider connections for comment generation

**Endpoints**:
- `POST /create` – Add LLM provider configuration
- `GET /index` – List user's providers (limit, offset)
- `GET /{id}` – Get specific provider (without API key)
- `GET /providers` – List available provider types
- `DELETE /{id}` – Remove provider (fails if in use)

**Supported Providers**:
- **OpenAI**: gpt-4, gpt-4-turbo, gpt-3.5-turbo
- **Mistral**: mistral-small, mistral-medium, mistral-large
- Extensible architecture for additional providers

**Configuration Fields**:
```json
{
  "provider_name": "openai",
  "api_key": "sk-...",
  "model": "gpt-4",
  "temperature": 0.7,
  "max_tokens": 500,
  "json_mode": true
}
```

**Security**:
- API keys encrypted at rest (Fernet)
- Never returned in responses
- Decrypted only during LLM calls

---

### 4. Prompt Templates (`/prompt-templates`)

**Purpose**: Manage reusable comment generation templates

**Endpoints**:
- `POST /create` – Create new template
- `GET /index` – List templates (user + system templates)
- `GET /{id}` – Get template content
- `PUT /{id}` – Update template (user templates only)
- `DELETE /{id}` – Remove template (user templates only)
- `GET /placeholders` – List available placeholders
- `POST /preview` – Test template rendering with sample data

**Template Features**:
- **Placeholders**: `{article_title}`, `{article_author}`, `{article_content}`, etc.
- **Required Prefix**: `[Dieser Kommentar stammt von einem KI-ChatBot.]`
- **System Templates**: Read-only, admin-created templates
- **User Templates**: User-created, fully editable

**Example Template**:
```
[Dieser Kommentar stammt von einem KI-ChatBot.]

Interessanter Artikel zum Thema "{article_title}".
Die Perspektive von {article_author} ist besonders aufschlussreich.
{article_excerpt}
```

**Validation**:
- AI prefix presence check
- Placeholder syntax validation
- Unknown placeholder detection

---

### 5. Monitoring Processes (`/monitoring-processes`)

**Purpose**: Orchestrate article monitoring and comment generation workflows

**Endpoints**:
- `POST /create` – Create new monitoring process
- `GET /index` – List user's processes (with filters)
- `GET /{id}` – Get process details and statistics
- `POST /{id}/start` – Initiate monitoring workflow
- `POST /{id}/stop` – Terminate running process
- `POST /{id}/pause` – Pause process execution
- `POST /{id}/resume` – Resume paused process
- `DELETE /{id}` – Remove process (must be stopped)

**Process Configuration**:
```json
{
  "name": "Tech News Monitor",
  "mymoment_login_ids": ["uuid1", "uuid2"],
  "prompt_template_ids": ["uuid3"],
  "llm_provider_id": "uuid4",
  "max_duration_minutes": 120,
  "article_filters": {
    "tabs": ["technology", "science"],
    "keywords": ["AI", "machine learning"]
  }
}
```

**Process States**:
- `CREATED` – Configured but not started
- `RUNNING` – Active monitoring and generation
- `PAUSED` – Temporarily suspended
- `STOPPED` – Manually stopped or duration limit reached
- `COMPLETED` – Successfully finished
- `FAILED` – Error during execution

**Process Limits**:
- Maximum processes per user: 10 (configurable)
- Duration enforcement: Automatic stop at `max_duration_minutes`
- Resource quotas: Configurable per user

**Statistics Available**:
```json
{
  "articles_discovered": 45,
  "comments_generated": 38,
  "comments_posted": 35,
  "runtime_minutes": 87,
  "success_rate": 0.92
}
```

---

### 6. Articles (`/articles`)

**Purpose**: Browse discovered articles and metadata

**Endpoints**:
- `GET /index` – List articles (with pagination, filters)
- `GET /{id}` – Get article details and content
- `GET /tabs` – List available article categories/tabs

**Filtering**:
```
GET /articles/index?
  tab=technology&
  from_date=2025-01-01&
  to_date=2025-01-31&
  has_comments=true&
  limit=50&
  offset=0
```

**Article Data**:
```json
{
  "id": "uuid",
  "title": "Article headline",
  "author": "username",
  "content": "Full article text...",
  "category": "technology",
  "published_at": "2025-01-15T10:00:00Z",
  "discovered_at": "2025-01-15T10:05:00Z",
  "comment_count": 3,
  "mymoment_url": "https://new.mymoment.ch/articles/..."
}
```

**Available Filters**:
- Tab/category slug
- Date range (from_date, to_date)
- Has comments flag
- Credential ID (which login discovered it)

---

### 7. Comments (`/comments`)

**Purpose**: View and manage generated AI comments

**Endpoints**:
- `GET /index` – List comments (with filters)
- `GET /{id}` – Get comment details
- `GET /article/{article_id}` – List comments for specific article
- `POST /{id}/retry` – Regenerate failed comment

**Comment Status**:
- `PENDING` – Queued for generation
- `GENERATING` – LLM call in progress
- `GENERATED` – Successfully created, pending post
- `POSTING` – Publishing to myMoment
- `POSTED` – Successfully published
- `FAILED` – Generation or posting error

**Comment Data**:
```json
{
  "id": "uuid",
  "article_id": "uuid",
  "content": "[Dieser Kommentar...] Comment text",
  "status": "posted",
  "llm_provider_used": "openai",
  "template_used": "Tech Analysis",
  "generated_at": "2025-01-15T10:10:00Z",
  "posted_at": "2025-01-15T10:11:00Z",
  "generation_time_ms": 1234,
  "token_count": 156
}
```

**Filtering**:
```
GET /comments/index?
  status=posted&
  process_id=uuid&
  from_date=2025-01-01&
  limit=100
```

---

### 8. Development Utilities (`/dev`)

**Purpose**: Development and debugging tools (disabled in production)

**Endpoints**:
- `GET /health` – System health check
- `GET /config` – Current configuration (sanitized)
- `POST /seed` – Populate test data
- `POST /reset` – Clear test data
- `GET /tasks` – List Celery tasks
- `GET /queues` – Show Celery queue stats

**Availability**: Only enabled when `ENVIRONMENT=development` or `ENVIRONMENT=testing`

**Health Check Response**:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "environment": "development",
  "uptime_seconds": 3600,
  "database": "ok",
  "redis": "ok",
  "celery_workers": 2
}
```

---

## Request/Response Patterns

### Standard Request Headers

```http
POST /api/v1/resource/create HTTP/1.1
Host: localhost:8000
Content-Type: application/json
Authorization: Bearer <jwt_token>
Content-Length: 123

{request_body}
```

### Standard Response Format

**Success Response (200/201)**:
```json
{
  "id": "uuid",
  "field1": "value1",
  "field2": "value2",
  "created_at": "2025-01-15T10:00:00Z"
}
```

**List Response (200)**:
```json
{
  "items": [
    {...},
    {...}
  ],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

**Error Response (4xx/5xx)**:
```json
{
  "error": "validation_error",
  "message": "Invalid request data",
  "detail": {
    "field": "email",
    "issue": "Invalid email format"
  }
}
```

### Pagination

All list endpoints support pagination:

```
GET /api/v1/resource/index?limit=50&offset=100
```

- `limit` – Number of items to return (max: 100-200 depending on endpoint)
- `offset` – Number of items to skip

Response includes total count for UI pagination.

### Filtering

List endpoints support filtering via query parameters:

```
GET /api/v1/articles/index?tab=technology&from_date=2025-01-01&has_comments=true
```

Available filters documented in OpenAPI spec for each endpoint.

---

## HTTP Status Codes

### Success Codes

| Code | Meaning | Usage |
|------|---------|-------|
| 200 | OK | Successful GET, PUT, DELETE |
| 201 | Created | Successful POST creating resource |
| 204 | No Content | Successful DELETE with no response body |

### Client Error Codes

| Code | Meaning | When Used |
|------|---------|-----------|
| 400 | Bad Request | Invalid request data, validation error |
| 401 | Unauthorized | Missing or invalid authentication token |
| 403 | Forbidden | User lacks permission for resource |
| 404 | Not Found | Resource doesn't exist |
| 409 | Conflict | Resource already exists, state conflict |
| 422 | Unprocessable Entity | Semantic validation error |
| 429 | Too Many Requests | Rate limit exceeded |

### Server Error Codes

| Code | Meaning | When Used |
|------|---------|-----------|
| 500 | Internal Server Error | Unexpected server error |
| 502 | Bad Gateway | External service (LLM, myMoment) unavailable |
| 503 | Service Unavailable | Server overloaded or maintenance |
| 504 | Gateway Timeout | External service timeout |

---

## Authentication

### Token-Based Authentication

All authenticated endpoints require a JWT token:

```http
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
```

### Cookie-Based Authentication (Web UI)

For server-rendered pages, token stored in httpOnly cookie:

```http
Cookie: access_token=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
```

### Token Lifecycle

1. **Obtain**: `POST /api/v1/auth/login` or `/auth/register`
2. **Use**: Include in `Authorization` header for all authenticated requests
3. **Refresh**: Not yet implemented (future enhancement)
4. **Revoke**: `POST /api/v1/auth/logout`

### Token Claims

```json
{
  "sub": "user_uuid",
  "exp": 1642348800,
  "iat": 1642347000,
  "type": "access"
}
```

---

## Error Handling

### Validation Errors

**Request**:
```json
POST /api/v1/auth/register
{
  "email": "invalid-email",
  "password": "short"
}
```

**Response (422)**:
```json
{
  "error": "validation_error",
  "message": "Request validation failed",
  "detail": [
    {
      "loc": ["body", "email"],
      "msg": "value is not a valid email address",
      "type": "value_error.email"
    },
    {
      "loc": ["body", "password"],
      "msg": "Password must be at least 8 characters",
      "type": "value_error.password.min_length"
    }
  ]
}
```

### Business Logic Errors

**Response (400)**:
```json
{
  "error": "insufficient_credits",
  "message": "Cannot start process: maximum 10 processes per user",
  "detail": {
    "current_processes": 10,
    "limit": 10
  }
}
```

### Authentication Errors

**Response (401)**:
```json
{
  "error": "authentication_failed",
  "message": "Invalid or expired token"
}
```

### Permission Errors

**Response (403)**:
```json
{
  "error": "access_denied",
  "message": "You do not own this resource"
}
```

---

## Rate Limiting

**Current Status**: Not implemented (planned enhancement)

**Future Implementation**:
- Per-user limits: 1000 requests/hour
- Per-IP limits: 100 requests/minute (unauthenticated)
- Burst allowance: 20 requests/second
- Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

---

## Middleware Stack

Requests pass through middleware layers:

1. **CORS Middleware** – Cross-origin request handling
2. **Trusted Host Middleware** – Host header validation
3. **GZip Middleware** – Response compression
4. **Request Validation Middleware** – Size/depth/structure limits
5. **Error Handler Middleware** – Exception catching and formatting
6. **Authentication** – JWT validation (per-endpoint)

**Request Size Limits**:
- Max request size: 10MB
- Max JSON depth: 10 levels
- Max array length: 1000 elements
- Max string length: 10,000 characters

---

## API Versioning

**Current Version**: v1

**URL Pattern**: `/api/v1/{resource}`

**Future Versioning Strategy**:
- Version in URL path (preferred)
- Breaking changes require new version
- Old versions supported for migration period
- Version deprecation announced in advance

---

## WebSocket Support

**Current Status**: Not implemented

**Planned Features**:
- Real-time process status updates
- Live comment generation events
- Article discovery notifications

---

## Best Practices

### Client Implementation

✅ **Do:**
- Store JWT securely (httpOnly cookie or secure storage)
- Handle token expiration gracefully
- Implement exponential backoff for retries
- Validate responses against schemas
- Use pagination for list endpoints
- Include timeout for long operations

❌ **Don't:**
- Store tokens in localStorage (XSS risk)
- Hardcode API credentials
- Retry errors without backoff
- Assume response structure
- Fetch all items without pagination
- Make synchronous blocking calls

### Error Handling

```python
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Configure retry strategy
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session = requests.Session()
session.mount("http://", adapter)
session.mount("https://", adapter)

# Make request with error handling
try:
    response = session.post(
        "http://localhost:8000/api/v1/monitoring-processes/create",
        headers={"Authorization": f"Bearer {token}"},
        json=process_config,
        timeout=10
    )
    response.raise_for_status()
    return response.json()

except requests.exceptions.HTTPError as e:
    if e.response.status_code == 401:
        # Re-authenticate
        token = refresh_token()
    elif e.response.status_code == 422:
        # Validation error
        errors = e.response.json()["detail"]
        handle_validation_errors(errors)
    else:
        # Other error
        logger.error(f"API error: {e}")

except requests.exceptions.Timeout:
    logger.error("Request timeout")

except requests.exceptions.RequestException as e:
    logger.error(f"Request failed: {e}")
```

---

## Security Considerations

### Production Deployment

- **HTTPS Required**: Use TLS/SSL for all API traffic
- **Secret Keys**: Generate strong `SECRET_KEY` and `JWT_SECRET`
- **CORS**: Configure `CORS_ORIGINS` for allowed domains
- **Host Validation**: Set `ALLOWED_HOSTS` appropriately
- **Docs Disabled**: `/docs` and `/redoc` disabled in production
- **Rate Limiting**: Implement before public exposure
- **Input Validation**: All inputs validated via Pydantic
- **SQL Injection**: Protected by SQLAlchemy ORM
- **XSS Protection**: Frontend must sanitize user content

### Data Encryption

- **At Rest**: Passwords and API keys encrypted with Fernet
- **In Transit**: HTTPS/TLS for API communication
- **In Memory**: Decrypted only during active use
- **Audit Trail**: All authentication events logged

---

## Client SDKs

**Current Status**: No official SDKs

**Auto-Generated Clients**:
Generate clients from OpenAPI spec at `/docs`:
- Python: `openapi-python-client`
- TypeScript: `openapi-typescript-codegen`
- Java: `openapi-generator`
- Go: `go-swagger`

**Example**:
```bash
# Generate Python client
openapi-python-client generate --url http://localhost:8000/openapi.json
```

---

## Performance

### Response Times (Typical)

| Endpoint Type | Avg Response | Notes |
|---------------|--------------|-------|
| Authentication | <100ms | Bcrypt hashing adds latency |
| List (paginated) | <50ms | Database query + serialization |
| Single resource | <20ms | Single DB lookup |
| Create/Update | <100ms | Validation + DB write |
| Process start | <200ms | Dispatches async task |
| Comment generation | 2-5s | LLM API call (async) |

### Optimization

- Database queries use eager loading
- Response compression (GZip)
- Connection pooling (SQLAlchemy)
- Async request handling (FastAPI)
- Celery for long-running operations

---

## Monitoring & Observability

### Health Endpoint

```bash
GET /dev/health

{
  "status": "healthy",
  "checks": {
    "database": "ok",
    "redis": "ok",
    "celery": "ok"
  },
  "version": "1.0.0",
  "uptime": 3600
}
```

---

## Migration & Compatibility

### Database Migrations

Managed by Alembic:
```bash
alembic upgrade head    # Apply migrations
alembic revision -m ""  # Create migration
```

### Breaking Changes

None planned for v1. 

---

## Support & Resources

- **Interactive Docs**: http://localhost:8000/docs
- **API Spec (OpenAPI)**: http://localhost:8000/openapi.json
- **Source Code**: See `src/api/` directory
- **Service Layer**: See `README_SERVICES.md`
- **Tasks Documentation**: See `README_TASKS.md`

---

**Last Updated**: January 2025
**API Version**: 1.0.0
**Documentation Version**: 1.0.0
