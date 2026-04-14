# Comment Monitoring Speedup Report

Date: 2026-04-13

Scope: analysis of one concurrent run with two monitoring processes:
- Reasoning process: `438aedd4-c848-4944-85ef-abedbdec07c0`
- CoT process: `1a58601a-25d3-4644-9372-8fe0667f59d2`

Primary sources:
- `logs/server.log`
- `logs/worker.log`
- `logs/scheduler.log`
- `logs/llm.log`
- `src/services/monitoring_service.py`
- `src/tasks/scheduler.py`
- `src/tasks/article_discovery.py`
- `src/tasks/article_preparation.py`
- `src/services/scraper_service.py`
- `src/services/mymoment_session_service.py`
- `src/models/mymoment_session.py`
- `src/tasks/worker.py`

## Executive Summary

The run is slow for two distinct reasons:

1. LLM generation is the largest intrinsic cost.
2. The orchestration layer is doing a large amount of avoidable work.

Generation consumed about `1884.0s` of worker time (`54.2%` of total stage time), which means model latency and output length are real contributors. But the avoidable waste is also large: discovery consumed about `1212.4s` (`34.9%`) even though only `3` out of `153` discovery tasks created any comments. The system also performed `225` myMoment session initializations and `225` successful authentications during this single run.

The highest ROI improvements are:

1. Fix the process start kickoff bug so a process start only triggers discovery for that process.
2. Add discovery backpressure with a **durable cooldown / lease**, and stop polling every `10s` while backlog or cooldown exists.
3. Replace per-article preparation with per-login batch preparation.
4. Batch posting by login, but only with an explicit completion coordinator for the generation wave.
5. Persist and restore myMoment cookies so repeated cycles do not require a full login.
6. Separate generation workers from short-running queues and add fairer generation dispatch.
7. Tune LLM reasoning/output size.

**Zero-code quick win (do immediately, in parallel with the above):** Disable reasoning mode on the `magistral-medium-latest` process or switch it to `mistral-large-latest`. This is a configuration change only and cuts Reasoning process generation time roughly in half (avg `68.5s` → `~36s`). It can be done before any code is written and should be validated on the next benchmark run regardless.

Important context: this run also includes a worker/scheduler restart during startup, which inflated wall clock time by about `132-148s`. That is real operational delay, but it is separate from the main pipeline design issues.

Important implementation caveat: two of the proposed optimizations need more structure than the original sketch implied:
- Discovery backpressure must be backed by durable scheduler state, not only a DB count of `status='discovered'`.
- Batch posting cannot simply replace per-article posting in the current chain model; it needs a coordinator/finalizer because generation currently finishes as independent per-article tasks.

## Evidence Summary

| Metric | Observation | Why it matters |
| --- | --- | --- |
| Initial startup gap | Process start requests at `15:44:15` and `15:44:18`; worker ready at `15:46:30` | Added about `132-148s` before work could start |
| Discovery cadence | Scheduler sent `trigger-monitoring-pipeline` every `10s` in this run | Aggressive polling multiplied auth and scrape overhead |
| Discovery volume | `153` discovery tasks total | Most discovery work was redundant |
| Discovery hit rate | `3` non-zero runs, `150` zero-result runs | Very poor yield from discovery polling |
| Discovery worker time | `1212.4s` (`34.9%`) | Large avoidable orchestration cost |
| Generation worker time | `1884.0s` (`54.2%`) | Largest intrinsic cost after orchestration fixes |
| Preparation worker time | `178.0s` (`5.1%`) | Small in total, but login-heavy and easy to optimize |
| Posting worker time | `200.4s` (`5.8%`) | Also login-heavy |
| myMoment auth volume | `225` session initializations and `225` auth successes | Authentication is repeated far too often |
| Preparation tasks | `36` single-article prepare tasks | Preparation is currently one login per article |
| Posting tasks | `36` single-article post tasks | Posting is also one login per article |
| Generation fairness | Reasoning first generation at `15:46:43`; CoT first generation at `15:52:54` | Second pipeline waited about `6m11s` for model capacity |
| Reasoning generation cost | `18` generations, avg `68.5s`, median `59.2s`, max `223.8s` | Reasoning mode is materially slower |
| CoT generation cost | `18` generations, avg `36.1s`, median `36.9s`, max `43.8s` | Non-reasoning path is much faster |
| Token usage | Reasoning completion tokens `56,642`; CoT completion tokens `31,564` | Longer outputs are driving latency |

## Detailed Findings

### 1. Startup delay inflated wall clock by about 2.3 minutes

Evidence:
- `logs/server.log` shows the API start calls at `15:44:15` and `15:44:18`.
- `logs/scheduler.log` shows beat restarted at `15:46:13`.
- `logs/worker.log` shows the worker became ready at `15:46:30`.

Assessment:
- This is an operational readiness issue, not the core pipeline bottleneck.
- Any before/after benchmark should be repeated on a clean run where worker and scheduler are already healthy.

Action:
- Add an active readiness check in `MonitoringService.start_process()` that uses Celery's control API (e.g. `celery_app.control.inspect(timeout=...)`) before proceeding, and surface an API error rather than silently queuing work that cannot be processed for minutes. A UI warning is a fallback, not a fix — the check should be server-side.
- Any benchmark comparing before/after must be run with worker and scheduler already healthy at the time of process start.

### 2. Process start is triggering global immediate discovery, not process-scoped discovery

Relevant code:
- `src/services/monitoring_service.py:552-557`
- `src/tasks/scheduler.py:37-79`
- `src/tasks/scheduler.py:171-180`

