"""Article browsing endpoints: targets, article lists and previews, live from the platform."""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    ArticleResponse,
    ArticleDetailResponse,
    ArticleListResponse,
    TargetListResponse,
    TargetOptionResponse,
    TargetValueResponse,
)
from src.api.auth import get_current_user
from src.config.database import get_session
from src.models.user import User
from src.platforms import (
    ArticleRef,
    PlatformAccount,
    PlatformAuthError,
    PlatformError,
    PlatformRejected,
    PlatformUnavailable,
    adapter_for,
    connect,
)
from src.platforms.accounts import load_platform_account
import logging

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/mymoment-articles", tags=["myMoment Articles"])


async def _platform_account(
    mymoment_login_id: uuid.UUID,
    user_id: uuid.UUID,
    session: AsyncSession
) -> PlatformAccount:
    """The user's active platform account; 404 if it is someone else's or inactive."""
    account = await load_platform_account(session, mymoment_login_id, user_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MyMoment login not found or not accessible"
        )
    return account


def _platform_error(e: PlatformError, action: str) -> HTTPException:
    """Rejected requests answer 422, rejected credentials 502, an unreachable platform 503."""
    if isinstance(e, PlatformRejected):
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(e, PlatformAuthError):
        status_code = status.HTTP_502_BAD_GATEWAY
    else:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(status_code=status_code, detail=f"Failed to {action}: {e}")


@router.get("/{mymoment_login_id}/index", response_model=ArticleListResponse)
async def get_articles(
    mymoment_login_id: uuid.UUID = Path(..., description="MyMoment login to use for viewing articles"),
    category: Optional[int] = Query(None, description="Filter by myMoment category ID"),
    tab: str = Query("alle", description="Classroom to list (alle, home or a classroom ID)"),
    limit: int = Query(20, ge=1, le=100, description="Number of articles to fetch from myMoment"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Browse the articles of a classroom live on the platform, optionally of one category.

    Note: This does NOT store articles in the database. Articles are only
    stored when AI comments are generated via monitoring processes.
    """
    account = await _platform_account(mymoment_login_id, current_user.id, session)
    target = {"classroom": tab}
    if category is not None:
        target["category"] = str(category)

    logger.info(f"User {current_user.id} listing articles with login {mymoment_login_id} (target={target}, limit={limit})")
    try:
        async with connect(account) as platform:
            summaries = (await platform.list_articles(target))[:limit]
    except PlatformError as e:
        raise _platform_error(e, "list articles") from e

    scraped_at = datetime.utcnow()
    article_responses = [
        ArticleResponse(
            id=summary.ref.id,
            title=summary.title,
            author=summary.author,
            published_at=None,  # not available in list views
            edited_at=summary.extra.get("date") or (summary.edited_at.isoformat() if summary.edited_at else None),
            scraped_at=scraped_at,
            mymoment_url=summary.ref.url,
            visibility=summary.extra.get("visibility", "Unknown"),
            ai_comments_count=0,  # Not stored yet
            accessible_by_login_ids=[mymoment_login_id]
        )
        for summary in summaries
    ]
    return ArticleListResponse(
        items=article_responses,
        total=len(article_responses),
        limit=limit,
        offset=0
    )


@router.get("/{mymoment_login_id}/targets", response_model=TargetListResponse)
async def get_targets(
    mymoment_login_id: uuid.UUID = Path(..., description="MyMoment login whose targets to describe"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    The target description of a platform account's platform, with the values the account sees.

    The form builds the fields of a target from it. For myMoment these are
    category, arrangement and classroom; "alle" is never offered as classroom.
    """
    account = await _platform_account(mymoment_login_id, current_user.id, session)

    logger.info(f"User {current_user.id} listing targets for login {mymoment_login_id}")
    try:
        async with connect(account) as platform:
            options = {option.key: option for option in await platform.list_targets()}
    except PlatformError as e:
        raise _platform_error(e, "list targets") from e

    return TargetListResponse(items=[
        TargetOptionResponse(
            key=dimension.key,
            label=dimension.label,
            required=dimension.required,
            values=[TargetValueResponse.model_validate(value) for value in options[dimension.key].values]
            if dimension.key in options else [],
        )
        for dimension in adapter_for(account).describe_target()
    ])


@router.get("/{mymoment_login_id}/article/{mymoment_article_id}", response_model=ArticleDetailResponse)
async def get_article_detail(
    mymoment_login_id: uuid.UUID = Path(..., description="MyMoment login to use for viewing article"),
    mymoment_article_id: str = Path(..., description="MyMoment article ID"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Preview an article with its content, read live from the platform.

    Note: This does NOT store the article in the database. Articles are only
    stored when AI comments are generated via monitoring processes.
    """
    account = await _platform_account(mymoment_login_id, current_user.id, session)

    logger.info(f"User {current_user.id} fetching article {mymoment_article_id} with login {mymoment_login_id}")
    try:
        async with connect(account) as platform:
            # Only the ID is known here; fetch_article reads ref.id and returns the ref with its URL
            article = await platform.fetch_article(ArticleRef(id=mymoment_article_id, url=""))
    except PlatformRejected as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Article not found or not accessible"
        ) from e
    except (PlatformAuthError, PlatformUnavailable) as e:
        raise _platform_error(e, "fetch article") from e

    return ArticleDetailResponse(
        id=article.ref.id,
        title=article.title,
        author=article.author,
        published_at=article.published_at,
        edited_at=article.edited_at.isoformat() if article.edited_at else None,
        scraped_at=datetime.utcnow(),
        mymoment_url=article.ref.url,
        visibility=article.extra.get("visibility", "Unknown"),
        ai_comments_count=0,  # Not stored yet
        accessible_by_login_ids=[mymoment_login_id],
        content=article.body_text,
        raw_html=article.body_html,
        comment_ids=[]  # No stored comments yet
    )
