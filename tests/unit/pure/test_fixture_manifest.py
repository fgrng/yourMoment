"""
Manifest integrity tests.

These tests verify that manifest.json is internally consistent and that
every file it references actually exists on disk.  They run as pure unit
tests — no DB, no network.
"""

import pytest

from tests.fixtures.loaders import load_manifest, _HTML_DIR

REQUIRED_FIXTURE_FIELDS = {"file", "source_type", "covers"}
NORMALISED_FIXTURE_FIELDS = {
    "covered_parser_methods",
    "required_assertions",
    "known_omitted_fields",
}


@pytest.fixture(scope="module")
def manifest():
    return load_manifest()


class TestManifestStructure:
    def test_top_level_keys_present(self, manifest):
        for key in ("captured_at", "last_schema_review", "source_policy", "fixtures", "sanitization"):
            assert key in manifest, f"Missing top-level key: {key!r}"

    def test_fixtures_is_non_empty_list(self, manifest):
        assert isinstance(manifest["fixtures"], list)
        assert len(manifest["fixtures"]) > 0

    def test_every_fixture_has_required_fields(self, manifest):
        for entry in manifest["fixtures"]:
            missing = REQUIRED_FIXTURE_FIELDS - entry.keys()
            assert not missing, (
                f"Fixture {entry.get('file', '?')!r} missing fields: {missing}"
            )

    def test_every_fixture_has_normalised_fields(self, manifest):
        """All fixtures should carry the full normalised metadata schema."""
        for entry in manifest["fixtures"]:
            missing = NORMALISED_FIXTURE_FIELDS - entry.keys()
            assert not missing, (
                f"Fixture {entry.get('file', '?')!r} missing normalised fields: {missing}"
            )

    def test_normalised_list_fields_are_lists(self, manifest):
        list_fields = ("covers", "covered_parser_methods", "required_assertions", "known_omitted_fields")
        for entry in manifest["fixtures"]:
            for field in list_fields:
                if field in entry:
                    assert isinstance(entry[field], list), (
                        f"Fixture {entry.get('file', '?')!r}: {field!r} should be a list"
                    )


class TestManifestFileIntegrity:
    def test_every_referenced_file_exists(self, manifest):
        """The manifest must not reference files that do not exist on disk."""
        missing = []
        for entry in manifest["fixtures"]:
            filename = entry["file"]
            if not (_HTML_DIR / filename).is_file():
                missing.append(filename)
        assert not missing, f"Manifest references missing files: {missing}"

    def test_no_duplicate_file_entries(self, manifest):
        files = [entry["file"] for entry in manifest["fixtures"]]
        seen = set()
        duplicates = []
        for f in files:
            if f in seen:
                duplicates.append(f)
            seen.add(f)
        assert not duplicates, f"Manifest has duplicate entries: {duplicates}"

    def test_all_html_files_on_disk_are_listed(self, manifest):
        """Every .html file under myMoment_html/ should appear in the manifest."""
        listed = {entry["file"] for entry in manifest["fixtures"]}
        on_disk = {p.name for p in _HTML_DIR.glob("*.html")}
        unlisted = on_disk - listed
        assert not unlisted, (
            f"HTML files on disk not in manifest: {unlisted}. "
            "Add them to manifest.json or remove them from the fixture directory."
        )
