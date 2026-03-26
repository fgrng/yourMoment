"""
API endpoints for the Student Backup feature.

Provides CRUD operations for tracked students and access to article versions.
All endpoints require authentication and check if the feature is enabled.
"""

import uuid
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import inspect

from src.api.auth import get_current_user
from src.api.schemas import (
    TrackedStudentCreate,
    TrackedStudentUpdate,
    TrackedStudentResponse,
    TrackedStudentListResponse,
    ArticleVersionResponse,
    ArticleVersionDetailResponse,
    ArticleVersionListResponse,
    ArticleSummaryResponse,
    ArticleSummaryListResponse,
    BackupTriggerRequest,
    BackupTriggerResponse,
    ErrorResponse
)
from src.config.database import get_session
from src.config.settings import get_student_backup_settings
from src.models.user import User
from src.services.student_backup_service import (
    StudentBackupService,
    StudentBackupServiceError,
    StudentBackupValidationError,
    StudentBackupNotFoundError,
    StudentBackupDisabledError,
    StudentBackupLimitError
)
from src.tasks.student_backup import trigger_backup as trigger_backup_task
from src.api.error_utils import http_error


router = APIRouter(prefix="/student-backup", tags=["Student Backup"])

logger = logging.getLogger(__name__)


def check_feature_enabled() -> None:
    """
    Check if the Student Backup feature is enabled.

    Raises:
        HTTPException: 403 if feature is disabled
    """
    settings = get_student_backup_settings()
    if not settings.STUDENT_BACKUP_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "feature_disabled",
                "message": "Student Backup feature is disabled on this instance."
            }
        )


def _handle_service_error(e: StudentBackupServiceError) -> None:
    """Convert service errors to appropriate HTTP responses."""
    message = str(e)

    if isinstance(e, StudentBackupDisabledError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "feature_disabled", "message": message}
        )

    if isinstance(e, StudentBackupLimitError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "limit_exceeded", "message": message}
        )

    if isinstance(e, StudentBackupNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "message": message}
        )

    if isinstance(e, StudentBackupValidationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "validation_error", "message": message}
        )

    # Generic error
    logger.error(f"Student backup service error: {e}")
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"error": "service_error", "message": "An unexpected error occurred"}
    )


# =========================================================================
# Tracked Students Endpoints
# =========================================================================

@router.post(
    "/tracked-students/create",
    response_model=TrackedStudentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        403: {"model": ErrorResponse, "description": "Feature disabled or limit exceeded"},
        404: {"model": ErrorResponse, "description": "Admin login not found"}
    }
)
async def create_tracked_student(
    request: TrackedStudentCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Create a new tracked student.

    Requires an admin login to be assigned for accessing the student's dashboard.
    """
    check_feature_enabled()

    try:
        service = StudentBackupService(session)
        tracked_student = await service.create_tracked_student(
            user_id=current_user.id,
            mymoment_student_id=request.mymoment_student_id,
            mymoment_login_id=request.mymoment_login_id,
            display_name=request.display_name,
            notes=request.notes
        )

        return _build_tracked_student_response(tracked_student)

    except StudentBackupServiceError as e:
        _handle_service_error(e)


@router.get(
    "/tracked-students/index",
    response_model=TrackedStudentListResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Feature disabled"}
    }
)
async def list_tracked_students(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    include_inactive: bool = Query(False, description="Include inactive tracked students")
):
    """List all tracked students for the current user."""
    check_feature_enabled()

    try:
        service = StudentBackupService(session)
        tracked_students = await service.get_user_tracked_students(
            user_id=current_user.id,
            include_inactive=include_inactive
        )

        items = [_build_tracked_student_response(s) for s in tracked_students]
        return TrackedStudentListResponse(items=items, total=len(items))

    except StudentBackupServiceError as e:
        _handle_service_error(e)


@router.get(
    "/tracked-students/{tracked_student_id}",
    response_model=TrackedStudentResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Feature disabled"},
        404: {"model": ErrorResponse, "description": "Not found"}
    }
)
async def get_tracked_student(
    tracked_student_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get a specific tracked student by ID."""
    check_feature_enabled()

    try:
        service = StudentBackupService(session)
        tracked_student = await service.get_tracked_student_by_id(
            tracked_student_id=tracked_student_id,
            user_id=current_user.id
        )

        if not tracked_student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": "Tracked student not found"}
            )

        return _build_tracked_student_response(tracked_student)

    except StudentBackupServiceError as e:
        _handle_service_error(e)


