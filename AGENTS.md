# yourMoment Codebase Guide

**Project**: yourMoment
**Type**: Production-ready Python web application with server-side rendered frontend
**Purpose**: AI-powered monitoring and automation for myMoment writing platform

This guide provides essential context for AI assistants working in the yourMoment codebase.

## Technology Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy (async), Alembic
- **Background tasks**: Celery 5 + Redis broker/result backend
- **LLM integration**: LiteLLM (unified API for OpenAI, Mistral, and any compatible provider)
- **Scraping**: aiohttp, BeautifulSoup4
- **Auth**: FastAPI-Users with JWT tokens
- **UI**: Jinja2 templates, Bootstrap 5, vanilla JavaScript (minimal)
- **Storage**: SQLite (default), PostgreSQL/MySQL compatible
- **Logging**: Python `logging` with rotating file handlers, split runtime logs, and a dedicated `yourmoment.llm` summary logger
- **Security**: Fernet encryption, audit logging, configurable password policies

## High-Level Architecture

**Runtime Stack**: FastAPI + SQLAlchemy (async) + Celery workers + Redis

### Project Structure

```
src/
├── api/            # FastAPI routers by domain (auth, monitoring, articles, etc.)
├── services/       # Business logic layer (context-managed service classes)
├── models/         # SQLAlchemy models with encryption helpers
├── tasks/          # Celery task entry points
├── config/         # Type-safe Pydantic settings
├── middleware/     # Error handling, validation, logging
└── utils/          # Shared utilities (encryption, validation)

templates/          # Jinja2 UI templates (Bootstrap 5)
tests/
├── contract/       # Full API endpoint tests
├── integration/    # Multi-step workflow tests
└── unit/           # Isolated component tests
```

### Key Design Patterns

- **Service layer**: All business logic in service classes used as async context managers
- **Encryption at rest**: Sensitive fields (API keys, credentials) encrypted via Fernet
- **Type safety**: Pydantic models for all API requests/responses and configuration
- **Async first**: Database access and external requests use async/await
- **Helper-based encryption**: Models expose `set_*`/`get_*` methods for encrypted fields
- **Stage-based monitoring pipeline**: `AIComment` rows move through `discovered → prepared → generated → posted/failed`
- **Idempotent task execution**: discovery uses a DB uniqueness constraint; later stages use compare-and-update semantics and skip stale rows safely
- **Scheduler discipline**: the scheduler spawns discovery only; per-article preparation/generation/posting are chained from newly created `AIComment` rows
- **Per-article retry budget**: the three single-article tasks (`prepare_article_content`, `generate_comment_for_article`, `post_comment_for_article`) each retry up to 3 times with exponential backoff (60 → 120 → 240 s, capped at 300 s) before permanently marking the row `failed`; the status stays at the prior stage during retries so the idempotency guard re-enters cleanly

## Core Data Models

| Entity | Purpose | Key Features |
|--------|---------|--------------|
| `User` | Authentication & user data | Relationships to all user-owned entities |
| `myMomentLogin` | Encrypted credentials | Fernet-encrypted username/password |
| `myMomentSession` | Active session state | Cookie storage, expiration tracking |
| `LLMProviderConfiguration` | Per-user LLM settings | Encrypted API keys, provider selection |
| `MonitoringProcess` | Monitoring workflow | Multi-credential fan-out, duration limits |
| `PromptTemplate` | Comment templates | System/user templates, validation |
| `Article` | Captured content | Browsing/filtering of scraped article data |
| `AIComment` | Pipeline state + immutable snapshot | Article snapshot, status workflow, reasoning, posting metadata, per-article uniqueness |
| `UserSession` / `AuditLog` | Tracking & compliance | Session lifecycle, audit trail |

**Junction Tables**: `MonitoringProcessLogin`, `MonitoringProcessPrompt`

## Product Capabilities

