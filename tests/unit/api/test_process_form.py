"""The monitoring process form builds the fields of the target from the platform's target description."""

from __future__ import annotations

import os
import uuid

import pytest
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from src.api.auth import get_current_web_user
from src.api.web import router as web_router
from src.platforms import TargetDimension


pytestmark = [pytest.mark.unit]

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "static")


@pytest.fixture
def client(fake_platform) -> TestClient:
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(web_router)
    app.dependency_overrides[get_current_web_user] = lambda: object()
    return TestClient(app)


def _target_fields(html: str) -> list[str]:
    """The labels of the fields under "Ziel des Prozesses", as the user reads them."""
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find(lambda tag: tag.name == "label" and "Ziel des Prozesses" in tag.get_text())
    block = heading.parent
    return [
        block.find("label", attrs={"for": select["id"]}).get_text(" ", strip=True)
        for select in block.find_all("select")
    ]


@pytest.fixture
def wordpress_like(fake_platform):
    fake_platform.target_description = (
        TargetDimension(key="site_category", label="Rubrik", required=True),
        TargetDimension(key="tag", label="Schlagwort"),
    )
    return fake_platform


@pytest.mark.parametrize("path", ["/processes/new", f"/processes/{uuid.uuid4()}/edit"], ids=["new", "edit"])
def test_form_offers_one_labelled_field_per_dimension_of_the_target_description(client, wordpress_like, path):
    html = client.get(path).text

    assert _target_fields(html) == ["Rubrik *", "Schlagwort"]
