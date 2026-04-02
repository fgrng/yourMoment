"""
Loader API tests.

Verify that the three public loader functions work correctly and that
they fail with a clear, narrow exception on bad input.
"""

import json

import pytest

from tests.fixtures.loaders import (
    FixtureNotFoundError,
    load_html_fixture,
    load_json_fixture,
    load_manifest,
)


class TestLoadHtmlFixture:
    def test_loads_by_bare_name(self):
        html = load_html_fixture("accounts_login")
        assert html.strip().startswith("<")
        assert len(html) > 100

    def test_loads_by_name_with_extension(self):
        html = load_html_fixture("accounts_login.html")
        assert "<!DOCTYPE" in html or "<html" in html or "<form" in html

    def test_all_manifest_fixtures_are_loadable(self):
        from tests.fixtures.loaders import load_manifest
        manifest = load_manifest()
        for entry in manifest["fixtures"]:
            name = entry["file"]
            html = load_html_fixture(name)
            assert len(html) > 0, f"Fixture {name!r} loaded empty"

    def test_missing_name_raises_fixture_not_found_error(self):
        with pytest.raises(FixtureNotFoundError) as exc_info:
            load_html_fixture("does_not_exist")
        assert "does_not_exist" in str(exc_info.value)

    def test_error_message_lists_available_fixtures(self):
        with pytest.raises(FixtureNotFoundError) as exc_info:
            load_html_fixture("no_such_page")
        assert "accounts_login.html" in str(exc_info.value)

    def test_fixture_not_found_is_subclass_of_file_not_found_error(self):
        with pytest.raises(FileNotFoundError):
            load_html_fixture("nonexistent")


class TestLoadJsonFixture:
    def test_loads_manifest_by_bare_name(self):
        data = load_json_fixture("manifest")
        assert isinstance(data, dict)
        assert "fixtures" in data

    def test_loads_manifest_with_extension(self):
        data = load_json_fixture("manifest.json")
        assert isinstance(data, dict)

    def test_returns_dict(self):
        data = load_json_fixture("manifest")
        assert isinstance(data, dict)

    def test_missing_name_raises_fixture_not_found_error(self):
        with pytest.raises(FixtureNotFoundError) as exc_info:
            load_json_fixture("no_such_json_file")
        assert "no_such_json_file" in str(exc_info.value)

    def test_fixture_not_found_is_subclass_of_file_not_found_error(self):
        with pytest.raises(FileNotFoundError):
            load_json_fixture("missing")


class TestLoadManifest:
    def test_returns_dict(self):
        manifest = load_manifest()
        assert isinstance(manifest, dict)

    def test_has_fixtures_list(self):
        manifest = load_manifest()
        assert "fixtures" in manifest
        assert isinstance(manifest["fixtures"], list)

    def test_consistent_with_load_json_fixture(self):
        from_loader = load_manifest()
        from_json = load_json_fixture("manifest")
        assert from_loader == from_json

    def test_each_fixture_entry_has_file_key(self):
        manifest = load_manifest()
        for entry in manifest["fixtures"]:
            assert "file" in entry