Observed behavior:
- Each process start calls `trigger_monitoring_pipeline.delay(force_immediate=True)`.
- The scheduler task scans **all** running processes.
- When `force_immediate=True`, the normal "already running" guard is bypassed.
- At worker startup, four scheduler tasks ran in quick succession and each spawned discovery for both running processes.

Evidence:
- `logs/worker.log` lines around `395-445` show multiple `trigger_monitoring_pipeline` tasks and repeated discovery spawns.
- `logs/worker.log` lines around `576-581` show the CoT process creating `17` comments in one discovery and `1` in another, which is the visible outcome of the duplicate kickoff race.

Impact:
- Extra discovery work at startup.
- Duplicate scraping/authentication pressure.
- More queue noise and more opportunities for race conditions.

Recommendation:
- Make the immediate kickoff process-scoped.
- Do **not** use `force_immediate=True` as "ignore in-flight detection for all running processes".
- Make "immediate" mean "check this process now", not "spawn regardless of current task state".

### 3. Discovery is heavily over-polling

Relevant code/config:
- `src/tasks/worker.py:100-119`
- `src/config/settings.py:342-345`
- `.env` currently sets `ARTICLE_DISCOVERY_INTERVAL_SECONDS=10`
- `.env.example` defaults that setting to `60`

Observed behavior:
- Beat fired `trigger-monitoring-pipeline` every `10s` in this run.
- Discovery task counts:
  - Reasoning process: `77` discovery runs, `1` non-zero and `76` zero-result runs
  - CoT process: `76` discovery runs, `2` non-zero and `74` zero-result runs
  - Total: `153` discovery runs, `150` zero-result

Impact:
- Discovery alone consumed about `1212.4s` of worker time.
- Discovery accounted for about `34.9%` of all stage time despite almost never producing new work.
- Every discovery run still pays auth/scrape/session setup cost.

Recommendation:
- Add backpressure: do not run discovery for a process while it still has `AIComment` rows in `status = 'discovered'` for that process. The predicate must be scoped to `discovered` specifically — not all non-terminal states. Articles in `prepared` or `generated` are already through scraping; suppressing discovery until they post would be overly conservative and would add unnecessary latency on the generation queue drain. The `discovered` predicate is exact: those rows represent articles that have been found but not yet fetched, so a new discovery wave would only produce duplicates that the uniqueness constraint discards anyway.
- Add a durable cooldown / lease (`next_discovery_at`, `discovery_empty_streak`, and/or a short-lived "queued discovery" lease) because the current scheduler only treats `STARTED` and `RETRY` tasks as in-flight. That guard is not enough to stop repeated empty discovery spawns under load.
- Add zero-hit backoff: after repeated zero-result runs, slow that process down further.
- Raise the effective interval from the current `10s` override unless there is a strong business reason to poll that aggressively.

### 4. Generation dispatch is unfair across concurrent processes

Relevant code:
- `src/tasks/article_discovery.py:434-461`
- `src/tasks/worker.py:47-83`

Observed behavior:
- Queue routing exists, but the current worker pool still allowed one process to monopolize generation capacity.
- Discovery immediately dispatches a full per-article chain for every new `AIComment`.
- The Reasoning process started generation at `15:46:43`.
- The CoT process did not start generation until `15:52:54`.
- All four worker slots were effectively occupied by the Reasoning process first.

Impact:
- The second concurrent pipeline was starved for about `6m11s`.
- Even if overall throughput is acceptable, fairness and time-to-first-result are poor.

Recommendation:
- Operationally split generation into its own worker pool so long LLM tasks do not block discovery/preparation/posting.
- In code, add a per-process cap or round-robin release strategy for generation so one discovery wave cannot flood the entire queue at once.

### 5. LLM generation is the largest remaining intrinsic cost

Observed behavior:
- Total stage time by category:
  - Generation: `1884.0s` (`54.2%`)
  - Discovery: `1212.4s` (`34.9%`)
  - Preparation: `178.0s` (`5.1%`)
  - Posting: `200.4s` (`5.8%`)
- Per-process generation stats:
  - Reasoning: `18` generations, avg `68.5s`, median `59.2s`, max `223.8s`
  - CoT: `18` generations, avg `36.1s`, median `36.9s`, max `43.8s`
- Prompt token totals were the same, but completion tokens were much higher in the Reasoning process:
  - Reasoning completion tokens: `56,642`
  - CoT completion tokens: `31,564`

Impact:
- Even after fixing orchestration, generation will still dominate total time.
- The biggest lever here is reasoning mode and output length, not prompt input size.

Recommendation:
- Evaluate reasoning mode immediately, not after orchestration fixes. Disabling reasoning on `magistral-medium-latest` is a config-only change. After all orchestration waste is removed, generation will be roughly 90% of remaining wall time, making this the single highest-leverage lever available.
- Consider explicit output/token limits to control the long tail (`max = 223.8s` is caused by `7,226` completion tokens on one article vs. an average of `3,145`). A `max_tokens` cap set to e.g. `2,000` completion tokens would eliminate that outlier with negligible quality cost for comment generation.
- Benchmark: compare reasoning vs. non-reasoning on the same article set before committing to a permanent policy.

### 6. myMoment authentication is being repeated excessively

Relevant code:
- `src/services/scraper_service.py:316-378`
- `src/services/scraper_service.py:386-460`
- `src/services/scraper_service.py:579-605`
- `src/services/mymoment_session_service.py:152-207`
- `src/services/mymoment_session_service.py:298-331`
- `src/models/mymoment_session.py:55-60`
- `src/models/mymoment_session.py:140-179`

