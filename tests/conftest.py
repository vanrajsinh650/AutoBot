"""
Global Pytest Configuration and Hard Isolation Guards for AutoBot v2.1.
Enforces that tests NEVER read or write to production logs/autobot.db.
"""

import os
from pathlib import Path
import pytest
import tempfile

from src.storage.db import DEFAULT_DB_PATH, init_db, get_db_connection


@pytest.fixture(autouse=True)
def isolated_test_database(tmp_path, monkeypatch):
    """
    Autouse fixture that runs before EVERY test.
    Forces all database operations in tests to target a fresh isolated SQLite DB in tmp_path.
    """
    test_db = tmp_path / "isolated_test.db"
    monkeypatch.setenv("AUTOBOT_DB_PATH", str(test_db))
    monkeypatch.setenv("AUTOBOT_DATA_DIR", str(tmp_path / "data"))
    try:
        import src.browser.proof_audit as _proof_audit
        monkeypatch.setattr(_proof_audit, "PROOF_DIR", tmp_path / "proofs")
    except Exception:
        pass
    
    # Initialize schema migrations on the temporary test database
    init_db(str(test_db))
    
    # Clear in-memory session caches and brute-force attempt trackers between tests
    try:
        from src.storage.auth import _ACTIVE_SESSIONS, reset_all_login_attempts
        _ACTIVE_SESSIONS.clear()
        reset_all_login_attempts()
    except Exception:
        pass

    yield str(test_db)

    # Teardown: clear in-memory caches
    try:
        from src.storage.auth import _ACTIVE_SESSIONS, reset_all_login_attempts
        _ACTIVE_SESSIONS.clear()
        reset_all_login_attempts()
    except Exception:
        pass