### Core Functionality
- **Multi-user monitoring**: Isolated workflows per user with quota management (max 10 processes/user)
- **Credential management**: Encrypted myMoment credentials with secure storage
- **LLM integration**: Provider-agnostic comment generation via LiteLLM (any LiteLLM-supported provider)
- **Template system**: Customizable prompts with required AI disclosure prefix and enforced paragraph-only HTML formatting
- **Process orchestration**: Start/stop workflows with strict duration enforcement, generate-only mode, and manual posting for generated comments
- **Article browsing**: Category/tag filtering with visibility tracking
- **AI comment review UI**: Global archive, process-specific comment views, detailed snapshots, generation metadata, and optional reasoning traces

### Security Features
- JWT-based authentication with configurable expiration
- Fernet encryption for all sensitive data (credentials, API keys)
- Audit logging for compliance
- Configurable password policies
- Rate limiting to respect platform constraints

### Scalability Targets
- 100 concurrent users
- ~10 monitoring processes per user
- Immediate process shutdown at `max_duration_minutes`
- Horizontal worker scaling for background tasks

## Request Flow

### Authentication
- Routes: `/api/v1/auth/*` (login, register, logout)
- Middleware: `get_current_user` dependency injects User model
- Tokens: JWT with configurable expiration (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`)

### API Endpoints
```
GET  /api/v1/{resource}/index     # List with pagination
POST /api/v1/{resource}/create    # Create new entity
GET  /api/v1/{resource}/{id}      # Get single entity
PUT  /api/v1/{resource}/{id}      # Update entity
DEL  /api/v1/{resource}/{id}      # Delete entity
```

### Process Lifecycle
1. **Create**: `POST /api/v1/monitoring-processes/create` → DB record created
2. **Start**: `POST /api/v1/monitoring-processes/{id}/start` → Celery task dispatched
3. **Discover**: Scheduler-driven discovery creates `AIComment` rows in `discovered`
4. **Prepare / Generate / Post**: Per-article Celery chain advances rows through `prepared`, `generated`, and optionally `posted`
5. **Stop**: `POST /api/v1/monitoring-processes/{id}/stop` OR auto-stop at `max_duration_minutes`

### AI Comment Surfaces
- API archive/detail routes: `/api/v1/comments/index`, `/api/v1/comments/{id}`, `/api/v1/comments/article/{mymoment_article_id}`
- Manual posting routes: `/api/v1/comments/{id}/post`, `/api/v1/monitoring-processes/{id}/post-comments`
- Process inspection route: `/api/v1/monitoring-processes/{id}/pipeline-status`
- UI routes: `/ai-comments`, `/ai-comments/{comment_id}`, `/processes/{process_id}/ai-comments`

### Frontend Integration
- UI routes: `/settings/*`, `/ai-comments*`, `/processes/*` (Jinja2 templates in `templates/`)
- JavaScript: Vanilla fetch calls to `/api/v1/*` endpoints
- Pattern: Server-rendered HTML with progressive enhancement

## Development Guidelines

> Temporary testing policy: the existing test suite is being rebuilt. Ignore the current `tests/` tree as an authority on expected behavior, and skip routine post-development testing steps unless the task is explicitly about rebuilding or fixing the test suite.

### Testing Patterns
```python
# Contract tests: Use helper functions
from tests.helper import create_test_app, create_test_user

app = create_test_app()
user = await create_test_user(session, email="test@example.com")
```

### Service Layer Pattern
```python
# Always use context managers
async with MonitoringService(session) as service:
    process = await service.create_process(user_id, config)
```

### LLM Generation
```python
# Use the DTO, not the SQLAlchemy model, when calling LLM APIs
from src.services.llm_types import LLMGenerationConfig
from src.services.llm_service import generate_completion_standalone

config = LLMGenerationConfig.from_model(provider, provider.get_api_key())
result = await generate_completion_standalone(user_prompt, config, system_prompt)
# result.comment_content, result.reasoning_content, result.total_tokens, etc.
```

The LLM layer appends `settings.monitoring.COMMENT_FORMAT_INSTRUCTION` to every request so generated comments are stored as paragraph-only HTML. `ensure_html_paragraphs()` and `validate_comment()` in `src/services/comment_service.py` are the final normalization and validation gates before persistence.

### Encryption Handling
```python
# NEVER access encrypted columns directly
provider.api_key = "sk-..."  # ❌ Wrong
provider.set_api_key("sk-...")  # ✅ Correct
key = provider.get_api_key()  # ✅ Correct
```

### Configuration Access
```python
from src.config.settings import get_settings

settings = get_settings()
db_file = settings.database.DB_SQLITE_FILE
is_prod = settings.is_production
```

### Common Tasks

```bash
# Activate virtual environment first (required for all commands below)
source .venv/bin/activate

# Install dependencies (clean env). requirements.txt has NO test runner;
# use requirements-dev.txt (or `pip install -e '.[test]'`) to run the suite.
pip install -r requirements-dev.txt

# Development server
python cli.py server

# Run tests
# TEMPORARY: Skip these routine test steps until the test-suite rebuild is complete.
pytest tests/contract -q        # API tests
pytest tests/integration -q     # Workflow tests
pytest tests/unit -q            # Unit tests

# Database migrations
python cli.py db migrate        # Run pending migrations (loads .env → correct DB file)
alembic revision -m "description"  # Create new migration
# ⚠️  NEVER run `alembic upgrade head` directly — it does not load .env and
#    will migrate yourmoment.db (alembic.ini default) instead of the active
#    DB file set by DB_SQLITE_FILE in .env (e.g. yourmoment_development.db).

# Celery workers
python cli.py worker            # Task worker
python cli.py scheduler         # Beat scheduler
```

## Important Notes

### API Limits
- Default pagination: 50-100 items
- Frontend typically requests `limit=100` or `limit=200`
- Update frontend code if server-side limits change

### Frontend Conventions
- UI routes in `src/api/web.py`
- Templates must receive `current_user`
- JavaScript uses `/api/v1/*` endpoints only
- The AI comments UI is client-rendered from `templates/ai_comments/*.html` plus `static/js/comments.js`

### Security Requirements
- AI comments MUST include prefix: `[Dieser Kommentar stammt von einem KI-ChatBot.]`
- All encrypted fields use Fernet symmetric encryption
- Production mode validates `SECRET_KEY` is not default value

### Logging
- Runtime entrypoints call `setup_logging(service_name=...)` so logs split by service (`server`, `worker`, `scheduler`, `cli`)
- Compact LLM request/result lines go to the `yourmoment.llm` logger, typically `logs/llm.log`
- Override paths with `LOG_SERVER_FILE`, `LOG_WORKER_FILE`, `LOG_SCHEDULER_FILE`, and `LOG_LLM_FILE`

### Database File
- The active DB file is set by `DB_SQLITE_FILE` in `.env` (e.g. `yourmoment_development.db`), **not** `yourmoment.db`
- `alembic.ini` hardcodes `sqlite:///./yourmoment.db` as a fallback — this is only correct when no `.env` is present
- Always use `python cli.py db migrate` to run migrations; it calls `load_dotenv()` before invoking alembic so the right file is targeted
- Running `alembic upgrade head` directly skips `.env` and silently migrates the wrong file

### Known Limitations
- No PATCH support for monitoring processes yet (UI references unimplemented endpoint)
- Article listing: no server-side search/sorting beyond category/tag filters
- Process deletion uses manual SQL (consider moving to `MonitoringService`)
- `src/api/comments.py` still validates `status_filter` against a reduced subset even though the UI exposes `discovered`, `prepared`, and `deleted`

## Production Deployment

### Pre-deployment Checklist
1. Set `ENVIRONMENT=production`
2. Generate and configure secure keys (see README)
3. Configure `ALLOWED_HOSTS` and `CORS_ORIGINS`
4. Set appropriate `SESSION_TIMEOUT_MINUTES`
5. Configure log retention (`LOG_FILE_*` settings)
6. Secure Redis instance if exposed
7. Run database migrations: `python cli.py db migrate` (not `alembic upgrade head` directly)

### Monitoring
- Logs: split by service under `logs/` (`server.log`, `worker.log`, `scheduler.log`, `cli.log`) plus `llm.log`
- Health: Process health checks every 30s (configurable)
- Metrics: Track process duration, comment success rate, session lifecycle

---

**Maintenance**: Keep this document synchronized with major architectural changes. Remove outdated information promptly.