@router.patch(
    "/tracked-students/{tracked_student_id}",
    response_model=TrackedStudentResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        403: {"model": ErrorResponse, "description": "Feature disabled"},
        404: {"model": ErrorResponse, "description": "Not found"}
    }
)
async def update_tracked_student(
    tracked_student_id: uuid.UUID,
    request: TrackedStudentUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Update a tracked student."""
    check_feature_enabled()

    try:
        service = StudentBackupService(session)
        tracked_student = await service.update_tracked_student(
            tracked_student_id=tracked_student_id,
            user_id=current_user.id,
            mymoment_login_id=request.mymoment_login_id,
            display_name=request.display_name,
            notes=request.notes,
            is_active=request.is_active
        )

        if not tracked_student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": "Tracked student not found"}
            )

        return _build_tracked_student_response(tracked_student)

    except StudentBackupServiceError as e:
        _handle_service_error(e)


@router.delete(
    "/tracked-students/{tracked_student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        403: {"model": ErrorResponse, "description": "Feature disabled"},
        404: {"model": ErrorResponse, "description": "Not found"}
    }
)
async def delete_tracked_student(
    tracked_student_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Delete (soft-delete) a tracked student."""
    check_feature_enabled()

    try:
        service = StudentBackupService(session)
        deleted = await service.delete_tracked_student(
            tracked_student_id=tracked_student_id,
            user_id=current_user.id
        )

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": "Tracked student not found"}
            )

    except StudentBackupServiceError as e:
        _handle_service_error(e)


# =========================================================================
# Article Versions Endpoints
# =========================================================================

@router.get(
    "/tracked-students/{tracked_student_id}/articles",
    response_model=ArticleSummaryListResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Feature disabled"},
        404: {"model": ErrorResponse, "description": "Not found"}
    }
)
async def get_articles_summary(
    tracked_student_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get summary of all articles for a tracked student."""
    check_feature_enabled()

    try:
        service = StudentBackupService(session)

        # Verify student exists and belongs to user
        tracked_student = await service.get_tracked_student_by_id(
            tracked_student_id=tracked_student_id,
            user_id=current_user.id
        )
        if not tracked_student:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": "Tracked student not found"}
            )

        # Get article summaries
        summaries = await service.get_articles_summary(
            tracked_student_id=tracked_student_id,
            user_id=current_user.id
        )

        items = [ArticleSummaryResponse(**s) for s in summaries]
        return ArticleSummaryListResponse(items=items, total=len(items))

    except StudentBackupServiceError as e:
        _handle_service_error(e)


@router.get(
    "/tracked-students/{tracked_student_id}/versions",
    response_model=ArticleVersionListResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Feature disabled"},
        404: {"model": ErrorResponse, "description": "Not found"}
    }
)
async def get_article_versions(
    tracked_student_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    mymoment_article_id: Optional[int] = Query(None, description="Filter by article ID"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Skip results")
):
    """Get article versions for a tracked student."""
    check_feature_enabled()

    try:
        service = StudentBackupService(session)

        # Get versions
        versions = await service.get_article_versions(
            tracked_student_id=tracked_student_id,
            user_id=current_user.id,
            mymoment_article_id=mymoment_article_id,
            limit=limit,
            offset=offset
        )

        items = [_build_article_version_response(v) for v in versions]
        return ArticleVersionListResponse(items=items, total=len(items))

    except StudentBackupServiceError as e:
        _handle_service_error(e)


@router.get(
    "/versions/{version_id}",
    response_model=ArticleVersionDetailResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Feature disabled"},
        404: {"model": ErrorResponse, "description": "Not found"}
    }
)
async def get_article_version_detail(
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """Get detailed article version including content."""
    check_feature_enabled()

    try:
        service = StudentBackupService(session)
        version = await service.get_article_version_by_id(
            version_id=version_id,
            user_id=current_user.id
        )

        if not version:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": "Article version not found"}
            )

        return _build_article_version_detail_response(version)

    except StudentBackupServiceError as e:
        _handle_service_error(e)


# =========================================================================
# Backup Trigger Endpoint
# =========================================================================

@router.post(
    "/trigger-backup",
    response_model=BackupTriggerResponse,
    responses={
        403: {"model": ErrorResponse, "description": "Feature disabled"}
    }
)
async def trigger_backup(
    request: Optional[BackupTriggerRequest] = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Manually trigger a backup.

    If tracked_student_ids is provided, only those students are backed up.
    Otherwise, all of the user's tracked students are backed up.
    """
    check_feature_enabled()

    try:
        # Get student IDs to backup
        student_ids = None
        if request and request.tracked_student_ids:
            # Validate that all students belong to the user
            service = StudentBackupService(session)
            student_ids = []
            for student_id in request.tracked_student_ids:
                student = await service.get_tracked_student_by_id(
                    tracked_student_id=student_id,
                    user_id=current_user.id
                )
                if student:
                    student_ids.append(str(student_id))

            if not student_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error": "no_valid_students",
                        "message": "No valid tracked students found to backup"
                    }
                )

        # Trigger the backup task
        result = trigger_backup_task.delay(student_ids)

        if student_ids:
            return BackupTriggerResponse(
                status="dispatched",
                tasks=[{"student_id": sid, "task_id": str(result.id)} for sid in student_ids],
                message=f"Backup triggered for {len(student_ids)} students"
            )
        else:
            return BackupTriggerResponse(
                status="dispatched",
                task_id=str(result.id),
                message="Full backup triggered for all tracked students"
            )

    except StudentBackupServiceError as e:
        _handle_service_error(e)


