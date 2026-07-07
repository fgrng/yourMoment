# yourMoment Codebase Guide

**Project**: yourMoment
**Type**: Production-ready Python web application with server-side rendered frontend
**Purpose**: AI-powered monitoring and automation for myMoment writing platform

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

## Project Structure

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
└── unit/           # Isolated component tests (the rebuilt suite lives here)
```

## Common Commands

```bash
# Activate virtual environment first (required for all commands below)
source .venv/bin/activate

# Install dependencies (clean env). requirements.txt has NO test runner;
# use requirements-dev.txt (or `pip install -e '.[test]'`) to run the suite.
pip install -r requirements-dev.txt

# Run tests
pytest tests/unit -q            # Unit tests

# Database migrations
python cli.py db migrate        # Run pending migrations (loads .env → correct DB file)
alembic revision -m "description"  # Create new migration
# ⚠️  NEVER run `alembic upgrade head` directly — it does not load .env and
#    will migrate yourmoment.db (alembic.ini default) instead of the active
#    DB file set by DB_SQLITE_FILE in .env (e.g. yourmoment_development.db).
```

## Coding Agent Guidance

### Issue tracker

Issues live as GitHub issues in `fgrng/yourMoment`; external PRs are also a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical labels. Agent provider support is detailed here. See `docs/agents/triage.md`.

