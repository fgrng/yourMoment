"""Monitoring process endpoints for creation, inspection, lifecycle control, and cleanup."""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Path, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    MonitoringProcessCreate,
    MonitoringProcessUpdate,
    MonitoringProcessResponse,
    ErrorResponse
)
from src.services.monitoring_service import (
    MonitoringService,
    ProcessValidationError,
    ProcessOperationError
)
from src.api.error_utils import http_error
from src.api.auth import get_current_user
from src.config.database import get_session
from src.models.user import User
import logging

logger = logging.getLogger(__name__)

# Initialize router
router = APIRouter(prefix="/monitoring-processes", tags=["Monitoring"])



@router.post("/create", status_code=status.HTTP_201_CREATED, response_model=MonitoringProcessResponse)
async def create_monitoring_process(
    process_data: MonitoringProcessCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Create a new monitoring process.

    Creates a monitoring process with the specified configuration.
    The process can be started later using the control endpoints.
    """
    try:
        service = MonitoringService(session)

        target_filters = process_data.target_filters or {}
        category_filter = target_filters.get("category")
        if category_filter is None:
            categories = target_filters.get("categories")
            if isinstance(categories, list) and categories:
                category_filter = categories[0]

        tab_filter = target_filters.get("tab")
        if tab_filter is None:
            tabs = target_filters.get("tabs")
            if isinstance(tabs, list) and tabs:
                tab_filter = tabs[0]

        process = await service.create_process(
            user_id=current_user.id,
            name=process_data.name,
            description=process_data.description,
            category_filter=category_filter,
            search_filter=target_filters.get("search"),
            tab_filter=tab_filter,
            sort_option=target_filters.get("sort"),
            max_duration_minutes=process_data.max_duration_minutes,
            login_ids=process_data.mymoment_login_ids,
            prompt_template_ids=process_data.prompt_template_ids,
            llm_provider_id=process_data.llm_provider_id,
            generate_only=process_data.generate_only
        )

        logger.info(f"Created monitoring process {process.id} for user {current_user.id}")

        # Convert to response format using model properties
        return MonitoringProcessResponse.model_validate(process)

    except ProcessValidationError as e:
        logger.warning(f"Process validation failed for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ProcessOperationError as e:
        logger.error(f"Process creation failed for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create monitoring process"
        )
    except Exception as e:
        logger.error(f"Unexpected error creating process for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/index", response_model=List[MonitoringProcessResponse])
async def list_monitoring_processes(
    limit: int = Query(default=50, ge=1, le=100, description="Maximum number of processes to return"),
    offset: int = Query(default=0, ge=0, description="Number of processes to skip"),
    is_running: Optional[bool] = Query(default=None, description="Filter by running status"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    List user's monitoring processes.

    Returns a paginated list of monitoring processes owned by the current user.
    """
    try:
        service = MonitoringService(session)

        processes = await service.list_user_processes(
            user_id=current_user.id,
            limit=limit,
            offset=offset,
            is_running=is_running
        )

        logger.debug(f"Retrieved {len(processes)} processes for user {current_user.id}")

        # Convert to response format using model properties
        return [MonitoringProcessResponse.model_validate(process) for process in processes]

    except Exception as e:
        logger.error(f"Unexpected error listing processes for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@router.get("/{process_id}", response_model=MonitoringProcessResponse)
async def get_monitoring_process(
    process_id: uuid.UUID = Path(..., description="Process unique identifier"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Get monitoring process details.

    Returns detailed information about a specific monitoring process
    owned by the current user.
    """
    try:
        service = MonitoringService(session)

        # Get process with user ownership validation
        process = await service._get_process_with_associations(process_id, current_user.id)

        if not process:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitoring process not found"
            )

        logger.debug(f"Retrieved process {process_id} for user {current_user.id}")

        # Convert to response format using model properties
        return MonitoringProcessResponse.model_validate(process)

    except ProcessOperationError as e:
        if "not found" in str(e).lower():
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "monitoring_process_not_found",
                "Monitoring process not found."
            )
        logger.error(
            "Process operation error retrieving process %s for user %s: %s",
            process_id,
            current_user.id,
            e,
            exc_info=True
        )
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "monitoring_process_error",
            "Failed to retrieve monitoring process."
        )
    except Exception as e:
        logger.error(f"Unexpected error getting process {process_id} for user {current_user.id}: {e}")
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "monitoring_process_error",
            "Failed to retrieve monitoring process."
        )


@router.patch("/{process_id}", response_model=MonitoringProcessResponse)
async def update_monitoring_process(
    process_id: uuid.UUID = Path(..., description="Process unique identifier"),
    process_data: MonitoringProcessUpdate = ...,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Update a monitoring process.

    Updates configuration for a monitoring process owned by the current user.
    The process must be stopped to be updated.

    Only the fields provided in the request will be updated.
    All fields are optional.
    """
    try:
        service = MonitoringService(session)

        # Extract target filters from request
        target_filters = process_data.target_filters or {}
        category_filter = target_filters.get("category")
        if category_filter is None:
            categories = target_filters.get("categories")
            if isinstance(categories, list) and categories:
                category_filter = categories[0]

        tab_filter = target_filters.get("tab")
        if tab_filter is None:
            tabs = target_filters.get("tabs")
            if isinstance(tabs, list) and tabs:
                tab_filter = tabs[0]

        # Build update kwargs with only provided fields
        update_kwargs = {}
        if process_data.name is not None:
            update_kwargs['name'] = process_data.name
        if process_data.description is not None:
            update_kwargs['description'] = process_data.description
        if process_data.max_duration_minutes is not None:
            update_kwargs['max_duration_minutes'] = process_data.max_duration_minutes
        if process_data.llm_provider_id is not None:
            update_kwargs['llm_provider_id'] = process_data.llm_provider_id
        if process_data.prompt_template_ids is not None:
            update_kwargs['prompt_template_ids'] = process_data.prompt_template_ids
        if process_data.mymoment_login_ids is not None:
            update_kwargs['login_ids'] = process_data.mymoment_login_ids
        if process_data.generate_only is not None:
            update_kwargs['generate_only'] = process_data.generate_only

        # Add filter fields if provided
        if category_filter is not None:
            update_kwargs['category_filter'] = category_filter
        if process_data.target_filters is not None:
            if 'search' in target_filters:
                update_kwargs['search_filter'] = target_filters['search']
            if tab_filter is not None:
                update_kwargs['tab_filter'] = tab_filter
            if 'sort' in target_filters:
                update_kwargs['sort_option'] = target_filters['sort']

        # Update the process
        updated_process = await service.update_process(
            process_id=process_id,
            user_id=current_user.id,
            **update_kwargs
        )

        logger.info(f"Updated monitoring process {process_id} for user {current_user.id}")

        return MonitoringProcessResponse.model_validate(updated_process)

    except ProcessValidationError as e:
        logger.warning(f"Process validation failed for update {process_id}: {e}")
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "monitoring_process_validation_error",
            str(e)
        )
    except ProcessOperationError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "monitoring_process_not_found",
                "Monitoring process not found."
            )
        logger.error(
            "Process operation error updating process %s for user %s: %s",
            process_id,
            current_user.id,
            e,
            exc_info=True
        )
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "monitoring_process_error",
            error_msg
        )
    except Exception as e:
        logger.error(f"Unexpected error updating process {process_id} for user {current_user.id}: {e}")
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "monitoring_process_error",
            "Failed to update monitoring process."
        )