# =========================================================================
# Helper Functions
# =========================================================================

def _build_tracked_student_response(student) -> TrackedStudentResponse:
    """Build a TrackedStudentResponse from a TrackedStudent model."""
    # Check if article_versions relationship is loaded to avoid MissingGreenlet error
    # in async context. Accessing a lazy relationship triggers a sync IO attempt.
    state = inspect(student)
    article_versions_loaded = 'article_versions' not in state.unloaded

    return TrackedStudentResponse(
        id=student.id,
        user_id=student.user_id,
        mymoment_login_id=student.mymoment_login_id,
        mymoment_student_id=student.mymoment_student_id,
        display_name=student.display_name,
        notes=student.notes,
        is_active=student.is_active,
        created_at=student.created_at,
        updated_at=student.updated_at,
        last_backup_at=student.last_backup_at,
        dashboard_url=student.dashboard_url,
        article_count=student.get_article_count() if article_versions_loaded else None,
        total_versions=student.get_total_versions_count() if article_versions_loaded else None
    )


def _build_article_version_response(version) -> ArticleVersionResponse:
    """Build an ArticleVersionResponse from an ArticleVersion model."""
    return ArticleVersionResponse(
        id=version.id,
        tracked_student_id=version.tracked_student_id,
        mymoment_article_id=version.mymoment_article_id,
        version_number=version.version_number,
        article_title=version.article_title,
        article_url=version.article_url,
        article_status=version.article_status,
        article_visibility=version.article_visibility,
        article_category=version.article_category,
        article_task=version.article_task,
        article_last_modified=version.article_last_modified,
        scraped_at=version.scraped_at,
        content_hash=version.content_hash,
        is_active=version.is_active
    )


def _build_article_version_detail_response(version) -> ArticleVersionDetailResponse:
    """Build an ArticleVersionDetailResponse from an ArticleVersion model."""
    return ArticleVersionDetailResponse(
        id=version.id,
        tracked_student_id=version.tracked_student_id,
        mymoment_article_id=version.mymoment_article_id,
        version_number=version.version_number,
        article_title=version.article_title,
        article_url=version.article_url,
        article_status=version.article_status,
        article_visibility=version.article_visibility,
        article_category=version.article_category,
        article_task=version.article_task,
        article_last_modified=version.article_last_modified,
        scraped_at=version.scraped_at,
        content_hash=version.content_hash,
        is_active=version.is_active,
        article_content=version.article_content,
        article_raw_html=version.article_raw_html,
        extra_metadata=version.extra_metadata
    )