Observed behavior:
- `logs/worker.log` contains:
  - `225` "Initializing scraping session for login" lines
  - `225` "Successfully authenticated session for login" lines
- Current task counts:
  - `153` discovery tasks
  - `36` single-article preparation tasks
  - `36` posting tasks

Assessment:
- The `225` auth events break down as follows: `153` from discovery + `36` from single-article preparation + `36` from posting = `225`.
- Authentication overhead therefore appears on all three pipeline stages, not just discovery and preparation.
- `_initialize_single_session()` always creates a new `aiohttp.ClientSession` and immediately calls `_authenticate_session()`. Cookies are never serialized back into `MyMomentSession.session_data` after a successful login, so every call is a cold start even when a session record exists.
- `_authenticate_session()` performs the full login flow on every invocation because `_check_authentication_status()` always fails on a fresh session with no restored cookies.
- The DB model and session service already support encrypted session persistence (`session_data_encrypted`, `get/set_session_data()`, `update_session_data()`, `touch_session()`), but the scraper does not yet write or read cookies from that store.

Recommendation:
- Implement cookie persistence/restore in `ScraperService` to turn repeated full logins into cheap cookie-validation requests.
- Also reduce the number of auth opportunities by batching preparation and posting by login (one auth per login per wave instead of one per article), and by throttling discovery polling.

## Assessment of the Proposed Optimizations

### A. Persist session cookies

Verdict: recommended, medium effort, good ROI, and no schema change is required.

Why it is feasible:
- `MyMomentSession.session_data_encrypted` already exists for encrypted session state.
- `MyMomentSession.get_session_data()` / `set_session_data()` / `update_session_data()` already exist.
- `MyMomentSessionService.update_session_data()`, `touch_session()`, and `renew_session()` already exist.
- `_check_authentication_status()` already provides a cheap validation step against the authenticated home page.

Current gap:
- `_initialize_single_session()` creates a new `aiohttp.ClientSession` and immediately calls `_authenticate_session()`.
- `_authenticate_session()` logs in from scratch and only `touch`es the DB session on success.
- Cookies are not persisted back into `MyMomentSession.session_data`.

Implementation outline:
1. Add helper methods in `ScraperService` to serialize and restore the `aiohttp` cookie jar.
2. After successful login in `_authenticate_session()`, persist:
   - cookies
   - current `csrf_token` if useful
   - `saved_at`
   - optional `base_url`
3. In `_initialize_single_session()`, if an active `MyMomentSession` record already has session data:
   - restore cookies into the new `aiohttp` session
   - set `context.csrf_token` if present
   - call `_check_authentication_status()`
4. If validation succeeds:
   - set `context.is_authenticated = True`
   - `touch` the session record, and renew it if the intended cache policy is "24h from last successful use" rather than "24h from creation"
   - skip full login
5. If validation fails:
   - fall back to the existing full login path
   - overwrite stale stored cookies with fresh data after successful login

Expected impact:
- Saves repeated full-login cost on discovery, preparation, and posting.
- Especially valuable for posting and any remaining repeated discovery cycles.
- If implemented alone, it can reduce a large fraction of the current `225` full login flows.
- If batch preparation is implemented first, the highest remaining gains shift from preparation to discovery and posting.

Risks:
- Stale cookies or stale CSRF token
- Cookie serialization bugs around domain/path/expiry
- Concurrent workers overwriting the same session record

Mitigations:
- Always validate restored cookies with `_check_authentication_status()` before trusting them.
- Store only minimal metadata needed for restore/debugging.
- If restore fails, treat it as cache miss and do a normal login.

### B. Batch preparation

Verdict: recommended, medium effort, and likely higher ROI than cookie persistence for the preparation stage.

Why it is feasible:
- `ArticlePreparationTask._prepare_articles_for_login()` already authenticates once and fetches multiple articles for the same login.
- There is already a process-level batch preparation idea in `prepare_content_of_articles()`, even though that code path is not part of the live pipeline today.
- The current discovery dispatch path is the main thing preventing reuse of this logic.

Current gap:
- `src/tasks/article_discovery.py:434-461` dispatches a per-article chain:
  - `prepare_article_content`
  - `generate_comment_for_article`
  - `post_comment_for_article`
- `prepare_article_content` then authenticates once per article.
- The existing process-level preparation code should not be treated as production-ready without inspection; it is not the current execution path and is easy to over-trust when refactoring.

Implementation outline:
1. Replace `_dispatch_processing_chains()` with grouping logic by `mymoment_login_id`.
2. Add a new public task, for example:
   - `prepare_articles_for_login_batch(login_id, ai_comment_ids, generate_only)`
3. Inside that task:
   - read snapshots for the explicit `AIComment` IDs
   - call `_prepare_articles_for_login()` once for that login
   - collect successfully prepared IDs
4. After preparation completes, dispatch generation per prepared comment.
5. If `generate_only` is false, chain posting from generation exactly as today.
6. Keep `prepare_article_content` as a fallback/manual retry path for targeted recovery.
7. Harden retry semantics before rollout:
   - authentication/session initialization failures should retry the **batch task** while leaving rows in `discovered`
   - only after the batch task exhausts retries should the remaining rows be marked `failed`
   - individual article fetch failures can still mark only that row `failed`

Expected impact:
- In this exact run, `36` single-article preparation auths can drop to `2` auths because there were two process/login waves of `18` articles each.
- At about `4-5s` per login, that is roughly `136-170s` saved in preparation auth overhead alone.
- It also reduces login pressure on myMoment and frees worker slots sooner.

