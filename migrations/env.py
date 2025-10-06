"""
Alembic migration environment configuration for yourMoment application.
"""

import asyncio
from logging.config import fileConfig
import os

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import the declarative base and all models
from src.models import Base
from src.config.database import get_database_manager

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_database_url():
    """Get database URL from environment or configuration."""
    # Try to get from DB_SQLITE_FILE environment variable (new approach)
    db_sqlite_file = os.getenv("DB_SQLITE_FILE")
    if db_sqlite_file:
        # Ensure absolute path
        if not os.path.isabs(db_sqlite_file):
            db_sqlite_file = os.path.abspath(db_sqlite_file)
        # Return sync SQLite URL for Alembic
        return f"sqlite:///{db_sqlite_file}"

    # Legacy: Try DATABASE_URL for backward compatibility
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        # Convert async URL to sync URL for Alembic
        if database_url.startswith("postgresql+asyncpg://"):
            database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
        elif database_url.startswith("mysql+aiomysql://"):
            database_url = database_url.replace("mysql+aiomysql://", "mysql://")
        elif database_url.startswith("sqlite+aiosqlite:///"):
            database_url = database_url.replace("sqlite+aiosqlite:///", "sqlite:///")
        return database_url

    # Fallback to alembic.ini configuration
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with database connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in async mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    # Always use sync engine for migrations
    from sqlalchemy import create_engine

    database_url = get_database_url()

    connectable = create_engine(
        database_url,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()