@router.delete("/{process_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_monitoring_process(
    process_id: uuid.UUID = Path(..., description="Process unique identifier"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Delete a monitoring process.

    Stops and deletes a monitoring process owned by the current user.
    If the process is running, it will be stopped first.
    """
    try:
        service = MonitoringService(session)

        await service.delete_process(process_id, current_user.id)

        logger.info(f"Deleted monitoring process {process_id} for user {current_user.id}")

    except HTTPException:
        raise
    except ProcessOperationError as e:
        await session.rollback()
        if "not found" in str(e).lower():
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "monitoring_process_not_found",
                "Monitoring process not found."
            )
        logger.error(
            "Process operation error deleting process %s for user %s: %s",
            process_id,
            current_user.id,
            e,
            exc_info=True
        )
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "monitoring_process_error",
            "Failed to delete monitoring process."
        )
    except Exception as e:
        logger.error(f"Unexpected error deleting process {process_id} for user {current_user.id}: {e}")
        await session.rollback()
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "monitoring_process_error",
            "Failed to delete monitoring process."
        )


@router.post("/{process_id}/start", response_model=MonitoringProcessResponse)
async def start_monitoring_process(
    process_id: uuid.UUID = Path(..., description="Process unique identifier"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Start a monitoring process.

    Starts the specified monitoring process if it exists and is owned by the current user.
    The process must be in a stopped state to be started.

    This will:
    - Set is_running to true
    - Set started_at to current timestamp
    - Calculate expires_at based on started_at + max_duration_minutes
    - Clear any previous error_message
    - Create myMomentSession entries for all associated logins
    - Initiate background Celery task for monitoring
    """
    try:
        # Validate process_id format
        if not isinstance(process_id, uuid.UUID):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid process ID format"
            )

        service = MonitoringService(session)

        # Verify process exists and user owns it
        process = await service._get_process_with_associations(process_id, current_user.id)

        if not process:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitoring process not found"
            )

        # Check if already running
        if process.is_running:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Monitoring process is already running"
            )

        # Start the process
        start_result = await service.start_process(process_id, current_user.id)

        logger.info(f"Started monitoring process {process_id} for user {current_user.id}")

        # Fetch the updated process to return in response format
        updated_process = await service._get_process_with_associations(process_id, current_user.id)
        return MonitoringProcessResponse.model_validate(updated_process)

    except HTTPException:
        raise
    except ProcessOperationError as e:
        error_msg = str(e)

        # Check for specific error types
        if "not found" in error_msg.lower():
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "monitoring_process_not_found",
                "Monitoring process not found."
            )
        elif "redis" in error_msg.lower() or "celery" in error_msg.lower() or "unavailable" in error_msg.lower():
            # User-friendly error for Redis/Celery unavailability
            raise http_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "background_service_unavailable",
                error_msg  # Use the detailed message from the service
            )
        else:
            # Generic error
            logger.error(
                "Process operation error starting process %s for user %s: %s",
                process_id,
                current_user.id,
                e,
                exc_info=True
            )
            raise http_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "monitoring_process_error",
                error_msg
            )
    except ProcessValidationError as e:
        logger.warning(f"Process validation failed for process {process_id}: {e}")
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "monitoring_process_validation_error",
            str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error starting process {process_id} for user {current_user.id}: {e}")
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "monitoring_process_error",
            "Failed to start monitoring process."
        )


