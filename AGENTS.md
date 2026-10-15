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
├── platforms/      # Platform interface (ADR-0001): connect(), typed results/errors, myMoment adapter
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

Dependencies live only in `pyproject.toml` (runtime in `[project] dependencies`, tooling in the `dev` dependency group) and are locked in `uv.lock`. Run every command through `uv run`; it uses the project's `.venv` and keeps it in sync with the lockfile.
The pre-commit hook (`.githooks/pre-commit`) runs `uv run ruff check` and `uv run ruff format --check` on every commit; fix formatting with `uv run ruff format`.

```bash
# Install dependencies (clean env); includes the dev group with pytest and ruff
uv sync
uv add <pkg> / uv add --dev <pkg>   # Add a dependency; updates pyproject.toml and uv.lock

# Run tests
uv run pytest tests/unit -q     # Unit tests

# Database migrations
uv run python cli.py db migrate # Run pending migrations (loads .env → correct DB file)
uv run alembic revision -m "description"  # Create new migration
# ⚠️  NEVER run `alembic upgrade head` directly — it does not load .env and
#    will migrate yourmoment.db (alembic.ini default) instead of the active
#    DB file set by DB_SQLITE_FILE in .env (e.g. yourmoment_development.db).
```

### Sandcastle (autonomous agents)

`.sandcastle/` holds a [Sandcastle](https://github.com/mattpocock/sandcastle) driver that works open issues labelled `ready-for-agent` (not `Spec`, not blocked) in Docker sandboxes: plan, implement, review, merge, then a PR per integration branch. Coding standards the reviewer enforces live in `CODING_STANDARDS.md`. Prerequisites: Node, Docker, and credentials from `.sandcastle/.env.example` copied to `.sandcastle/.env`.

```bash
npm install
npm run sandcastle:build-image      # required once, and after changes to .sandcastle/Dockerfile or uv.lock
npm run sandcastle                  # Claude Code line-up (default)
npm run sandcastle:codex            # Codex line-up
npm run sandcastle -- --spec <n>    # only spec <n>: its sub-issues, only spec/<n>
npm run sandcastle:refresh-tools    # rebuild only the Codex / Claude Code layers of the image
npm run test:sandcastle             # the driver's own tests (fakes, no Docker)
```

Branch and closing rules are in `docs/agents/issue-tracker.md` (section "Finishing work").

## Agent skills

### Issue tracker

Issues live as GitHub issues in `fgrng/yourMoment` (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
