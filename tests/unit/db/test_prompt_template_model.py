"""DB-backed tests for the current `PromptTemplate` model behavior."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from tests.fixtures.factories import (
    create_system_prompt_template,
    create_user,
    create_user_prompt_template,
)


pytestmark = pytest.mark.database


async def test_factory_variants_match_category_helpers_and_persist_timestamps(db_session):
    user = await create_user(db_session)
    user_prompt = await create_user_prompt_template(db_session, user=user)
    system_prompt = await create_system_prompt_template(db_session)

    assert user_prompt.is_user_template is True
    assert user_prompt.is_system_template is False
    assert user_prompt.user_id == user.id
    assert user_prompt.created_at is not None
    assert user_prompt.updated_at is not None

    assert system_prompt.is_system_template is True
    assert system_prompt.is_user_template is False
    assert system_prompt.user_id is None
    assert system_prompt.created_at is not None
    assert system_prompt.updated_at is not None


async def test_placeholder_helpers_render_and_validate_persisted_templates(db_session):
    user = await create_user(db_session)
    prompt = await create_user_prompt_template(
        db_session,
        user=user,
        user_prompt_template=(
            "Title: {article_title}; Author: {article_author}; "
            "Account: {mymoment_username}."
        ),
    )

    assert set(prompt.extract_placeholders()) == {
        "article_title",
        "article_author",
        "mymoment_username",
    }
    assert prompt.validate_placeholders() == {
        "article_title": True,
        "article_author": True,
        "mymoment_username": True,
    }
    assert set(prompt.get_missing_context_keys({"article_title": "A"})) == {
        "article_author",
        "mymoment_username",
    }
    assert prompt.render_prompt(
        {
            "article_title": "My Story",
            "article_author": "Alex",
            "mymoment_username": "teacher.one",
        }
    ) == "Title: My Story; Author: Alex; Account: teacher.one."
    assert prompt.is_valid_template() is True


async def test_invalid_placeholder_marks_template_invalid(db_session):
    user = await create_user(db_session)
    prompt = await create_user_prompt_template(
        db_session,
        user=user,
        user_prompt_template="Unsupported {unknown_field}",
    )

    assert prompt.validate_placeholders() == {"unknown_field": False}
    assert prompt.is_valid_template() is False


async def test_system_template_constraint_rejects_user_ownership(db_session):
    user = await create_user(db_session)
    prompt = await create_system_prompt_template(db_session)

    prompt.user_id = user.id

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_user_template_constraint_requires_user_ownership(db_session):
    user = await create_user(db_session)
    prompt = await create_user_prompt_template(db_session, user=user)

    prompt.user_id = None

    with pytest.raises(IntegrityError):
        await db_session.flush()