@router.post("/{process_id}/stop", response_model=MonitoringProcessResponse)
async def stop_monitoring_process(
    process_id: uuid.UUID = Path(..., description="Process unique identifier"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Stop a monitoring process.

    Stops the specified monitoring process if it exists and is owned by the current user.
    This operation is idempotent - stopping an already stopped process will succeed.

    This will:
    - Set is_running to false
    - Set stopped_at to current timestamp (if not already set)
    - Update updated_at timestamp
    - Clean up myMomentSession entries for all associated logins
    - Terminate background Celery task
    - Preserve started_at and expires_at timestamps
    """
    try:
        # Validate process_id format
        if not isinstance(process_id, uuid.UUID):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid process ID format"
            )

        service = MonitoringService(session)

        # Verify process exists and user owns it
        process = await service._get_process_with_associations(process_id, current_user.id)

        if not process:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitoring process not found"
            )

        # Stop the process (idempotent operation)
        stop_result = await service.stop_process(process_id, current_user.id)

        logger.info(f"Stopped monitoring process {process_id} for user {current_user.id}")

        # Fetch the updated process to return in response format
        updated_process = await service._get_process_with_associations(process_id, current_user.id)
        return MonitoringProcessResponse.model_validate(updated_process)

    except HTTPException:
        raise
    except ProcessOperationError as e:
        if "not found" in str(e).lower():
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "monitoring_process_not_found",
                "Monitoring process not found."
            )
        logger.error(
            "Process operation error stopping process %s for user %s: %s",
            process_id,
            current_user.id,
            e,
            exc_info=True
        )
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "monitoring_process_error",
            "Failed to stop monitoring process."
        )
    except ProcessValidationError as e:
        logger.warning(f"Process validation failed for process {process_id}: {e}")
        raise http_error(
            status.HTTP_400_BAD_REQUEST,
            "monitoring_process_validation_error",
            str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error stopping process {process_id} for user {current_user.id}: {e}")
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "monitoring_process_error",
            "Failed to stop monitoring process."
        )


@router.post("/{process_id}/post-comments", status_code=status.HTTP_202_ACCEPTED, response_model=dict)
async def trigger_comment_poster_task(
    process_id: uuid.UUID = Path(..., description="Process unique identifier"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Trigger comment poster task for a monitoring process.

    Starts a background Celery task to post all generated (but not yet posted)
    AI comments for the specified monitoring process to myMoment.

    This endpoint is useful when a monitoring process has `generate_only=True`
    and comments have been generated but not automatically posted.

    **Requirements:**
    - Process must exist and belong to the current user
    - Process must have at least one AI comment with status='generated'

    Returns a task ID that can be used to track the posting progress.
    """
    try:
        # Validate process_id format
        if not isinstance(process_id, uuid.UUID):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid process ID format"
            )

        service = MonitoringService(session)

        # Verify process exists and user owns it
        process = await service._get_process_with_associations(process_id, current_user.id)

        if not process:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Monitoring process not found"
            )

        # Import the Celery task
        from src.tasks.comment_poster import post_comments_for_process

        # Trigger the task
        task = post_comments_for_process.apply_async(
            args=[str(process_id)],
            queue='comments'
        )

        logger.info(
            f"Triggered comment poster task {task.id} for process {process_id} "
            f"by user {current_user.id}"
        )

        return {
            "message": "Comment posting task started",
            "task_id": task.id,
            "process_id": str(process_id)
        }

    except HTTPException:
        raise
    except ProcessOperationError as e:
        if "not found" in str(e).lower():
            raise http_error(
                status.HTTP_404_NOT_FOUND,
                "monitoring_process_not_found",
                "Monitoring process not found."
            )
        logger.error(
            "Process operation error triggering comment poster for process %s: %s",
            process_id,
            e,
            exc_info=True
        )
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "monitoring_process_error",
            "Failed to trigger comment posting."
        )
    except Exception as e:
        logger.error(
            f"Unexpected error triggering comment poster for process {process_id}: {e}",
            exc_info=True
        )
        raise http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "monitoring_process_error",
            "Failed to trigger comment posting task."
        )
