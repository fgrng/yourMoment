# yourMoment

AI-powered monitoring and comment automation platform for the myMoment writing community. Automates article discovery, generates context-aware LLM-generated comments, and manages multiple monitoring workflows.

This software project was developed as [part of the DEEP myMoment research and development project](https://deep-consortium.ch/en/project/deep-mymoment) which itself is a member of the [DEEP research consortium](https://deep-consortium.ch/en/about) that explores how digital transformation can promote equitable and effective learning in Swiss primary education. The development lead was located at [St.Gallen University of teacher education](https://www.phsg.ch/de/forschung-entwicklung/projekte/deep-digital-literacy-participation-writing-platform-mymoment).

This [linked preprint provides a preliminary overview of the yourMoment platform concept](https://www.researchgate.net/publication/399564199_Social_Feedback_and_Simulated_Audiences_A_Proof-of-Concept_for_Persona-Based_LLM_Feedback_in_Writing_Instruction).

(This is also my personal learning project for LLM-driven software engineering tools like Claude Code, spec-kit and alike.)

## The context of myMoment

myMoment is a digital writing platform that encourages creative and reflective writing among primary school students. Originally launched in 2005, it was developed to support open, community-based writing in a safe online environment. Over time, it has evolved through collaborations with teachers, the “Zentrum Lesen,” and imedias (PH FHNW), aiming to strengthen students’ writing skills, media literacy, and engagement through peer feedback and collaborative writing activities.

The platform allows students to draft, publish, and share their texts within their class or across the broader myMoment community. Teachers moderate publication and feedback, helping to build a culture of writing as a social practice rather than an isolated task. Alongside this, myMoment includes teacher resources—tutorials, lesson ideas, and professional development materials to support meaningful classroom integration.

In its current form, myMoment is being developed further as part of the DEEP myMoment research and development project. Within this framework, myMoment functions as both a learning tool and a research platform that investigates how digital writing environments can foster participation, creativity, and literacy development.

# Overview of the yourMoment project

yourMoment enables teachers and researchers to monitor myMoment articles and automatically generate LLM-powered comments using their preferred LLM providers (like OpenAI or Mistral). The platform handles authenticated scraping, comment generation with customizable prompts, and process orchestration through a simple web interface.

## Key Features

- **Multi-user architecture** – Isolated workflows with per-user LLM configurations, credentials, and templates
- **Basic security** – JWT authentication, Fernet encryption for sensitive data and configurable password policies
- **LLM provider flexibility** – Support for OpenAI, Mistral. Other providers will be available in the future.
- **Customizable templates** – System and user-defined prompt templates with validation and required AI disclosure prefix
- **Automated monitoring** – Background processes with configurable duration limits, multi-credential fan-out, and (hopefully) graceful shutdown
- **Article management** – Comprehensive article browsing with category (leaning tasks in myMoment) and tag (classroom in myMoment) filtering
- **Somewhat Production-ready** – Type-safe configuration, health checks and logging

See `AGENTS.md` for the condensed architecture brief used by AI assistants.

See also the detailed [documentation of the API layer](./README_API.md), the [business logic layer](./README_SERVICES.md) and the [layer of the Celery-based background tasks](./README_TASKS.md).

## Stack

| Layer | Technologies |
|-------|--------------|
| API & services | FastAPI, SQLAlchemy (async), Alembic |
| Background jobs | Celery 5 + Redis broker/result store |
| Scraping | aiohttp, BeautifulSoup4 |
| LLM integration | instructor library |
| UI | Jinja2 templates, Bootstrap 5, vanilla JS (fetch) |
| Storage | SQLite by default (PostgreSQL/MySQL compatible) |

## Quick Start

### Prerequisites

- Python 3.11+
- Redis (optional, required for background workers)

### Installation

```bash
# Clone and setup virtual environment (recommeded)
git clone <repo>
cd yourMoment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your configuration (see Configuration section)

# Initialize database and seed development data
python cli.py db migrate
python cli.py db seed  # Creates system templates + test user in development

# Start development server
python cli.py server
```

Access the application at `http://localhost:8000` (UI) and `http://localhost:8000/api/v1/docs` (API docs).

**Development test credentials:**
- Email: `test@yourmoment.dev`
- Password: `Valid!Password123`

**Note:** The seed command is environment-aware. In production (`ENVIRONMENT=production`), it only creates system templates and prompts you to use `python cli.py user create` for secure user creation. This is mandatory since user creation with email validation is not implemted in yourMoment right now.

### Background Workers (Optional)

For automated monitoring processes, start Celery workers:

```bash
# Terminal 1: Worker
python cli.py worker

# Terminal 2: Beat scheduler
python cli.py scheduler
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

The test suite 

**Unit Tests** – Isolated component testing:
```bash
pytest tests/unit -q
```

**Contract Tests** – API endpoint validation with full app bootstrap:
```bash
pytest tests/contract -q
```

**Integration Tests** – Multi-step workflows (may require Celery):
```bash
pytest tests/integration -q
```

**Performance Tests** – External endpoints testing (myMoment platform, LLM poviders):
```bash
pytest tests/performance -q
```


### Test Configuration

Tests use isolated configuration:
- Separate SQLite database (`yourMoment_testing.db`)
- Dedicated Redis database (db 1)
- Test-specific encryption keys
- Minimal logging output

Set `ENVIRONMENT=testing` for test-specific behavior.

## Management CLI

yourMoment includes a unified `cli.py` script for all management operations. See [CLI.md](./CLI.md) for complete documentation.

**Common commands:**
```bash
# Server management
python cli.py server                    # Start web server
python cli.py worker                    # Start Celery worker
python cli.py scheduler                 # Start beat scheduler

# Database operations
python cli.py db migrate                # Run migrations
python cli.py db seed                   # Seed test data
python cli.py db stats                  # Show statistics
python cli.py db reset                  # Reset database (⚠️ destructive)

# User management
python cli.py user create               # Create new user

# Celery monitoring
python cli.py celery info               # Show configuration
python cli.py celery health             # Check health
python cli.py celery clear              # Clear queues
```

## Production Considerations

### Security Checklist

- [ ] Generate and set strong `SECRET_KEY`, `JWT_SECRET`, and `YOURMOMENT_ENCRYPTION_KEY`
- [ ] Set `ENVIRONMENT=production` in `.env`
- [ ] Configure `ALLOWED_HOSTS` and `CORS_ORIGINS` for your domain
- [ ] Review password policy settings (min length, complexity requirements)
- [ ] Enable audit logging and configure log retention
- [ ] Use HTTPS/TLS for all external connections
- [ ] Secure Redis instance with authentication (if exposed)
- [ ] Set appropriate `SESSION_TIMEOUT_MINUTES` for your use case

### Production Deployment

```bash
# 1. Web server (use --workers for multi-process)
ENVIRONMENT=production python cli.py server --workers 4

# 2. Celery workers (multiple instances for scalability)
python cli.py worker --concurrency 4

# 3. Beat scheduler (single instance only)
python cli.py scheduler
```

See [CLI.md](./CLI.md) for systemd service examples configuration.

## Architecture

See `AGENTS.md` for detailed codebase architecture and development guidelines.

## License

### Application Code

Application code is released under the permissive [MIT License](./LICENSE), enabling unrestricted use, modification, and distribution.

### Static Assets and bundled Prompt Templates

Static assets and bundled prompt templates (files in `static/` and `templates/prompt_templates/`) are provided under the [Creative Commons Attribution 4.0 International License (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/). When reusing these assets or templates, you must provide appropriate credit, include a link to the license, and indicate if changes were made. A suggested attribution statement is:

> "Includes assets and prompt templates from the yourMoment project (https://github.com/yourMoment/yourMoment) licensed under CC BY 4.0."

For the full legal text of the license, visit the [CC BY 4.0 legal code](https://creativecommons.org/licenses/by/4.0/legalcode).