Risks:
- One login failure affects the whole batch for that login.
- Retry semantics change from per-article prepare to per-batch auth plus per-article fetch/update.
- Large batches hold a worker slot longer.

Mitigations:
- Batch by login and explicit `AIComment` ID list, not by whole process backlog.
- Preserve stage semantics: transient auth failure should not immediately flip every row to `failed`.
- Keep per-article failure marking and compare-and-update status guards for article-level failures.
- If needed, chunk very large batches.

### C. Batch posting by login

Verdict: recommended, but not "just swap one task for another". It is moderate effort because the current chain model needs a coordinator/finalizer before login-batch posting is safe.

Why it is feasible:
- Posting currently follows the same one-auth-per-article pattern as preparation: each `post_comment_for_article` task initializes a fresh scraping session.
- There is already a process-level batch posting task, `post_comments_for_articles`, that proves the posting loop itself can be done in batch form.
- What is missing is not the posting loop, but the coordination step that decides when a login-scoped set of generation tasks is ready to post.

Current gap:
- `_dispatch_processing_chains()` in `src/tasks/article_discovery.py:434-461` chains `post_comment_for_article` per article.
- Generation currently completes as independent per-article tasks; there is no barrier that says "this login wave is now ready to post".
- The codebase already has `post_comments_for_articles(process_id)`, but that task is process-scoped and not sufficient by itself to coordinate login-scoped waves created by discovery.

Implementation outline:
1. Add a login-scoped batch posting task such as `post_comments_for_login_batch(login_id, ai_comment_ids)` in `src/tasks/comment_posting.py`, or refactor the existing process-level batch poster so the core posting helper can operate on an explicit `(login_id, ai_comment_ids)` set.
2. Do **not** dispatch it as a naive replacement for `post_comment_for_article` inside the current chain. Instead, give it coordinator behavior:
   - read the explicit `AIComment` IDs for that login wave
   - if any rows are still `prepared`, retry the task later without authenticating
   - if all rows are terminal and at least one row is `generated`, proceed to posting
   - if all rows failed generation, exit without authenticating
3. Once the coordinator sees the wave is ready, authenticate once and post only the rows that are still `generated`.
4. Mark rows one at a time exactly as today, preserving compare-and-update idempotency.
5. Keep `post_comment_for_article` for targeted retry and recovery.
6. Keep compatibility for existing manual entry points:
   - `/api/v1/comments/{id}/post` currently uses the direct API path, not the Celery single-row task
   - `/api/v1/monitoring-processes/{id}/post-comments` currently calls the process-level batch posting task and should continue to work

Expected impact:
- `36` posting auth events drop to `2` (one per login per process wave) for the same workload.
- At `4-5s` per login, that is roughly `136-170s` saved in posting auth overhead.
- Refactoring around the existing process-level poster reduces duplication compared with inventing a second batch posting implementation from scratch.

Risks and mitigations:
- Missing coordinator: if the batch task authenticates before generation is done, it either posts too early or re-authenticates later. Mitigate by making "wait until explicit IDs are terminal/generated" part of the task contract.
- Same as batch preparation: one login failure affects the batch. Mitigate by keeping per-comment failure marking and batch-level retries for auth failures.
- Rate limits: posting sequentially for one login is already what the single-article path does; the auth savings do not change request cadence.

### D. Relationship between all four suggestions

The four changes are complementary and stack:

| Change | Auth events eliminated | Code effort |
| --- | --- | --- |
| Batch preparation | `34` of `36` prepare auths (from `36` to `2`) | Medium |
| Batch posting | `34` of `36` posting auths (from `36` to `2`) | Medium (same posting loop, but needs coordinator/finalizer) |
| Cookie persistence | Most of `153` discovery auths + remaining prepare/post | Medium |
| Discovery backpressure + lease | Eliminates most of the `153` discovery tasks | Medium |

Recommended order:
1. Implement discovery backpressure + durable cooldown/lease first — it removes the largest volume of pointless work.
2. Implement batch preparation next — highest immediate auth savings per article wave once discovery is sane.
3. Implement batch posting with its coordinator immediately after — same auth savings family, but do not underestimate the coordination work.
4. Then implement cookie persistence to cover the remaining discovery and any residual auth cycles.

## Implementation Guardrails

The following constraints should shape the implementation, because they are easy to miss when reading only the happy-path design:

- Do not rely only on `AsyncResult.state in {'STARTED', 'RETRY'}` as a discovery in-flight guard. That is the current behavior, and the checked logs show it still allows repeated scheduler spawns throughout the run.
- Do not treat `prepare_content_of_articles()` as a drop-in foundation for the new pipeline without inspecting it first. It is not part of the live path today.
- Do not switch posting to batch mode without a completion coordinator. The current chain model has no natural "all generation for this login wave is done" signal.
- Preserve the current retry contract as closely as practical:
  - transient auth/session failures should retry at the stage level before rows are marked `failed`
  - per-row content fetch / generation / posting failures may still fail only that row
  - idempotent compare-and-update guards must remain the source of truth

## Recommended Implementation Order

**Immediate (no code change):**
- Disable reasoning mode or switch `magistral-medium-latest` to `mistral-large-latest`. Do this now and use the next benchmark to validate quality. ~2× generation speedup for that process.

