# yourMoment Background Tasks

Celery-based background task processing system for the yourMoment application.

## Overview

The background task system provides asynchronous execution for:

- **Article Monitoring** – Scraping myMoment platform for new articles
- **Comment Generation** – AI-powered comment creation using configured LLM providers
- **Comment Posting** – Publishing generated comments to myMoment
- **Session Management** – myMoment login session lifecycle and cleanup
- **Timeout Enforcement** – Automatic process termination based on duration limits
- **Health Monitoring** – Periodic system health checks and maintenance

## Quick Start

### 1. Start Redis (required)

```bash
# Using Docker
docker run -d --name redis -p 6379:6379 redis:7-alpine

# Or using Docker Compose (recommended)
docker-compose -f docker-compose.celery.yml up -d redis
```

### 2. Start Celery Worker

```bash
# Basic worker (all queues)
python celery_cli.py worker

# Worker with specific queues
python celery_cli.py worker --queues monitoring,comments

# Worker with custom concurrency
python celery_cli.py worker --concurrency 8
```

### 3. Start Celery Beat (for periodic tasks)

```bash
python celery_cli.py beat
```

### 4. Monitor Tasks (optional)

```bash
# CLI monitoring
python celery_cli.py monitor

# Web-based monitoring (Flower)
docker-compose -f docker-compose.celery.yml up -d celery_monitor
# Then visit http://localhost:5555
```

## Task Architecture

### Registered Tasks

**Article Monitoring** (`monitoring` queue)
- `start_monitoring_process` – Initialize monitoring workflow for a process
- `stop_monitoring_process` – Terminate monitoring workflow
- `periodic_monitoring_check` – Scheduled article discovery
- `cleanup_old_articles` – Remove old article/comment records

**Comment Generation & Posting** (`comments` queue)
- `generate_comments_for_process` – Generate AI comments using LLM providers
- `post_comments_for_process` – Post generated comments to myMoment

**Session Management** (`sessions` queue)
- `initialize_process_sessions` – Create myMoment sessions for process credentials
- `terminate_process_sessions` – Close all sessions for a process
- `cleanup_expired_sessions` – Remove expired session records
- `cleanup_old_session_records` – Archive old session data
- `health_check_sessions` – Verify session health

**Timeout Enforcement** (`timeouts` queue)
- `check_process_timeouts` – Enforce max_duration_minutes limits

**System Scheduler** (`scheduler` queue)
- `health_check_monitoring_processes` – Process health status checks
- `system_maintenance` – Coordinate maintenance tasks

### Task Queues

| Queue | Purpose | Task Modules |
|-------|---------|--------------|
| `monitoring` | Article discovery & scraping | `article_monitor.*` |
| `comments` | AI comment workflow | `comment_generator.*`, `comment_poster.*` |
| `sessions` | Session lifecycle | `session_manager.*` |
| `timeouts` | Duration enforcement | `timeout_enforcer.*` |
| `scheduler` | Maintenance & health | `scheduler.*` |
| `celery` | Default queue | Miscellaneous tasks |

### Periodic Tasks (Celery Beat)

| Task | Schedule | Description |
|------|----------|-------------|
| `check-process-timeouts` | Every 60s | Enforce max_duration_minutes limits |
| `cleanup-expired-sessions` | Every 5 min | Remove expired myMoment sessions |
| `health-check-monitoring` | Every 2 min | Check process and session health |

## Configuration

### Environment Variables

Set in `.env` file or environment:

```bash
# Redis connection (required for Celery)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Worker configuration
CELERY_WORKER_CONCURRENCY=4  # Number of worker processes
```

### Task Settings (in `src/tasks/worker.py`)

**Execution Limits**
- Task soft time limit: 300s (5 minutes)
- Task hard time limit: 600s (10 minutes)
- Worker tasks per child: 100 (auto-restart after 100 tasks)

**Reliability**
- Prefetch multiplier: 1 (one task at a time for better control)
- Acks late: True (acknowledge after completion)
- Result expiration: 3600s (1 hour)

