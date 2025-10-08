# Implementation Plan: Refactor Monitoring Tasks to Isolated Processes

Based on an analysis of the codebase, this comprehensive implementation plan to refactor the monitoring tasks into isolated, non-blocking processes was created.

## Current Architecture Issues

Problems identified:
1. article_monitor.py:244-335: Long database transaction holding session open while scraping articles (lines 279-295 fetch full article content inside the same transaction)
2. Task coupling: article_monitor directly schedules comment_generator, which schedules comment_poster - creates tight coupling
3. Blocking operations: ScraperService initialization and article fetching happens within database transactions
4. No granular retry: If one article scraping fails during discovery, the entire batch may be affected

## Proposed Architecture

Four Independent Celery Tasks

### Task 1: Article Discovery (discover_articles)

- Purpose: Scrape myMoment article index, create minimal AIComment records
- Input: monitoring_process_id for database lookup
- Database writes: Only basic metadata (no article_content, no article_raw_html)
- AIComment fields populated:
  - mymoment_article_id, article_title, article_author, article_category, article_url, article_edited_at
  - monitoring_process_id, user_id
  - mymoment_login_id, llm_provider_id
  - status='discovered', article_scraped_at
- Database session pattern: 
  Open session → Read MonitoringProcess → Read relationship ids with myMomentLogins and PromptTempplates (only ids necessary) → Close
  For each mymoment_login_id of MonitoringProcess:
    Scrape articles index (outside DB session)
    For each scraped article:
      For each prompt_template_id of MonitoringProcess:
        Prepare AIComment project (outside DB session)
  Open → Write batch → Close
- Output: discovered articles saved as AIComment records, no automatic scheduling

### Task 2: Article Content Preparation (prepare_content_of_articles)

- Purpose: Fetch detailed content for discovered articles
- Input: monitoring_process_id for database lookup for all discovered articles of MonitoringProcess with status 'discovered'
- Database writes: Update AIComment record for ONE article at a time.
- AIComment fields populated:
  - article_content, article_raw_html, article_published_at, 
  - Update article_scraped_at, keep status='discovered'
- Database session pattern:
  Open session → Read discovered AIComments → Close
  For each discovered article:
  a. Scrape article (outside DB session)
  b. Open session → Update AIComment → Close (< 0.1s)
- Error handling: Mark individual AIComment as failed, don't affect others
- Output: prepared articles updated as AIComment records, no automatic scheduling

### Task 3: AI Comment Generation (generate_comments_for_articles)

- Purpose: Generate AI comment for prepared articles
- Input: monitoring_process_id for database lookup for all prepared articles of MonitoringProcess with status 'prepared'
- Database writes: Update AIComment record with comment_content for ONE article at a time.
- AIComment fields populated:
  - comment_content
  - ai_model_name, ai_provider_name, generation_tokens, generation_time_ms
  - Update status='generated'
- Database session pattern:
  Open session → Read prepared AIComments → Close
  Identify list of unique used llm_provider_id and prompt_template_id (outside DB session)
  Open session → Read LLMProvider and PromptTemplates → Close
  Cash records of LLMProvider and PromptTemplates in memory
  For each prepared AIComment:
    Open session → Read AIComment → Close (necessary if AIComments read above?)
    Prepare / format user_prompt (outside DB session)
    Call LLM API (outside DB session)
    Open session → Update AIComment → Close
- Error handling: Mark as status='failed' with error_message
- Output: articles with generated comments updated as AIComment records, no automatic scheduling

### Task 4: Comment Posting (post_comments_for_articles)

- Purpose: post AI comment for commented (generated) articles
- Input: monitoring_process_id for database lookup for all commented articles of MonitoringProcess with status 'generated'
- Database writes: Update AIComment record with posting result for ONE article at a time.
- AIComment fields populated:
  - mymoment_comment_id, posted_at, status='posted'
  - OR: error_message, failed_at, status='failed', increment retry_count
- Database session pattern:
  Open session → Read generated AIComments → Close
  Identify list of unique used mymoment_login_id (outside DB session)
  Open session → Read myMomentLogins → Close
  Cash records of myMomentLogins in memory
  For each generated AIComment:
    Open session → Read AIComment → Close (necessary if AIComments read above?)
    Post to myMoment (outside DB session)
    Open session → Update AIComment status → Close (< 0.1s)
- Error handling: Automatic retry with exponential backoff (max 3 attempts)

## Orchestration Strategy (Orchestrator Task)

@celery_app.task(name='orchestrate_monitoring_process')
def orchestrate_monitoring_process(process_id: str, stage: str):
    """
    Orchestrate monitoring workflow stages:
    - stage='discover': Run discovery, then schedule preparation
    - stage='prepare': Check preparation completion, schedule generation
    - stage='generate': Check generation completion, schedule posting
    - stage='post': Monitor posting completion
    """
    
## Database Access Patterns

### Pattern 1: Read-Only Data Fetching
Used in Task 1 (discover_articles) for reading process configuration.

