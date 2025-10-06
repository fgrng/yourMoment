"""
Base model class for yourMoment application.

Provides common functionality and SQLAlchemy declarative base for all models.
"""

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import DeclarativeBase

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
