#!/usr/bin/env python3
"""
yourMoment CLI - Production-ready management interface

Usage:
    python cli.py server                    # Start web server
    python cli.py worker                    # Start Celery worker
    python cli.py scheduler                 # Start Celery beat scheduler
    python cli.py db migrate                # Run database migrations
    python cli.py db seed                   # Seed database with test data
    python cli.py db reset                  # Reset and seed database
    python cli.py db stats                  # Show database statistics
    python cli.py user create               # Create a new user interactively
    python cli.py celery info               # Show Celery configuration
    python cli.py celery health             # Check Celery health
    python cli.py celery clear [queue]      # Clear Celery queue(s)
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure .env is loaded before any imports
from dotenv import load_dotenv
load_dotenv()

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# SERVER COMMANDS
# ============================================================================

def cmd_server(args: argparse.Namespace) -> None:
    """Start the web server."""
    import uvicorn

    logger.info("Starting yourMoment web server...")

    # Determine environment
    env = os.getenv("ENVIRONMENT", "development")
    is_production = env == "production"

    # Production server configuration
    if is_production:
        logger.info("Running in PRODUCTION mode")
        uvicorn.run(
            "src.main:app",
            host=args.host,
            port=args.port,
            workers=args.workers,
            log_level=args.loglevel,
            access_log=True,
            proxy_headers=True,
            forwarded_allow_ips="*",
        )
    # Development server configuration
    else:
        logger.info("Running in DEVELOPMENT mode")
        logger.info(f"Web Interface: http://{args.host}:{args.port}")
        logger.info(f"API Docs: http://{args.host}:{args.port}/api/v1/docs")
        uvicorn.run(
            "src.main:app",
            host=args.host,
            port=args.port,
            reload=True,
            log_level=args.loglevel,
        )


# ============================================================================
# WORKER COMMANDS
# ============================================================================

def cmd_worker(args: argparse.Namespace) -> None:
    """Start Celery worker."""
    from src.tasks.worker import start_worker

    logger.info(f"Starting Celery worker (concurrency={args.concurrency})")
    if args.queues:
        logger.info(f"Consuming queues: {', '.join(args.queues)}")

    start_worker(
        loglevel=args.loglevel,
        queues=args.queues,
        concurrency=args.concurrency,
    )


def cmd_scheduler(args: argparse.Namespace) -> None:
    """Start Celery beat scheduler."""
    from src.tasks.worker import start_beat

    logger.info("Starting Celery beat scheduler")
    start_beat(loglevel=args.loglevel)


# ============================================================================
# DATABASE COMMANDS
# ============================================================================

async def cmd_db_migrate(args: argparse.Namespace) -> None:
    """Run database migrations."""
    import subprocess

    logger.info("Running database migrations...")

    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            check=True,
            capture_output=True,
            text=True
        )
        print(result.stdout)
        logger.info("✓ Migrations completed successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"Migration failed: {e.stderr}")
        sys.exit(1)


async def cmd_db_seed(args: argparse.Namespace) -> None:
    """Seed database with essential data (system templates and optionally a test user)."""
    from datetime import datetime
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.config.database import get_database_manager
    from src.config.settings import get_settings
    from src.models.user import User
    from src.models.prompt_template import PromptTemplate

    settings = get_settings()
    is_production = settings.is_production

    if is_production and not args.force:
        logger.warning("⚠️  Production environment detected!")
        logger.warning("This command will only create system prompt templates.")
        logger.warning("Use 'python cli.py user create' to create users securely.")
        logger.warning("Use --force to proceed anyway.")
        response = input("\nContinue with seeding system templates? (yes/no): ")
        if response.lower() != "yes":
            logger.info("Aborted")
            return

    logger.info("Seeding database with essential data...")

    db_manager = get_database_manager()
    engine = await db_manager.create_engine()

    async with AsyncSession(engine) as session:
        try:
            # Always create system prompt templates
            result = await session.execute(
                select(PromptTemplate).where(PromptTemplate.category == "SYSTEM")
            )
            templates = result.scalars().all()

            if not templates:
                system_prompts = [
                    {
                        "name": "Constructive Feedback",
                        "description": "Provides thoughtful, constructive feedback on articles",
                        "system_prompt": "Du bist ein hilfreicher Kommentator, der konstruktives Feedback zu Artikeln gibt. Sei respektvoll, nachdenklich und biete wertvolle Einsichten.",
                        "user_prompt_template": "Bitte lies diesen Artikel '{article_title}' von {article_author} und gib konstruktives Feedback. Artikelinhalt: {article_content}",
                    },
                    {
                        "name": "Question Generator",
                        "description": "Generates thoughtful questions about the article content",
                        "system_prompt": "Du bist ein neugieriger Leser, der durchdachte Fragen zu Artikeln stellt, um Diskussionen anzuregen.",
                        "user_prompt_template": "Nach dem Lesen dieses Artikels '{article_title}' von {article_author}, welche interessanten Fragen würdest du stellen? Artikel: {article_content}",
                    },
                    {
                        "name": "Summary and Analysis",
                        "description": "Provides summaries and key insights from articles",
                        "system_prompt": "Du bist ein analytischer Leser, der prägnante Zusammenfassungen und wichtige Erkenntnisse aus Artikeln extrahiert.",
                        "user_prompt_template": "Fasse diesen Artikel '{article_title}' von {article_author} zusammen und hebe die wichtigsten Punkte hervor. Artikel: {article_content}",
                    },
                    {
                        "name": "Supportive Response",
                        "description": "Provides encouraging and supportive responses",
                        "system_prompt": "Du bist ein unterstützender Kommentator, der ermutigende und positive Antworten auf Artikel gibt.",
                        "user_prompt_template": "Schreibe eine unterstützende Antwort auf diesen Artikel '{article_title}' von {article_author}. Zeige Verständnis und Ermutigung. Artikel: {article_content}",
                    },
                ]

                for prompt_data in system_prompts:
                    template = PromptTemplate(
                        name=prompt_data["name"],
                        description=prompt_data["description"],
                        system_prompt=prompt_data["system_prompt"],
                        user_prompt_template=prompt_data["user_prompt_template"],
                        category="SYSTEM",
                        user_id=None,
                        is_active=True,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                    session.add(template)

                await session.flush()
                logger.info(f"✓ Created {len(system_prompts)} system prompt templates")
            else:
                logger.info(f"✓ System prompt templates already exist ({len(templates)} templates)")

            # Only create test user in development or if explicitly forced
            if not is_production or args.force:
                result = await session.execute(
                    select(User).where(User.email == "test@yourmoment.dev")
                )
                user = result.scalar_one_or_none()

                if not user:
                    import bcrypt
                    password_hash = bcrypt.hashpw(
                        "Valid!Password123".encode('utf-8'),
                        bcrypt.gensalt()
                    ).decode('utf-8')

                    user = User(
                        email="test@yourmoment.dev",
                        password_hash=password_hash,
                        is_active=True,
                        is_verified=True,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                    session.add(user)
                    await session.flush()
                    logger.warning("⚠️  Created DEVELOPMENT test user: test@yourmoment.dev")
                    logger.warning("⚠️  Password: Valid!Password123")
                    logger.warning("⚠️  DO NOT use this in production!")
                else:
                    logger.info("✓ Test user already exists")

            await session.commit()

            logger.info("✓ Database seeding completed successfully")

            if is_production:
                logger.info("")
                logger.info("For production user creation, use:")
                logger.info("  python cli.py user create")

        except Exception as e:
            await session.rollback()
            logger.error(f"Seeding failed: {e}", exc_info=True)
            raise
        finally:
            await db_manager.close()


async def cmd_db_reset(args: argparse.Namespace) -> None:
    """Reset and recreate database."""
    from src.config.database import get_database_manager
    from src.models.base import Base

    if not args.force:
        response = input("⚠ This will delete ALL data. Continue? (yes/no): ")
        if response.lower() != "yes":
            logger.info("Aborted")
            return

    logger.info("Resetting database...")

    db_manager = get_database_manager()
    engine = await db_manager.create_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    await db_manager.close()
    logger.info("✓ Database reset completed")

    # Now seed with fresh data (create new args without force flag for safety)
    import argparse
    seed_args = argparse.Namespace(force=False)
    await cmd_db_seed(seed_args)


async def cmd_db_stats(args: argparse.Namespace) -> None:
    """Show database statistics."""
    from sqlalchemy import select, func
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.config.database import get_database_manager
    from src.models.user import User
    from src.models.mymoment_login import MyMomentLogin
    from src.models.ai_comment import AIComment
    from src.models.monitoring_process import MonitoringProcess
    from src.models.prompt_template import PromptTemplate

    db_manager = get_database_manager()
    engine = await db_manager.create_engine()

    async with AsyncSession(engine) as session:
        # Get counts
        user_count = (await session.execute(select(func.count(User.id)))).scalar()
        login_count = (await session.execute(select(func.count(MyMomentLogin.id)))).scalar()
        comment_count = (await session.execute(select(func.count(AIComment.id)))).scalar()
        process_count = (await session.execute(select(func.count(MonitoringProcess.id)))).scalar()
        template_count = (await session.execute(select(func.count(PromptTemplate.id)))).scalar()

        # Get comment status breakdown
        result = await session.execute(
            select(AIComment.status, func.count(AIComment.id))
            .group_by(AIComment.status)
        )
        status_counts = {row[0]: row[1] for row in result.all()}

        print("\n📊 Database Statistics:")
        print(f"   Users: {user_count}")
        print(f"   MyMoment Logins: {login_count}")
        print(f"   AI Comments: {comment_count}")
        for status, count in status_counts.items():
            print(f"     - {status}: {count}")
        print(f"   Monitoring Processes: {process_count}")
        print(f"   Prompt Templates: {template_count}")
        print()

    await db_manager.close()


# ============================================================================
# USER COMMANDS
# ============================================================================

async def cmd_user_create(args: argparse.Namespace) -> None:
    """Create a new user interactively."""
    import bcrypt
    from datetime import datetime
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.config.database import get_database_manager
    from src.models.user import User

    logger.info("Creating a new user...")

    # Get user input
    email = input("Email: ")
    password = input("Password: ")
    is_verified = input("Mark as verified? (Y/n): ").lower() != 'n'

    # Validate email
    from pydantic import BaseModel, EmailStr
    class EmailDummy(BaseModel):
        email: EmailStr

    # Use EmailDummy class with pedantic validator
    try:
        EmailDummy(email = email)
        email_validated = True
    except ValueError:
        email_validated = False

    if not email_validated:
        logger.error("Invalid email format")
        return

    # Hash password
    password_hash = bcrypt.hashpw(
        password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    # Create user
    db_manager = get_database_manager()
    engine = await db_manager.create_engine()

    async with AsyncSession(engine) as session:
        try:
            user = User(
                email=email,
                password_hash=password_hash,
                is_active=True,
                is_verified=is_verified,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

            session.add(user)
            await session.commit()

            logger.info(f"✓ Created user: {email}")

        except Exception as e:
            await session.rollback()
            logger.error(f"Error creating user: {e}")
        finally:
            await db_manager.close()


# ============================================================================
# CELERY COMMANDS
# ============================================================================

def cmd_celery_info(args: argparse.Namespace) -> None:
    """Show Celery configuration."""
    from src.tasks.worker import get_task_info

    info = get_task_info()

    print("\n=== Celery Configuration ===")
    print(f"Project tasks: {len(info['project_tasks'])}")
    for task in info['project_tasks']:
        print(f"  - {task}")

    print(f"\nQueues: {len(info['queues'])}")
    for queue in info['queues']:
        print(f"  - {queue}")

    print(f"\nBeat schedule: {len(info['beat_schedule'])}")
    for schedule in info['beat_schedule']:
        print(f"  - {schedule}")

    print()


def cmd_celery_health(args: argparse.Namespace) -> None:
    """Check Celery health."""
    from src.tasks.worker import health_check

    health = health_check()

    print(f"\n=== Celery Health Check ===")
    print(f"Status: {health['status']}")
    print(f"Broker connection: {health.get('broker_connection', 'unknown')}")

    if health['status'] == 'healthy':
        print(f"Active workers: {health.get('workers', 0)}")
        print(f"Available queues: {len(health.get('queues', []))}")
        for queue in health.get('queues', []):
            print(f"  - {queue}")
    else:
        print(f"Error: {health.get('error', 'Unknown error')}")

    print()


def cmd_celery_clear(args: argparse.Namespace) -> None:
    """Clear Celery queue(s)."""
    from src.tasks.worker import clear_queue

    if args.queue:
        logger.info(f"Clearing queue: {args.queue}")
    else:
        logger.info("Clearing all queues")

    result = clear_queue(args.queue)

    print(f"\n=== Queue Clear Result ===")
    print(f"Status: {result['status']}")

    if result['status'] == 'success':
        print(f"Total tasks cleared: {result['total_tasks_cleared']}")
        print("\nCleared queues:")
        for queue, count in result['cleared_queues'].items():
            if isinstance(count, int):
                print(f"  - {queue}: {count} tasks")
            else:
                print(f"  - {queue}: {count}")
    else:
        print(f"Error: {result.get('error', 'Unknown error')}")

    print()


# ============================================================================
# MAIN CLI
# ============================================================================

def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='yourMoment Management CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Server command
    server_parser = subparsers.add_parser('server', help='Start web server')
    server_parser.add_argument('--host', default='0.0.0.0', help='Host to bind')
    server_parser.add_argument('--port', type=int, default=8000, help='Port to bind')
    server_parser.add_argument('--workers', type=int, default=4, help='Number of workers (production only)')
    server_parser.add_argument('--loglevel', default='info', choices=['debug', 'info', 'warning', 'error'])

    # Worker command
    worker_parser = subparsers.add_parser('worker', help='Start Celery worker')
    worker_parser.add_argument('--loglevel', default='info', choices=['debug', 'info', 'warning', 'error'])
    worker_parser.add_argument('--queues', nargs='+', help='Queues to consume')
    worker_parser.add_argument('--concurrency', type=int, default=4, help='Number of worker processes')

    # Scheduler command
    scheduler_parser = subparsers.add_parser('scheduler', help='Start Celery beat scheduler')
    scheduler_parser.add_argument('--loglevel', default='info', choices=['debug', 'info', 'warning', 'error'])

    # Database commands
    db_parser = subparsers.add_parser('db', help='Database management')
    db_subparsers = db_parser.add_subparsers(dest='db_command', help='Database commands')

    db_subparsers.add_parser('migrate', help='Run database migrations')

    db_seed_parser = db_subparsers.add_parser('seed', help='Seed database with essential data')
    db_seed_parser.add_argument('--force', action='store_true', help='Force creation of test user in production')

    db_reset_parser = db_subparsers.add_parser('reset', help='Reset and seed database')
    db_reset_parser.add_argument('--force', action='store_true', help='Skip confirmation')

    db_subparsers.add_parser('stats', help='Show database statistics')

    # User commands
    user_parser = subparsers.add_parser('user', help='User management')
    user_subparsers = user_parser.add_subparsers(dest='user_command', help='User commands')
    user_subparsers.add_parser('create', help='Create a new user')

    # Celery commands
    celery_parser = subparsers.add_parser('celery', help='Celery management')
    celery_subparsers = celery_parser.add_subparsers(dest='celery_command', help='Celery commands')

    celery_subparsers.add_parser('info', help='Show Celery configuration')
    celery_subparsers.add_parser('health', help='Check Celery health')

    celery_clear_parser = celery_subparsers.add_parser('clear', help='Clear queue(s)')
    celery_clear_parser.add_argument('--queue', help='Specific queue to clear')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    try:
        # Route to appropriate command
        if args.command == 'server':
            cmd_server(args)
        elif args.command == 'worker':
            cmd_worker(args)
        elif args.command == 'scheduler':
            cmd_scheduler(args)
        elif args.command == 'db':
            if not args.db_command:
                db_parser.print_help()
                return

            if args.db_command == 'migrate':
                asyncio.run(cmd_db_migrate(args))
            elif args.db_command == 'seed':
                asyncio.run(cmd_db_seed(args))
            elif args.db_command == 'reset':
                asyncio.run(cmd_db_reset(args))
            elif args.db_command == 'stats':
                asyncio.run(cmd_db_stats(args))
        elif args.command == 'user':
            if not args.user_command:
                user_parser.print_help()
                return

            if args.user_command == 'create':
                asyncio.run(cmd_user_create(args))
        elif args.command == 'celery':
            if not args.celery_command:
                celery_parser.print_help()
                return

            if args.celery_command == 'info':
                cmd_celery_info(args)
            elif args.celery_command == 'health':
                cmd_celery_health(args)
            elif args.celery_command == 'clear':
                cmd_celery_clear(args)
        else:
            parser.print_help()

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
