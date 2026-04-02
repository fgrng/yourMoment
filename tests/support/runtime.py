"""
Singleton reset helpers for test isolation.

Call reset_all_singletons() before and after each test to ensure that
cached Settings, DatabaseManager, and EncryptionManager instances don't
leak state between tests.

Usage in conftest.py:
    @pytest.fixture(autouse=True)
    def _reset_singletons():
        reset_all_singletons()
        yield
        reset_all_singletons()
"""


def reset_all_singletons() -> None:
    """
    Null out all module-level singleton globals so the next access
    re-reads from the current environment.

    Deliberately avoids awaiting async cleanup (close_database) because
    this function is called from sync fixtures.  Tests that hold a live
    database engine must tear it down through their own async fixture
    (db_engine in tests/support/database.py).
    """
    import src.config.settings as _settings_mod
    import src.config.database as _database_mod
    import src.config.encryption as _encryption_mod

    _settings_mod._settings = None
    _encryption_mod._encryption_manager = None
    _database_mod._database_manager = None
