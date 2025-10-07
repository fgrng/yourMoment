import asyncio
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from bs4 import BeautifulSoup

from src.services.scraper_service import (
    ScraperService,
    ScrapingError,
    SessionContext,
    SessionError,
)


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def scraper_service(mock_db_session):
    return ScraperService(db_session=mock_db_session)


@pytest.mark.asyncio
async def test_initialize_sessions_partial_success(scraper_service, mock_db_session):
    process_id = uuid.uuid4()
    user_id = uuid.uuid4()
    login_ids = [uuid.uuid4(), uuid.uuid4()]
    process = SimpleNamespace(
        id=process_id,
        user_id=user_id,
        mymoment_login_associations=[
            SimpleNamespace(mymoment_login_id=login_ids[0]),
            SimpleNamespace(mymoment_login_id=login_ids[1]),
        ],
    )
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = process
    mock_db_session.execute.return_value = execute_result

    successful_context = SimpleNamespace(login_id=login_ids[0])
    call_log = []

    async def fake_initialize(login_id, _user_id):
        call_log.append(login_id)
        if login_id == login_ids[0]:
            return successful_context
        raise SessionError("boom")

    scraper_service._initialize_single_session = fake_initialize  # type: ignore[attr-defined]
    scraper_service.cleanup_all_sessions = AsyncMock()

    contexts = await scraper_service.initialize_sessions_for_process(process_id, user_id)

    assert contexts == [successful_context]
    assert call_log == login_ids
    scraper_service.cleanup_all_sessions.assert_not_called()


@pytest.mark.asyncio
async def test_initialize_sessions_all_fail(scraper_service, mock_db_session):
    process_id = uuid.uuid4()
    user_id = uuid.uuid4()
    login_ids = [uuid.uuid4(), uuid.uuid4()]
    process = SimpleNamespace(
        id=process_id,
        user_id=user_id,
        mymoment_login_associations=[
            SimpleNamespace(mymoment_login_id=login_ids[0]),
            SimpleNamespace(mymoment_login_id=login_ids[1]),
        ],
    )
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = process
    mock_db_session.execute.return_value = execute_result

    async def always_fail(*_args, **_kwargs):
        raise SessionError("nope")

    scraper_service._initialize_single_session = always_fail  # type: ignore[attr-defined]
    scraper_service.cleanup_all_sessions = AsyncMock()

    with pytest.raises(ScrapingError) as exc:
        await scraper_service.initialize_sessions_for_process(process_id, user_id)

    assert "Failed to initialize any sessions" in str(exc.value)
    scraper_service.cleanup_all_sessions.assert_awaited()


@pytest.mark.asyncio
async def test_initialize_sessions_no_logins(scraper_service, mock_db_session):
    process_id = uuid.uuid4()
    user_id = uuid.uuid4()
    process = SimpleNamespace(
        id=process_id,
        user_id=user_id,
        mymoment_login_associations=[],
    )
    execute_result = MagicMock()
    execute_result.scalar_one_or_none.return_value = process
    mock_db_session.execute.return_value = execute_result

    scraper_service.cleanup_all_sessions = AsyncMock()

    with pytest.raises(ScrapingError) as exc:
        await scraper_service.initialize_sessions_for_process(process_id, user_id)

    assert "No myMoment logins configured" in str(exc.value)
    scraper_service.cleanup_all_sessions.assert_awaited()


def test_extract_article_metadata(scraper_service):
    html = """
    <div class=\"card\">
        <a href=\"/article/123/\">Read</a>
        <div class=\"card-header publiziert\"></div>
        <div class=\"article-title\">Sample Title</div>
        <div class=\"article-author\">Jane Doe</div>
        <div class=\"article-date\">2024-03-01</div>
        <div class=\"article-classroom\">Klasse 5A</div>
        <div class=\"card-body\">
            <img src=\"/media/2025/2/14/unterhalten.png.1500x1500_q85_upscale.png\" />
        </div>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    metadata = scraper_service._extract_article_metadata(soup.div)

    assert metadata is not None
    assert metadata.id == "123"
    assert metadata.title == "Sample Title"
    assert metadata.author == "Jane Doe"
    assert metadata.date == "2024-03-01"
    assert metadata.status == "Publiziert"
    assert metadata.visibility == "Klasse 5A"
    assert str(metadata.category_id) == "9"
    assert metadata.category_name == "Unterhalten"
    assert metadata.url.endswith("/article/123/")


@pytest.mark.asyncio
async def test_cleanup_session_removes_context(scraper_service):
    login_id = uuid.uuid4()
    context = SessionContext(
        login_id=login_id,
        session_id=uuid.uuid4(),
        username="tester",
        aiohttp_session=SimpleNamespace(close=AsyncMock()),
        csrf_token=None,
        last_activity=datetime.utcnow(),
        is_authenticated=True,
    )
    async with scraper_service.session_lock:
        scraper_service.active_sessions[login_id] = context

    await scraper_service.cleanup_session(login_id)

    assert login_id not in scraper_service.active_sessions
    context.aiohttp_session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_session_status(scraper_service):
    login_id = uuid.uuid4()
    context = SessionContext(
        login_id=login_id,
        session_id=uuid.uuid4(),
        username="tester",
        aiohttp_session=SimpleNamespace(close=AsyncMock()),
        csrf_token="token",
        last_activity=datetime.utcnow(),
        is_authenticated=True,
    )
    async with scraper_service.session_lock:
        scraper_service.active_sessions[login_id] = context

    status = await scraper_service.get_session_status()

    assert status["total_sessions"] == 1
    assert status["authenticated_sessions"] == 1
    assert status["sessions"][0]["login_id"] == str(login_id)
    assert status["sessions"][0]["session_id"] == str(context.session_id)
    assert status["sessions"][0]["username"] == "tester"
    assert status["sessions"][0]["is_authenticated"] is True
    iso_value = status["sessions"][0]["last_activity"]
    assert iso_value is not None and iso_value.startswith(str(context.last_activity.date()))

    await scraper_service.cleanup_all_sessions()