**Routing**
Tasks are automatically routed by module name:
- `article_monitor.*` → `monitoring` queue
- `comment_generator.*`, `comment_poster.*` → `comments` queue
- `session_manager.*` → `sessions` queue
- `timeout_enforcer.*` → `timeouts` queue
- `scheduler.*` → `scheduler` queue

## Development

### CLI Commands

The `celery_cli.py` script provides convenient management commands:

```bash
# Worker management
python celery_cli.py worker                    # Start worker (all queues)
python celery_cli.py worker --loglevel debug   # Debug logging
python celery_cli.py worker --queues monitoring,comments  # Specific queues
python celery_cli.py worker --concurrency 8    # Custom concurrency

# Scheduler
python celery_cli.py beat                      # Start beat scheduler

# Monitoring
python celery_cli.py monitor                   # CLI monitoring
python celery_cli.py health                    # Health check
python celery_cli.py info                      # Task and queue info

# Debugging
python celery_cli.py purge                     # Clear all queues
```

### Task Information

```bash
# Get registered tasks and queue information
python -c "
import sys
sys.path.insert(0, 'src')
from tasks.worker import get_task_info
import json
print(json.dumps(get_task_info(), indent=2))
"
```

### Testing Tasks

```bash
# Test individual task execution
PYTHONPATH=src python -c "
from tasks.scheduler import health_check_monitoring_processes
result = health_check_monitoring_processes.delay()
print(f'Task ID: {result.id}')
print(f'Status: {result.status}')
"
```

## Production Deployment

### Horizontal Scaling

**Multiple Workers**
```bash
# Scale workers for different workloads
python celery_cli.py worker --queues monitoring --concurrency 4 &
python celery_cli.py worker --queues comments --concurrency 8 &
python celery_cli.py worker --queues sessions,timeouts --concurrency 2 &
```

**Resource Allocation**
- `monitoring` queue: CPU-intensive (web scraping) – moderate concurrency
- `comments` queue: I/O-intensive (LLM API calls) – higher concurrency
- `sessions`/`timeouts`: Low load – minimal workers needed

### Process Management

**Systemd** (recommended for production)
```ini
# /etc/systemd/system/yourmoment-celery-worker.service
[Unit]
Description=yourMoment Celery Worker
After=network.target redis.service

[Service]
Type=forking
User=yourmoment
WorkingDirectory=/opt/yourmoment
Environment="PATH=/opt/yourmoment/.venv/bin"
ExecStart=/opt/yourmoment/.venv/bin/python celery_cli.py worker --loglevel info
Restart=always

[Install]
WantedBy=multi-user.target
```

**Supervisor** (alternative)
```ini
[program:yourmoment-celery-worker]
command=/opt/yourmoment/.venv/bin/python celery_cli.py worker
directory=/opt/yourmoment
user=yourmoment
autostart=true
autorestart=true
```

### Monitoring

**Flower Web UI** (if docker-compose.celery.yml available)
```bash
docker-compose -f docker-compose.celery.yml up -d celery_monitor
# Access at http://localhost:5555
```

**Redis Monitoring**
```bash
redis-cli monitor                # Real-time command monitoring
redis-cli info clients           # Client connections
redis-cli --stat                 # Stats every second
```

**Health Checks**
```bash
# Application health check
curl http://localhost:8000/health

# Celery health (programmatic)
python celery_cli.py health
```

## Troubleshooting

### Redis Connection Issues

**Problem**: `Cannot connect to broker`
```bash
# Verify Redis is running
redis-cli ping  # Should return "PONG"

# Check connection settings
echo $CELERY_BROKER_URL
echo $CELERY_RESULT_BACKEND

# Test connection
python -c "
import redis
r = redis.from_url('redis://localhost:6379/0')
print(r.ping())
"
```

### Task Execution Issues

**Problem**: Tasks not being picked up
```bash
# Verify worker is running and consuming from correct queues
python celery_cli.py info

# Check queue contents
redis-cli llen monitoring    # Check monitoring queue depth
redis-cli llen comments      # Check comments queue depth

# Restart workers
pkill -f "celery worker" && python celery_cli.py worker &
```

