"""
Celery worker configuration and task routing for yourMoment application.

This module configures Celery for background task processing including:
- Article monitoring and scraping tasks
- AI comment generation tasks
- Session management tasks
- Process timeout enforcement tasks
"""

import os
import logging
from importlib import import_module
from typing import Any, Dict, Iterable
from celery import Celery
from celery.signals import setup_logging, task_prerun, task_postrun
from kombu import Queue

from src.config.settings import get_settings

# Task modules that need to be imported so Celery registers them
TASK_MODULES: Iterable[str] = (
    'src.tasks.session_manager',
    'src.tasks.timeout_enforcer',
    'src.tasks.scheduler',
    'src.tasks.article_discovery',
    'src.tasks.article_preparation',
    'src.tasks.comment_generation',
    'src.tasks.comment_posting',
    'src.tasks.student_backup',
)

# Configure logging for Celery
logger = logging.getLogger(__name__)


class CeleryConfig:
    """Celery configuration settings."""

    # Broker and result backend configuration
    settings = get_settings()
    broker_url = settings.celery.CELERY_BROKER_URL
    result_backend = settings.celery.CELERY_RESULT_BACKEND

    # Task routing and queues
    task_routes = {
        'src.tasks.session_manager.*': {'queue': 'sessions'},
        'src.tasks.timeout_enforcer.*': {'queue': 'timeouts'},
        'src.tasks.scheduler.*': {'queue': 'scheduler'},
        'src.tasks.article_discovery.*': {'queue': 'discovery'},
        'src.tasks.article_preparation.*': {'queue': 'preparation'},
        'src.tasks.comment_generation.*': {'queue': 'generation'},
        'src.tasks.comment_posting.*': {'queue': 'posting'},
        'src.tasks.student_backup.*': {'queue': 'backup'},
    }

    # Define queues
    task_queues = (
        Queue('sessions', routing_key='sessions'),
        Queue('timeouts', routing_key='timeouts'),
        Queue('scheduler', routing_key='scheduler'),
        Queue('discovery', routing_key='discovery'),
        Queue('preparation', routing_key='preparation'),
        Queue('generation', routing_key='generation'),
        Queue('posting', routing_key='posting'),
        Queue('backup', routing_key='backup'),  # Student Backup feature
        Queue('celery', routing_key='celery'),  # default queue
    )

    # Task execution settings
    task_serializer = 'json'
    accept_content = ['json']
    result_serializer = 'json'
    timezone = 'UTC'
    enable_utc = True

    # Worker settings
    worker_prefetch_multiplier = 1  # One task at a time for better resource control
    task_acks_late = True  # Acknowledge tasks after completion
    worker_max_tasks_per_child = 100  # Restart worker after 100 tasks to prevent memory leaks

    # Task time limits
    task_soft_time_limit = 3*(60*60)  # 3 hours soft limit
    task_time_limit = 6*(60*60)  # 6 hours hard limit

    # Result expiration
    result_expires = 24*(60*60)  # 24 hours

    # Task routing optimization
    task_ignore_result = False
    task_store_eager_result = True

    # Monitoring and logging
    worker_send_task_events = True
    task_send_sent_event = True

    # Beat schedule for periodic tasks
    beat_schedule = {
        'check-process-timeouts': {
            'task': 'src.tasks.timeout_enforcer.check_process_timeouts',
            'schedule': settings.monitoring.PROCESS_HEALTH_CHECK_INTERVAL_SECONDS,
        },
        'cleanup-expired-sessions': {
            'task': 'src.tasks.session_manager.cleanup_expired_sessions',
            'schedule': 300.0,  # Every 5 minutes
        },
        'trigger-monitoring-pipeline': {
            'task': 'src.tasks.scheduler.trigger_monitoring_pipeline',
            'schedule': settings.monitoring.ARTICLE_DISCOVERY_INTERVAL_SECONDS,
        },
        # Student Backup feature - task checks STUDENT_BACKUP_ENABLED internally
        'backup-tracked-students': {
            'task': 'src.tasks.student_backup.backup_all_tracked_students',
            'schedule': settings.student_backup.STUDENT_BACKUP_INTERVAL_MINUTES * 60,
        },
    }
    beat_scheduler = 'celery.beat:PersistentScheduler'


def create_celery_app() -> Celery:
    """
    Create and configure Celery application.

    Returns:
        Configured Celery application instance
    """
    # Create Celery app
    celery_app = Celery('yourMoment')

    # Load configuration
    celery_app.config_from_object(CeleryConfig)

    return celery_app


def import_task_modules():
    """Import task modules so Celery registers their tasks."""
    for module_path in TASK_MODULES:
        try:
            import_module(module_path)
        except Exception:  # pragma: no cover - surface via log for debugging
            logger.exception("Failed to import Celery task module %s", module_path)


# Create the Celery app instance
celery_app = create_celery_app()


@setup_logging.connect
def setup_celery_logging(loglevel=None, logfile=None, format=None, colorize=None, **kwargs):
    """Configure Celery logging to integrate with application logging."""
    # Get the root logger
    root_logger = logging.getLogger()

    # Set log level
    if loglevel:
        root_logger.setLevel(loglevel)
    else:
        root_logger.setLevel(logging.INFO)

    # Create formatter
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # File handler for Celery logs
    if logfile:
        file_handler = logging.FileHandler(logfile)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


@task_prerun.connect
def task_prerun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None, **kwds):
    """Log task start information."""
    logger.info(f"Starting task {task.name} [{task_id}] with args={args} kwargs={kwargs}")