**Phase sequence:**
1. Fix process-scoped immediate kickoff and stop bypassing the running-task guard globally.
2. Add discovery backpressure scoped to `status = 'discovered'` rows, plus a durable cooldown / lease; raise polling interval from `10s`.
3. Implement per-login batch preparation.
4. Implement per-login batch posting with a coordinator/finalizer for generation completion.
5. Implement persisted session cookies to cover remaining discovery and residual auth.
6. Split worker pools by queue and add fairer generation dispatch.
7. Add instrumentation and compare before/after metrics on a clean run.

## Step-by-Step Implementation Plan

### Phase 0: LLM configuration and clean benchmarking

1. Disable reasoning mode on `magistral-medium-latest` (set `reasoning=False` in the LLM provider config or template) or replace it with `mistral-large-latest`. Benchmark the output quality on the same article set. This is a configuration change only — no code deploy needed.
2. Add a server-side readiness check in `MonitoringService.start_process()` that verifies at least one Celery worker is reachable via Celery's control API before marking the process as running and dispatching the kickoff trigger. Return an API error if the worker is not ready rather than silently queuing work.
3. Re-run the same two-process benchmark with worker and scheduler already healthy so the baseline is not distorted by the `132-148s` startup gap.

Acceptance criteria:
- Reasoning process average generation time falls below `40s`.
- New benchmark starts doing useful work within seconds, not after a restart gap.
- `start_process` returns an explicit error if Celery is unavailable at call time.

### Phase 1: Remove duplicate startup work

1. Extend the scheduler trigger path so it can target specific process IDs instead of scanning all running processes on every immediate kickoff.
2. Update `MonitoringService.start_process()` to call the process-scoped path instead of global `trigger_monitoring_pipeline(force_immediate=True)`.
3. Keep the in-flight discovery guard active even for immediate runs.
4. Add logging that records whether the trigger is periodic or process-scoped.

Recommended implementation detail:
- Prefer `trigger_monitoring_pipeline(process_ids=[...], force_immediate=False)` or a new dedicated process-scoped scheduler task.
- Avoid calling `discover_articles.delay()` directly from the service unless the process record is updated with the resulting task ID in a race-safe way.

Acceptance criteria:
- Starting two processes produces exactly one immediate discovery spawn per process.
- No repeated startup discovery bursts like the ones seen around `logs/worker.log` lines `395-445`.

### Phase 2: Add discovery backpressure

1. Before spawning discovery for a process, count `AIComment` rows for that process where `status = 'discovered'` (i.e. found but not yet fetched). This is the correct predicate — do not count `prepared` or `generated` rows. Those are already past the scraping stage and their presence should not suppress discovery, because doing so would stall the pipeline until the slow generation queue drains. Only `discovered` rows represent duplicate-risk work that a new discovery wave would produce.
2. If any `discovered` rows exist for that process, skip spawning discovery.
3. Add durable scheduler state. This should not be optional:
   - track `next_discovery_at` and/or `discovery_empty_streak` per process
   - optionally add a short-lived "discovery queued" lease timestamp when enqueueing discovery so the scheduler does not re-enqueue before the worker starts
   - do not rely only on `celery_discovery_task_id` + `AsyncResult`, because the current `STARTED`/`RETRY` guard misses exactly the kind of repeated empty-run scheduling seen in this benchmark
4. Add zero-result backoff:
   - Minimal acceptable version: increase the effective interval from the current `10s` override to `30-60s`
   - Preferred version: exponential backoff keyed off `discovery_empty_streak`, persisted per process
5. Emit discovery metrics:
   - discovered count
   - zero-hit streak
   - pending backlog count
   - next eligible discovery time

Acceptance criteria:
- Discovery task count drops sharply on the same workload.
- Zero-result discovery ratio is materially lower than `150/153`.
- myMoment auth count drops because redundant discovery auths disappear.
- Scheduler logs show real skips while cooldown/backlog is active; repeated "spawned 2, skipped 0" waves should disappear under steady-state load.

### Phase 3: Batch preparation by login

1. Add a new batch preparation task `prepare_articles_for_login_batch(login_id, ai_comment_ids, generate_only)` in `src/tasks/article_preparation.py`.
2. In `_dispatch_processing_chains()` (`src/tasks/article_discovery.py:434-461`), replace per-article chain dispatch with grouping logic by `mymoment_login_id`. Dispatch one batch preparation task per login group instead of one chain per article.
3. Reuse `_prepare_articles_for_login()` inside the batch task, but harden it first so transient login/auth failures retry the batch instead of immediately marking the whole batch failed.
4. After the batch finishes, enqueue `generate_comment_for_article` for each successfully prepared comment ID.
5. If not `generate_only`, chain posting from generation as before — this will be replaced by batch posting in Phase 4.
6. Retain `prepare_article_content` as a fallback for manual retry, debugging, or targeted repair of individual articles.

**Note on dead code / misleading code:** `prepare_content_of_articles` (`src/tasks/article_preparation.py:578-615`) and its async counterpart `_prepare_content_async` are not called from `_dispatch_processing_chains()` and are therefore unreachable in the normal pipeline today. Do not assume they are a proven production path just because they exist. The batch task introduced in this phase should either replace them cleanly or remove/clearly deprecate them to avoid confusion.

Acceptance criteria:
- A discovery wave of `18` articles for one login performs one preparation authentication, not `18`.
- Preparation time per article drops and worker utilization becomes smoother.
- A transient auth failure retries the batch without immediately flipping every pending row from `discovered` to `failed`.

### Phase 4: Batch posting by login

