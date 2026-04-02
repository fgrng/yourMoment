# Tests

The rebuilt test tree is organized around execution boundaries. The local milestone command is:

```bash
.venv/bin/pytest tests/unit -q
```

Run that command from the repository root. It is the authoritative signal for the unit-suite rebuild milestone. The unit tree must stay free of live network calls, Redis, Celery workers, and real LLM provider credentials.

## Layout

```text
tests/
├── conftest.py              # test env contract + singleton resets
├── support/
│   ├── runtime.py           # settings/database/encryption reset helpers
│   └── database.py          # opt-in async SQLite fixtures
├── fixtures/
│   ├── loaders.py           # static fixture loader API
│   ├── factories/           # valid-by-default persisted model rows
│   ├── builders.py          # named multi-record scenarios
│   ├── stubs.py             # LiteLLM, aiohttp, Celery doubles
│   └── myMoment_html/       # canonical scraper fixture corpus
└── unit/
    ├── pure/                # no DB fixture required
    ├── db/                  # models, factories, runtime contract
    ├── services/            # service-layer tests
    └── tasks/               # task entrypoints and task helpers
```

Use the narrowest layer that matches the behavior under test. Pure tests should not request `db_session`. DB, service, and task tests should reuse the shared fixtures instead of creating ad hoc engines or inline payloads.

## Fixture Loaders

Static scraper assets live only under `tests/fixtures/`. Do not read from `examples/` or `devlog/`.

Use the loader API instead of building file paths inline:

```python
from tests.fixtures.loaders import load_html_fixture, load_json_fixture, load_manifest

html = load_html_fixture("articles_index")
manifest = load_manifest()
metadata = load_json_fixture("manifest")
```

`load_html_fixture()` accepts names with or without `.html`. `load_json_fixture()` searches `tests/fixtures/myMoment_html/` first and then `tests/fixtures/`. `load_manifest()` is the canonical way to inspect the HTML corpus catalog.

## Factories And Scenarios

Factories create valid-by-default persisted rows. Prefer them when a test needs only one or two records:

```python
from tests.fixtures.factories import create_user, create_mymoment_login, create_llm_provider

user = await create_user(db_session)
login = await create_mymoment_login(db_session, user=user)
provider = await create_llm_provider(db_session, user=user)
```

Factory conventions:

- Pass `user=` or `user_id=` explicitly for user-owned rows.
- Let factories handle encrypted fields through model helpers such as `set_credentials()` and `set_api_key()`.
- Treat returned objects as already persisted; they have been added to the session and flushed.

Scenarios build a reusable workflow state when a test needs multiple related records:

```python
from tests.fixtures.builders import build_scenario

scenario = await build_scenario("prepared_not_generated", db_session)
comment = scenario["ai_comment"]
process = scenario["process"]
```

Use `overrides=` to adjust a named scenario without forking it:

```python
scenario = await build_scenario(
    "minimal_happy_path",
    db_session,
    overrides={"process": {"generate_only": True}},
)
```

Current public scenario names are defined in `tests/fixtures/builders.py` and include:

- `minimal_happy_path`
- `multi_login_monitoring`
- `generate_only_process`
- `hidden_comment_process`
- `provider_fallback`
- `expired_mymoment_session`
- `article_discovered_not_prepared`
- `prepared_not_generated`
- `generated_not_posted`
- `posted_comment_audit_snapshot`
- `cross_user_access_denied`
- `max_process_limit_reached`
- `student_backup_with_versions`

## Unit-Only Commands

Use the unit tree directly instead of broad `pytest` invocations while the larger suite is being rebuilt:

```bash
.venv/bin/pytest tests/unit -q
.venv/bin/pytest tests/unit/pure -q
.venv/bin/pytest tests/unit/db -q
.venv/bin/pytest tests/unit/services -q
.venv/bin/pytest tests/unit/tasks -q
```

Useful focused runs:

```bash
.venv/bin/pytest tests/unit -q -k scenario
.venv/bin/pytest tests/unit/tasks -q -m "database and celery"
```

`tests/conftest.py` sets the test env contract before app imports. If a test needs different environment inputs, override them with `monkeypatch` inside the test and rely on the autouse singleton reset fixture to clear cached settings afterwards.
