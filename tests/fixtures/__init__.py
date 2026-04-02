"""Shared fixture API for rebuilt unit tests.

Other agents should prefer:
- `tests.fixtures.factories.create_*` for persisted model rows.
- `tests.fixtures.builders.build_scenario(...)` for multi-record workflow states.
- `tests.fixtures.stubs` for LiteLLM, aiohttp, and Celery adapter doubles.
- `tests.fixtures.assertions` for common invariant checks.
"""

from tests.fixtures import factories as _factories
from tests.fixtures.assertions import (
    assert_ai_comment_state,
    assert_api_key_round_trip,
    assert_cross_user_access_denied,
    assert_mymoment_credentials_round_trip,
    assert_owned_by,
    assert_session_data_round_trip,
    assert_task_result_shape,
)
from tests.fixtures.builders import build_scenario
from tests.fixtures.factories import *  # noqa: F403

__all__ = [
    "assert_ai_comment_state",
    "assert_api_key_round_trip",
    "assert_cross_user_access_denied",
    "assert_mymoment_credentials_round_trip",
    "assert_owned_by",
    "assert_session_data_round_trip",
    "assert_task_result_shape",
    "build_scenario",
] + _factories.__all__
