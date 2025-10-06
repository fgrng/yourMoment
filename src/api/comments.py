"""Read-only endpoints exposing the current user's AI-generated comments and snapshots."""

import uuid
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from src.api.schemas import (
    AICommentResponse,
    AICommentListResponse,
    ErrorResponse
)
from src.api.auth import get_current_user
from src.config.database import get_session
from src.models.user import User
from src.models.ai_comment import AIComment
from src.models.mymoment_login import MyMomentLogin
from src.services.scraper_service import ScraperService, ScrapingError
import logging

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/comments", tags=["Comments"])


@router.get("/index", response_model=AICommentListResponse)
async def get_user_ai_comments(
    status_filter: Optional[str] = Query(None, description="Filter by status: generated, posted, failed, deleted"),
    mymoment_login_id: Optional[uuid.UUID] = Query(None, description="Filter by myMoment login ID"),
    monitoring_process_id: Optional[uuid.UUID] = Query(None, description="Filter by monitoring process ID"),
    limit: int = Query(20, ge=1, le=100, description="Number of comments to return"),
    offset: int = Query(0, ge=0, description="Number of comments to skip"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Get user's AI-generated comments with optional filters.

    Returns AI comments ordered by creation time (newest first).
    Each comment includes the article snapshot captured at generation time.

    **Filters:**
    - `status`: Filter by comment status (generated, posted, failed, deleted)
    - `mymoment_login_id`: Filter by login used to post
    - `monitoring_process_id`: Filter by monitoring process that generated the comment
    """
    try:
        # Build query
        conditions = [
            AIComment.user_id == current_user.id,
            AIComment.is_active.is_(True)
        ]

        if status_filter:
            if status_filter not in ["generated", "posted", "failed", "deleted"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid status filter. Must be: generated, posted, failed, or deleted"
                )
            conditions.append(AIComment.status == status_filter)

        if mymoment_login_id:
            conditions.append(AIComment.mymoment_login_id == mymoment_login_id)

        if monitoring_process_id:
            conditions.append(AIComment.monitoring_process_id == monitoring_process_id)

        # Get total count
        count_stmt = select(AIComment).where(and_(*conditions))
        count_result = await session.execute(count_stmt)
        total = len(count_result.scalars().all())

        # Get paginated results
        stmt = (
            select(AIComment)
            .where(and_(*conditions))
            .order_by(desc(AIComment.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(stmt)
        ai_comments = result.scalars().all()

        logger.debug(f"Retrieved {len(ai_comments)} AI comments for user {current_user.id}")

        # Convert to response format
        comment_responses = [
            AICommentResponse(
                id=comment.id,
                mymoment_article_id=comment.mymoment_article_id,
                mymoment_comment_id=comment.mymoment_comment_id,
                article_title=comment.article_title,
                article_author=comment.article_author,
                article_content=comment.article_content,
                article_url=comment.article_url,
                article_category=comment.article_category,
                article_published_at=comment.article_published_at,
                article_scraped_at=comment.article_scraped_at,
                comment_content=comment.comment_content,
                status=comment.status,
                ai_model_name=comment.ai_model_name,
                ai_provider_name=comment.ai_provider_name,
                generation_time_ms=comment.generation_time_ms,
                created_at=comment.created_at,
                posted_at=comment.posted_at,
                user_id=comment.user_id,
                mymoment_login_id=comment.mymoment_login_id,
                monitoring_process_id=comment.monitoring_process_id
            )
            for comment in ai_comments
        ]

        return AICommentListResponse(
            items=comment_responses,
            total=total,
            limit=limit,
            offset=offset
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error retrieving AI comments for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/{comment_id}", response_model=AICommentResponse)
async def get_ai_comment_detail(
    comment_id: uuid.UUID = Path(..., description="AI comment unique identifier"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Get detailed information about a specific AI comment with article snapshot.

    Returns the complete AI comment including:
    - Article snapshot (title, author, content, HTML) from generation time
    - Comment content and metadata
    - Generation details (model, provider, timing)
    - Status and timestamps

    Access is restricted to the user's own AI comments.
    """
    try:
        # Get AI comment
        stmt = select(AIComment).where(
            and_(
                AIComment.id == comment_id,
                AIComment.user_id == current_user.id,
                AIComment.is_active.is_(True)
            )
        )
        result = await session.execute(stmt)
        ai_comment = result.scalar_one_or_none()

        if not ai_comment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI comment not found or not accessible"
            )

        logger.debug(f"Retrieved AI comment {comment_id} for user {current_user.id}")

        return AICommentResponse(
            id=ai_comment.id,
            mymoment_article_id=ai_comment.mymoment_article_id,
            mymoment_comment_id=ai_comment.mymoment_comment_id,
            article_title=ai_comment.article_title,
            article_author=ai_comment.article_author,
            article_content=ai_comment.article_content,
            article_raw_html=ai_comment.article_raw_html,
            article_url=ai_comment.article_url,
            article_category=ai_comment.article_category,
            article_published_at=ai_comment.article_published_at,
            article_scraped_at=ai_comment.article_scraped_at,
            comment_content=ai_comment.comment_content,
            status=ai_comment.status,
            ai_model_name=ai_comment.ai_model_name,
            ai_provider_name=ai_comment.ai_provider_name,
            generation_time_ms=ai_comment.generation_time_ms,
            created_at=ai_comment.created_at,
            posted_at=ai_comment.posted_at,
            user_id=ai_comment.user_id,
            mymoment_login_id=ai_comment.mymoment_login_id,
            monitoring_process_id=ai_comment.monitoring_process_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error retrieving AI comment {comment_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/article/{mymoment_article_id}", response_model=AICommentListResponse)
async def get_ai_comments_by_article(
    mymoment_article_id: str = Path(..., description="myMoment article ID"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Get all user's AI comments for a specific myMoment article.

    Returns all AI comments the user has generated for the specified article,
    ordered by creation time (oldest first for chronological reading).

    Each comment includes the article snapshot from when it was generated,
    allowing you to see how the article may have changed over time.

    **Use case:**
    - View all your AI comments on a specific article
    - Compare article content across different comment generations
    - Track comment posting status for an article
    """
    try:
        # Get all user's AI comments for this article
        stmt = (
            select(AIComment)
            .where(
                and_(
                    AIComment.mymoment_article_id == mymoment_article_id,
                    AIComment.user_id == current_user.id,
                    AIComment.is_active.is_(True)
                )
            )
            .order_by(AIComment.created_at.asc())  # Chronological order
        )
        result = await session.execute(stmt)
        ai_comments = result.scalars().all()

        logger.debug(
            f"Retrieved {len(ai_comments)} AI comments for article {mymoment_article_id} "
            f"by user {current_user.id}"
        )

        # Convert to response format
        comment_responses = [
            AICommentResponse(
                id=comment.id,
                mymoment_article_id=comment.mymoment_article_id,
                mymoment_comment_id=comment.mymoment_comment_id,
                article_title=comment.article_title,
                article_author=comment.article_author,
                article_content=comment.article_content,
                article_url=comment.article_url,
                article_category=comment.article_category,
                article_published_at=comment.article_published_at,
                article_scraped_at=comment.article_scraped_at,
                comment_content=comment.comment_content,
                status=comment.status,
                ai_model_name=comment.ai_model_name,
                ai_provider_name=comment.ai_provider_name,
                generation_time_ms=comment.generation_time_ms,
                created_at=comment.created_at,
                posted_at=comment.posted_at,
                user_id=comment.user_id,
                mymoment_login_id=comment.mymoment_login_id,
                monitoring_process_id=comment.monitoring_process_id
            )
            for comment in ai_comments
        ]

        return AICommentListResponse(
            items=comment_responses,
            total=len(comment_responses),
            limit=len(comment_responses),
            offset=0
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error retrieving AI comments for article {mymoment_article_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.post("/{comment_id}/post", response_model=AICommentResponse)
async def post_comment_to_mymoment(
    comment_id: uuid.UUID = Path(..., description="AI comment unique identifier"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Post an AI comment to myMoment platform.

    Posts a generated AI comment to the myMoment platform if it hasn't been posted yet.
    This endpoint uses the associated myMoment login credentials to authenticate
    with the platform and post the comment.

    **Requirements:**
    - Comment must exist and belong to the current user
    - Comment status must be 'generated' (not already 'posted')
    - Associated myMoment login credentials must be active

    **Process:**
    1. Validates comment ownership and status
    2. Initializes scraper session with myMoment credentials
    3. Posts comment using the scraper service
    4. Updates comment status to 'posted' on success

    Returns the updated AI comment with posted status and timestamp.
    """
    try:
        # Get AI comment
        stmt = select(AIComment).where(
            and_(
                AIComment.id == comment_id,
                AIComment.user_id == current_user.id,
                AIComment.is_active.is_(True)
            )
        )
        result = await session.execute(stmt)
        ai_comment = result.scalar_one_or_none()

        if not ai_comment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI comment not found or not accessible"
            )

        # Check if already posted
        if ai_comment.status == "posted":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Comment has already been posted to myMoment"
            )

        # Check if comment content exists
        if not ai_comment.comment_content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Comment content is empty, cannot post"
            )

        # Get associated myMoment login
        if not ai_comment.mymoment_login_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No myMoment login associated with this comment"
            )

        login_stmt = select(MyMomentLogin).where(
            and_(
                MyMomentLogin.id == ai_comment.mymoment_login_id,
                MyMomentLogin.user_id == current_user.id,
                MyMomentLogin.is_active.is_(True)
            )
        )
        login_result = await session.execute(login_stmt)
        mymoment_login = login_result.scalar_one_or_none()

        if not mymoment_login:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Associated myMoment login not found or inactive"
            )

        # Initialize scraper service and post comment
        async with ScraperService(session) as scraper:
            try:
                # Initialize session for this login
                session_context = await scraper.initialize_session_for_login(
                    login_id=mymoment_login.id,
                    user_id=current_user.id
                )

                # Post the comment
                post_success = await scraper.post_comment(
                    context=session_context,
                    article_id=ai_comment.mymoment_article_id,
                    comment_content=ai_comment.comment_content,
                    highlight=None
                )

                if not post_success:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to post comment to myMoment"
                    )

                # Generate a placeholder comment ID (myMoment doesn't return one in current implementation)
                # Format: article_id-timestamp to ensure uniqueness
                posted_timestamp = datetime.utcnow()
                placeholder_comment_id = f"{ai_comment.mymoment_article_id}-{int(posted_timestamp.timestamp())}"

                # Update comment status using the model's method
                ai_comment.mark_as_posted(
                    mymoment_comment_id=placeholder_comment_id,
                    posted_at=posted_timestamp
                )

                await session.commit()
                await session.refresh(ai_comment)

                logger.info(
                    f"Successfully posted AI comment {comment_id} to myMoment "
                    f"article {ai_comment.mymoment_article_id}"
                )

            except ScrapingError as e:
                logger.error(f"Scraping error while posting comment {comment_id}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to communicate with myMoment platform: {str(e)}"
                )
            except Exception as e:
                logger.error(f"Unexpected error posting comment {comment_id}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to post comment to myMoment"
                )

        # Return updated comment
        return AICommentResponse(
            id=ai_comment.id,
            mymoment_article_id=ai_comment.mymoment_article_id,
            mymoment_comment_id=ai_comment.mymoment_comment_id,
            article_title=ai_comment.article_title,
            article_author=ai_comment.article_author,
            article_content=ai_comment.article_content,
            article_raw_html=ai_comment.article_raw_html,
            article_url=ai_comment.article_url,
            article_category=ai_comment.article_category,
            article_published_at=ai_comment.article_published_at,
            article_scraped_at=ai_comment.article_scraped_at,
            comment_content=ai_comment.comment_content,
            status=ai_comment.status,
            ai_model_name=ai_comment.ai_model_name,
            ai_provider_name=ai_comment.ai_provider_name,
            generation_time_ms=ai_comment.generation_time_ms,
            created_at=ai_comment.created_at,
            posted_at=ai_comment.posted_at,
            user_id=ai_comment.user_id,
            mymoment_login_id=ai_comment.mymoment_login_id,
            monitoring_process_id=ai_comment.monitoring_process_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in post_comment_to_mymoment for comment {comment_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )
