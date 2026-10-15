"""Displaying a target: the dimension labels of the static description with the stored raw values."""

from __future__ import annotations

import pytest

from src.platforms import TargetDimension, TargetEntry, label_target
from tests.support.platform import FakePlatform


pytestmark = [pytest.mark.unit]


@pytest.fixture
def platform() -> FakePlatform:
    platform = FakePlatform()
    platform.target_description = (
        TargetDimension(key="category", label="Kategorie"),
        TargetDimension(key="classroom", label="Klasse", required=True),
    )
    return platform


def test_set_dimensions_are_labelled_in_description_order(platform):
    assert label_target(platform, {"classroom": "4711", "category": "7"}) == (
        TargetEntry(key="category", label="Kategorie", value="7"),
        TargetEntry(key="classroom", label="Klasse", value="4711"),
    )


def test_unset_optional_dimension_is_left_out(platform):
    assert label_target(platform, {"classroom": "4711"}) == (
        TargetEntry(key="classroom", label="Klasse", value="4711"),
    )


def test_unknown_key_is_shown_with_its_raw_key(platform):
    assert label_target(platform, {"classroom": "4711", "site": "blog"}) == (
        TargetEntry(key="classroom", label="Klasse", value="4711"),
        TargetEntry(key="site", label="site", value="blog"),
    )


def test_labelling_needs_no_connection(platform):
    label_target(platform, {"classroom": "4711"})

    assert platform.connected_accounts == []
