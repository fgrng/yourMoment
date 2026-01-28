"""
Student Backup service for yourMoment application.

Implements business logic for the Student Backup feature:
- CRUD operations for TrackedStudent and ArticleVersion
- Content hash comparison for change detection
- Version limit enforcement (soft-delete oldest versions)
- Validation (limits, ownership, admin login validation)
"""

import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import select, and_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.models.tracked_student import TrackedStudent
from src.models.article_version import ArticleVersion
from src.models.mymoment_login import MyMomentLogin
from src.services.base_service import BaseService, ServiceValidationError, ServiceNotFoundError
from src.config.settings import get_student_backup_settings


class StudentBackupServiceError(Exception):
    """Base exception for Student Backup service operations."""
    pass


class StudentBackupValidationError(StudentBackupServiceError):
    """Raised when validation fails."""
    pass


class StudentBackupNotFoundError(StudentBackupServiceError):
    """Raised when a resource is not found."""
    pass


class StudentBackupDisabledError(StudentBackupServiceError):
    """Raised when the Student Backup feature is disabled."""
    pass


class StudentBackupLimitError(StudentBackupServiceError):
    """Raised when a user limit is exceeded."""
    pass


class StudentBackupService(BaseService):
    """
    Service for handling Student Backup operations.

    Implements:
    - TrackedStudent CRUD with admin login validation
    - ArticleVersion CRUD with content hash comparison
    - Version limit enforcement
    - Feature toggle validation
    """

    def __init__(self, db_session: AsyncSession):
        """
        Initialize Student Backup service.

        Args:
            db_session: Database session for operations
        """
        super().__init__(db_session)
        self.settings = get_student_backup_settings()

    def _check_feature_enabled(self) -> None:
        """
        Check if the Student Backup feature is enabled.

        Raises:
            StudentBackupDisabledError: If the feature is disabled
        """
        if not self.settings.STUDENT_BACKUP_ENABLED:
            raise StudentBackupDisabledError(
                "Student Backup feature is disabled. "
                "Set STUDENT_BACKUP_ENABLED=true to enable it."
            )

    # =========================================================================
    # TrackedStudent Operations
    # =========================================================================

    async def create_tracked_student(
        self,
        user_id: uuid.UUID,
        mymoment_student_id: int,
        mymoment_login_id: uuid.UUID,
        display_name: Optional[str] = None,
        notes: Optional[str] = None
    ) -> TrackedStudent:
        """
        Create a new tracked student record.

        Args:
            user_id: ID of the user creating the tracking
            mymoment_student_id: Student's user ID on myMoment platform
            mymoment_login_id: ID of admin login to use for scraping
            display_name: Optional friendly name for the student
            notes: Optional notes about the student

        Returns:
            Created TrackedStudent object

        Raises:
            StudentBackupDisabledError: If feature is disabled
            StudentBackupValidationError: If validation fails
            StudentBackupLimitError: If user has reached tracking limit
        """
        self._check_feature_enabled()

        # Validate mymoment_student_id
        if mymoment_student_id <= 0:
            raise StudentBackupValidationError(
                "myMoment student ID must be a positive integer"
            )

        # Validate admin login exists and is actually an admin login
        login = await self._validate_admin_login(mymoment_login_id, user_id)

        # Check if user has reached the tracking limit
        current_count = await self._get_user_tracked_students_count(user_id)
        max_allowed = self.settings.STUDENT_BACKUP_MAX_TRACKED_STUDENTS_PER_USER
        if current_count >= max_allowed:
            raise StudentBackupLimitError(
                f"Maximum tracked students limit reached ({max_allowed}). "
                f"Please remove some tracked students before adding new ones."
            )

        # Check for duplicate: same user tracking same myMoment student
        existing = await self._get_existing_tracking(user_id, mymoment_student_id)
        if existing:
            raise StudentBackupValidationError(
                f"Student with myMoment ID {mymoment_student_id} is already being tracked"
            )

        # Create the tracked student record
        tracked_student = TrackedStudent(
            user_id=user_id,
            mymoment_login_id=mymoment_login_id,
            mymoment_student_id=mymoment_student_id,
            display_name=display_name.strip() if display_name else None,
            notes=notes.strip() if notes else None,
            is_active=True
        )

        try:
            self.db_session.add(tracked_student)
            await self.db_session.commit()
            await self.db_session.refresh(tracked_student)
            self.log_operation(
                "create_tracked_student",
                user_id=user_id,
                resource_id=tracked_student.id,
                additional_data={"mymoment_student_id": mymoment_student_id}
            )
        except IntegrityError as e:
            await self.db_session.rollback()
            raise StudentBackupValidationError(f"Failed to create tracked student: {e}")

        return tracked_student

    async def get_tracked_student_by_id(
        self,
        tracked_student_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        include_versions: bool = False
    ) -> Optional[TrackedStudent]:
        """
        Get a tracked student by ID.

        Args:
            tracked_student_id: ID of the tracked student
            user_id: Optional user ID for ownership validation
            include_versions: Whether to eagerly load article versions

        Returns:
            TrackedStudent if found and active, None otherwise
        """
        self._check_feature_enabled()

        conditions = [
            TrackedStudent.id == tracked_student_id,
            TrackedStudent.is_active == True
        ]

        if user_id is not None:
            conditions.append(TrackedStudent.user_id == user_id)

        stmt = select(TrackedStudent).where(and_(*conditions))

        if include_versions:
            stmt = stmt.options(selectinload(TrackedStudent.article_versions))

        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_tracked_students(
        self,
        user_id: uuid.UUID,
        include_inactive: bool = False
    ) -> List[TrackedStudent]:
        """
        Get all tracked students for a user.

        Args:
            user_id: ID of the user
            include_inactive: Whether to include inactive tracked students

        Returns:
            List of TrackedStudent objects
        """
        self._check_feature_enabled()

        conditions = [TrackedStudent.user_id == user_id]

        if not include_inactive:
            conditions.append(TrackedStudent.is_active == True)

        stmt = (
            select(TrackedStudent)
            .where(and_(*conditions))
            .order_by(TrackedStudent.created_at.desc())
        )

        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def update_tracked_student(
        self,
        tracked_student_id: uuid.UUID,
        user_id: uuid.UUID,
        mymoment_login_id: Optional[uuid.UUID] = None,
        display_name: Optional[str] = None,
        notes: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Optional[TrackedStudent]:
        """
        Update a tracked student record.

        Args:
            tracked_student_id: ID of the tracked student to update
            user_id: ID of the owning user (for validation)
            mymoment_login_id: New admin login ID (optional)
            display_name: New display name (optional)
            notes: New notes (optional)
            is_active: New active status (optional)

        Returns:
            Updated TrackedStudent if successful, None if not found

        Raises:
            StudentBackupValidationError: If validation fails
        """
        self._check_feature_enabled()

        tracked_student = await self.get_tracked_student_by_id(
            tracked_student_id, user_id
        )
        if not tracked_student:
            return None

        # Validate and update admin login if provided
        if mymoment_login_id is not None:
            await self._validate_admin_login(mymoment_login_id, user_id)
            tracked_student.mymoment_login_id = mymoment_login_id

        # Update optional fields
        if display_name is not None:
            tracked_student.display_name = display_name.strip() if display_name else None

        if notes is not None:
            tracked_student.notes = notes.strip() if notes else None

        if is_active is not None:
            tracked_student.is_active = is_active

        tracked_student.updated_at = datetime.utcnow()

        try:
            await self.db_session.commit()
            await self.db_session.refresh(tracked_student)
            self.log_operation(
                "update_tracked_student",
                user_id=user_id,
                resource_id=tracked_student_id
            )
        except IntegrityError as e:
            await self.db_session.rollback()
            raise StudentBackupValidationError(f"Failed to update tracked student: {e}")

        return tracked_student

    async def delete_tracked_student(
        self,
        tracked_student_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> bool:
        """
        Soft-delete a tracked student (marks as inactive).

        Args:
            tracked_student_id: ID of the tracked student to delete
            user_id: ID of the owning user (for validation)

        Returns:
            True if deletion was successful, False if not found
        """
        self._check_feature_enabled()

        tracked_student = await self.get_tracked_student_by_id(
            tracked_student_id, user_id
        )
        if not tracked_student:
            return False

        tracked_student.is_active = False
        tracked_student.updated_at = datetime.utcnow()

        try:
            await self.db_session.commit()
            self.log_operation(
                "delete_tracked_student",
                user_id=user_id,
                resource_id=tracked_student_id
            )
            return True
        except Exception:
            await self.db_session.rollback()
            return False

    # =========================================================================
    # ArticleVersion Operations
    # =========================================================================

    async def create_article_version(
        self,
        user_id: uuid.UUID,
        tracked_student_id: uuid.UUID,
        mymoment_article_id: int,
        article_title: Optional[str] = None,
        article_url: Optional[str] = None,
        article_content: Optional[str] = None,
        article_raw_html: Optional[str] = None,
        article_status: Optional[str] = None,
        article_visibility: Optional[str] = None,
        article_category: Optional[str] = None,
        article_task: Optional[str] = None,
        article_last_modified: Optional[datetime] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[ArticleVersion]:
        """
        Create a new article version if content has changed.

        If STUDENT_BACKUP_CONTENT_CHANGES_ONLY is enabled, only creates a new
        version if the content hash differs from the latest version.

        Args:
            user_id: ID of the user owning this backup
            tracked_student_id: ID of the tracked student
            mymoment_article_id: Article ID on myMoment platform
            article_title: Article title
            article_url: Article view URL
            article_content: Plain text content
            article_raw_html: Raw HTML content
            article_status: Publication status
            article_visibility: Visibility/class info
            article_category: Article category
            article_task: Writing task if assigned
            article_last_modified: Last modification timestamp from myMoment
            extra_metadata: Additional metadata as JSON

        Returns:
            Created ArticleVersion if new version was created, None if content unchanged

        Raises:
            StudentBackupValidationError: If validation fails
        """
        self._check_feature_enabled()

        # Validate tracked student exists and belongs to user
        tracked_student = await self.get_tracked_student_by_id(
            tracked_student_id, user_id
        )
        if not tracked_student:
            raise StudentBackupValidationError(
                f"Tracked student {tracked_student_id} not found or does not belong to user"
            )

        # Compute content hash
        content_hash = ArticleVersion.compute_content_hash(article_content or "")

        # Check if we should skip creating a new version (content unchanged)
        if self.settings.STUDENT_BACKUP_CONTENT_CHANGES_ONLY:
            latest_version = await self._get_latest_article_version(
                tracked_student_id, mymoment_article_id
            )
            if latest_version and latest_version.content_hash == content_hash:
                self.logger.debug(
                    f"Skipping version creation for article {mymoment_article_id}: "
                    f"content unchanged"
                )
                return None

        # Determine version number
        version_number = await self._get_next_version_number(
            tracked_student_id, mymoment_article_id
        )

        # Create the article version
        article_version = ArticleVersion(
            user_id=user_id,
            tracked_student_id=tracked_student_id,
            mymoment_article_id=mymoment_article_id,
            version_number=version_number,
            article_title=article_title,
            article_url=article_url,
            article_content=article_content,
            article_raw_html=article_raw_html,
            article_status=article_status,
            article_visibility=article_visibility,
            article_category=article_category,
            article_task=article_task,
            article_last_modified=article_last_modified,
            content_hash=content_hash,
            extra_metadata=extra_metadata,
            is_active=True
        )

        try:
            self.db_session.add(article_version)
            await self.db_session.commit()
            await self.db_session.refresh(article_version)

            self.log_operation(
                "create_article_version",
                user_id=user_id,
                resource_id=article_version.id,
                additional_data={
                    "mymoment_article_id": mymoment_article_id,
                    "version_number": version_number
                }
            )
        except IntegrityError as e:
            await self.db_session.rollback()
            raise StudentBackupValidationError(f"Failed to create article version: {e}")

        # Enforce version limit (soft-delete oldest versions if needed)
        await self._enforce_version_limit(tracked_student_id, mymoment_article_id)

        # Update tracked student's last_backup_at timestamp
        tracked_student.last_backup_at = datetime.utcnow()
        await self.db_session.commit()

        return article_version

    async def get_article_version_by_id(
        self,
        version_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None
    ) -> Optional[ArticleVersion]:
        """
        Get an article version by ID.

        Args:
            version_id: ID of the article version
            user_id: Optional user ID for ownership validation

        Returns:
            ArticleVersion if found and active, None otherwise
        """
        self._check_feature_enabled()

        conditions = [
            ArticleVersion.id == version_id,
            ArticleVersion.is_active == True
        ]

        if user_id is not None:
            conditions.append(ArticleVersion.user_id == user_id)

        stmt = select(ArticleVersion).where(and_(*conditions))
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_article_versions(
        self,
        tracked_student_id: uuid.UUID,
        user_id: uuid.UUID,
        mymoment_article_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[ArticleVersion]:
        """
        Get article versions for a tracked student.

        Args:
            tracked_student_id: ID of the tracked student
            user_id: ID of the owning user (for validation)
            mymoment_article_id: Optional filter by specific article
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of ArticleVersion objects
        """
        self._check_feature_enabled()

        # Validate tracked student ownership
        tracked_student = await self.get_tracked_student_by_id(
            tracked_student_id, user_id
        )
        if not tracked_student:
            return []

        conditions = [
            ArticleVersion.tracked_student_id == tracked_student_id,
            ArticleVersion.user_id == user_id,
            ArticleVersion.is_active == True
        ]

        if mymoment_article_id is not None:
            conditions.append(ArticleVersion.mymoment_article_id == mymoment_article_id)

        stmt = (
            select(ArticleVersion)
            .where(and_(*conditions))
            .order_by(
                ArticleVersion.mymoment_article_id,
                ArticleVersion.version_number.desc()
            )
            .limit(limit)
            .offset(offset)
        )

        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())

    async def get_articles_summary(
        self,
        tracked_student_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> List[Dict[str, Any]]:
        """
        Get a summary of articles for a tracked student.

        Returns aggregated information per article: article ID, title,
        version count, latest version date.

        Args:
            tracked_student_id: ID of the tracked student
            user_id: ID of the owning user (for validation)

        Returns:
            List of dictionaries with article summary information
        """
        self._check_feature_enabled()

        # Validate tracked student ownership
        tracked_student = await self.get_tracked_student_by_id(
            tracked_student_id, user_id
        )
        if not tracked_student:
            return []

        # Query to get latest version per article with counts
        stmt = (
            select(
                ArticleVersion.mymoment_article_id,
                func.max(ArticleVersion.article_title).label("article_title"),
                func.count(ArticleVersion.id).label("version_count"),
                func.max(ArticleVersion.scraped_at).label("latest_scraped_at"),
                func.max(ArticleVersion.article_status).label("article_status")
            )
            .where(
                and_(
                    ArticleVersion.tracked_student_id == tracked_student_id,
                    ArticleVersion.user_id == user_id,
                    ArticleVersion.is_active == True
                )
            )
            .group_by(ArticleVersion.mymoment_article_id)
            .order_by(func.max(ArticleVersion.scraped_at).desc())
        )

        result = await self.db_session.execute(stmt)
        rows = result.all()

        return [
            {
                "mymoment_article_id": row.mymoment_article_id,
                "article_title": row.article_title,
                "version_count": row.version_count,
                "latest_scraped_at": row.latest_scraped_at.isoformat() if row.latest_scraped_at else None,
                "article_status": row.article_status,
                "view_url": f"https://www.mymoment.ch/article/{row.mymoment_article_id}/"
            }
            for row in rows
        ]

    # =========================================================================
    # Helper Methods
    # =========================================================================

    async def _validate_admin_login(
        self,
        login_id: uuid.UUID,
        user_id: uuid.UUID
    ) -> MyMomentLogin:
        """
        Validate that a login exists, belongs to the user, and is an admin login.

        Args:
            login_id: ID of the login to validate
            user_id: ID of the user who should own the login

        Returns:
            MyMomentLogin object if valid

        Raises:
            StudentBackupValidationError: If validation fails
        """
        stmt = select(MyMomentLogin).where(
            and_(
                MyMomentLogin.id == login_id,
                MyMomentLogin.user_id == user_id,
                MyMomentLogin.is_active == True
            )
        )
        result = await self.db_session.execute(stmt)
        login = result.scalar_one_or_none()

        if not login:
            raise StudentBackupValidationError(
                f"Login {login_id} not found or does not belong to user"
            )

        if not login.is_admin:
            raise StudentBackupValidationError(
                f"Login '{login.name}' is not an admin login. "
                f"Only admin logins can be used for Student Backup. "
                f"Please mark the login as 'Admin' in the credentials settings."
            )

        return login

    async def _get_user_tracked_students_count(self, user_id: uuid.UUID) -> int:
        """Get count of active tracked students for a user."""
        stmt = (
            select(func.count(TrackedStudent.id))
            .where(
                and_(
                    TrackedStudent.user_id == user_id,
                    TrackedStudent.is_active == True
                )
            )
        )
        result = await self.db_session.execute(stmt)
        return result.scalar_one() or 0

    async def _get_existing_tracking(
        self,
        user_id: uuid.UUID,
        mymoment_student_id: int
    ) -> Optional[TrackedStudent]:
        """Check if user is already tracking a specific myMoment student."""
        stmt = select(TrackedStudent).where(
            and_(
                TrackedStudent.user_id == user_id,
                TrackedStudent.mymoment_student_id == mymoment_student_id,
                TrackedStudent.is_active == True
            )
        )
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_latest_article_version(
        self,
        tracked_student_id: uuid.UUID,
        mymoment_article_id: int
    ) -> Optional[ArticleVersion]:
        """Get the latest version of an article for a tracked student."""
        stmt = (
            select(ArticleVersion)
            .where(
                and_(
                    ArticleVersion.tracked_student_id == tracked_student_id,
                    ArticleVersion.mymoment_article_id == mymoment_article_id,
                    ArticleVersion.is_active == True
                )
            )
            .order_by(ArticleVersion.version_number.desc())
            .limit(1)
        )
        result = await self.db_session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_next_version_number(
        self,
        tracked_student_id: uuid.UUID,
        mymoment_article_id: int
    ) -> int:
        """Get the next version number for an article."""
        stmt = (
            select(func.max(ArticleVersion.version_number))
            .where(
                and_(
                    ArticleVersion.tracked_student_id == tracked_student_id,
                    ArticleVersion.mymoment_article_id == mymoment_article_id
                )
            )
        )
        result = await self.db_session.execute(stmt)
        max_version = result.scalar_one()
        return (max_version or 0) + 1

    async def _enforce_version_limit(
        self,
        tracked_student_id: uuid.UUID,
        mymoment_article_id: int
    ) -> int:
        """
        Enforce the maximum versions per article limit.

        Soft-deletes oldest versions if the limit is exceeded.

        Args:
            tracked_student_id: ID of the tracked student
            mymoment_article_id: myMoment article ID

        Returns:
            Number of versions soft-deleted
        """
        max_versions = self.settings.STUDENT_BACKUP_MAX_VERSIONS_PER_ARTICLE

        # Get count of active versions
        count_stmt = (
            select(func.count(ArticleVersion.id))
            .where(
                and_(
                    ArticleVersion.tracked_student_id == tracked_student_id,
                    ArticleVersion.mymoment_article_id == mymoment_article_id,
                    ArticleVersion.is_active == True
                )
            )
        )
        result = await self.db_session.execute(count_stmt)
        active_count = result.scalar_one() or 0

        if active_count <= max_versions:
            return 0

        # Find versions to soft-delete (oldest first)
        versions_to_delete = active_count - max_versions
        stmt = (
            select(ArticleVersion)
            .where(
                and_(
                    ArticleVersion.tracked_student_id == tracked_student_id,
                    ArticleVersion.mymoment_article_id == mymoment_article_id,
                    ArticleVersion.is_active == True
                )
            )
            .order_by(ArticleVersion.version_number.asc())
            .limit(versions_to_delete)
        )
        result = await self.db_session.execute(stmt)
        old_versions = result.scalars().all()

        for version in old_versions:
            version.is_active = False

        await self.db_session.commit()

        self.logger.info(
            f"Soft-deleted {len(old_versions)} old versions for article "
            f"{mymoment_article_id} (limit: {max_versions})"
        )

        return len(old_versions)

    async def get_all_active_tracked_students(self) -> List[TrackedStudent]:
        """
        Get all active tracked students across all users.

        Used by the Celery backup task to find all students that need backing up.

        Returns:
            List of all active TrackedStudent objects with their admin logins loaded
        """
        self._check_feature_enabled()

        stmt = (
            select(TrackedStudent)
            .options(selectinload(TrackedStudent.mymoment_login))
            .where(TrackedStudent.is_active == True)
            .order_by(TrackedStudent.last_backup_at.asc().nullsfirst())
        )

        result = await self.db_session.execute(stmt)
        return list(result.scalars().all())
