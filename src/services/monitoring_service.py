"""
Monitoring process orchestration service for yourMoment application.

This service provides complete lifecycle management for monitoring processes,
integrating with the existing multi-session scraping infrastructure, process
scheduling, and duration enforcement capabilities.
"""

import asyncio
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum

from sqlalchemy import select, and_, or_, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.models.monitoring_process import MonitoringProcess
from src.models.monitoring_process_login import MonitoringProcessLogin
from src.models.monitoring_process_prompt import MonitoringProcessPrompt
from src.models.mymoment_login import MyMomentLogin
from src.models.prompt_template import PromptTemplate
from src.models.llm_provider import LLMProviderConfiguration
from src.models.user import User

logger = logging.getLogger(__name__)


class ProcessStatus(str, Enum):
    """Valid monitoring process status values."""
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class ProcessValidationError(Exception):
    """Raised when process validation fails."""
    pass


class ProcessOperationError(Exception):
    """Raised when process operations fail."""
    pass


class MonitoringService:
    """
    Comprehensive monitoring process orchestration service.

    This service manages the complete lifecycle of monitoring processes:

    1. Process Creation & Configuration:
       - Create processes with filtering criteria
       - Associate with multiple myMoment logins
       - Configure prompt templates for comment generation
       - Validate user access and resource constraints

    2. Process Execution:
       - Start monitoring with multi-session scraping
       - Coordinate article discovery across sessions
       - Manage background task scheduling
       - Handle process state transitions

    3. Duration & Lifecycle Management:
       - Enforce maximum duration limits (FR-008)
       - Automatic process termination on timeout
       - Process stopping and cleanup
       - Status monitoring and reporting

    4. Multi-Login Coordination:
       - Support multiple myMoment logins per process
       - Session management across login credentials
       - Comment posting coordination
       - Login attribution and access control

    5. Error Handling & Recovery:
       - Robust error handling with graceful degradation
       - Process failure recovery and cleanup
       - Comprehensive audit logging
       - Resource cleanup on failures
    """

    def __init__(
        self,
        db_session: AsyncSession,
        max_concurrent_processes_per_user: int = 10
    ):
        """
        Initialize monitoring service.

        Args:
            db_session: Database session for operations
            max_concurrent_processes_per_user: Max concurrent processes per user (FR-019)
        """
        self.db_session = db_session
        self.max_concurrent_processes_per_user = max_concurrent_processes_per_user

    async def create_process(
        self,
        user_id: uuid.UUID,
        name: str,
        description: Optional[str] = None,
        category_filter: Optional[int] = None,
        search_filter: Optional[str] = None,
        tab_filter: Optional[str] = None,
        sort_option: Optional[str] = None,
        max_duration_minutes: int = 60,
        login_ids: Optional[List[uuid.UUID]] = None,
        prompt_template_ids: Optional[List[uuid.UUID]] = None,
        prompt_weights: Optional[Dict[uuid.UUID, float]] = None,
        llm_provider_id: Optional[uuid.UUID] = None,
        generate_only: bool = True
    ) -> MonitoringProcess:
        """
        Create a new monitoring process with all associations.

        Args:
            user_id: User creating the process
            name: Process name
            description: Optional process description
            category_filter: Optional myMoment category filter
            search_filter: Optional search terms
            tab_filter: Optional tab filter (new, popular, etc.)
            sort_option: Optional sort criteria
            max_duration_minutes: Maximum duration in minutes (FR-008)
            login_ids: List of myMoment login IDs to associate
            prompt_template_ids: List of prompt template IDs to associate
            prompt_weights: Optional weights for prompt templates

        Returns:
            Created MonitoringProcess instance

        Raises:
            ProcessValidationError: If validation fails
            ProcessOperationError: If creation fails
        """
        try:
            # Validate user exists and is active
            user_stmt = select(User).where(
                and_(User.id == user_id, User.is_active == True)
            )
            user_result = await self.db_session.execute(user_stmt)
            user = user_result.scalar_one_or_none()

            if not user:
                raise ProcessValidationError(f"User {user_id} not found or inactive")

            # Check concurrent process limit (FR-019)
            await self._validate_concurrent_process_limit(user_id)

            validated_llm_provider_id = None
            if llm_provider_id:
                validated_llm_provider_id = await self._validate_llm_provider(user_id, llm_provider_id)

            # Validate login associations
            validated_login_ids = []
            if login_ids:
                validated_login_ids = await self._validate_login_associations(
                    user_id, login_ids
                )

            # Validate prompt template associations
            validated_prompt_ids = []
            if prompt_template_ids:
                validated_prompt_ids = await self._validate_prompt_associations(
                    user_id, prompt_template_ids
                )

            # Create the monitoring process
            process = MonitoringProcess(
                user_id=user_id,
                name=name,
                description=description,
                category_filter=category_filter,
                search_filter=search_filter,
                tab_filter=tab_filter,
                sort_option=sort_option,
                max_duration_minutes=max_duration_minutes,
                llm_provider_id=validated_llm_provider_id,
                status=ProcessStatus.CREATED,
                generate_only=generate_only
            )

            self.db_session.add(process)
            await self.db_session.flush()  # Get process ID

            # Create login associations
            for login_id in validated_login_ids:
                process_login = MonitoringProcessLogin(
                    monitoring_process_id=process.id,
                    mymoment_login_id=login_id,
                    is_active=True
                )
                self.db_session.add(process_login)

            # Create prompt template associations
            for prompt_id in validated_prompt_ids:
                weight = prompt_weights.get(prompt_id, 1.0) if prompt_weights else 1.0
                process_prompt = MonitoringProcessPrompt(
                    monitoring_process_id=process.id,
                    prompt_template_id=prompt_id,
                    weight=weight,
                    is_active=True
                )
                self.db_session.add(process_prompt)

            await self.db_session.commit()

            logger.info(
                f"Created monitoring process {process.id} for user {user_id} "
                f"with {len(validated_login_ids)} logins and {len(validated_prompt_ids)} prompts"
            )

            return await self._get_process_with_associations(process.id, user_id)

        except Exception as e:
            await self.db_session.rollback()
            logger.error(f"Failed to create monitoring process for user {user_id}: {e}")
            if isinstance(e, (ProcessValidationError, ProcessOperationError)):
                raise
            raise ProcessOperationError(f"Process creation failed: {e}")

    async def update_process(
        self,
        process_id: uuid.UUID,
        user_id: uuid.UUID,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category_filter: Optional[int] = None,
        search_filter: Optional[str] = None,
        tab_filter: Optional[str] = None,
        sort_option: Optional[str] = None,
        max_duration_minutes: Optional[int] = None,
        login_ids: Optional[List[uuid.UUID]] = None,
        prompt_template_ids: Optional[List[uuid.UUID]] = None,
        llm_provider_id: Optional[uuid.UUID] = None,
        generate_only: Optional[bool] = None
    ) -> MonitoringProcess:
        """
        Update an existing monitoring process.

        Args:
            process_id: Process ID to update
            user_id: User ID for ownership validation
            name: New process name (optional)
            description: New process description (optional)
            category_filter: New category filter (optional)
            search_filter: New search filter (optional)
            tab_filter: New tab filter (optional)
            sort_option: New sort option (optional)
            max_duration_minutes: New max duration (optional)
            login_ids: New list of login IDs (optional)
            prompt_template_ids: New list of prompt template IDs (optional)
            llm_provider_id: New LLM provider ID (optional)
            generate_only: New generate_only setting (optional)

        Returns:
            Updated MonitoringProcess instance

        Raises:
            ProcessValidationError: If validation fails
            ProcessOperationError: If update fails
        """
        try:
            # Get existing process with ownership validation
            process = await self._get_process_with_associations(process_id, user_id)

            # Cannot update a running process
            if process.is_running:
                raise ProcessValidationError(
                    f"Cannot update process {process_id} while it is running. Stop it first."
                )

            # Update basic fields if provided
            if name is not None:
                process.name = name
            if description is not None:
                process.description = description
            if max_duration_minutes is not None:
                process.max_duration_minutes = max_duration_minutes
            if generate_only is not None:
                process.generate_only = generate_only

            # Update filter fields
            if category_filter is not None:
                process.category_filter = category_filter
            if search_filter is not None:
                process.search_filter = search_filter
            if tab_filter is not None:
                process.tab_filter = tab_filter
            if sort_option is not None:
                process.sort_option = sort_option

            # Update LLM provider if provided
            if llm_provider_id is not None:
                validated_provider_id = await self._validate_llm_provider(user_id, llm_provider_id)
                process.llm_provider_id = validated_provider_id

            # Update login associations if provided
            if login_ids is not None:
                validated_login_ids = await self._validate_login_associations(user_id, login_ids)

                # Create a set of existing login IDs for quick lookup
                existing_associations = {assoc.mymoment_login_id: assoc for assoc in process.monitoring_process_logins}

                # Deactivate all existing associations first
                for assoc in process.monitoring_process_logins:
                    assoc.is_active = False

                # Reactivate or create associations for the new login list
                from src.models.monitoring_process_login import MonitoringProcessLogin
                for login_id in validated_login_ids:
                    if login_id in existing_associations:
                        # Reactivate existing association
                        existing_associations[login_id].is_active = True
                    else:
                        # Create new association
                        process_login = MonitoringProcessLogin(
                            monitoring_process_id=process.id,
                            mymoment_login_id=login_id,
                            is_active=True
                        )
                        self.db_session.add(process_login)

            # Update prompt template associations if provided
            if prompt_template_ids is not None:
                validated_prompt_ids = await self._validate_prompt_associations(
                    user_id, prompt_template_ids
                )

                # Create a set of existing prompt IDs for quick lookup
                existing_prompt_associations = {assoc.prompt_template_id: assoc for assoc in process.monitoring_process_prompts}

                # Deactivate all existing associations first
                for assoc in process.monitoring_process_prompts:
                    assoc.is_active = False

                # Reactivate or create associations for the new prompt list
                from src.models.monitoring_process_prompt import MonitoringProcessPrompt
                for prompt_id in validated_prompt_ids:
                    if prompt_id in existing_prompt_associations:
                        # Reactivate existing association
                        existing_prompt_associations[prompt_id].is_active = True
                    else:
                        # Create new association
                        process_prompt = MonitoringProcessPrompt(
                            monitoring_process_id=process.id,
                            prompt_template_id=prompt_id,
                            weight=1.0,
                            is_active=True
                        )
                        self.db_session.add(process_prompt)

            # Update timestamp
            process.updated_at = datetime.now(timezone.utc)

            await self.db_session.commit()

            logger.info(f"Updated monitoring process {process_id} for user {user_id}")

            # Return fresh instance with all associations
            return await self._get_process_with_associations(process_id, user_id)

        except ProcessValidationError:
            # Validation errors don't need rollback, just re-raise
            raise
        except ProcessOperationError:
            # Operation errors don't need rollback, just re-raise
            raise
        except Exception as e:
            # Rollback for unexpected errors
            try:
                await self.db_session.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during rollback: {rollback_error}")

            logger.error(f"Failed to update monitoring process {process_id}: {e}")
            raise ProcessOperationError(f"Process update failed: {e}")

    async def start_process(
        self,
        process_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Start a monitoring process by enqueueing Celery task.

        Args:
            process_id: Process ID to start
            user_id: User ID for validation

        Returns:
            Start result with task_id

        Raises:
            ProcessOperationError: If start fails
        """
        process = None
        login_count = 0

        try:
            # Validate process exists and belongs to user
            process = await self._get_process_with_associations(process_id, user_id)

            if not process.can_start:
                raise ProcessOperationError(
                    f"Process {process_id} cannot be started (status: {process.status})"
                )

            # Validate has associated logins (count them before any errors)
            login_count = len([mpl for mpl in process.monitoring_process_logins if mpl.is_active])
            if login_count == 0:
                raise ProcessOperationError(
                    f"Process {process_id} has no associated myMoment logins"
                )

            # Update process status to running
            now_utc = datetime.now(timezone.utc)
            process.status = ProcessStatus.RUNNING
            process.started_at = now_utc
            process.last_activity_at = now_utc

            # Enqueue Celery task with error handling for Redis connection
            try:
                from src.tasks.article_monitor import start_monitoring_process
                task = start_monitoring_process.delay(str(process_id))
                task_id = task.id
            except Exception as celery_error:
                # Check if it's a Redis connection error
                error_msg = str(celery_error).lower()
                if 'redis' in error_msg or 'connection refused' in error_msg or 'connection error' in error_msg:
                    # Rollback process status changes
                    process.status = ProcessStatus.CREATED
                    process.started_at = None
                    process.last_activity_at = None
                    await self.db_session.commit()
                    raise ProcessOperationError(
                        "Background task system (Redis/Celery) is unavailable. "
                        "Please ensure Redis is running or contact the administrator."
                    )
                else:
                    # Re-raise other Celery errors
                    raise

            # Store task ID for tracking
            process.celery_task_id = task_id

            await self.db_session.commit()

            logger.info(f"Started monitoring process {process_id} with Celery task {task_id}")

            return {
                'process_id': str(process_id),
                'task_id': task_id,
                'status': 'queued',
                'started_at': process.started_at.isoformat(),
                'associated_logins': login_count,
                'max_duration_minutes': process.max_duration_minutes
            }

        except ProcessOperationError:
            # Already a ProcessOperationError, just re-raise
            raise
        except Exception as e:
            # Rollback only if we have a session
            try:
                await self.db_session.rollback()
            except Exception as rollback_error:
                logger.error(f"Error during rollback: {rollback_error}")

            logger.error(f"Failed to start process {process_id}: {e}")
            raise ProcessOperationError(f"Process start failed: {e}")

    async def stop_process(
        self,
        process_id: uuid.UUID,
        user_id: uuid.UUID,
        reason: str = "user_requested"
    ) -> Dict[str, Any]:
        """
        Stop a running monitoring process by revoking Celery task.

        Args:
            process_id: Process ID to stop
            user_id: User ID for validation
            reason: Reason for stopping (user_requested, duration_exceeded, error, etc.)

        Returns:
            Stop result information

        Raises:
            ProcessOperationError: If stop fails
        """
        try:
            # Get process
            process = await self._get_process_with_associations(process_id, user_id)

            if not process.is_running:
                return {
                    'process_id': str(process_id),
                    'status': 'already_stopped',
                    'current_status': process.status
                }

            # Revoke Celery task if exists
            if process.celery_task_id:
                from src.tasks.worker import celery_app
                celery_app.control.revoke(process.celery_task_id, terminate=True)
                logger.info(f"Revoked Celery task {process.celery_task_id} for process {process_id}")

            # Update process status
            now_utc = datetime.now(timezone.utc)
            process.status = ProcessStatus.STOPPED if reason == "user_requested" else ProcessStatus.FAILED
            process.stopped_at = now_utc
            process.last_activity_at = now_utc

            await self.db_session.commit()

            logger.info(f"Stopped monitoring process {process_id} (reason: {reason})")

            return {
                'process_id': str(process_id),
                'status': 'stopped',
                'stopped_at': process.stopped_at.isoformat(),
                'reason': reason,
                'final_stats': {
                    'articles_discovered': process.articles_discovered,
                    'comments_generated': process.comments_generated,
                    'comments_posted': process.comments_posted,
                    'errors_encountered': process.errors_encountered
                }
            }

        except Exception as e:
            logger.error(f"Failed to stop process {process_id}: {e}")
            if isinstance(e, ProcessOperationError):
                raise
            raise ProcessOperationError(f"Process stop failed: {e}")

    async def get_process_status(
        self,
        process_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> Dict[str, Any]:
        """
        Get detailed status of a monitoring process from DB + Celery.

        Args:
            process_id: Process ID to get status for
            user_id: User ID for validation

        Returns:
            Detailed process status information
        """
        try:
            process = await self._get_process_with_associations(process_id, user_id)

            status_info = {
                'process_id': str(process_id),
                'name': process.name,
                'description': process.description,
                'status': process.status,
                'is_active': process.is_active,
                'started_at': process.started_at.isoformat() if process.started_at else None,
                'stopped_at': process.stopped_at.isoformat() if process.stopped_at else None,
                'last_activity_at': process.last_activity_at.isoformat() if process.last_activity_at else None,
                'max_duration_minutes': process.max_duration_minutes,
                'duration_exceeded': process.duration_exceeded,
                'statistics': {
                    'articles_discovered': process.articles_discovered,
                    'comments_generated': process.comments_generated,
                    'comments_posted': process.comments_posted,
                    'errors_encountered': process.errors_encountered
                },
                'filters': {
                    'category_filter': process.category_filter,
                    'search_filter': process.search_filter,
                    'tab_filter': process.tab_filter,
                    'sort_option': process.sort_option
                },
                'associations': {
                    'login_count': len(process.get_associated_logins()),
                    'prompt_count': len(process.get_associated_prompts())
                }
            }

            # Add Celery task information if exists
            if process.celery_task_id:
                from celery.result import AsyncResult
                task = AsyncResult(process.celery_task_id)
                status_info['celery_task'] = {
                    'task_id': process.celery_task_id,
                    'state': task.state,  # PENDING, STARTED, SUCCESS, FAILURE, RETRY, REVOKED
                    'info': str(task.info) if task.info else None
                }

            return status_info

        except Exception as e:
            logger.error(f"Failed to get process status {process_id}: {e}")
            return {'error': str(e)}

    async def list_user_processes(
        self,
        user_id: uuid.UUID,
        is_running: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[MonitoringProcess]:
        """Return monitoring processes for a user with associations preloaded."""
        try:
            from src.models.monitoring_process_login import MonitoringProcessLogin
            from src.models.monitoring_process_prompt import MonitoringProcessPrompt

            stmt = select(MonitoringProcess).options(
                selectinload(MonitoringProcess.monitoring_process_logins).selectinload(MonitoringProcessLogin.mymoment_login),
                selectinload(MonitoringProcess.monitoring_process_prompts).selectinload(MonitoringProcessPrompt.prompt_template)
            ).where(
                and_(
                    MonitoringProcess.user_id == user_id,
                    MonitoringProcess.is_active == True
                )
            )

            if is_running is not None:
                if is_running:
                    stmt = stmt.where(MonitoringProcess.status == ProcessStatus.RUNNING)
                else:
                    stmt = stmt.where(MonitoringProcess.status != ProcessStatus.RUNNING)

            stmt = stmt.order_by(MonitoringProcess.id.desc()).limit(limit).offset(offset)
            result = await self.db_session.execute(stmt)
            return result.scalars().all()

        except Exception as e:
            logger.error(f"Failed to list processes for user {user_id}: {e}")
            raise

    # Private helper methods

    async def _get_process_with_associations(
        self,
        process_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        include_inactive: bool = False
    ) -> MonitoringProcess:
        """Get process with all associations loaded."""
        from src.models.monitoring_process_login import MonitoringProcessLogin
        from src.models.monitoring_process_prompt import MonitoringProcessPrompt

        stmt = select(MonitoringProcess).options(
            selectinload(MonitoringProcess.monitoring_process_logins).selectinload(MonitoringProcessLogin.mymoment_login),
            selectinload(MonitoringProcess.monitoring_process_prompts).selectinload(MonitoringProcessPrompt.prompt_template)
        )

        conditions = [
            MonitoringProcess.id == process_id,
            MonitoringProcess.user_id == user_id,
        ]

        if not include_inactive:
            conditions.append(MonitoringProcess.is_active == True)

        stmt = stmt.where(and_(*conditions))

        result = await self.db_session.execute(stmt)
        process = result.scalar_one_or_none()

        if not process:
            raise ProcessOperationError(f"Process {process_id} not found for user {user_id}")

        return process

    async def delete_process(
        self,
        process_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> None:
        """Soft delete a monitoring process and deactivate associations."""

        process = await self._get_process_with_associations(process_id, user_id)

        if process.is_running:
            await self.stop_process(process_id, user_id)
            process = await self._get_process_with_associations(
                process_id,
                user_id,
                include_inactive=False
            )

        process.is_active = False
        if process.status == ProcessStatus.RUNNING:
            process.status = ProcessStatus.STOPPED
        if not process.stopped_at:
            process.stopped_at = datetime.now(timezone.utc)
        process.last_activity_at = datetime.now(timezone.utc)

        for association in process.monitoring_process_logins or []:
            association.is_active = False

        for association in process.monitoring_process_prompts or []:
            association.is_active = False

        await self.db_session.commit()

    async def _validate_concurrent_process_limit(self, user_id: uuid.UUID):
        """Validate user hasn't exceeded concurrent process limit."""
        running_count_stmt = select(func.count(MonitoringProcess.id)).where(
            and_(
                MonitoringProcess.user_id == user_id,
                MonitoringProcess.status == ProcessStatus.RUNNING,
                MonitoringProcess.is_active == True
            )
        )

        result = await self.db_session.execute(running_count_stmt)
        running_count = result.scalar()

        if running_count >= self.max_concurrent_processes_per_user:
            raise ProcessValidationError(
                f"User {user_id} has reached maximum concurrent process limit "
                f"({self.max_concurrent_processes_per_user})"
            )

    async def _validate_login_associations(
        self,
        user_id: uuid.UUID,
        login_ids: List[uuid.UUID]
    ) -> List[uuid.UUID]:
        """Validate myMoment login associations belong to user."""
        if not login_ids:
            return []

        login_stmt = select(MyMomentLogin).where(
            and_(
                MyMomentLogin.id.in_(login_ids),
                MyMomentLogin.user_id == user_id,
                MyMomentLogin.is_active == True
            )
        )

        result = await self.db_session.execute(login_stmt)
        valid_logins = result.scalars().all()
        valid_ids = [login.id for login in valid_logins]

        invalid_ids = set(login_ids) - set(valid_ids)
        if invalid_ids:
            raise ProcessValidationError(
                f"Invalid or inaccessible login IDs for user {user_id}: {invalid_ids}"
            )

        return valid_ids

    async def _validate_prompt_associations(
        self,
        user_id: uuid.UUID,
        prompt_template_ids: List[uuid.UUID]
    ) -> List[uuid.UUID]:
        """Validate prompt template associations belong to user or are system templates."""
        if not prompt_template_ids:
            return []

        prompt_stmt = select(PromptTemplate).where(
            and_(
                PromptTemplate.id.in_(prompt_template_ids),
                PromptTemplate.is_active == True,
                or_(
                    PromptTemplate.user_id == user_id,  # User's own templates
                    PromptTemplate.category == "SYSTEM"  # System templates
                )
            )
        )

        result = await self.db_session.execute(prompt_stmt)
        valid_prompts = result.scalars().all()
        valid_ids = [prompt.id for prompt in valid_prompts]

        invalid_ids = set(prompt_template_ids) - set(valid_ids)
        if invalid_ids:
            raise ProcessValidationError(
                f"Invalid or inaccessible prompt template IDs for user {user_id}: {invalid_ids}"
            )

        return valid_ids

    async def _validate_llm_provider(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID
    ) -> uuid.UUID:
        stmt = select(LLMProviderConfiguration).where(
            and_(
                LLMProviderConfiguration.id == provider_id,
                LLMProviderConfiguration.user_id == user_id,
                LLMProviderConfiguration.is_active == True
            )
        )
        result = await self.db_session.execute(stmt)
        provider = result.scalar_one_or_none()

        if not provider:
            raise ProcessValidationError(
                f"LLM provider {provider_id} not found or inactive for user {user_id}"
            )

        return provider.id
