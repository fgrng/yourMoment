"""Creating and editing a monitoring process through the router: the target and the search term."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.monitoring_processes import (
    create_monitoring_process,
    get_monitoring_process,
    list_monitoring_processes,
    update_monitoring_process,
)
from src.api.schemas import MonitoringProcessCreate, MonitoringProcessUpdate
from src.platforms import PlatformUnavailable, TargetDimension
from tests.fixtures.factories.mymoment import create_mymoment_login
from tests.fixtures.factories.prompts import create_user_prompt_template
from tests.fixtures.factories.providers import create_llm_provider
from tests.fixtures.factories.users import create_user


pytestmark = [pytest.mark.unit, pytest.mark.database]


async def _create(db_session, user, **fields):
    provider = await create_llm_provider(db_session, user=user)
    prompt = await create_user_prompt_template(db_session, user=user)
    login = await create_mymoment_login(db_session, user=user)
    data = MonitoringProcessCreate(
        name="Klasse 4711",
        max_duration_minutes=60,
        llm_provider_id=provider.id,
        prompt_template_ids=[prompt.id],
        mymoment_login_ids=[login.id],
        **fields,
    )
    return await create_monitoring_process(
        process_data=data, current_user=user, session=db_session
    )


async def test_create_returns_target_and_search(db_session):
    user = await create_user(db_session)

    response = await _create(
        db_session,
        user,
        target={"classroom": "4711", "category": "7"},
        search="Rotpanda",
    )

    assert (response.target, response.search) == (
        {"classroom": "4711", "category": "7"},
        "Rotpanda",
    )


async def test_create_rejects_an_invalid_target_with_422(db_session):
    user = await create_user(db_session)

    with pytest.raises(HTTPException) as error:
        await _create(db_session, user, target={"category": "7"})

    assert error.value.status_code == 422
    assert "classroom" in error.value.detail["message"]


async def test_update_replaces_the_target_and_clears_the_search(db_session):
    user = await create_user(db_session)
    created = await _create(
        db_session,
        user,
        target={"classroom": "4711", "arrangement": "12"},
        search="Rotpanda",
    )

    response = await update_monitoring_process(
        process_id=created.id,
        process_data=MonitoringProcessUpdate(target={"classroom": "4711"}, search=None),
        current_user=user,
        session=db_session,
    )

    assert (response.target, response.search) == ({"classroom": "4711"}, None)


async def test_update_without_target_and_search_keeps_both(db_session):
    user = await create_user(db_session)
    created = await _create(
        db_session, user, target={"classroom": "4711"}, search="Rotpanda"
    )

    response = await update_monitoring_process(
        process_id=created.id,
        process_data=MonitoringProcessUpdate(name="Neu"),
        current_user=user,
        session=db_session,
    )

    assert (response.name, response.target, response.search) == (
        "Neu",
        {"classroom": "4711"},
        "Rotpanda",
    )


async def test_update_rejects_an_invalid_target_with_422(db_session):
    user = await create_user(db_session)
    created = await _create(db_session, user, target={"classroom": "4711"})

    with pytest.raises(HTTPException) as error:
        await update_monitoring_process(
            process_id=created.id,
            process_data=MonitoringProcessUpdate(target={"classroom": "alle"}),
            current_user=user,
            session=db_session,
        )

    assert error.value.status_code == 422


def _shown(response):
    return [(entry.label, entry.value) for entry in response.target_display]


async def test_list_and_detail_show_the_target_with_the_labels_of_the_description(
    db_session,
):
    user = await create_user(db_session)
    created = await _create(
        db_session, user, target={"classroom": "4711", "arrangement": "10"}
    )

    listed = await list_monitoring_processes(
        limit=50, offset=0, is_running=None, current_user=user, session=db_session
    )
    detail = await get_monitoring_process(
        process_id=created.id, current_user=user, session=db_session
    )

    assert (
        _shown(listed[0])
        == _shown(detail)
        == [("Schreibaufgabe", "10"), ("Klasse", "4711")]
    )


async def test_target_is_shown_while_the_platform_is_unreachable(
    db_session, fake_platform
):
    fake_platform.target_description = (
        TargetDimension(key="classroom", label="Klasse", required=True),
    )
    fake_platform.fail("connect", PlatformUnavailable("myMoment ist nicht erreichbar"))
    user = await create_user(db_session)
    created = await _create(db_session, user, target={"classroom": "4711"})

    detail = await get_monitoring_process(
        process_id=created.id, current_user=user, session=db_session
    )

    assert _shown(detail) == [("Klasse", "4711")]
