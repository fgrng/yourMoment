"""Pure unit tests for API helper exports."""

import src.api.utils as api_utils


def test_api_utils_only_exposes_development_only_helper() -> None:
    """Dead environment and URL helper wrappers should stay removed."""
    assert hasattr(api_utils, "development_only")

    for helper_name in (
        "get_environment",
        "is_development",
        "is_production",
        "get_base_url",
        "build_absolute_url",
        "build_redirect_url",
    ):
        assert not hasattr(api_utils, helper_name)