```python
async def read_process_config(process_id: uuid.UUID):
    db_manager = get_database_manager()
    sessionmaker = await db_manager.create_sessionmaker()

    async with sessionmaker() as session:
        # Read MonitoringProcess with relationships
        result = await session.execute(
            select(MonitoringProcess)
            .where(MonitoringProcess.id == process_id)
        )
        process = result.scalar_one()

        # Extract IDs for associated logins and prompt templates
        login_ids = await get_login_ids_for_process(session, process_id)
        prompt_ids = await get_prompt_ids_for_process(session, process_id)
        llm_provider_id = await get_llm_provider_id(session, process.user_id)

        # Create snapshot of configuration data
        config_snapshot = {
            'process_id': process_id,
            'user_id': process.user_id,
            'login_ids': login_ids,
            'prompt_ids': prompt_ids,
            'llm_provider_id': llm_provider_id,
            'tab_filter': process.tab_filter,
            'category_filter': process.category_filter
        }
    # Session closed automatically (< 100ms total)

    return config_snapshot
```

### Pattern 2: Batch Write Operations
Used in Task 1 (discover_articles) for creating AIComment records in bulk.

```python
async def batch_create_ai_comments(ai_comment_data_list: List[dict]):
    db_manager = get_database_manager()
    sessionmaker = await db_manager.create_sessionmaker()

    async with sessionmaker() as session:
        # Batch create AIComment objects
        ai_comments = [AIComment(**data) for data in ai_comment_data_list]
        session.add_all(ai_comments)

        # Single commit for all records
        await session.commit()

        # Extract IDs for return
        created_ids = [comment.id for comment in ai_comments]
    # Session closed automatically (< 500ms for batch)

    return created_ids
```

### Pattern 3: Iterative Single-Record Updates
Used in Tasks 2, 3, 4 for updating individual AIComment records.

```python
async def update_single_ai_comment(ai_comment_id: uuid.UUID, update_data: dict):
    db_manager = get_database_manager()
    sessionmaker = await db_manager.create_sessionmaker()

    # Quick update - no long operations
    async with sessionmaker() as session:
        ai_comment = await session.get(AIComment, ai_comment_id)

        if not ai_comment:
            raise ValueError(f"AIComment {ai_comment_id} not found")

        # Update fields
        for key, value in update_data.items():
            setattr(ai_comment, key, value)

        # Commit single record
        await session.commit()
    # Session closed automatically (< 50ms)
```

### Pattern 4: Batch Read with Cached Reference Data
Used in Tasks 3 and 4 for reading multiple AIComments and caching related entities.

```python
async def read_and_cache_for_processing(process_id: uuid.UUID, status: str):
    db_manager = get_database_manager()
    sessionmaker = await db_manager.create_sessionmaker()

    # Step 1: Read AIComments to process
    async with sessionmaker() as session:
        result = await session.execute(
            select(AIComment).where(
                and_(
                    AIComment.monitoring_process_id == process_id,
                    AIComment.status == status
                )
            )
        )
        ai_comments = result.scalars().all()

        # Extract unique foreign key IDs
        unique_llm_ids = set(c.llm_provider_id for c in ai_comments if c.llm_provider_id)
        unique_prompt_ids = set(c.prompt_template_id for c in ai_comments if c.prompt_template_id)
        unique_login_ids = set(c.mymoment_login_id for c in ai_comments if c.mymoment_login_id)

        # Create lightweight snapshots of AIComments
        comment_snapshots = [
            {
                'id': c.id,
                'mymoment_article_id': c.mymoment_article_id,
                'article_title': c.article_title,
                'article_content': c.article_content,
                'article_author': c.article_author,
                'llm_provider_id': c.llm_provider_id,
                'prompt_template_id': c.prompt_template_id,
                'mymoment_login_id': c.mymoment_login_id
            }
            for c in ai_comments
        ]
    # Session closed

    # Step 2: Read and cache reference data
    cached_data = {}

    if unique_llm_ids:
        async with sessionmaker() as session:
            result = await session.execute(
                select(LLMProviderConfiguration).where(
                    LLMProviderConfiguration.id.in_(unique_llm_ids)
                )
            )
            providers = result.scalars().all()
            cached_data['llm_providers'] = {
                p.id: {
                    'provider_name': p.provider_name,
                    'model_name': p.model_name,
                    'api_key': p.get_api_key()  # Decrypt once and cache
                }
                for p in providers
            }
        # Session closed

    if unique_prompt_ids:
        async with sessionmaker() as session:
            result = await session.execute(
                select(PromptTemplate).where(
                    PromptTemplate.id.in_(unique_prompt_ids)
                )
            )
            templates = result.scalars().all()
            cached_data['prompt_templates'] = {
                t.id: {
                    'system_prompt': t.system_prompt,
                    'user_prompt_template': t.user_prompt_template
                }
                for t in templates
            }
        # Session closed

    if unique_login_ids:
        async with sessionmaker() as session:
            result = await session.execute(
                select(MyMomentLogin).where(
                    MyMomentLogin.id.in_(unique_login_ids)
                )
            )
            logins = result.scalars().all()
            cached_data['logins'] = {
                login.id: {
                    'username': login.get_username(),
                    'password': login.get_password()
                }
                for login in logins
            }
        # Session closed

    return comment_snapshots, cached_data
```

