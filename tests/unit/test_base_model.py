"""Unit tests for BaseModel utility behavior."""

from sqlalchemy import Column, Integer, String

from src.models.base import BaseModel


class DummyModel(BaseModel):
    """Simple BaseModel subclass for testing to_dict."""

    __tablename__ = "dummy_model"

    id = Column(Integer, primary_key=True)
    name = Column(String(50))


class TestBaseModel:
    """Tests for BaseModel helper methods."""

    def test_to_dict_returns_column_values(self):
        instance = DummyModel(id=1, name="example")

        result = instance.to_dict()

        assert result == {"id": 1, "name": "example"}
