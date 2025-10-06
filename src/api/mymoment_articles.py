"""Article discovery endpoints backed by live myMoment scraping."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload

from src.api.schemas import (
    ArticleResponse,
    ArticleDetailResponse,
    ArticleListResponse,
    TabResponse,
    TabListResponse,
    ErrorResponse
)
from src.api.auth import get_current_user
from src.config.database import get_session
from src.models.user import User
from src.models.mymoment_login import MyMomentLogin
import logging

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/mymoment-articles", tags=["myMoment Articles"])


async def verify_login_ownership(
    mymoment_login_id: uuid.UUID,
    user_id: uuid.UUID,
    session: AsyncSession
) -> MyMomentLogin:
    """Verify that the user owns the specified myMoment login."""
    result = await session.execute(
        select(MyMomentLogin).where(
            and_(
                MyMomentLogin.id == mymoment_login_id,
                MyMomentLogin.user_id == user_id,
                MyMomentLogin.is_active == True
            )
        )
    )
    login = result.scalar_one_or_none()

    if not login:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MyMoment login not found or not accessible"
        )

    return login


@router.get("/{mymoment_login_id}/index", response_model=ArticleListResponse)
async def get_articles(
    mymoment_login_id: uuid.UUID = Path(..., description="MyMoment login to use for viewing articles"),
    category: Optional[int] = Query(None, description="Filter by myMoment category ID"),
    tab: str = Query("alle", description="MyMoment tab to scrape (alle, favoriten, entwuerfe, etc.)"),
    limit: int = Query(20, ge=1, le=100, description="Number of articles to fetch from myMoment"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Browse articles from myMoment platform live via scraping.

    This endpoint:
    1. Verifies user owns the specified myMoment login
    2. Initializes a scraping session with myMoment platform
    3. Discovers articles based on filters (category, tab)
    4. Returns article metadata (title, author, category, etc.)

    Note: This does NOT store articles in the database. Articles are only
    stored when AI comments are generated via monitoring processes.
    """
    try:
        # Verify user owns the myMoment login
        login = await verify_login_ownership(mymoment_login_id, current_user.id, session)

        logger.info(f"User {current_user.id} scraping articles with login {mymoment_login_id} (tab={tab}, limit={limit})")

        # Initialize scraper service
        from src.services.scraper_service import ScraperService
        scraper = ScraperService(db_session=session)

        try:
            # Initialize scraping session for this login
            context = await scraper.initialize_session_for_login(
                login_id=mymoment_login_id,
                user_id=current_user.id
            )

            # Discover articles from myMoment platform
            discovered_articles = await scraper.discover_new_articles(
                context=context,
                tab=tab,
                limit=limit
            )

            logger.info(f"Discovered {len(discovered_articles)} articles from myMoment")

            # Apply filters, not implementet here / yet
            filtered_articles = discovered_articles

            if category is not None:
                filtered_articles = [
                    a for a in filtered_articles
                    if a.category_id == category
                ]

            # Convert to response format
            from datetime import datetime
            article_responses = []
            for article_meta in filtered_articles:
                article_responses.append(ArticleResponse(
                    id=article_meta.id,
                    title=article_meta.title,
                    author=article_meta.author,
                    # category=article_meta.category_id if article_meta.category_id is not None else 0,
                    published_at=None, # not available in index view
                    edited_at=article_meta.date,
                    scraped_at=datetime.utcnow(), # Current scraping time
                    mymoment_url=article_meta.url,
                    visibility=article_meta.visibility,
                    ai_comments_count=0,  # Not stored yet
                    accessible_by_login_ids=[mymoment_login_id]  # Current login
                ))

            return ArticleListResponse(
                items=article_responses,
                total=len(article_responses),
                limit=limit,
                offset=0
            )

        finally:
            # Clean up scraping session
            await scraper.cleanup_session(mymoment_login_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error scraping articles for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to scrape articles from myMoment: {str(e)}"
        )