### Key Principles

1. **Short-lived sessions**: All database sessions < 500ms
2. **No external I/O inside sessions**: Scraping, LLM calls, HTTP requests happen outside sessions
3. **Batch reads, single writes**: Read many at once, update one at a time
4. **Cache reference data**: Load related entities once, use in-memory for processing
5. **Snapshot pattern**: Copy data out of session context before processing

## Implementation Steps

### Phase 1: Create New Isolated Tasks (No Breaking Changes)

**Step 1.1: Update AIComment model to support new status values**
- [x] Add 'prepared' status to AIComment.status CheckConstraint in `src/models/ai_comment.py:143`
- [x] Update status documentation in AIComment docstring to reflect workflow: discovered → prepared → generated → posted
- [x] Add property method `is_prepared()` to AIComment model
- [x] Create Alembic migration for status constraint change: `alembic revision -m "Add prepared status to AIComment"`
- [x] Test migration: `alembic upgrade head` in development environment

**Step 1.2: Create article discovery task**
- [x] Create new file `src/tasks/article_discovery.py`
- [x] Implement `ArticleDiscoveryTask` class inheriting from `BaseTask`
- [x] Implement helper method `_read_process_config(session, process_id)` - reads MonitoringProcess, login IDs, prompt IDs, LLM provider ID
- [x] Implement helper method `_scrape_articles_for_login(login_id, user_id, config_snapshot)` - uses ScraperService to get article metadata only
- [x] Implement helper method `_create_ai_comment_records(session, articles_metadata, config)` - batch creates AIComment records with status='discovered'
- [x] Implement main async method `_discover_articles_async(process_id)` using Pattern 1 and Pattern 2
- [x] Implement Celery task wrapper `discover_articles(self, process_id: str)`
- [x] Add error handling for scraping failures (log and continue with successful articles)
- [x] Add logging for discovery progress (articles found per login, total created)
- [x] Return result dictionary with counts: `{'discovered': N, 'errors': []}`

**Step 1.3: Create article content preparation task**
- [x] Create new file `src/tasks/article_preparation.py`
- [x] Implement `ArticlePreparationTask` class inheriting from `BaseTask`
- [x] Implement helper method `_read_discovered_articles(session, process_id)` - reads AIComments with status='discovered'
- [x] Implement helper method `_scrape_single_article_content(article_id, login_id, user_id)` - uses ScraperService.get_article_content()
- [x] Implement helper method `_update_article_content(session, ai_comment_id, content_data)` - updates single AIComment with content and status='prepared'
- [x] Implement main async method `_prepare_content_async(process_id)` using Pattern 3
- [x] Implement Celery task wrapper `prepare_content_of_articles(self, process_id: str)`
- [x] Add error handling per article (mark failed articles with status='failed', continue processing others)
- [x] Add rate limiting between article fetches (respect ScrapingConfig.rate_limit_delay)
- [x] Add logging for preparation progress (X/Y articles prepared)
- [x] Return result dictionary: `{'prepared': N, 'failed': M, 'errors': [...]}`

**Step 1.4: Create AI comment generation task**
- [x] Create new file `src/tasks/comment_generation.py`
- [x] Implement `CommentGenerationTask` class inheriting from `BaseTask`
- [x] Implement helper method `_read_and_cache_for_generation(session, process_id)` - uses Pattern 4 to read prepared AIComments and cache LLM configs and prompt templates
- [x] Implement helper method `_format_user_prompt(article_snapshot, prompt_template)` - formats user_prompt_template with article data
- [x] Implement helper method `_generate_comment_with_llm(formatted_prompt, system_prompt, llm_config)` - calls LLMProviderService.generate_completion()
- [x] Implement helper method `_add_ai_prefix(comment_text)` - prepends AI_COMMENT_PREFIX from settings
- [x] Implement helper method `_update_generated_comment(session, ai_comment_id, comment_data)` - updates AIComment with comment_content, AI metadata, status='generated'
- [x] Implement main async method `_generate_comments_async(process_id)` using Pattern 4
- [x] Implement Celery task wrapper `generate_comments_for_articles(self, process_id: str)`
- [x] Add error handling per article (mark failed with status='failed' and error_message)
- [x] Add timing measurement for each LLM call (populate generation_time_ms)
- [x] Add logging for generation progress (X/Y comments generated, avg time)
- [x] Return result dictionary: `{'generated': N, 'failed': M, 'errors': [...]}`

