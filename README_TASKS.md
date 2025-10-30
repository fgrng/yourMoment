# yourMoment Background Tasks

Celery-based background task processing system for the yourMoment application.

## Overview

The background task system provides asynchronous execution using a **parallel pipeline architecture** with four independent stages:

- **Article Discovery** – Scrape myMoment article metadata and create work items
- **Article Preparation** – Fetch full article content for discovered items
- **Comment Generation** – AI-powered comment creation using configured LLM providers
- **Comment Posting** – Publishing generated comments to myMoment
- **Session Management** – myMoment login session lifecycle and cleanup
- **Timeout Enforcement** – Automatic process termination based on duration limits (FR-008)

### Architecture Diagram

```
API Layer: POST /start-process
    ↓
MonitoringService.start_process()
    ↓
[Spawn 4 Tasks in Parallel]
    ├─→ discover_articles task (queue: discovery)
    ├─→ prepare_content_of_articles task (queue: preparation)
    ├─→ generate_comments_for_articles task (queue: generation)
    └─→ post_comments_for_articles task (queue: posting)

Each task polls for work via AIComment.status:
    Discovery Stage          Preparation Stage        Generation Stage       Posting Stage
    ┌─────────────────────┐  ┌────────────────────┐   ┌──────────────────┐  ┌──────────────────┐
    │  discover_articles  │  │  prepare_content   │   │  generate_comment│  │  post_comments   │
    │  ├─ Scrape articles │  │  ├─ Fetch content  │   │  ├─ Call LLM     │  │  ├─ Post to myMoment
    │  └─ status:'disc'   │→ │  └─ status:'prep'  │→ │  └─ status:'gen' │→ │  └─ status:'posted'
    └─────────────────────┘  └────────────────────┘   └──────────────────┘  └──────────────────┘
         ↓                           ↓                        ↓                      ↓
      AIComment                  AIComment                AIComment            AIComment
      Database Coordination       Database Coordination    Database Coordination Database Coordination

Continuous Monitoring (Celery Beat):
    Every 60 seconds (configurable): trigger_monitoring_pipeline
    ├─ Find all running processes
    ├─ Check if each stage task is already running
    └─ Respawn only if previous iteration completed

Timeout Enforcement (Celery Beat):
    Every 30 seconds (configurable): check_process_timeouts
    ├─ Check all running processes
    ├─ Compare elapsed time vs max_duration_minutes
    └─ Revoke all 4 stage tasks if exceeded
```

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

**Pipeline Stage Tasks** (run in parallel, coordinate via AIComment.status)
- `discover_articles` (discovery queue) – Scrape article metadata, create AIComment records with status='discovered'
- `prepare_content_of_articles` (preparation queue) – Fetch full article content, update status='prepared'
- `generate_comments_for_articles` (generation queue) – Generate AI comments via LLM, update status='generated'
- `post_comments_for_articles` (posting queue) – Post to myMoment, update status='posted' or 'failed'

**Session Management** (`sessions` queue)
- `cleanup_expired_sessions` – Remove expired myMoment session records
- `cleanup_old_session_records` – Archive old session data

**Timeout Enforcement** (`timeouts` queue)
- `check_process_timeouts` – Enforce max_duration_minutes limits, revoke all 4 stage tasks on timeout

**Continuous Monitoring** (`scheduler` queue)
- `trigger_monitoring_pipeline` – Periodic task spawner (configurable interval) for continuous monitoring

### Task Queues

| Queue | Purpose | Task Modules | Concurrency |
|-------|---------|--------------|-------------|
| `discovery` | Article metadata scraping | `article_discovery.*` | 1-2 (network-bound) |
| `preparation` | Article content fetching | `article_preparation.*` | 1-2 (network-bound) |
| `generation` | LLM comment generation | `comment_generation.*` | 2-4 (I/O-bound) |
| `posting` | Comment posting to myMoment | `comment_posting.*` | 1-2 (network-bound) |
| `sessions` | Session lifecycle management | `session_manager.*` | 1 (low volume) |
| `timeouts` | Duration enforcement | `timeout_enforcer.*` | 1 (low volume) |
| `scheduler` | Continuous monitoring | `scheduler.*` | 1 (low volume) |
| `celery` | Default queue | Miscellaneous | - |

### Periodic Tasks (Celery Beat)

| Task | Schedule | Description |
|------|----------|-------------|
| `check-process-timeouts` | Every 30s (configurable) | Enforce max_duration_minutes limits, revoke stage tasks on timeout |
| `cleanup-expired-sessions` | Every 5 min | Remove expired myMoment session records |
| `trigger-monitoring-pipeline` | Every 60s (configurable) | Spawn pipeline stage tasks for running processes (continuous monitoring) |

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
- Task soft time limit: 3 hours (for long-running monitoring processes)
- Task hard time limit: 6 hours (absolute maximum)
- Worker tasks per child: 100 (auto-restart after 100 tasks to prevent memory leaks)

