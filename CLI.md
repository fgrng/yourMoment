# yourMoment CLI Documentation

The `cli.py` script is the unified management interface for yourMoment. It consolidates server management, worker management, database operations, and system administration into a single, production-ready tool.

## Quick Start

```bash
# Start the web server (development mode with auto-reload)
uv run python cli.py server

# Start the web server (production mode)
ENVIRONMENT=production uv run --no-dev python cli.py server --workers 4

# Start a Celery worker
uv run python cli.py worker

# Start the Celery beat scheduler
uv run python cli.py scheduler

# Run database migrations
uv run python cli.py db migrate

# Seed database with test data
uv run python cli.py db seed
```

## Command Reference

### Server Commands

#### `uv run python cli.py server`
Start the web server (FastAPI/Uvicorn).

**Options:**
- `--host HOST` - Host to bind (default: 0.0.0.0)
- `--port PORT` - Port to bind (default: 8000)
- `--workers N` - Number of workers for production (default: 4)
- `--loglevel LEVEL` - Log level: debug, info, warning, error (default: info)

**Behavior:**
- **Development mode** (`ENVIRONMENT=development`): Auto-reload enabled
- **Production mode** (`ENVIRONMENT=production`): Multi-worker, optimized for performance

**Example:**
```bash
# Development
uv run python cli.py server

# Production
ENVIRONMENT=production uv run --no-dev python cli.py server --workers 8 --port 8080
```

---

### Worker Commands

#### `uv run python cli.py worker`
Start a Celery worker for background task processing.

**Options:**
- `--loglevel LEVEL` - Log level (default: info)
- `--queues QUEUE [QUEUE ...]` - Specific queues to consume
- `--concurrency N` - Number of concurrent worker processes (default: 4)

**Example:**
```bash
# Start worker with default settings
uv run python cli.py worker

# Start worker for specific queues
uv run python cli.py worker --queues monitoring articles --concurrency 8

# Start worker with debug logging
uv run python cli.py worker --loglevel debug
```

#### `uv run python cli.py scheduler`
Start the Celery beat scheduler for periodic tasks.

**Options:**
- `--loglevel LEVEL` - Log level (default: info)

**Example:**
```bash
uv run python cli.py scheduler
```

---

### Database Commands

#### `uv run python cli.py db migrate`
Run Alembic database migrations to update schema to latest version.

**Example:**
```bash
uv run python cli.py db migrate
```

#### `uv run python cli.py db seed`
Seed database with essential data (environment-aware):

**Development mode** (`ENVIRONMENT=development`):
- System prompt templates
- Test user: `test@yourmoment.dev` / `Valid!Password123` (⚠️ development only!)

**Production mode** (`ENVIRONMENT=production`):
- System prompt templates only
- Requires confirmation before proceeding
- **Does NOT** create test users for security
- Use `uv run --no-dev python cli.py user create` to create production users securely

**Options:**
- `--force` - Force creation of test user even in production (⚠️ dangerous!)

**Examples:**
```bash
# Development: Creates templates + test user
uv run python cli.py db seed

# Production: Creates only templates (prompts for confirmation)
ENVIRONMENT=production uv run --no-dev python cli.py db seed

# Production: Force test user creation (NOT RECOMMENDED)
ENVIRONMENT=production uv run --no-dev python cli.py db seed --force
```

**Security Note:** In production, always use `uv run --no-dev python cli.py user create` to create users with secure, unique passwords.

#### `uv run python cli.py db reset`
**⚠️ DESTRUCTIVE:** Drop all tables, recreate schema, and seed with fresh data.

**Options:**
- `--force` - Skip confirmation prompt

**Example:**
```bash
# With confirmation
uv run python cli.py db reset

# Skip confirmation (dangerous!)
uv run python cli.py db reset --force
```

#### `uv run python cli.py db stats`
Show database statistics including counts of users, logins, comments, processes, and templates.

**Example:**
```bash
uv run python cli.py db stats
```

**Output:**
```
📊 Database Statistics:
   Users: 1
   MyMoment Logins: 2
   AI Comments: 15
     - generated: 3
     - posted: 10
     - failed: 2
   Monitoring Processes: 2
   Prompt Templates: 4
```

---

### User Commands

#### `uv run python cli.py user create`
Interactively create a new user account.

**Prompts:**
- Email
- Password
- Verified status (Y/n)

**Example:**
```bash
uv run python cli.py user create
```

---

### Celery Commands

#### `uv run python cli.py celery info`
Display Celery configuration including registered tasks, queues, and beat schedule.

**Example:**
```bash
uv run python cli.py celery info
```

**Output:**
```
=== Celery Configuration ===
Project tasks: 3
  - src.tasks.monitoring.run_monitoring_process
  - src.tasks.monitoring.stop_monitoring_process
  - src.tasks.health.check_process_health

Queues: 2
  - default
  - monitoring

Beat schedule: 1
  - health-check-schedule
```

#### `uv run python cli.py celery health`
Check Celery worker and broker health status.

**Example:**
```bash
uv run python cli.py celery health
```

**Output:**
```
=== Celery Health Check ===
Status: healthy
Broker connection: ok
Active workers: 2
Available queues: 2
  - default
  - monitoring
```

#### `uv run python cli.py celery clear`
Clear pending tasks from Celery queues.

