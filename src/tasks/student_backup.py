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
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.tasks.worker import celery_app, BaseTask
from src.config.database import get_database_manager
from src.config.settings import get_student_backup_settings
from src.platforms import (
    ArticleContent,
    ArticleRef,
    ArticleSummary,
    PlatformAccount,
    PlatformConnection,
    PlatformError,
    StudentRef,
    connect,
)
from src.platforms.accounts import load_platform_account
from src.services.student_backup_service import (
    StudentBackupService,
    StudentBackupDisabledError,
    StudentBackupValidationError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StudentSnapshot:
    """Snapshot of a tracked student, read in a short session."""
    id: uuid.UUID
    user_id: uuid.UUID
    login_id: Optional[uuid.UUID]
    mymoment_student_id: int


class StudentBackupTask(BaseTask):
    """
    Base class for student backup tasks.

    Works like the monitoring tasks: short DB sessions for reads and writes,
    the platform connection via `async with connect(...)`. No DB session is
    open while the platform is called.
    """

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

    async def _read_active_students(self) -> List[StudentSnapshot]:
        session = await self.get_async_session()
        async with session:
            students = await StudentBackupService(session).get_all_active_tracked_students()
            return [_snapshot(student) for student in students]

    async def _read_student(self, tracked_student_id: uuid.UUID) -> Optional[StudentSnapshot]:
        session = await self.get_async_session()
        async with session:
            student = await StudentBackupService(session).get_tracked_student_by_id(
                tracked_student_id, user_id=None  # Allow any user for task
            )
            return _snapshot(student) if student else None

    async def _load_admin_account(self, student: StudentSnapshot) -> PlatformAccount:
        """Load the decrypted platform account; only admin accounts back up students."""
        session = await self.get_async_session()
        async with session:
            account = await load_platform_account(session, student.login_id, student.user_id)
        if account is None:
            raise ValueError(f"Platform account {student.login_id} not found or inactive")
        if account.role != "admin":
            raise ValueError(f"Platform account {student.login_id} is not an admin account")
        return account

    async def _store_version(
        self,
        student: StudentSnapshot,
        summary: ArticleSummary,
        content: ArticleContent,
    ) -> bool:
        """Store a new Article Version unless content and metadata are unchanged."""
        session = await self.get_async_session()
        async with session:
            version = await StudentBackupService(session).create_article_version(
                user_id=student.user_id,
                tracked_student_id=student.id,
                mymoment_article_id=_article_version_id(summary.ref),
                article_title=summary.title,
                article_url=summary.ref.url,
                article_content=content.body_text,
                article_raw_html=content.body_html,
                article_status=summary.extra.get("status"),
                article_visibility=summary.extra.get("visibility"),
                article_category=summary.extra.get("categories"),
                article_task=None,  # Not available from the student's article list
                article_last_modified=summary.edited_at,
            )
        if version:
            logger.debug(f"Created version {version.version_number} for article {summary.ref.id}")
        return version is not None

    async def _backup_all_students_async(self) -> Dict[str, Any]:
        """
        Async implementation of backing up all tracked students.

        Workflow:
        1. Load all active TrackedStudents
        2. Per admin account: connect once, then for each student
           a. List the student's articles
           b. Fetch each article's content
           c. Create ArticleVersion if content changed
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

        try:
            tracked_students = await self._read_active_students()
            logger.info(f"Starting backup for {len(tracked_students)} tracked students")

            # Group students by admin login to connect once per account
            students_by_login: Dict[uuid.UUID, List[StudentSnapshot]] = {}
            for student in tracked_students:
                if student.login_id:
                    students_by_login.setdefault(student.login_id, []).append(student)

            for login_id, students in students_by_login.items():
                try:
                    await self._backup_students_with_login(students, stats)
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
        students: List[StudentSnapshot],
        stats: Dict[str, Any]
    ) -> None:
        """Backup all students of one admin account over a single connection."""
        account = await self._load_admin_account(students[0])
        async with connect(account) as platform:
            for student in students:
                try:
                    await self._backup_single_student(platform, student, stats)
                    stats["students_processed"] += 1
                except Exception as e:
                    error_msg = f"Failed to backup student {student.mymoment_student_id}: {e}"
                    logger.error(error_msg)
                    stats["errors"].append(error_msg)

    async def _backup_single_student(
        self,
        platform: PlatformConnection,
        student: StudentSnapshot,
        stats: Dict[str, Any]
    ) -> None:
        """Backup all articles of a single tracked student."""
        articles = await platform.list_student_articles(StudentRef(id=str(student.mymoment_student_id)))
        stats["articles_found"] += len(articles)
        logger.debug(f"Found {len(articles)} articles for student {student.mymoment_student_id}")

        for summary in articles:
            try:
                content = await platform.fetch_article(summary.ref)
                if await self._store_version(student, summary, content):
                    stats["versions_created"] += 1
                else:
                    stats["versions_skipped"] += 1
            except (PlatformError, StudentBackupValidationError) as e:
                error_msg = f"Failed to backup article {summary.ref.id}: {e}"
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

        try:
            student = await self._read_student(uuid.UUID(tracked_student_id))

            if not student:
                stats["status"] = "not_found"
                stats["errors"].append(f"Tracked student {tracked_student_id} not found")
                return stats

            if not student.login_id:
                stats["status"] = "no_login"
                stats["errors"].append("No admin login assigned to tracked student")
                return stats

            account = await self._load_admin_account(student)
            async with connect(account) as platform:
                await self._backup_single_student(platform, student, stats)
            stats["students_processed"] = 1
            stats["status"] = "completed"

        except StudentBackupDisabledError:
            stats["status"] = "disabled"

        except Exception as e:
            error_msg = f"Backup failed: {e}"
            logger.error(error_msg)
            stats["errors"].append(error_msg)
            stats["status"] = "failed"

        stats["execution_time_seconds"] = (datetime.utcnow() - start_time).total_seconds()
        return stats


def _snapshot(student) -> StudentSnapshot:
    return StudentSnapshot(
        id=student.id,
        user_id=student.user_id,
        login_id=student.mymoment_login_id,
        mymoment_student_id=student.mymoment_student_id,
    )


def _article_version_id(ref: ArticleRef) -> int:
    """The one place where the platform's string ID becomes the integer column of ArticleVersion."""
    if not (ref.id.isascii() and ref.id.isdigit()):
        raise StudentBackupValidationError(f"Article ID {ref.id!r} does not fit the integer column of ArticleVersion")
    return int(ref.id)


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