**Problem**: Tasks hanging or timing out
```bash
# Check task time limits in worker.py:
# - Soft limit: 300s (5 min)
# - Hard limit: 600s (10 min)

# View active tasks
python celery_cli.py monitor

# Increase limits if needed (in src/tasks/worker.py)
task_soft_time_limit = 600  # 10 minutes
task_time_limit = 1200      # 20 minutes
```

### Memory Issues

**Problem**: Worker consuming excessive memory
```bash
# Reduce concurrency
CELERY_WORKER_CONCURRENCY=2 python celery_cli.py worker

# Note: Workers auto-restart after 100 tasks (configured)
# Check current setting in worker.py:
# worker_max_tasks_per_child = 100
```

### Database Lock Issues

**Problem**: SQLite database locked errors
```bash
# This happens with high concurrency on SQLite
# Solutions:
# 1. Reduce worker concurrency to 1-2
CELERY_WORKER_CONCURRENCY=1 python celery_cli.py worker

# 2. Migrate to PostgreSQL for production
# Update DB_SQLITE_FILE in .env or set DATABASE_URL
```

### Beat Scheduler Issues

**Problem**: Periodic tasks not running
```bash
# Check beat is running
ps aux | grep "celery beat"

# Start beat if not running
python celery_cli.py beat &

# Verify schedule
python -c "
import sys
sys.path.insert(0, 'src')
from tasks.worker import CeleryConfig
print(CeleryConfig.beat_schedule)
"
```

### Debugging Tools

```bash
# Enable debug logging
python celery_cli.py worker --loglevel debug

# Monitor all task events
python celery_cli.py monitor --refresh 0.5

# Clear stuck tasks (use with caution!)
python celery_cli.py purge

# Inspect active workers
celery -A src.tasks.worker inspect active

# View worker stats
celery -A src.tasks.worker inspect stats
```

## Task Workflow

### Monitoring Process Lifecycle

1. **Start Process** (via API: `POST /api/v1/monitoring-processes/{id}/start`)
   - API dispatches: `start_monitoring_process.delay(process_id)`
   - Task initializes sessions: `initialize_process_sessions`
   - Begins periodic monitoring loop

2. **Article Discovery**
   - `periodic_monitoring_check` runs at configured intervals
   - Scrapes articles from myMoment
   - Stores new articles in database

3. **Comment Generation**
   - `generate_comments_for_process` triggered for new articles
   - Uses LLM provider configurations
   - Applies prompt templates
   - Stores generated comments

4. **Comment Posting**
   - `post_comments_for_process` publishes to myMoment
   - Respects rate limits
   - Updates comment status

5. **Timeout Enforcement**
   - `check_process_timeouts` runs every 60s
   - Compares runtime against `max_duration_minutes`
   - Dispatches `stop_monitoring_process` if exceeded

6. **Stop Process** (via API or timeout)
   - Terminates monitoring loop
   - Closes sessions: `terminate_process_sessions`
   - Updates process status to "stopped"

## Security & Best Practices

### Production Security

- **Redis**: Use password authentication (`requirepass` in redis.conf)
- **Network**: Bind Redis to localhost only or use firewall rules
- **TLS**: Use `rediss://` for encrypted connections if Redis is remote
- **Task Results**: Contain sensitive data – configured to expire after 1 hour
- **Credentials**: myMoment credentials encrypted in database, decrypted only during task execution

### Resource Management

- **Concurrency**: Adjust per queue based on workload characteristics
- **Memory**: Workers auto-restart after 100 tasks to prevent leaks
- **Database**: Consider PostgreSQL for >10 concurrent workers
- **Monitoring**: Track queue depth and task execution time

### Logging

- Task execution logged with task ID, args, and state
- Failed tasks log full exception info
- Logs available via Celery CLI or application logs (`logs/app.log`)

### Environment Isolation

Development and production use separate Redis databases:
- Development: `redis://localhost:6379/0`
- Testing: `redis://localhost:6379/1`
- Production: Configure separately with authentication