# yourMoment

AI-powered monitoring and automation platform for the myMoment writing community. Automates article discovery, generates context-aware AI comments, and manages multiple monitoring workflows with enterprise-grade security and scalability.

## Overview

yourMoment enables users to monitor myMoment articles and automatically generate AI-powered comments using their preferred LLM providers. The platform handles authenticated scraping, comment generation with customizable prompts, and process orchestration through an intuitive web interface.

## Key Features

- **Multi-user architecture** – Isolated workflows with per-user LLM configurations, credentials, and templates
- **Enterprise security** – JWT authentication, Fernet encryption for sensitive data, audit logging, and configurable password policies
- **LLM provider flexibility** – Support for OpenAI, Mistral, and extensible provider system with JSON mode optimization
- **Customizable templates** – System and user-defined prompt templates with validation and required AI disclosure prefix
- **Automated monitoring** – Background processes with configurable duration limits, multi-credential fan-out, and graceful shutdown
- **Article management** – Comprehensive article browsing with category/tag filtering and visibility tracking
- **Production-ready** – Type-safe configuration, health checks, structured logging, and horizontal scalability

See `AGENTS.md` for the condensed architecture brief used by AI assistants.

## Stack

| Layer | Technologies |
|-------|--------------|
| API & services | FastAPI, SQLAlchemy (async), Alembic |
| Background jobs | Celery 5 + Redis broker/result store |
| Scraping | aiohttp, BeautifulSoup4 |
| LLM integration | instructor library (provider-agnostic) |
| UI | Jinja2 templates, Bootstrap 5, vanilla JS (fetch) |
| Storage | SQLite by default (PostgreSQL/MySQL compatible) |

## Quick Start

### Prerequisites

- Python 3.11+
- Redis (optional, required for background workers)

### Installation

```bash
# Clone and setup virtual environment
git clone <repo>
cd yourMoment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your configuration (see Configuration section)

# Initialize database
alembic upgrade head

# Start development server
python manage.py run
```

Access the application at `http://localhost:8000` (UI) and `http://localhost:8000/docs` (API docs).

### Background Workers (Optional)

For automated monitoring processes, start Celery workers:

```bash
# Terminal 1: Worker
python celery_cli.py worker

# Terminal 2: Beat scheduler
python celery_cli.py beat
```

## Configuration

### Environment Setup

1. Copy the example configuration:
   ```bash
   cp .env.example .env
   ```

2. Generate secure keys:
   ```bash
   # Application secret key
   python -c "import secrets; print(secrets.token_urlsafe(32))"

   # JWT secret
   python -c "import secrets; print(secrets.token_urlsafe(32))"

   # Fernet encryption key
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. Edit `.env` with your configuration values

### Critical Settings

**Security (Required for Production)**
- `SECRET_KEY` – Application secret (auto-validated in production)
- `JWT_SECRET` – JWT token signing key
- `YOURMOMENT_ENCRYPTION_KEY` – Fernet key for encrypting credentials/API keys

**Database**
- `DB_SQLITE_FILE` – Database file path (default: `yourmoment.db`)

**Celery (Optional)**
- `CELERY_BROKER_URL` – Redis broker URL (required for background workers)
- `CELERY_RESULT_BACKEND` – Redis result backend URL

**Environment Control**
- `ENVIRONMENT` – Set to `production`, `development`, or `testing`

### Environment-Specific Behavior

The application automatically adjusts defaults based on `ENVIRONMENT`:

| Setting | Development | Production |
|---------|-------------|------------|
| Logging | Verbose (DEBUG) | Structured (INFO) |
| Security | Relaxed | Strict validation |
| Encryption | Auto-generated | Required explicit keys |
| Database | Local SQLite | Configurable path |

### Configuration API

Access settings type-safely throughout the application:

```python
from src.config.settings import get_settings

settings = get_settings()
db_file = settings.database.DB_SQLITE_FILE
is_prod = settings.is_production
```

See `.env.example` for complete configuration reference.

## Testing

### Test Suites

**Contract Tests** – API endpoint validation with full app bootstrap:
```bash
pytest tests/contract -q
```

**Integration Tests** – Multi-step workflows (may require Celery):
```bash
pytest tests/integration -q
```

**Unit Tests** – Isolated component testing:
```bash
pytest tests/unit -q
```

### Test Configuration

Tests use isolated configuration:
- Separate SQLite database (`yourMoment_testing.db`)
- Dedicated Redis database (db 1)
- Test-specific encryption keys
- Minimal logging output

Set `ENVIRONMENT=testing` for test-specific behavior.

## Production Considerations

### Security Checklist

- [ ] Generate and set strong `SECRET_KEY`, `JWT_SECRET`, and `YOURMOMENT_ENCRYPTION_KEY`
- [ ] Set `ENVIRONMENT=production` in `.env`
- [ ] Configure `ALLOWED_HOSTS` and `CORS_ORIGINS` for your domain
- [ ] Review password policy settings (min length, complexity requirements)
- [ ] Enable audit logging and configure log retention
- [ ] Use HTTPS/TLS for all external connections
- [ ] Secure Redis instance with authentication if exposed
- [ ] Set appropriate `SESSION_TIMEOUT_MINUTES` for your use case

### Scalability

- **Target load**: 100 concurrent users, ~10 processes each
- **Database**: SQLite suitable for moderate loads; migrate to PostgreSQL for high concurrency
- **Workers**: Scale Celery workers horizontally as needed
- **Rate limiting**: Configured per process to respect myMoment platform limits
- **Session management**: Automatic cleanup with configurable intervals

### Monitoring

- **Logs**: Structured logging via Loguru with rotation (see `LOG_FILE_*` settings)
- **Health checks**: Built-in process health monitoring
- **Metrics**: Process execution time, comment generation success rate, session lifecycle
- **Alerts**: Configure Sentry integration for error tracking (optional)

### Operational Notes

- Monitoring processes enforce strict `max_duration_minutes` limits with immediate shutdown
- Article filtering supports category (numeric) and tag (slug) filters
- All sensitive data (credentials, API keys) encrypted at rest with Fernet
- Session cleanup runs automatically based on `SESSION_CLEANUP_INTERVAL_MINUTES`

## Architecture

See `AGENTS.md` for detailed codebase architecture and development guidelines.

## License

[Specify your license here]
