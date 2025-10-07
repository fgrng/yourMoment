"""Contract tests for GET endpoints under /api/v1/comments."""

from datetime import datetime, timezone
import uuid

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from tests.helper import create_test_app, create_test_user
from src.models.user import User
from src.models.ai_comment import AIComment


async def _get_user(db_session, email: str) -> User:
    async with db_session() as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one()


async def _seed_comment(db_session, user_id: uuid.UUID, article_id: str = "article-123") -> AIComment:
    async with db_session() as session:
        comment = AIComment(
            mymoment_article_id=article_id,
            user_id=user_id,
            article_title="Test Article",
            article_author="Author",
            article_category=None,
            article_url="https://example.com/article",
            article_content="Test content",
            article_raw_html="<p>Test content</p>",
            article_scraped_at=datetime.now(timezone.utc),
            comment_content="[Dieser Kommentar stammt von einem KI-ChatBot.] Test comment",
        )
        session.add(comment)
        await session.commit()
        await session.refresh(comment)
        return comment


@pytest.mark.contract
@pytest.mark.asyncio
async def test_list_comments_returns_user_items():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)
    user = await _get_user(db_session, email)
    comment = await _seed_comment(db_session, user.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]

        response = await client.get(
            "/api/v1/comments/index",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] >= 1
        assert any(item["id"] == str(comment.id) for item in payload["items"])


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_comment_detail_success():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)
    user = await _get_user(db_session, email)
    comment = await _seed_comment(db_session, user.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]

        response = await client.get(
            f"/api/v1/comments/{comment.id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == str(comment.id)
        assert payload["mymoment_article_id"] == comment.mymoment_article_id


@pytest.mark.contract
@pytest.mark.asyncio
async def test_get_comments_by_article_filters_results():
    app, db_session = await create_test_app()
    email, password = await create_test_user(app, db_session)
    user = await _get_user(db_session, email)
    target_comment = await _seed_comment(db_session, user.id, article_id="article-target")
    await _seed_comment(db_session, user.id, article_id="article-other")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]

        response = await client.get(
            f"/api/v1/comments/article/{target_comment.mymoment_article_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        payload = response.json()
        ids = {item["id"] for item in payload["items"]}
        assert str(target_comment.id) in ids
        assert payload["total"] == len(payload["items"])


@pytest.mark.contract
@pytest.mark.asyncio
async def test_comments_endpoints_require_authentication():
    app, db_session = await create_test_app()
    email, _ = await create_test_user(app, db_session)
    user = await _get_user(db_session, email)
    comment = await _seed_comment(db_session, user.id)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        list_response = await client.get("/api/v1/comments/index")
        assert list_response.status_code == 401

        detail_response = await client.get(f"/api/v1/comments/{comment.id}")
        assert detail_response.status_code == 401

        article_response = await client.get(f"/api/v1/comments/article/{comment.mymoment_article_id}")
        assert article_response.status_code == 401
