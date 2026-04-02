"""Foundation checks for named fixture scenarios."""

from __future__ import annotations

import pytest

from tests.fixtures.assertions import (
    assert_ai_comment_state,
    assert_cross_user_access_denied,
)
from tests.fixtures.builders import build_scenario


pytestmark = pytest.mark.database


@pytest.mark.parametrize(
    "scenario_name",
    [
        "minimal_happy_path",
        "multi_login_monitoring",
        "generate_only_process",
        "hidden_comment_process",
        "provider_fallback",
        "expired_mymoment_session",
        "article_discovered_not_prepared",
        "prepared_not_generated",
        "generated_not_posted",
        "posted_comment_audit_snapshot",
        "cross_user_access_denied",
        "max_process_limit_reached",
        "student_backup_with_versions",
    ],
)
async def test_named_scenarios_build_on_fresh_sessions(db_session, scenario_name):
    scenario = await build_scenario(scenario_name, db_session)

    assert scenario["name"] == scenario_name


async def test_cross_user_scenario_exposes_foreign_resource_boundary(db_session):
    scenario = await build_scenario("cross_user_access_denied", db_session)

    assert_cross_user_access_denied(scenario["actor"], [scenario["foreign_comment"]])


async def test_pipeline_scenarios_expose_expected_comment_states(db_session):
    discovered = await build_scenario("article_discovered_not_prepared", db_session)
    assert_ai_comment_state(discovered["ai_comment"], "discovered")


async def test_scenario_overrides_apply_to_public_api(db_session):
    scenario = await build_scenario(
        "minimal_happy_path",
        db_session,
        overrides={
            "user": {"email": "scenario@example.test"},
            "process": {"name": "Override Process", "generate_only": True},
        },
    )

    assert scenario["user"].email == "scenario@example.test"
    assert scenario["process"].name == "Override Process"
    assert scenario["process"].generate_only is True
