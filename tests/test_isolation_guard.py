"""
Test for Hard Database Isolation Guard.
Verifies that pytest cannot access logs/autobot.db under any circumstances.
"""

import pytest
from src.storage.db import get_db_connection, DEFAULT_DB_PATH


def test_hard_guard_blocks_production_database_access():
    """Verify that attempting to open logs/autobot.db in pytest raises RuntimeError."""
    with pytest.raises(RuntimeError) as exc_info:
        get_db_connection("logs/autobot.db")
    
    assert "CRITICAL HARD GUARD" in str(exc_info.value)
    assert "logs/autobot.db" in str(exc_info.value)
