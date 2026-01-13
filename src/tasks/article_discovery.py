"""
Article discovery task for myMoment monitoring processes.

This module implements Task 1 of the refactored monitoring pipeline:
- Scrapes myMoment article index for each login
- Creates minimal AIComment records with metadata only (no full content)
- Uses short-lived database sessions with no external I/O inside transactions
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from celery import current_task
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from src.tasks.worker import celery_app, BaseTask
from src.models.monitoring_process import MonitoringProcess
from src.models.mymoment_login import MyMomentLogin
from src.models.prompt_template import PromptTemplate
from src.models.llm_provider import LLMProviderConfiguration
from src.models.ai_comment import AIComment
from src.models.monitoring_process_login import MonitoringProcessLogin
from src.models.monitoring_process_prompt import MonitoringProcessPrompt
from src.services.scraper_service import ScraperService, ScrapingConfig, ArticleMetadata
from src.config.database import get_database_manager

logger = logging.getLogger(__name__)


@dataclass
class ProcessConfig:
    """Configuration snapshot for a monitoring process."""
    process_id: uuid.UUID
    user_id: uuid.UUID
    login_ids: List[uuid.UUID]
    prompt_ids: List[uuid.UUID]
    llm_provider_id: Optional[uuid.UUID]
    tab_filter: Optional[str]
    category_filter: Optional[int]
    task_filter: Optional[int]
    search_filter: Optional[str]


class ArticleDiscoveryTask(BaseTask):
    """Task for discovering articles and creating AIComment records."""

    def __init__(self):
        self.db_manager = get_database_manager()

    async def get_async_session(self) -> AsyncSession:
        """Get async database session."""
        sessionmaker = await self.db_manager.create_sessionmaker()
        return sessionmaker()

    async def _read_process_config(self, process_id: uuid.UUID) -> ProcessConfig:
        """
        Read monitoring process configuration.

        Uses Pattern 1: Read-Only Data Fetching with short-lived session.
        Session is closed before any scraping begins.

        Args:
            process_id: Monitoring process UUID

        Returns:
            ProcessConfig snapshot with all necessary IDs
        """
        session = await self.get_async_session()
        async with session:
            # Read MonitoringProcess
            result = await session.execute(
                select(MonitoringProcess).where(MonitoringProcess.id == process_id)
            )
            process = result.scalar_one_or_none()

            if not process:
                raise ValueError(f"MonitoringProcess {process_id} not found")

            # Extract login IDs from junction table
            login_result = await session.execute(
                select(MonitoringProcessLogin.mymoment_login_id)
                .where(
                    and_(
                        MonitoringProcessLogin.monitoring_process_id == process_id,
                        MonitoringProcessLogin.is_active == True
                    )
                )
            )
            login_ids = [row[0] for row in login_result.all()]

            # Extract prompt template IDs from junction table
            prompt_result = await session.execute(
                select(MonitoringProcessPrompt.prompt_template_id)
                .where(
                    and_(
                        MonitoringProcessPrompt.monitoring_process_id == process_id,
                        MonitoringProcessPrompt.is_active == True
                    )
                )
            )
            prompt_ids = [row[0] for row in prompt_result.all()]

            # Get LLM provider ID (use process-level or user's active provider)
            llm_provider_id = process.llm_provider_id
            if not llm_provider_id:
                # Fallback: Get user's active LLM provider
                provider_result = await session.execute(
                    select(LLMProviderConfiguration.id)
                    .where(
                        and_(
                            LLMProviderConfiguration.user_id == process.user_id,
                            LLMProviderConfiguration.is_active == True
                        )
                    )
                    .limit(1)
                )
                provider_row = provider_result.first()
                llm_provider_id = provider_row[0] if provider_row else None

            # Create configuration snapshot
            config_snapshot = ProcessConfig(
                process_id=process_id,
                user_id=process.user_id,
                login_ids=login_ids,
                prompt_ids=prompt_ids,
                llm_provider_id=llm_provider_id,
                tab_filter=process.tab_filter,
                category_filter=process.category_filter,
                task_filter=process.task_filter,
                search_filter=process.search_filter
            )

        # Session closed automatically (< 100ms total)
        logger.info(f"Read config for process {process_id}: "
                   f"{len(login_ids)} logins, {len(prompt_ids)} prompts")
        return config_snapshot

    async def _scrape_articles_for_login(
        self,
        login_id: uuid.UUID,
        user_id: uuid.UUID,
        config_snapshot: ProcessConfig
    ) -> List[ArticleMetadata]:
        """
        Scrape articles index for a single login.

        This method runs OUTSIDE any database session.
        Only fetches article metadata from the index page, not full content.

        Args:
            login_id: MyMomentLogin UUID
            user_id: User UUID (for session lookup)
            config_snapshot: Process configuration

        Returns:
            List of ArticleMetadata objects
        """
        # Get login credentials - short session
        session = await self.get_async_session()
        async with session:
            result = await session.execute(
                select(MyMomentLogin).where(MyMomentLogin.id == login_id)
            )
            login = result.scalar_one_or_none()

            if not login or not login.is_active:
                logger.warning(f"Login {login_id} not found or inactive")
                return []

            # Get decrypted credentials
            username = login.get_username()
            password = login.get_password()
        # Session closed

        # Initialize scraper with config (outside DB session)
        scraping_config = ScrapingConfig.from_settings()

        # Create temporary session for scraping
        session = await self.get_async_session()
        async with session:
            async with ScraperService(session, scraping_config) as scraper:
                try:
                    # Initialize session for this login
                    context = await scraper.initialize_session_for_login(
                        login_id=login_id,
                        user_id=user_id
                    )

                    # Scrape article index (metadata only, no full content)
                    # Tab filter must be explicitly set, no default to "alle"
                    if not config_snapshot.tab_filter:
                        logger.warning(f"No tab filter specified for process {config_snapshot.process_id}, skipping article discovery")
                        return []

                    tab = config_snapshot.tab_filter
                    category = str(config_snapshot.category_filter) if config_snapshot.category_filter else None
                    task = str(config_snapshot.task_filter) if config_snapshot.task_filter else None
                    search = config_snapshot.search_filter
                    limit = 20  # Default articles per login

                    articles = await scraper.discover_new_articles(
                        context=context,
                        tab=tab,
                        category=category,
                        task=task,
                        search=search,
                        limit=limit
                    )

                    # Cleanup session
                    await scraper.cleanup_session(login_id)

                    logger.info(f"Scraped {len(articles)} articles for login {login_id}")
                    return articles

                except Exception as e:
                    logger.error(f"Failed to scrape articles for login {login_id}: {e}")
                    return []

    async def _create_ai_comment_records(
        self,
        articles_metadata: List[tuple[ArticleMetadata, uuid.UUID, Optional[uuid.UUID]]],
        config: ProcessConfig
    ) -> int:
        """
        Batch create AIComment records from article metadata.

        Uses Pattern 2: Batch Write Operations.
        Creates all records in a single transaction for efficiency.

        Args:
            articles_metadata: List of (ArticleMetadata, login_id, prompt_id) tuples
            config: Process configuration snapshot

        Returns:
            Number of AIComment records created
        """
        session = await self.get_async_session()
        async with session:
            created_count = 0

            for article_meta, login_id, prompt_id in articles_metadata:
                try:
                    # Check if this article+login+process combination already exists
                    existing = await session.execute(
                        select(AIComment).where(
                            and_(
                                AIComment.mymoment_article_id == article_meta.id,
                                AIComment.monitoring_process_id == config.process_id,
                                AIComment.mymoment_login_id == login_id,
                                AIComment.prompt_template_id == prompt_id
                            )
                        )
                    )

                    if existing.scalar_one_or_none():
                        logger.debug(f"Article {article_meta.id} already exists for "
                                   f"login {login_id}, prompt {prompt_id}")
                        continue

                    # Create AIComment record with metadata only
                    ai_comment = AIComment(
                        # Article snapshot fields (metadata only)
                        mymoment_article_id=article_meta.id,
                        article_title=article_meta.title,
                        article_author=article_meta.author,
                        article_category=article_meta.category_id,
                        article_task_id=article_meta.task_id,
                        article_url=article_meta.url,
                        article_edited_at=None,  # Not available from index
                        article_scraped_at=datetime.utcnow(),

                        # Content fields - empty for now (filled in preparation stage)
                        article_content="",
                        article_raw_html="",
                        article_published_at=None,

                        # Process and login attribution
                        monitoring_process_id=config.process_id,
                        user_id=config.user_id,
                        mymoment_login_id=login_id,
                        llm_provider_id=config.llm_provider_id,
                        prompt_template_id=prompt_id,

                        # Status
                        status='discovered',

                        # Comment fields (will be filled later)
                        comment_content=None,
                        ai_model_name=None,
                        ai_provider_name=None
                    )

                    session.add(ai_comment)
                    created_count += 1

                except Exception as e:
                    logger.error(f"Failed to create AIComment for article {article_meta.id}: {e}")
                    continue

            # Single commit for all records
            if created_count > 0:
                await session.commit()

        # Session closed automatically (< 500ms for batch)
        logger.info(f"Created {created_count} AIComment records")
        return created_count

    async def _discover_articles_async(self, process_id: uuid.UUID) -> Dict[str, Any]:
        """
        Main async method for article discovery.

        Implements the discovery workflow:
        1. Read process configuration (Pattern 1)
        2. For each login: scrape article metadata (outside DB session)
        3. For each article × prompt: prepare AIComment data
        4. Batch create AIComment records (Pattern 2)

        Args:
            process_id: Monitoring process UUID

        Returns:
            Result dictionary with counts and errors
        """
        start_time = datetime.utcnow()
        errors = []
        total_discovered = 0

        try:
            # Step 1: Read process configuration (short-lived session)
            config = await self._read_process_config(process_id)

            if not config.login_ids:
                raise ValueError(f"No active logins found for process {process_id}")

            if not config.prompt_ids:
                raise ValueError(f"No active prompt templates found for process {process_id}")

            logger.info(f"Starting article discovery for process {process_id}: "
                       f"{len(config.login_ids)} logins × {len(config.prompt_ids)} prompts")

            # Step 2: Scrape articles for each login (outside DB sessions)
            all_articles_metadata = []

            for login_id in config.login_ids:
                try:
                    articles = await self._scrape_articles_for_login(
                        login_id=login_id,
                        user_id=config.user_id,
                        config_snapshot=config
                    )

                    # For each article, create entries for each prompt template
                    # This is the cross-product: articles × prompts
                    for article in articles:
                        for prompt_id in config.prompt_ids:
                            all_articles_metadata.append((article, login_id, prompt_id))

                    logger.info(f"Found {len(articles)} articles for login {login_id}")

                except Exception as e:
                    error_msg = f"Scraping failed for login {login_id}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
                    # Continue with other logins

            # Step 3: Batch create AIComment records (single transaction)
            if all_articles_metadata:
                total_discovered = await self._create_ai_comment_records(
                    all_articles_metadata,
                    config
                )

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            logger.info(f"Article discovery completed for process {process_id}: "
                       f"{total_discovered} records created, "
                       f"{len(errors)} errors, "
                       f"{execution_time:.2f}s")

            return {
                'discovered': total_discovered,
                'errors': errors,
                'execution_time_seconds': execution_time,
                'status': 'success' if not errors else 'partial'
            }

        except Exception as e:
            error_msg = f"Article discovery failed: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)

            execution_time = (datetime.utcnow() - start_time).total_seconds()

            return {
                'discovered': total_discovered,
                'errors': errors,
                'execution_time_seconds': execution_time,
                'status': 'failed'
            }


@celery_app.task(
    bind=True,
    base=ArticleDiscoveryTask,
    name='src.tasks.article_discovery.discover_articles',
    queue='discovery',
    max_retries=3,
    default_retry_delay=120
)
def discover_articles(self, process_id: str) -> Dict[str, Any]:
    """
    Celery task wrapper for article discovery.

    This is the entry point for the discovery stage of the monitoring pipeline.
    Discovers articles and creates AIComment records with status='discovered'.

    Args:
        process_id: Monitoring process UUID as string

    Returns:
        Dictionary with discovery results:
        - discovered: Number of AIComment records created
        - errors: List of error messages
        - execution_time_seconds: Task execution time
        - status: 'success', 'partial', or 'failed'
    """
    try:
        logger.info(f"Starting article discovery task for process {process_id}")
        result = asyncio.run(self._discover_articles_async(uuid.UUID(process_id)))
        logger.info(f"Article discovery task completed: {result}")
        return result

    except Exception as exc:
        logger.error(f"Article discovery task failed for process {process_id}: {exc}")
        # Retry with exponential backoff
        self.retry(exc=exc, countdown=120)