**Step 1.5: Create comment posting task**
- [x] Create new file `src/tasks/comment_posting.py`
- [x] Implement `CommentPostingTask` class inheriting from `BaseTask`
- [x] Implement helper method `_read_and_cache_for_posting(session, process_id)` - uses Pattern 4 to read generated AIComments and cache MyMomentLogin credentials
- [x] Implement helper method `_post_single_comment(article_id, comment_content, login_credentials)` - uses ScraperService.post_comment()
- [x] Implement helper method `_generate_placeholder_comment_id(article_id, ai_comment_id)` - creates unique comment ID (myMoment doesn't return one)
- [x] Implement helper method `_update_posted_comment(session, ai_comment_id, comment_id, posted_at)` - updates AIComment with status='posted'
- [x] Implement helper method `_mark_comment_failed(session, ai_comment_id, error_msg)` - updates AIComment with status='failed', increment retry_count
- [x] Implement main async method `_post_comments_async(process_id)` using Pattern 4
- [x] Implement Celery task wrapper `post_comments_for_articles(self, process_id: str)` with retry logic
- [x] Add exponential backoff retry configuration (max_retries=3, backoff=2)
- [x] Add rate limiting between comment posts (respect platform rate limits)
- [x] Add logging for posting progress (X/Y comments posted)
- [x] Return result dictionary: `{'posted': N, 'failed': M, 'errors': [...]}`

**Step 1.6: Create monitoring orchestrator**
- [ ] Create new file `src/tasks/monitoring_orchestrator.py`
- [ ] Implement `MonitoringOrchestratorTask` class inheriting from `BaseTask`
- [ ] Implement helper method `_get_process_status(session, process_id)` - reads MonitoringProcess and checks current stage
- [ ] Implement helper method `_count_ai_comments_by_status(session, process_id)` - returns count dict {'discovered': N, 'prepared': M, ...}
- [ ] Implement helper method `_update_process_stage(session, process_id, stage, stats)` - updates MonitoringProcess metadata
- [ ] Implement stage handler `_handle_discover_stage(process_id)` - calls discover_articles task, schedules prepare stage
- [ ] Implement stage handler `_handle_prepare_stage(process_id)` - calls prepare_content_of_articles task, schedules generate stage
- [ ] Implement stage handler `_handle_generate_stage(process_id)` - calls generate_comments_for_articles task, checks generate_only flag, conditionally schedules post stage
- [ ] Implement stage handler `_handle_post_stage(process_id)` - calls post_comments_for_articles task, marks process complete
- [ ] Implement main async method `_orchestrate_async(process_id, stage)`
- [ ] Implement Celery task wrapper `orchestrate_monitoring_process(self, process_id: str, stage: str)`
- [ ] Add process timeout enforcement (check max_duration_minutes, stop if exceeded)
- [ ] Add logging for orchestration state transitions
- [ ] Add error aggregation across stages
- [ ] Return result dictionary with overall workflow status

**Step 1.7: Update ScraperService for isolated operations**
- [ ] Extract method in `src/services/scraper_service.py`: `get_article_metadata_only(context, tab, category, limit)` - returns ArticleMetadata without fetching full content
- [ ] Extract method: `get_single_article_content(login_id, user_id, article_id)` - initializes session, fetches content, cleans up session
- [ ] Ensure no method holds database session while performing HTTP requests
- [ ] Add session lifecycle logging (debug level)
- [ ] Update existing methods to use new isolated methods internally (backward compatibility)

**Step 1.8: Register new tasks with Celery**
- [ ] Update `src/tasks/worker.py` TASK_MODULES to include new task modules
- [ ] Add task route for 'src.tasks.article_discovery.*' → queue 'discovery'
- [ ] Add task route for 'src.tasks.article_preparation.*' → queue 'preparation'
- [ ] Add task route for 'src.tasks.comment_generation.*' → queue 'generation'
- [ ] Add task route for 'src.tasks.comment_posting.*' → queue 'posting'
- [ ] Add task route for 'src.tasks.monitoring_orchestrator.*' → queue 'orchestration'
- [ ] Define new Queue objects for each task type
- [ ] Test task registration: `python -c "from src.tasks.worker import get_task_info; print(get_task_info())"`

### Phase 2: Update Monitoring Service

**Step 2.1: Add configuration flag for new implementation**
- [ ] Add setting to `src/config/settings.py` MonitoringSettings: `USE_V2_PIPELINE: bool = False`
- [ ] Add environment variable `MONITORING_USE_V2_PIPELINE` with default False
- [ ] Document setting in docstring: "Enable new isolated task pipeline for monitoring processes"
- [ ] Test configuration loading with both True and False values

**Step 2.2: Update MonitoringService to support v2 pipeline**
- [ ] Open `src/services/monitoring_service.py`
- [ ] Add method `start_process_v2(self, process_id: uuid.UUID) -> dict` that calls monitoring orchestrator
- [ ] Implement v2 method to call `orchestrate_monitoring_process.apply_async(args=[str(process_id), 'discover'])`
- [ ] Add method `get_pipeline_status(self, process_id: uuid.UUID) -> dict` to return AIComment status counts
- [ ] Keep existing `start_process()` method unchanged for backward compatibility
- [ ] Add routing logic in service layer to choose v2 or v1 based on USE_V2_PIPELINE setting
- [ ] Add docstrings explaining v1 vs v2 pipeline differences

**Step 2.3: Update API endpoint to expose v2 option**
- [ ] Open `src/api/monitoring_processes.py`
- [ ] Add query parameter `use_v2: bool = False` to start endpoint: `POST /api/v1/monitoring-processes/{id}/start`
- [ ] Update endpoint to check query param OR global setting to determine pipeline version
- [ ] Call `service.start_process_v2()` when v2 is enabled, otherwise call `service.start_process()`
- [ ] Update endpoint response to include `pipeline_version` field ("v1" or "v2")
- [ ] Add API documentation for `use_v2` parameter

**Step 2.4: Create new pipeline status endpoint**
- [ ] Add new endpoint in `src/api/monitoring_processes.py`: `GET /api/v1/monitoring-processes/{id}/pipeline-status`
- [ ] Endpoint calls `MonitoringService.get_pipeline_status(process_id)`
- [ ] Return JSON with status counts: `{'discovered': N, 'prepared': M, 'generated': X, 'posted': Y, 'failed': Z}`
- [ ] Add endpoint to API router
- [ ] Add Pydantic response model `PipelineStatusResponse`
- [ ] Test endpoint with httpie: `http GET localhost:8000/api/v1/monitoring-processes/{id}/pipeline-status`

**Step 2.5: Update frontend to display pipeline status (optional)**
- [ ] Add JavaScript function in monitoring process detail page to fetch pipeline status
- [ ] Display status breakdown in UI (discovered/prepared/generated/posted/failed counts)
- [ ] Add auto-refresh every 5 seconds while process is running
- [ ] Add progress bar visualization based on status counts
- [ ] OR: Skip if planning to do this in a later iteration 

### Phase 3: Add Monitoring & Observability

**Step 3.1: Add task execution logging model (optional, for advanced tracking)**
- [ ] Create migration file: `alembic revision -m "Add task execution log table"`
- [ ] Define table in migration:
  ```sql
  CREATE TABLE task_execution_log (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      task_name VARCHAR(100) NOT NULL,
      ai_comment_id UUID REFERENCES ai_comments(id) ON DELETE CASCADE,
      monitoring_process_id UUID REFERENCES monitoring_processes(id) ON DELETE CASCADE,
      status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'running', 'success', 'failed')),
      started_at TIMESTAMP WITH TIME ZONE,
      completed_at TIMESTAMP WITH TIME ZONE,
      error_message TEXT,
      execution_time_ms INTEGER,
      created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
  );
  CREATE INDEX idx_task_exec_process ON task_execution_log(monitoring_process_id);
  CREATE INDEX idx_task_exec_comment ON task_execution_log(ai_comment_id);
  CREATE INDEX idx_task_exec_status ON task_execution_log(status);
  ```
- [ ] Create SQLAlchemy model `src/models/task_execution_log.py`
- [ ] Run migration: `alembic upgrade head`
- [ ] OR: Skip this step if task logging is not needed initially

**Step 3.2: Add task execution tracking in orchestrator**
- [ ] In `src/tasks/monitoring_orchestrator.py`, add helper method `_log_task_execution(task_name, process_id, status, execution_time_ms, error=None)`
- [ ] Log task start before calling each stage task
- [ ] Log task completion after each stage task returns
- [ ] Include execution time measurement
- [ ] Include error details if task fails

**Step 3.3: Add metrics collection for task performance**
- [ ] In each task file (discovery, preparation, generation, posting), add execution time tracking
- [ ] Use `start_time = datetime.utcnow()` at beginning of async method
- [ ] Calculate `execution_time_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)` at end
- [ ] Include execution_time_ms in task result dictionaries
- [ ] Log metrics at INFO level: "Task {name} completed in {time}ms: {results}"

**Step 3.4: Add database session duration monitoring**
- [ ] Add debug logging in database session context managers
- [ ] Log session open/close events with timestamps
- [ ] Calculate and log session duration
- [ ] Emit warning if session duration exceeds 500ms
- [ ] Create helper decorator `@log_db_session_duration` to wrap session blocks
- [ ] Apply decorator to all session usage in new tasks

**Step 3.5: Create monitoring dashboard data endpoint**
- [ ] Add endpoint `GET /api/v1/monitoring-processes/{id}/metrics`
- [ ] Return aggregated metrics: total articles, avg preparation time, avg generation time, avg posting time
- [ ] Return failure rates per stage
- [ ] Return current queue depths (requires Celery inspect)
- [ ] Return estimated completion time based on current progress
- [ ] Add Pydantic response model `ProcessMetricsResponse`

**Step 3.6: Add health check for new queues**
- [ ] Update `src/tasks/worker.py` health_check() function
- [ ] Check new queues (discovery, preparation, generation, posting, orchestration)
- [ ] Return queue depths and worker counts per queue
- [ ] Add endpoint `GET /api/v1/system/celery-health` to expose health check
- [ ] Test health check: `http GET localhost:8000/api/v1/system/celery-health`

### Phase 4: Migration & Testing

**Step 4.1: Create unit tests for new tasks**
- [ ] Create test file `tests/unit/tasks/test_article_discovery.py`
  - [ ] Test `_read_process_config()` with mocked database session
  - [ ] Test `_create_ai_comment_records()` batch creation
  - [ ] Test error handling when scraping fails for one login
  - [ ] Test discovery result dictionary format
- [ ] Create test file `tests/unit/tasks/test_article_preparation.py`
  - [ ] Test `_update_article_content()` single record update
  - [ ] Test error handling for failed article fetch
  - [ ] Test status transition from 'discovered' to 'prepared'
  - [ ] Test rate limiting behavior
- [ ] Create test file `tests/unit/tasks/test_comment_generation.py`
  - [ ] Test `_format_user_prompt()` with article data
  - [ ] Test `_add_ai_prefix()` functionality
  - [ ] Test error handling for LLM API failures
  - [ ] Test status transition from 'prepared' to 'generated'
- [ ] Create test file `tests/unit/tasks/test_comment_posting.py`
  - [ ] Test `_generate_placeholder_comment_id()` uniqueness
  - [ ] Test retry logic with exponential backoff
  - [ ] Test status transition from 'generated' to 'posted'
  - [ ] Test failure marking with error message
- [ ] Create test file `tests/unit/tasks/test_monitoring_orchestrator.py`
  - [ ] Test stage handlers call correct tasks
  - [ ] Test stage progression logic
  - [ ] Test generate_only flag behavior
  - [ ] Test timeout enforcement
- [ ] Run all unit tests: `pytest tests/unit/tasks/ -v`

**Step 4.2: Create integration tests for full pipeline**
- [ ] Create test file `tests/integration/test_monitoring_pipeline_v2.py`
- [ ] Test helper: Create test monitoring process with logins and prompts
- [ ] Test full pipeline: discover → prepare → generate → post
  - [ ] Mock ScraperService to return fake articles
  - [ ] Mock LLMProviderService to return fake comments
  - [ ] Mock comment posting to return success
  - [ ] Verify AIComment status transitions at each stage
  - [ ] Verify final status is 'posted' for all articles
- [ ] Test pipeline with generate_only=True
  - [ ] Verify pipeline stops after generation
  - [ ] Verify no posting task is scheduled
  - [ ] Verify final status is 'generated'
- [ ] Test error handling scenarios
  - [ ] Test article preparation failure for one article
  - [ ] Test LLM generation failure for one article
  - [ ] Test posting failure with retry
  - [ ] Verify failed articles marked as 'failed'
  - [ ] Verify successful articles continue through pipeline
- [ ] Test process timeout enforcement
  - [ ] Set short max_duration_minutes
  - [ ] Verify orchestrator stops process after timeout
  - [ ] Verify process status updated to 'completed' or 'stopped'
- [ ] Run integration tests: `pytest tests/integration/test_monitoring_pipeline_v2.py -v`

**Step 4.3: Test database session isolation**
- [ ] Create test file `tests/integration/test_db_session_isolation.py`
- [ ] Test no long-running transactions during article discovery
  - [ ] Mock sleep in scraping to simulate slow network
  - [ ] Verify database session duration < 500ms
  - [ ] Verify session closes before scraping starts
- [ ] Test no long-running transactions during article preparation
  - [ ] Mock slow article content fetch
  - [ ] Verify each article update has isolated session < 100ms
- [ ] Test no long-running transactions during comment generation
  - [ ] Mock slow LLM API call
  - [ ] Verify session closes before LLM call
  - [ ] Verify session reopens only for update
- [ ] Test database connection pool not exhausted
  - [ ] Run 50 articles through pipeline
  - [ ] Monitor active database connections
  - [ ] Verify connection count stays within pool limit
- [ ] Run session isolation tests: `pytest tests/integration/test_db_session_isolation.py -v`

**Step 4.4: Load testing with realistic data volume**
- [ ] Create load test script `tests/load/test_monitoring_load.py`
- [ ] Test scenario: 100 articles through full pipeline
  - [ ] Create monitoring process with 2 logins
  - [ ] Generate 100 fake articles per login (200 total)
  - [ ] Run full v2 pipeline
  - [ ] Measure total execution time
  - [ ] Measure peak database connections
  - [ ] Measure peak memory usage
  - [ ] Verify all 200 articles reach 'posted' status
- [ ] Compare v1 vs v2 performance
  - [ ] Run same scenario with v1 pipeline (USE_V2_PIPELINE=False)
  - [ ] Compare execution times
  - [ ] Compare database connection usage
  - [ ] Compare failure rates
- [ ] Document load test results in `docs/performance_comparison.md`
- [ ] Run load tests: `pytest tests/load/ -v --tb=short`

**Step 4.5: Manual testing in development environment**
- [ ] Enable v2 pipeline: Set `MONITORING_USE_V2_PIPELINE=true` in .env
- [ ] Create test monitoring process via UI or API
- [ ] Start monitoring process with v2 pipeline
- [ ] Monitor Celery worker logs for task execution
- [ ] Monitor database for AIComment status transitions
- [ ] Check pipeline status endpoint for progress: `http GET localhost:8000/api/v1/monitoring-processes/{id}/pipeline-status`
- [ ] Verify articles move through stages: discovered → prepared → generated → posted
- [ ] Test stopping a running process
- [ ] Test process timeout (set short max_duration_minutes)
- [ ] Test generate_only mode
- [ ] Review logs for any errors or warnings
- [ ] Document any issues found

**Step 4.6: Gradual rollout preparation**
- [ ] Create feature flag documentation in README or docs
- [ ] Create rollback procedure document
  - [ ] How to disable v2 pipeline (set USE_V2_PIPELINE=false)
  - [ ] How to clear new task queues
  - [ ] How to verify v1 pipeline is working
- [ ] Prepare monitoring checklist for production rollout
  - [ ] Database connection pool usage
  - [ ] Task queue depths
  - [ ] Task execution times
  - [ ] Failure rates by stage
  - [ ] Process completion rates
- [ ] Plan gradual rollout strategy
  - [ ] Week 1: Enable for new processes only, keep existing processes on v1
  - [ ] Week 2: If stable, enable globally via USE_V2_PIPELINE=true
  - [ ] Week 3: Deprecation notice for v1 pipeline
  - [ ] Week 4: Remove v1 implementation

### Phase 5: Cleanup

**Step 5.1: Deprecate old task implementations**
- [ ] Add deprecation warnings to old tasks
  - [ ] Add `@deprecated` decorator to `start_monitoring_process` in `src/tasks/article_monitor.py`
  - [ ] Add `@deprecated` decorator to `generate_comments_for_process` in `src/tasks/comment_generator.py`
  - [ ] Add `@deprecated` decorator to `post_comments_for_process` in `src/tasks/comment_poster.py`
  - [ ] Log deprecation warning when these tasks execute
- [ ] Update documentation to recommend v2 pipeline
  - [ ] Update AGENTS.md with new architecture description
  - [ ] Add migration guide for existing processes
  - [ ] Document v1 deprecation timeline

**Step 5.2: Remove old task files after deprecation period**
- [ ] Verify all production processes are using v2 pipeline
- [ ] Check Celery queues for old task types (should be empty)
- [ ] Remove old task files:
  - [ ] Delete `src/tasks/article_monitor.py`
  - [ ] Delete `src/tasks/comment_generator.py` (old version)
  - [ ] Delete `src/tasks/comment_poster.py` (old version)
- [ ] Remove old task routes from `src/tasks/worker.py`
- [ ] Remove old queue definitions from CeleryConfig
- [ ] Update TASK_MODULES to exclude deleted modules
- [ ] Test that application starts without errors

**Step 5.3: Remove v2 feature flag**
- [ ] Remove `USE_V2_PIPELINE` setting from `src/config/settings.py`
- [ ] Remove `use_v2` query parameter from API endpoint
- [ ] Update `MonitoringService` to always use v2 pipeline (remove conditional logic)
- [ ] Rename methods: `start_process_v2()` → `start_process()`
- [ ] Update all references to v2 pipeline (remove "v2" nomenclature)
- [ ] Update API response to remove `pipeline_version` field (now implicit)

**Step 5.4: Clean up database (optional)**
- [ ] Check for orphaned AIComment records with old status values
- [ ] Archive or delete old task_execution_log records if using that feature
- [ ] Optimize AIComment table indexes based on new query patterns
- [ ] Run VACUUM or equivalent database maintenance

**Step 5.5: Update documentation**
- [ ] Update AGENTS.md to reflect final architecture
- [ ] Remove all references to "v1" and "v2" pipelines
- [ ] Document final task structure and workflow
- [ ] Update task lifecycle diagrams
- [ ] Document database access patterns
- [ ] Update API documentation with final endpoints
- [ ] Create troubleshooting guide for common issues

**Step 5.6: Performance tuning (optional)**
- [ ] Review Celery worker concurrency settings
- [ ] Adjust queue prefetch multiplier based on load test results
- [ ] Tune database connection pool size
- [ ] Review and adjust task time limits
- [ ] Optimize rate limiting parameters
- [ ] Document recommended production settings

## File Structure After Refactoring

```
src/tasks/
├── __init__.py                      # Existing
├── worker.py                        # Updated: New queues and routes
├── monitoring_orchestrator.py       # NEW: Workflow coordination
├── article_discovery.py             # NEW: Task 1 - Article discovery
├── article_preparation.py           # NEW: Task 2 - Content preparation
├── comment_generation.py            # NEW: Task 3 - AI comment generation
├── comment_posting.py               # NEW: Task 4 - Comment posting
├── session_manager.py               # Existing: Independent task
├── timeout_enforcer.py              # Existing: Independent task
└── scheduler.py                     # Existing: Periodic tasks

# REMOVED after Phase 5:
# ├── article_monitor.py             # DELETED (old monolithic implementation)
# ├── comment_generator.py (old)     # DELETED (old implementation)
# └── comment_poster.py (old)        # DELETED (old implementation)
```

**New task organization:**
- **Orchestration**: `monitoring_orchestrator.py` coordinates workflow
- **Stage tasks**: 4 isolated tasks for each pipeline stage
- **Support tasks**: session_manager, timeout_enforcer, scheduler remain unchanged
- **Total**: 7 task modules (down from 8, better separation of concerns)

## Queue Configuration

**Updated Celery worker configuration in `src/tasks/worker.py`:**

```python
# Task routing by queue
task_routes = {
    # NEW: Monitoring v2 pipeline tasks
    'src.tasks.article_discovery.*': {'queue': 'discovery'},
    'src.tasks.article_preparation.*': {'queue': 'preparation'},
    'src.tasks.comment_generation.*': {'queue': 'generation'},
    'src.tasks.comment_posting.*': {'queue': 'posting'},
    'src.tasks.monitoring_orchestrator.*': {'queue': 'orchestration'},

    # Existing: Support tasks
    'src.tasks.session_manager.*': {'queue': 'sessions'},
    'src.tasks.timeout_enforcer.*': {'queue': 'timeouts'},
    'src.tasks.scheduler.*': {'queue': 'scheduler'},
}

# Queue definitions
task_queues = (
    # NEW: Pipeline stage queues
    Queue('discovery', routing_key='discovery'),
    Queue('preparation', routing_key='preparation'),
    Queue('generation', routing_key='generation'),
    Queue('posting', routing_key='posting'),
    Queue('orchestration', routing_key='orchestration'),

    # Existing: Support queues
    Queue('sessions', routing_key='sessions'),
    Queue('timeouts', routing_key='timeouts'),
    Queue('scheduler', routing_key='scheduler'),
    Queue('celery', routing_key='celery'),  # Default queue
)
```

**Worker deployment strategies:**

**Option 1: Single worker consuming all queues (development/small scale)**
```bash
celery -A src.tasks.worker worker \
  --loglevel=info \
  --queues=discovery,preparation,generation,posting,orchestration,sessions,timeouts,scheduler,celery
```

**Option 2: Dedicated workers per queue type (production/large scale)**
```bash
# Pipeline workers (can scale independently)
celery -A src.tasks.worker worker --loglevel=info --queues=discovery --concurrency=2
celery -A src.tasks.worker worker --loglevel=info --queues=preparation --concurrency=4
celery -A src.tasks.worker worker --loglevel=info --queues=generation --concurrency=2
celery -A src.tasks.worker worker --loglevel=info --queues=posting --concurrency=2

# Orchestration and support workers
celery -A src.tasks.worker worker --loglevel=info --queues=orchestration --concurrency=1
celery -A src.tasks.worker worker --loglevel=info --queues=sessions,timeouts,scheduler --concurrency=2
```

**Option 3: Hybrid approach (recommended for production)**
```bash
# Pipeline workers grouped by I/O type
celery -A src.tasks.worker worker --loglevel=info \
  --queues=discovery,preparation,posting \
  --concurrency=4  # I/O bound tasks (scraping, HTTP)

celery -A src.tasks.worker worker --loglevel=info \
  --queues=generation \
  --concurrency=2  # CPU/API bound tasks (LLM calls)

# Orchestration and support
celery -A src.tasks.worker worker --loglevel=info \
  --queues=orchestration,sessions,timeouts,scheduler \
  --concurrency=1
```

**Queue prioritization (if needed):**
```python
# Add to CeleryConfig if certain tasks need priority
task_default_priority = 5
task_queue_priorities = {
    'orchestration': 10,  # Highest priority
    'timeouts': 9,
    'discovery': 7,
    'preparation': 6,
    'generation': 5,
    'posting': 4,
    'sessions': 3,
}
```

**Monitoring queue health:**
```bash
# Check queue depths
celery -A src.tasks.worker inspect active_queues

# Check active tasks
celery -A src.tasks.worker inspect active

# Check worker stats
celery -A src.tasks.worker inspect stats

# Purge specific queue (use with caution)
celery -A src.tasks.worker purge -Q preparation
```

## Key Benefits Summary

### Database Performance
- **Short-lived transactions**: All DB sessions < 500ms (vs. minutes in v1)
- **No blocking**: External I/O (scraping, LLM calls) happens outside DB sessions
- **Connection efficiency**: Predictable connection pool usage
- **Scalability**: Can handle 10x more concurrent processes

### Reliability & Error Handling
- **Fine-grained retry**: Individual articles can fail without affecting batch
- **Isolated failures**: Failed scraping doesn't block comment generation
- **Better observability**: Track progress at article level
- **Graceful degradation**: Partial failures don't stop entire workflow

### Operational Benefits
- **Independent scaling**: Scale each task type (discovery, preparation, generation, posting) independently
- **Resource optimization**: LLM tasks can have different concurrency than scraping tasks
- **Easier debugging**: Isolated tasks are simpler to test and troubleshoot
- **Better monitoring**: Clear metrics per pipeline stage

### Development Benefits
- **Testability**: Each task is independently testable with mocked dependencies
- **Maintainability**: Clear separation of concerns, easier to understand code
- **Flexibility**: Easy to add new pipeline stages or modify existing ones
- **Backward compatibility**: v1 and v2 can run simultaneously during migration

## Estimated Implementation Timeline

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Create New Tasks | 3-5 days | None |
| Phase 2: Update Service/API | 1-2 days | Phase 1 complete |
| Phase 3: Observability | 1-2 days | Phase 1 complete (can run parallel with Phase 2) |
| Phase 4: Testing | 2-3 days | Phases 1-3 complete |
| Phase 5: Cleanup | 1 day | Phase 4 complete, production validation |
| **Total** | **8-13 days** | Sequential with some parallelization |

**Risk mitigation**: Feature flag approach allows gradual rollout and easy rollback if issues arise.

---

**Document version**: 1.0
**Last updated**: 2025-10-08
**Status**: Ready for implementation


