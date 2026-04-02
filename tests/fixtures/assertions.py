"""Reusable assertions for the shared fixture layer."""

from __future__ import annotations

from typing import Any, Iterable


def assert_mymoment_credentials_round_trip(login: Any, *, username: str, password: str) -> None:
    """Assert that a myMoment login encrypted and decrypts its credentials correctly."""
    assert login.username_encrypted != username
    assert login.password_encrypted != password
    assert login.get_credentials() == (username, password)


def assert_api_key_round_trip(provider: Any, *, api_key: str) -> None:
    """Assert that a provider encrypted and decrypts its API key correctly."""
    assert provider.api_key_encrypted != api_key
    assert provider.get_api_key() == api_key


def assert_session_data_round_trip(session_record: Any, *, expected_data: dict[str, Any] | str) -> None:
    """Assert that a myMoment session decrypts back to its original payload."""
    assert session_record.session_data_encrypted != expected_data
    assert session_record.get_session_data(as_dict=isinstance(expected_data, dict)) == expected_data


def assert_owned_by(record: Any, owner: Any) -> None:
    """Assert that a user-owned record belongs to the expected user."""
    assert getattr(record, "user_id") == owner.id


def assert_cross_user_access_denied(actor: Any, owned_records: Iterable[Any]) -> None:
    """Assert that the actor cannot access the supplied foreign resources."""
    for record in owned_records:
        assert getattr(record, "user_id") != actor.id
        assert actor.can_access_resource(getattr(record, "user_id")) is False


def assert_ai_comment_state(comment: Any, expected_status: str) -> None:
    """Assert that an AI comment matches a pipeline state and required fields."""
    assert comment.status == expected_status
    if expected_status == "discovered":
        assert comment.article_content is None
        assert comment.comment_content is None
    if expected_status == "prepared":
        assert comment.article_content
        assert comment.comment_content is None
    if expected_status == "generated":
        assert comment.article_content
        assert comment.comment_content
        assert comment.posted_at is None
    if expected_status == "posted":
        assert comment.comment_content
        assert comment.posted_at is not None
        assert comment.mymoment_comment_id is not None
    if expected_status == "failed":
        assert comment.error_message
        assert comment.failed_at is not None


def assert_task_result_shape(
    result: dict[str, Any],
    *,
    required_keys: Iterable[str] | None = None,
    expected_status: str | None = None,
) -> None:
    """Assert the common dict payload shape used by task entrypoints."""
    assert isinstance(result, dict)
    for key in required_keys or ("status",):
        assert key in result
    if expected_status is not None:
        assert result["status"] == expected_status