@task_postrun.connect
def task_postrun_handler(sender=None, task_id=None, task=None, args=None, kwargs=None,
                        retval=None, state=None, **kwds):
    """Log task completion information."""
    logger.info(f"Completed task {task.name} [{task_id}] with state={state}")
    if state == 'FAILURE':
        logger.error(f"Task {task.name} [{task_id}] failed with return value: {retval}")


class BaseTask(celery_app.Task):
    """
    Base task class with common functionality.

    Provides:
    - Database session management
    - Error handling and logging
    - Retry logic
    """

    abstract = True
    max_retries = 3
    default_retry_delay = 60  # 1 minute

    def get_database_session(self):
        """
        Get database session for task execution.

        Note: This will be implemented when database integration is needed.
        For now, tasks should handle their own database connections.
        """
        # Import here to avoid circular imports
        from src.config.database import get_database_manager

        # Return async session maker for tasks to use
        db_manager = get_database_manager()
        return db_manager.get_async_sessionmaker()

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure."""
        logger.error(f"Task {self.name} [{task_id}] failed: {exc}")
        logger.error(f"Exception info: {einfo}")

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Handle task retry."""
        logger.warning(f"Task {self.name} [{task_id}] retry attempt {self.request.retries + 1}: {exc}")

    def on_success(self, retval, task_id, args, kwargs):
        """Handle task success."""
        logger.info(f"Task {self.name} [{task_id}] completed successfully")


# Set the base task class
celery_app.Task = BaseTask


# Import task modules after BaseTask is available so registrations succeed
import_task_modules()


def get_task_info() -> Dict[str, Any]:
    """
    Get information about registered tasks and queues.

    Returns:
        Dictionary with task and queue information
    """
    tasks = sorted(celery_app.tasks.keys())
    project_tasks = [task for task in tasks if task.startswith('src.tasks.')]
    builtin_tasks = [task for task in tasks if task not in project_tasks]

    return {
        'registered_tasks': tasks,
        'project_tasks': project_tasks,
        'builtin_tasks': builtin_tasks,
        'queues': [queue.name for queue in CeleryConfig.task_queues],
        'routes': CeleryConfig.task_routes,
        'beat_schedule': list(CeleryConfig.beat_schedule.keys()),
    }


def health_check() -> Dict[str, Any]:
    """
    Perform health check on Celery worker and queues.

    Returns detailed information about:
    - Broker connection status
    - Active workers count
    - Queue configurations
    - Active tasks per queue (if workers are available)

    Returns:
        Health status information dictionary
    """
    try:
        # Check if we can connect to broker
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        active_queues = inspect.active_queues()

        # Build queue status information
        queue_status = {}
        all_queues = [queue.name for queue in CeleryConfig.task_queues]

        for queue_name in all_queues:
            queue_info = {
                'configured': True,
                'workers_consuming': 0
            }

            # Count workers consuming from this queue
            if active_queues:
                for worker, queues in active_queues.items():
                    if any(q['name'] == queue_name for q in queues):
                        queue_info['workers_consuming'] += 1

            queue_status[queue_name] = queue_info

        return {
            'status': 'healthy',
            'broker_connection': 'ok',
            'workers': len(stats) if stats else 0,
            'queues': all_queues,
            'queue_details': queue_status,
            'pipeline_queues': [
                'discovery', 'preparation', 'generation', 'posting'
            ]
        }
    except Exception as e:
        logger.error(f"Celery health check failed: {e}")
        return {
            'status': 'unhealthy',
            'error': str(e),
            'broker_connection': 'failed',
        }


def clear_queue(queue_name: str = None) -> Dict[str, Any]:
    """
    Clear all tasks from specified queue(s).

    Args:
        queue_name: Name of queue to clear. If None, clears all queues.

    Returns:
        Dictionary with cleared queues and task counts
    """
    try:
        from kombu import Connection

        result = {}
        queues_to_clear = []

        if queue_name:
            # Clear specific queue
            queues_to_clear = [queue_name]
        else:
            # Clear all configured queues
            queues_to_clear = [queue.name for queue in CeleryConfig.task_queues]

        with Connection(celery_app.conf.broker_url) as conn:
            for queue in queues_to_clear:
                try:
                    # Purge the queue
                    purged = conn.default_channel.queue_purge(queue)
                    result[queue] = purged or 0
                    logger.info(f"Cleared {purged or 0} tasks from queue '{queue}'")
                except Exception as e:
                    logger.error(f"Failed to clear queue '{queue}': {e}")
                    result[queue] = f"error: {str(e)}"

        return {
            'status': 'success',
            'cleared_queues': result,
            'total_tasks_cleared': sum(v for v in result.values() if isinstance(v, int))
        }
    except Exception as e:
        logger.error(f"Failed to clear queues: {e}")
        return {
            'status': 'failed',
            'error': str(e)
        }


# CLI helper functions
def start_worker(loglevel='info', queues=None, concurrency=None):
    """
    Start Celery worker programmatically.

    Args:
        loglevel: Log level (debug, info, warning, error)
        queues: List of queues to consume from
        concurrency: Number of worker processes
    """
    argv = [
        'worker',
        f'--loglevel={loglevel}',
    ]

    if queues:
        argv.append(f'--queues={",".join(queues)}')

    if concurrency:
        argv.append(f'--concurrency={concurrency}')

    celery_app.worker_main(argv)


def start_beat(loglevel='info'):
    """
    Start Celery beat scheduler programmatically.

    Args:
        loglevel: Log level (debug, info, warning, error)
    """
    argv = [
        'beat',
        f'--loglevel={loglevel}',
    ]

    celery_app.start(argv)


if __name__ == '__main__':
    # Start worker when running directly
    celery_app.start()