1. Add a new login-scoped batch posting task `post_comments_for_login_batch(login_id, ai_comment_ids)` in `src/tasks/comment_posting.py`, or refactor the existing process-level batch posting code so it can be reused for login-scoped explicit ID sets.
2. Give that task coordinator behavior rather than dispatching it as a naive direct replacement for `post_comment_for_article`:
   - if any explicit IDs are still `prepared`, retry later without authenticating
   - if all explicit IDs are terminal and at least one is `generated`, proceed to posting
   - if all explicit IDs failed generation, exit without authenticating
3. Once ready, authenticate once via `initialize_session_for_login`, iterate over the provided `AIComment` IDs that are still `generated`, post each, mark each row.
4. Retain `post_comment_for_article` as the fallback for targeted retry and debugging.
5. Keep both manual entry points working:
   - `/api/v1/comments/{id}/post` uses the direct API path today
   - `/api/v1/monitoring-processes/{id}/post-comments` uses the process-level Celery batch poster today

Acceptance criteria:
- A posting wave for `18` generated comments performs one posting authentication, not `18`.
- The batch posting task does not authenticate early while generation is still in progress for the same explicit ID set.
- Existing manual posting behavior continues to work.

### Phase 5: Persist and restore session cookies

1. Add cookie serialization helpers in `ScraperService`.
2. Persist the cookie jar into `MyMomentSession.session_data` after successful login.
3. Restore persisted cookies during `_initialize_single_session()`.
4. Validate restored cookies with `_check_authentication_status()`.
5. Fall back to full login only when validation fails.
6. On success, `touch` or renew the session record so active session metadata stays current. If the desired session TTL is rolling, call out explicitly that `touch_session()` alone updates `last_accessed` but does not extend `expires_at`.
7. Log whether a session was restored or fully re-authenticated.

Acceptance criteria:
- Full login count drops materially on repeated discovery cycles (the dominant remaining auth source after Phases 3 and 4 are in place).
- Restored sessions succeed often enough to justify the extra code path (target: >80% cookie-restore hit rate on discovery).
- Failed cookie restores degrade cleanly into normal login without breaking the pipeline.

### Phase 6: Improve worker topology and fairness

1. Change deployment so generation runs on dedicated worker processes, separate from discovery/preparation/posting/scheduler.
2. Keep some worker capacity reserved for short-running queues.
3. Add an app-level fairness mechanism for generation, for example:
   - per-process in-flight generation cap, or
   - round-robin release of generation tasks
4. Monitor time-to-first-generation for each concurrent process.

Acceptance criteria:
- The second concurrent process no longer waits about `6m11s` to start generation.
- Discovery/preparation/posting stay responsive even while long LLM jobs are running.

### Phase 7: Tune LLM cost (if not already done in Phase 0)

1. Compare reasoning and non-reasoning runs on the same article set.
2. Measure quality vs latency vs completion tokens.
3. If acceptable, use non-reasoning mode for production monitoring or reserve reasoning for specific processes/templates.
4. Consider explicit output/token limits to control long-tail generation time.

Acceptance criteria:
- Average generation time drops without unacceptable quality loss.
- Completion token growth is kept under control.

### Phase 8: Add metrics and verify gains

1. Add structured counters/log fields for:
   - discovery attempts
   - discovery hits
   - full logins
   - cookie restores
   - preparation batch size
   - time-to-first-generated-comment
   - per-process in-flight generation count
2. Re-run the same two-process benchmark after each phase.
3. Compare stage-time shares and auth counts against the current baseline.

Acceptance criteria:
- The improvements are visible in logs/metrics, not just inferred from code changes.

## Suggested Success Metrics for the Next Benchmark

Use the same workload (two concurrent processes, same articles) and compare against this baseline:

| Metric | Baseline | Target after Phases 1-5 |
| --- | --- | --- |
| Discovery tasks (total) | `153` | Under `10` |
| Zero-result discovery ratio | `150/153` (98%) | Under `30%` |
| Full logins (total) | `225` | Under `10` (2 per login after batching + cookie restore) |
| Preparation auths per 18-article wave | `18` | `1` |
| Posting auths per 18-article wave | `18` | `1` |
| Time to first generation, second process | `6m11s` | Under `90s` |
| Reasoning process avg generation time | `68.5s` | Under `40s` (after Phase 0 LLM change) |
| Discovery share of total stage time | `34.9%` | Under `5%` |
| Generation share of total stage time | `54.2%` | Over `85%` (expected: generation dominates after orchestration fixes) |

## Final Recommendation

**If only one thing can be done today:** disable reasoning mode on the `magistral-medium-latest` process. It is a config change, zero risk, and cuts that process's generation time in half.

**If three code changes can be done first, the best sequence is:**

1. Fix the duplicate/global immediate kickoff (`monitoring_service.py:557` + `scheduler.py:171-180`).
2. Add discovery backpressure scoped to `status = 'discovered'` rows, plus a durable cooldown / lease; raise the polling interval from `10s`.
3. Implement per-login batch preparation, then add login-batch posting with an explicit coordinator/finalizer for generation completion.

That sequence removes the clearest orchestration waste first and brings the `225` auth events down to the low single digits for a typical run. After that, persisted cookie reuse eliminates the remaining discovery auth overhead, and worker topology changes address fairness between concurrent processes.

---

## Implementation Log

### Phase 1 — Remove duplicate startup work (2026-04-14)

**Status:** Complete

**Files changed:**
- `src/tasks/scheduler.py`
- `src/services/monitoring_service.py`
- `tests/unit/services/test_monitoring_service.py`

**What was done:**

