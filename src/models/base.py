"""
Base model class for yourMoment application.

Provides common functionality and SQLAlchemy declarative base for all models.
"""

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.types import TypeDecorator

# SQLAlchemy declarative base for all models
Base = declarative_base()


class BaseModel(Base):
    """
    Abstract base model providing common functionality.

    This class provides common methods and attributes that all models can inherit.
    It's abstract and won't create a table itself.
    """

    __abstract__ = True

    def to_dict(self):
        """
        Convert model instance to dictionary.

        Returns:
            Dictionary representation of the model

        Note:
            This is a basic implementation. Models should override this
            method to customize the output and handle sensitive data.
        """
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }


class UTCDateTime(TypeDecorator):
    """
    DateTime column that only accepts and returns aware UTC datetimes.

    Naive values are rejected on write; aware values are converted to UTC.
    SQLite drops the offset, so the stored text is unchanged; naive values
    read back are UTC and get `tzinfo=UTC`.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect: Dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"UTCDateTime requires an aware datetime, got naive {value!r}")
        return value.astimezone(UTC)

    def process_result_value(self, value: Optional[datetime], dialect: Dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