**Reliability**
- Prefetch multiplier: 1 (one task at a time for resource control)
- Acks late: True (acknowledge after successful completion)
- Result expiration: 24 hours (preserve task results for API status queries)

**Periodic Task Intervals** (configurable via environment variables)
- `PROCESS_HEALTH_CHECK_INTERVAL_SECONDS` – Check process timeouts (default: 30 seconds)
- `ARTICLE_DISCOVERY_INTERVAL_SECONDS` – Trigger monitoring pipeline (default: 60 seconds)
- Session cleanup interval is hardcoded to 300 seconds (5 minutes)

**Task Routing** (parallel architecture)
Tasks are automatically routed by module name:
- `article_discovery.*` → `discovery` queue
- `article_preparation.*` → `preparation` queue
- `comment_generation.*` → `generation` queue
- `comment_posting.*` → `posting` queue
- `session_manager.*` → `sessions` queue
- `timeout_enforcer.*` → `timeouts` queue
- `scheduler.*` → `scheduler` queue


## Task Workflow

### Monitoring Process Lifecycle

1. **Start Process** (via API: `POST /api/v1/monitoring-processes/{id}/start`)
   - API calls `MonitoringService.start_process(process_id)`
   - **Spawns all 4 pipeline tasks in parallel** (no sequential orchestration)
   - Each task gets unique Celery task ID, stored in MonitoringProcess
   - Process status set to "running"

2. **Continuous Monitoring Loop** (via Celery Beat)
   - `trigger_monitoring_pipeline` runs at configurable interval (default 60 seconds)
   - Checks each running process
   - Respawns stage tasks only if previous iteration completed
   - Prevents double-spawning via task state checking

3. **Article Discovery Stage** (`discover_articles` task)
   - Scrapes article metadata from each associated login
   - Creates AIComment records with status='discovered'
   - Creates cross-product: articles × logins × prompts
   - No external I/O within database transactions

4. **Article Preparation Stage** (`prepare_content_of_articles` task)
   - Polls for AIComments with status='discovered'
   - Fetches full article content for each
   - Updates AIComment with content, sets status='prepared'
   - Per-article error isolation (failures don't cascade)

5. **Comment Generation Stage** (`generate_comments_for_articles` task)
   - Polls for AIComments with status='prepared'
   - Calls LLM provider for each article
   - Caches LLM configs and prompt templates in memory
   - Updates AIComment with generated text, sets status='generated'
   - Per-article LLM error handling

6. **Comment Posting Stage** (`post_comments_for_articles` task)
   - Polls for AIComments with status='generated'
   - Posts to myMoment via each associated login
   - Caches login credentials in memory
   - Updates status='posted' on success, 'failed' on error
   - Exponential backoff retry (max 3 attempts)
   - Optional if `generate_only=True` (task not spawned)

7. **Timeout Enforcement** (runs at configurable interval, default 30s)
   - `check_process_timeouts` queries all running processes
   - Compares elapsed time against `max_duration_minutes`
   - **Revokes all 4 stage tasks** if exceeded (uses stage-specific task IDs)
   - Updates process status to "stopped"

8. **Stop Process** (via API or automatic timeout)
   - API calls `MonitoringService.stop_process(process_id)`
   - **Revokes all 4 active stage tasks** (discovery, preparation, generation, posting)
   - Updates process status to "stopped"
   - Sessions cleanup handled by `cleanup_expired_sessions` (5-minute schedule)

## Database Session Management

The pipeline tasks use optimized database session patterns to minimize lock contention:

### Session Patterns

**Pattern 1: Read-Only Config** (< 100ms)
- Used by: Article discovery (reading process config)
- Session: Opens → reads data → closes immediately
- I/O: Happens AFTER session closes

**Pattern 2: Batch Write** (single transaction)
- Used by: Article discovery (creating AIComment records)
- Session: Opens → batch insert → commit → closes
- Benefit: Single commit for many records

**Pattern 3: Iterative Single Updates** (< 50ms per update)
- Used by: Preparation, generation, posting stages
- Session: For each record: open → update → commit → close
- Benefit: No long-lived locks, failures isolated per record

**Pattern 4: Batch Read + Cached Data** (< 500ms total)
- Used by: Generation and posting stages
- Process:
  1. Open session → read all items to process
  2. Close session
  3. Extract unique foreign key IDs from memory
  4. Open session → read reference data (LLM configs, templates, logins)
  5. Close session
  6. Cache reference data in memory
  7. Process items using cached data (no DB access)

### Key Benefits
- **Short transactions**: All DB sessions < 500ms
- **No blocking I/O**: Network operations outside sessions
- **Predictable pool usage**: Connections released quickly
- **Better scalability**: Can handle many concurrent processes

See `TODO_refactor_monitoring.md` lines 212-394 for detailed examples.

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