1. **Extended `trigger_monitoring_pipeline` and `_trigger_pipeline_async`** to accept an optional `process_ids: Optional[List[str]]` parameter. When provided, the DB query filters to only those process IDs instead of scanning all running processes. UUID normalization (with error handling for invalid IDs) happens inside the scheduler task so callers can safely pass string IDs.

2. **Updated `MonitoringService.start_process()`** (previously line 557): replaced `trigger_monitoring_pipeline.delay(force_immediate=True)` with `trigger_monitoring_pipeline.delay(process_ids=[str(process_id)])`. The process-scoped call triggers discovery for exactly the process being started — not a global re-scan of all running processes.

3. **In-flight guard preserved**: The old `force_immediate=True` call bypassed the `STARTED`/`RETRY` task-state check (line 220: `if not force_immediate and current_task_id`). The new call leaves `force_immediate` at its default `False`, so the guard is fully active. Gemini review confirmed this is safe: a freshly started process will have `celery_discovery_task_id = None` (cleared by `_clear_process_task_ids` on stop), so the guard will not block the first discovery. Abnormal-termination edge cases are already handled by the `STARTED`/`RETRY` predicate — expired or completed task IDs do not block re-spawning.

4. **Added trigger-mode logging**: Both the Celery entrypoint and the async implementation log `mode=process_scoped` or `mode=periodic_global` with process counts and `force_immediate` value. The result dict also includes a `trigger_mode` key.

5. **`force_immediate` kept as legacy parameter**: It is still wired through to `_spawn_stage_tasks_for_process` for backward compatibility with any older callers that might pass it. Docstring updated to note it is superseded by `process_ids` for new startup kickoffs.

6. **Unit test updated**: `test_start_process` mock assertion updated from `mock_delay.assert_called_once_with(force_immediate=True)` to `mock_delay.assert_called_once_with(process_ids=[str(process.id)])`.

**Rationale:**

The root cause of the duplicate startup burst (documented in Finding §2 and `logs/worker.log` lines ~395-445) was that `force_immediate=True` on `trigger_monitoring_pipeline` caused a global scan of all running processes, bypassing the in-flight guard. With two processes starting near-simultaneously, each start call re-scanned both processes and each spawned discovery for both — producing up to 4× the expected discovery work at startup.

The `process_ids` scoping fixes this at the source: each start call dispatches discovery for its own process only, and does so through the normal scheduler path so the in-flight guard remains in force.

**Gemini review findings (2026-04-14):**
- Implementation correctly achieves Phase 1 goals.
- Removal of `force_immediate=True` is safe given normal `_clear_process_task_ids` lifecycle and the STARTED/RETRY guard semantics.
- UUID normalization is robust.
- Race condition between `start_process` DB commit and scheduler execution is safe: the process is committed as `running` before the scheduler task is dispatched.
- `force_immediate` should be retained for backward compatibility but its docstring updated (done).

**Expected acceptance criteria check:**
- Starting two processes should now produce exactly one immediate discovery spawn per process. ✓ (scoped DB query + active guard)
- No repeated startup discovery bursts like `logs/worker.log` lines 395-445. ✓ (global re-scan eliminated)

### Phase 1 Unit Tests (2026-04-14)

**Status:** Complete

**Files changed:**
- `tests/unit/tasks/test_scheduler.py` — new file, 12 tests
- `tests/unit/services/test_monitoring_service.py` — one test strengthened, timezone comparison fixed

**Workflow:** Codex plan pass (read-only) → plan reviewed → Codex implementation pass (workspace-write) → Gemini review → manual fixes applied.

**Tests added in `tests/unit/tasks/test_scheduler.py`:**

| Test | What it pins |
|---|---|
| `test_trigger_pipeline_async_process_scoped_filters_to_requested_running_active_processes` | process-scoped mode only dispatches requested IDs that are `running` + `is_active`; stopped/inactive/unrequested rows excluded; `trigger_mode == "process_scoped"` |
| `test_trigger_pipeline_async_process_scoped_reports_invalid_ids` | invalid UUIDs (`"not-a-uuid"`, `None`) land in `errors`; valid IDs still dispatch; error count matches invalid count |
| `test_trigger_pipeline_async_periodic_global_scans_all_running_active_processes` | `process_ids=None` scans all `running` + `is_active` rows; stopped/inactive excluded; `trigger_mode == "periodic_global"` |
| `test_trigger_pipeline_async_inflight_guard_skips_started_or_retry_tasks` (parametrized 4×) | `STARTED` and `RETRY` states skip dispatch in both trigger modes; `skipped_details` shape verified; `celery_discovery_task_id` unchanged in DB |
| `test_trigger_pipeline_async_inflight_guard_spawns_on_pending_state` (parametrized 2×) | `PENDING` is NOT treated as in-flight; re-spawning is allowed (guards against stale/expired result TTL permanently blocking a process) |
| `test_trigger_pipeline_async_inflight_guard_spawns_on_async_result_exception` (parametrized 2×) | AsyncResult raising an exception → fail-open: warning logged, new task spawned anyway |
| `test_trigger_monitoring_pipeline_wrapper_forwards_process_ids_to_async_impl` | Celery wrapper passes `force_immediate` and `process_ids` through to async impl unchanged |

**Test in `tests/unit/services/test_monitoring_service.py` strengthened:**
- `test_start_process_triggers_process_scoped_scheduler_delay`: verifies full result payload (associated_logins, associated_prompts, max_duration_minutes, generate_only, started_at), process DB state, and `mock_delay.assert_called_once_with(process_ids=[str(process.id)])`
- Timezone comparison fixed: was `.replace("+00:00", "")` string strip (fragile); now uses `datetime.fromisoformat()` + `.astimezone(timezone.utc)` comparison (robust to any UTC representation)

