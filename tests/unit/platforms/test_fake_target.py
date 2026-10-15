"""The fake adapter's target description is configurable, so tests can use other platforms' dimensions."""

from __future__ import annotations

import pytest

from src.platforms import InvalidTarget, TargetDimension, validate_target
from tests.support.platform import FakePlatform


pytestmark = [pytest.mark.unit]


@pytest.fixture
def wordpress_like() -> FakePlatform:
    platform = FakePlatform()
    platform.target_description = (TargetDimension(key="site_category", label="Kategorie", required=True),)
    return platform


def test_configured_description_is_what_the_fake_describes(wordpress_like):
    assert [(d.key, d.required) for d in wordpress_like.describe_target()] == [("site_category", True)]


def test_target_matching_the_configured_description_is_accepted(wordpress_like):
    assert validate_target(wordpress_like, {"site_category": "news"}) == {"site_category": "news"}


def test_key_of_the_default_description_is_unknown_to_a_configured_one(wordpress_like):
    with pytest.raises(InvalidTarget, match="classroom"):
        validate_target(wordpress_like, {"site_category": "news", "classroom": "82"})


def test_configured_rule_rejects_a_target_matching_the_description():
    platform = FakePlatform()

    def no_home(target):
        if target.get("classroom") == "home":
            raise InvalidTarget("home is not allowed")

    platform.target_rules.append(no_home)

    with pytest.raises(InvalidTarget, match="home"):
        validate_target(platform, {"classroom": "home"})
