"""
Student Backup background tasks for periodic article backups.

This module implements Celery tasks for the Student Backup feature:
- Periodic backup of tracked students' articles
- Manual backup triggering
- Version creation with change detection

The feature must be enabled via STUDENT_BACKUP_ENABLED=true environment variable.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.tasks.worker import celery_app, BaseTask
from src.config.database import get_database_manager
from src.config.settings import get_student_backup_settings
from src.services.student_backup_service import (
    StudentBackupService,
    StudentBackupDisabledError
)
from src.services.scraper_service import ScraperService, SessionContext
from src.services.mymoment_credentials_service import MyMomentCredentialsService

logger = logging.getLogger(__name__)


class StudentBackupTask(BaseTask):
    """Base class for student backup tasks."""

    def __init__(self):
        self.db_manager = get_database_manager()
        self.settings = get_student_backup_settings()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()

    def is_feature_enabled(self) -> bool:
        """Check if the Student Backup feature is enabled."""
        return self.settings.STUDENT_BACKUP_ENABLED

    async def _backup_all_students_async(self) -> Dict[str, Any]:
        """
        Async implementation of backing up all tracked students.

        Workflow:
        1. Load all active TrackedStudents
        2. For each student:
           a. Get admin login and authenticate
           b. Fetch student dashboard
           c. For each article, fetch content
           d. Create ArticleVersion if content changed
        """
        start_time = datetime.utcnow()
        stats = {
            "students_processed": 0,
            "articles_found": 0,
            "versions_created": 0,
            "versions_skipped": 0,
            "errors": [],
            "timestamp": start_time.isoformat()
        }

        if not self.is_feature_enabled():
            logger.info("Student Backup feature is disabled, skipping backup")
            stats["status"] = "disabled"
            return stats

        async with await self.get_async_session() as session:
            try:
                # Get all active tracked students
                backup_service = StudentBackupService(session)
                tracked_students = await backup_service.get_all_active_tracked_students()

                logger.info(f"Starting backup for {len(tracked_students)} tracked students")

                # Group students by admin login to minimize authentication overhead
                students_by_login: Dict[uuid.UUID, list] = {}
                for student in tracked_students:
                    if student.mymoment_login_id:
                        if student.mymoment_login_id not in students_by_login:
                            students_by_login[student.mymoment_login_id] = []
                        students_by_login[student.mymoment_login_id].append(student)

                # Process students grouped by login
                for login_id, students in students_by_login.items():
                    try:
                        await self._backup_students_with_login(
                            session, login_id, students, stats
                        )
                    except Exception as e:
                        error_msg = f"Failed to process students with login {login_id}: {e}"
                        logger.error(error_msg)
                        stats["errors"].append(error_msg)

                stats["status"] = "completed"

            except StudentBackupDisabledError:
                stats["status"] = "disabled"
                logger.info("Student Backup feature is disabled")

            except Exception as e:
                error_msg = f"Student backup failed: {e}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)
                stats["status"] = "failed"

        stats["execution_time_seconds"] = (datetime.utcnow() - start_time).total_seconds()
        logger.info(
            f"Student backup completed: {stats['students_processed']} students, "
            f"{stats['versions_created']} new versions, "
            f"{stats['versions_skipped']} unchanged"
        )

        return stats

    async def _backup_students_with_login(
        self,
        session: AsyncSession,
        login_id: uuid.UUID,
        students: list,
        stats: Dict[str, Any]
    ) -> None:
        """
        Backup all students using a specific admin login.

        Args:
            session: Database session
            login_id: Admin login ID to use
            students: List of TrackedStudent objects to backup
            stats: Statistics dictionary to update
        """
        # Initialize scraper service and authenticate
        scraper = ScraperService(session)

        try:
            # Use initialize_session_for_login with the user_id from the first student
            context = await scraper.initialize_session_for_login(
                login_id, students[0].user_id
            )
            if not context.is_authenticated:
                raise Exception(f"Failed to authenticate with login {login_id}")

            # Process each student
            for student in students:
                try:
                    await self._backup_single_student(
                        session, scraper, context, student, stats
                    )
                    stats["students_processed"] += 1
                except Exception as e:
                    error_msg = (
                        f"Failed to backup student {student.mymoment_student_id}: {e}"
                    )
                    logger.error(error_msg)
                    stats["errors"].append(error_msg)

        finally:
            # Clean up the scraper session
            await scraper.cleanup_session(login_id)

    async def _backup_single_student(
        self,
        session: AsyncSession,
        scraper: ScraperService,
        context: SessionContext,
        student,
        stats: Dict[str, Any]
    ) -> None:
        """
        Backup all articles for a single tracked student.

        Args:
            session: Database session
            scraper: Scraper service instance
            context: Authenticated session context
            student: TrackedStudent object
            stats: Statistics dictionary to update
        """
        backup_service = StudentBackupService(session)

        # Get list of articles from student dashboard
        articles = await scraper.get_student_articles_from_dashboard(
            context, student.mymoment_student_id
        )
        stats["articles_found"] += len(articles)

        logger.debug(
            f"Found {len(articles)} articles for student {student.mymoment_student_id}"
        )

        # Process each article
        for article_info in articles:
            try:
                # Get full article content
                article_content = await scraper.get_article_content(
                    context, str(article_info.article_id)
                )

                if not article_content:
                    logger.warning(
                        f"Could not fetch content for article {article_info.article_id}"
                    )
                    continue

                # Create article version (will skip if content unchanged)
                version = await backup_service.create_article_version(
                    user_id=student.user_id,
                    tracked_student_id=student.id,
                    mymoment_article_id=article_info.article_id,
                    article_title=article_info.title,
                    article_url=article_info.view_url,
                    article_content=article_content.get("content", ""),
                    article_raw_html=article_content.get("full_html", ""),
                    article_status=article_info.status,
                    article_visibility=article_info.visibility,
                    article_category=article_info.category,
                    article_task=None,  # Not available from dashboard
                    article_last_modified=article_info.last_modified
                )

                if version:
                    stats["versions_created"] += 1
                    logger.debug(
                        f"Created version {version.version_number} for article "
                        f"{article_info.article_id}"
                    )
                else:
                    stats["versions_skipped"] += 1

            except Exception as e:
                error_msg = (
                    f"Failed to backup article {article_info.article_id}: {e}"
                )
                logger.error(error_msg)
                stats["errors"].append(error_msg)

    async def _backup_single_student_by_id_async(
        self,
        tracked_student_id: str
    ) -> Dict[str, Any]:
        """
        Async implementation of backing up a single tracked student.

        Args:
            tracked_student_id: UUID string of the tracked student

        Returns:
            Backup result dictionary
        """
        start_time = datetime.utcnow()
        stats = {
            "tracked_student_id": tracked_student_id,
            "articles_found": 0,
            "versions_created": 0,
            "versions_skipped": 0,
            "errors": [],
            "timestamp": start_time.isoformat()
        }

        if not self.is_feature_enabled():
            stats["status"] = "disabled"
            return stats

        async with await self.get_async_session() as session:
            try:
                backup_service = StudentBackupService(session)

                # Get the tracked student
                student_uuid = uuid.UUID(tracked_student_id)
                student = await backup_service.get_tracked_student_by_id(
                    student_uuid, user_id=None  # Allow any user for task
                )

                if not student:
                    stats["status"] = "not_found"
                    stats["errors"].append(f"Tracked student {tracked_student_id} not found")
                    return stats

                if not student.mymoment_login_id:
                    stats["status"] = "no_login"
                    stats["errors"].append("No admin login assigned to tracked student")
                    return stats

                # Initialize scraper and authenticate
                scraper = ScraperService(session)

                try:
                    context = await scraper.initialize_session_for_login(
                        student.mymoment_login_id,
                        student.user_id
                    )
                    if not context.is_authenticated:
                        raise Exception("Authentication failed")

                    # Backup the student
                    await self._backup_single_student(
                        session, scraper, context, student, stats
                    )
                    stats["students_processed"] = 1
                    stats["status"] = "completed"

                finally:
                    await scraper.cleanup_session(student.mymoment_login_id)

            except StudentBackupDisabledError:
                stats["status"] = "disabled"

            except Exception as e:
                error_msg = f"Backup failed: {e}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)
                stats["status"] = "failed"

        stats["execution_time_seconds"] = (datetime.utcnow() - start_time).total_seconds()
        return stats


# =========================================================================
# Celery Task Definitions
# =========================================================================

@celery_app.task(
    name='src.tasks.student_backup.backup_all_tracked_students',
    queue='backup'
)
def backup_all_tracked_students() -> Dict[str, Any]:
    """
    Backup all active tracked students.

    This is the main periodic task that runs on the configured interval
    to backup all tracked students' articles.

    Returns:
        Dictionary with backup statistics
    """
    settings = get_student_backup_settings()
    if not settings.STUDENT_BACKUP_ENABLED:
        logger.debug("Student Backup feature is disabled, task skipped")
        return {"status": "disabled", "message": "Feature disabled"}

    try:
        task = StudentBackupTask()
        result = asyncio.run(task._backup_all_students_async())
        return result
    except Exception as exc:
        logger.error(f"Student backup task failed: {exc}")
        raise


@celery_app.task(
    name='src.tasks.student_backup.backup_single_student',
    queue='backup'
)
def backup_single_student(tracked_student_id: str) -> Dict[str, Any]:
    """
    Backup a specific tracked student.

    Args:
        tracked_student_id: UUID string of the tracked student to backup

    Returns:
        Dictionary with backup statistics
    """
    settings = get_student_backup_settings()
    if not settings.STUDENT_BACKUP_ENABLED:
        return {"status": "disabled", "message": "Feature disabled"}

    try:
        task = StudentBackupTask()
        result = asyncio.run(task._backup_single_student_by_id_async(tracked_student_id))
        return result
    except Exception as exc:
        logger.error(f"Single student backup task failed: {exc}")
        raise


@celery_app.task(
    name='src.tasks.student_backup.trigger_backup',
    queue='backup'
)
def trigger_backup(tracked_student_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Manually trigger backup for specific students or all students.

    Args:
        tracked_student_ids: Optional list of tracked student UUIDs.
                           If None, backs up all tracked students.

    Returns:
        Dictionary with task dispatch information
    """
    settings = get_student_backup_settings()
    if not settings.STUDENT_BACKUP_ENABLED:
        return {"status": "disabled", "message": "Feature disabled"}

    if tracked_student_ids:
        # Dispatch individual backup tasks
        tasks = []
        for student_id in tracked_student_ids:
            task = backup_single_student.delay(student_id)
            tasks.append({"student_id": student_id, "task_id": str(task.id)})

        return {
            "status": "dispatched",
            "tasks": tasks,
            "count": len(tasks)
        }
    else:
        # Dispatch full backup task
        task = backup_all_tracked_students.delay()
        return {
            "status": "dispatched",
            "task_id": str(task.id),
            "type": "full_backup"
        }