**Options:**
- `--queue QUEUE` - Clear specific queue (default: all queues)

**Example:**
```bash
# Clear all queues
uv run python cli.py celery clear

# Clear specific queue
uv run python cli.py celery clear --queue monitoring
```

---

## Production Deployment

### Recommended Setup

**1. Web Server (multiple instances with load balancer)**
```bash
ENVIRONMENT=production uv run --no-dev python cli.py server --workers 4
```

**2. Celery Workers (multiple instances for scalability)**
```bash
uv run --no-dev python cli.py worker --concurrency 4
```

**3. Celery Beat Scheduler (single instance only)**
```bash
uv run --no-dev python cli.py scheduler
```

**4. Initial Database Setup**
```bash
# Run migrations
uv run --no-dev python cli.py db migrate

# Seed system templates (production-safe)
ENVIRONMENT=production uv run --no-dev python cli.py db seed

# Create first admin user securely
uv run --no-dev python cli.py user create
```

### Systemd Service Examples

The services call `.venv/bin/python` directly. Build that virtualenv on the server from `uv.lock` without the dev tooling:

```bash
uv sync --no-dev
```

**Web Server** (`/etc/systemd/system/yourmoment-web.service`):
```ini
[Unit]
Description=yourMoment Web Server
After=network.target

[Service]
Type=simple
User=yourmoment
WorkingDirectory=/opt/yourmoment
Environment="ENVIRONMENT=production"
EnvironmentFile=/opt/yourmoment/.env
ExecStart=/opt/yourmoment/.venv/bin/python cli.py server --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
```

**Celery Worker** (`/etc/systemd/system/yourmoment-worker.service`):
```ini
[Unit]
Description=yourMoment Celery Worker
After=network.target redis.service

[Service]
Type=simple
User=yourmoment
WorkingDirectory=/opt/yourmoment
EnvironmentFile=/opt/yourmoment/.env
ExecStart=/opt/yourmoment/.venv/bin/python cli.py worker --concurrency 4
Restart=always

[Install]
WantedBy=multi-user.target
```

**Celery Beat** (`/etc/systemd/system/yourmoment-scheduler.service`):
```ini
[Unit]
Description=yourMoment Celery Beat Scheduler
After=network.target redis.service

[Service]
Type=simple
User=yourmoment
WorkingDirectory=/opt/yourmoment
EnvironmentFile=/opt/yourmoment/.env
ExecStart=/opt/yourmoment/.venv/bin/python cli.py scheduler
Restart=always

[Install]
WantedBy=multi-user.target
```

### Docker Compose Example

```yaml
version: '3.8'

services:
  web:
    build: .
    command: python cli.py server --workers 4
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=production
    env_file:
      - .env
    depends_on:
      - redis

  worker:
    build: .
    command: python cli.py worker --concurrency 4
    environment:
      - ENVIRONMENT=production
    env_file:
      - .env
    depends_on:
      - redis

  scheduler:
    build: .
    command: python cli.py scheduler
    environment:
      - ENVIRONMENT=production
    env_file:
      - .env
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

---

## Development Workflow

```bash
# 1. Set up database
uv run python cli.py db migrate
uv run python cli.py db seed

# 2. Start server (terminal 1)
uv run python cli.py server

# 3. Start worker (terminal 2)
uv run python cli.py worker

# 4. Start scheduler (terminal 3 - if needed)
uv run python cli.py scheduler

# 5. Check status
uv run python cli.py db stats
uv run python cli.py celery health
```

---

## Troubleshooting

### Database Issues
```bash
# Check database stats
uv run python cli.py db stats

# Reset database (⚠️ destructive)
uv run python cli.py db reset
```

### Celery Issues
```bash
# Check Celery health
uv run python cli.py celery health

# View Celery configuration
uv run python cli.py celery info

# Clear stuck tasks
uv run python cli.py celery clear
```

### Common Errors

**"No module named 'src'"**
- Ensure you're running from the project root directory
- The CLI automatically adds `src/` to Python path

**"Connection refused" (Celery)**
- Ensure Redis is running: `redis-cli ping`
- Check Redis URL in `.env` file

**"Database is locked" (SQLite)**
- Only occurs with SQLite under high concurrency
- Consider using PostgreSQL for production
- Reduce worker concurrency: `--concurrency 1`

---

## Migration from Old Scripts

The new `cli.py` replaces three previous scripts:

| Old Script | New Command |
|------------|-------------|
| `python manage.py run` | `uv run python cli.py server` |
| `python manage.py seed` | `uv run python cli.py db seed` |
| `python manage.py reset` | `uv run python cli.py db reset` |
| `python manage.py create-user` | `uv run python cli.py user create` |
| `python manage.py migrate` | `uv run python cli.py db migrate` |
| `python manage.py db-stats` | `uv run python cli.py db stats` |
| `python celery_cli.py worker` | `uv run python cli.py worker` |
| `python celery_cli.py beat` | `uv run python cli.py scheduler` |
| `python celery_cli.py info` | `uv run python cli.py celery info` |
| `python celery_cli.py health` | `uv run python cli.py celery health` |
| `python celery_cli.py clear` | `uv run python cli.py celery clear` |

All old scripts have been removed and replaced with this unified CLI.