@router.get("/{mymoment_login_id}/tabs", response_model=TabListResponse)
async def get_available_tabs(
    mymoment_login_id: uuid.UUID = Path(..., description="MyMoment login to use for discovering tabs"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Get available article tabs for a myMoment login.

    Tabs represent different article filters on the myMoment platform:
    - **home**: User's own articles ("Meine")
    - **alle**: All publicly visible articles ("Alle")
    - **class**: Articles visible to specific classes (e.g., "Dummy Klasse 01")

    This endpoint scrapes the myMoment articles page to discover which tabs
    are available for the specified login credentials.
    """
    try:
        # Verify user owns the myMoment login
        login = await verify_login_ownership(mymoment_login_id, current_user.id, session)

        logger.info(f"User {current_user.id} discovering tabs for login {mymoment_login_id}")

        # Initialize scraper service
        from src.services.scraper_service import ScraperService
        scraper = ScraperService(db_session=session)

        try:
            # Initialize scraping session for this login
            context = await scraper.initialize_session_for_login(
                login_id=mymoment_login_id,
                user_id=current_user.id
            )

            # Discover available tabs from myMoment platform
            discovered_tabs = await scraper.discover_available_tabs(context)

            logger.info(f"Discovered {len(discovered_tabs)} tabs for login {mymoment_login_id}")

            # Convert to response format
            tab_responses = [
                TabResponse(
                    id=tab.id,
                    name=tab.name,
                    tab_type=tab.tab_type
                )
                for tab in discovered_tabs
            ]

            return TabListResponse(
                items=tab_responses,
                total=len(tab_responses)
            )

        finally:
            # Clean up scraping session
            await scraper.cleanup_session(mymoment_login_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error discovering tabs for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to discover tabs from myMoment: {str(e)}"
        )


@router.get("/{mymoment_login_id}/article/{mymoment_article_id}", response_model=ArticleDetailResponse)
async def get_article_detail(
    mymoment_login_id: uuid.UUID = Path(..., description="MyMoment login to use for viewing article"),
    mymoment_article_id: str = Path(..., description="MyMoment article ID"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Get detailed article information with content from myMoment platform.

    This endpoint:
    1. Verifies user owns the specified myMoment login
    2. Initializes a scraping session with myMoment platform
    3. Fetches article content, HTML, and metadata
    4. Returns complete article information

    Note: This scrapes content live from myMoment and does NOT store it in the database.
    Articles are only stored when AI comments are generated via monitoring processes.
    """
    try:
        # Verify user owns the myMoment login
        login = await verify_login_ownership(mymoment_login_id, current_user.id, session)

        logger.info(f"User {current_user.id} fetching article {mymoment_article_id} with login {mymoment_login_id}")

        # Initialize scraper service
        from src.services.scraper_service import ScraperService
        scraper = ScraperService(db_session=session)

        try:
            # Initialize scraping session for this login
            context = await scraper.initialize_session_for_login(
                login_id=mymoment_login_id,
                user_id=current_user.id
            )

            # Get article content from myMoment platform
            article_data = await scraper.get_article_content(
                context=context,
                article_id=mymoment_article_id
            )

            if not article_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Article not found or not accessible"
                )

            logger.info(f"Successfully fetched article {mymoment_article_id}")

            # Convert to response format
            from datetime import datetime
            return ArticleDetailResponse(
                id=article_data['id'],
                title=article_data['title'],
                author=article_data['author'],
                published_at=None,  # Not available on detail page
                edited_at=None,  # Not available on detail page
                scraped_at=datetime.utcnow(),  # Current scraping time
                mymoment_url=article_data['url'],
                visibility='Unknown',  # Not available on detail page
                ai_comments_count=0,  # Not stored yet
                accessible_by_login_ids=[mymoment_login_id],  # Current login
                content=article_data['content'],
                raw_html=article_data['full_html'],
                comment_ids=[]  # No stored comments yet
            )

        finally:
            # Clean up scraping session
            await scraper.cleanup_session(mymoment_login_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching article {mymoment_article_id} for user {current_user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch article from myMoment: {str(e)}"
        )