**Rationale for PENDING and exception edge cases:**
The `_spawn_stage_tasks_for_process` implementation contains an explicit comment (lines 222-226) that `PENDING` means "unknown or queued" in Celery and also represents expired results. The intent is that only `STARTED` and `RETRY` should block re-spawning. Without a test, this invariant could silently regress. Similarly, the `except Exception` guard in the AsyncResult path is designed to fail open — a test confirms this is not just dead code.

**Gemini review findings (2026-04-14):**
- Coverage completeness: all Phase 1 goals covered
- Mocking approach sound; real `db_engine` usage ensures SQL queries are valid
- Parametrize coverage across both trigger modes confirmed correct
- Flagged timezone fix as fragile → applied `datetime.fromisoformat()` fix
- Suggested PENDING state test and AsyncResult exception test → both added
- All 18 tests pass

### Phase 2 — Add discovery backpressure (2026-04-14)

**Status:** Complete

**Files changed:**
- `src/models/monitoring_process.py` — 3 new columns
- `migrations/versions/2026041401_add_discovery_backpressure_state.py` — new migration
- `src/tasks/scheduler.py` — backpressure logic, backoff, durable state refresh
- `src/services/monitoring_service.py` — reset durable state on process start
- `tests/unit/tasks/test_scheduler.py` — updated `fake_spawn` signatures (`session` param)

**What was done:**

1. **Three new `MonitoringProcess` columns** (`next_discovery_at`, `discovery_empty_streak`, `discovery_queued_at`) track durable per-process discovery scheduler state, persisted in DB so restarts and coordinator hand-offs do not lose cooldown context.

2. **Migration** (`2026041401_add_discovery_backpressure_state.py`) uses `op.batch_alter_table` for SQLite compatibility. `down_revision = 'f0c58f54ecfa'`.

3. **`_spawn_stage_tasks_for_process` now accepts `session`** and applies a layered decision gate before each spawn:
   - **Terminal state refresh**: reads the previous discovery task's `AsyncResult`; if `SUCCESS`/`FAILURE`/`REVOKED`, updates streak/cooldown and clears the task ID + lease. This converts the last run's outcome into the next eligibility window before any skip decision.
   - **Backlog gate** (`pending_discovered_backlog`): counts `AIComment.status='discovered'` rows for this process. If any exist, skip. Predicate is exact — does not count `prepared` or `generated` rows.
   - **Cooldown gate** (`cooldown_active`): if `next_discovery_at` is in the future, skip.
   - **Lease gate** (`discovery_lease_active`): if `discovery_queued_at` is within the last 30s, skip. Prevents double-spawn when a task is queued but not yet `STARTED`.
   - **Existing `STARTED`/`RETRY` guard** retained as a final in-flight check.
   - On spawn: sets `discovery_queued_at = now`.

4. **Exponential backoff formula**:
   ```
   effective_base = max(ARTICLE_DISCOVERY_INTERVAL_SECONDS, 30)
   delay = min(effective_base * 2^(streak-1), 600)
   ```
   - Zero-result success: `streak += 1`, `next_discovery_at = now + delay`
   - Non-zero success: `streak = 0`, `next_discovery_at = now` (backlog gate is still primary guard)
   - FAILURE/REVOKED (no parseable count): `next_discovery_at = now + effective_base` (minimum cooldown, no streak increment — prevents tight-loop retries on persistent errors without penalizing backoff)

5. **`_trigger_pipeline_async` returns `discovery_metrics`** per process: `last_discovered_count`, `zero_hit_streak`, `pending_backlog_count`, `next_eligible_discovery_at`, `skip_reason`.

6. **`start_process()` resets** `next_discovery_at = now`, `discovery_empty_streak = 0`, `discovery_queued_at = None` before dispatching the process-scoped scheduler trigger. A restart is never delayed by stale cooldown from a previous run.

**Rationale:**

The original scheduler had only one guard: `AsyncResult.state in {STARTED, RETRY}`. The benchmark showed that this was insufficient — 150 of 153 discovery runs produced zero results because the guard only blocked re-spawn while a task was actively running; once a task finished (or its result TTL expired, making it `PENDING`), the scheduler would immediately spawn another. The durable state approach changes the semantics: the scheduler now tracks *when the next discovery is eligible* and *whether there is outstanding work to drain*, independently of whether Celery's result backend is reachable.

**Gemini review findings (2026-04-14):**
- Backoff formula correct (`2^max(streak-1, 0)`, base floor of 30s, cap of 600s)
- Terminal state refresh logic correct; `REVOKED` handled gracefully (streak not incremented)
- Backlog predicate (`status='discovered'` only) correct per TODO spec
- Lease of 30s is reasonable as safety valve for PENDING → STARTED transition
- Cooldown reset to `now` on non-zero success is safe (backlog gate is primary guard)
- **Flagged**: FAILURE terminal state with unparseable result set no cooldown → tight-loop retry risk → **fixed**: minimum cooldown (`effective_base` seconds) applied on FAILURE/REVOKED with no parseable count
- `discovery_metrics` key in wrapper test: not a regression (test mocks `_trigger_pipeline_async` and returns hardcoded dict; test still passes)
- SQLite batch_alter_table, timezone-awareness, double-fetch of task ID after terminal refresh — all confirmed correct
- All 18 existing tests pass after updating `fake_spawn` signatures to accept the new `session` parameter
