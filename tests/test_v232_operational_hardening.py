"""
AutoBot v2.3.2 Operational Hardening Tests.
Verifies:
1. Multi-process database-backed scheduler lease acquisition & mutual exclusion.
2. Crash recovery & lease reclamation upon TTL expiration.
3. Safe release protection (ownership token required for release).
4. DiscoveryScheduler multi-worker coordination and skipping leased boards.
5. Benchmark integrity verification against frozen SHA-256 baseline and tamper detection.
"""

import asyncio
from datetime import datetime, timedelta
import json
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.discovery.models import JobSourceConfig, SourceType
from src.discovery.registry import FetchSourceResult
from src.discovery.scheduler import DiscoveryScheduler
from src.matching.independent_benchmark import (
    BenchmarkIntegrityError,
    FROZEN_BENCHMARK_SHA256,
    IndependentBenchmarkSuite,
    verify_benchmark_integrity,
)
from src.storage.db import (
    acquire_scheduler_lease,
    get_db_connection,
    get_scheduler_lease,
    init_db,
    release_scheduler_lease,
    renew_scheduler_lease,
)


@pytest.fixture
def temp_test_db():
    """Create an isolated test database with fresh schema migrations."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        os.remove(db_path)


def test_scheduler_lease_mutual_exclusion(temp_test_db):
    """Verify two independent worker processes cannot hold the same board lease simultaneously."""
    res_key = "lever:figma"
    token_a = f"worker-A:{uuid.uuid4().hex}"
    token_b = f"worker-B:{uuid.uuid4().hex}"

    # Worker A acquires lease
    acquired_a = acquire_scheduler_lease(res_key, token_a, ttl_seconds=30, db_path=temp_test_db)
    assert acquired_a is True

    # Worker B attempts to acquire same lease -> must fail
    acquired_b = acquire_scheduler_lease(res_key, token_b, ttl_seconds=30, db_path=temp_test_db)
    assert acquired_b is False

    # Worker A renews lease -> succeeds
    renewed = renew_scheduler_lease(res_key, token_a, ttl_seconds=60, db_path=temp_test_db)
    assert renewed is True

    # Worker B attempts to renew Worker A's lease -> must fail
    renew_b = renew_scheduler_lease(res_key, token_b, ttl_seconds=60, db_path=temp_test_db)
    assert renew_b is False

    # Worker B attempts to release Worker A's lease -> must fail (safe release)
    released_b = release_scheduler_lease(res_key, token_b, db_path=temp_test_db)
    assert released_b is False

    # Verify Worker A still owns lease
    lease = get_scheduler_lease(res_key, db_path=temp_test_db)
    assert lease is not None
    assert lease["owner_token"] == token_a

    # Worker A releases lease -> succeeds
    released_a = release_scheduler_lease(res_key, token_a, db_path=temp_test_db)
    assert released_a is True

    # Worker B can now acquire lease
    acquired_b2 = acquire_scheduler_lease(res_key, token_b, ttl_seconds=30, db_path=temp_test_db)
    assert acquired_b2 is True


def test_scheduler_lease_crash_recovery_on_expiration(temp_test_db):
    """Verify an expired lease is automatically reclaimed when the previous worker crashed."""
    res_key = "greenhouse:stripe"
    crashed_token = f"worker-crashed:{uuid.uuid4().hex}"
    survivor_token = f"worker-survivor:{uuid.uuid4().hex}"

    # Simulate crashed worker acquiring a lease that expired 10 seconds ago
    past_acquired = (datetime.now() - timedelta(seconds=20)).isoformat()
    past_expired = (datetime.now() - timedelta(seconds=10)).isoformat()

    with get_db_connection(temp_test_db) as conn:
        conn.execute(
            """
            INSERT INTO scheduler_leases (resource_key, owner_token, acquired_at, expires_at, last_heartbeat_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (res_key, crashed_token, past_acquired, past_expired, past_acquired),
        )
        conn.commit()

    # Survivor worker attempts acquisition -> should detect crash/expiration and succeed
    acquired_survivor = acquire_scheduler_lease(res_key, survivor_token, ttl_seconds=60, db_path=temp_test_db)
    assert acquired_survivor is True

    # Verify ownership was transferred to survivor
    lease = get_scheduler_lease(res_key, db_path=temp_test_db)
    assert lease is not None
    assert lease["owner_token"] == survivor_token


@pytest.mark.asyncio
async def test_discovery_scheduler_multi_worker_board_coordination(temp_test_db):
    """Verify DiscoveryScheduler skips boards currently leased by another independent worker process."""
    sched1 = DiscoveryScheduler(db_path=temp_test_db, worker_id="worker-proc-1")
    sched2 = DiscoveryScheduler(db_path=temp_test_db, worker_id="worker-proc-2")

    source = sched1.registry.add_board(
        name="Linear",
        source_type="ashby",
        board_slug="linear",
        refresh_interval=300,
    )

    res_key = f"{source.source_type.value}:{source.board_token_or_slug}"

    # Worker 1 acquires distributed lease
    token1 = sched1.acquire_lease(res_key, ttl_seconds=60)
    assert token1 is not None

    # Worker 2 attempts to sync this board -> must return None without executing
    mock_session = AsyncMock()
    result_worker2 = await sched2.sync_board(source, mock_session, force=True)
    assert result_worker2 is None
    # Underlying HTTP network call should not have been made by Worker 2
    mock_session.get.assert_not_called()

    # Worker 1 finishes and releases lease
    released = sched1.release_lease(res_key, token1)
    assert released is True

    # Worker 2 can now sync board
    with patch.object(sched2.engine, "_fetch_single_source", return_value=FetchSourceResult(source, [], None, is_complete=True)):
        result_worker2_after = await sched2.sync_board(source, mock_session, force=True)
        assert result_worker2_after is not None
        assert result_worker2_after.is_complete is True


def test_frozen_benchmark_integrity_verification():
    """Verify independent benchmark evaluation dataset matches frozen SHA-256 manifest."""
    # Official baseline verification
    is_valid = verify_benchmark_integrity()
    assert is_valid is True

    # Check that IndependentBenchmarkSuite initializes successfully
    suite = IndependentBenchmarkSuite()
    assert len(suite.dataset) == 80


def test_frozen_benchmark_tamper_detection(tmp_path):
    """Verify tampering with evaluation dataset raises BenchmarkIntegrityError."""
    tampered_file = tmp_path / "tampered_dataset.json"
    with open(tampered_file, "w") as f:
        json.dump([{"pair_id": "fake", "ground_truth": {}}], f)

    # Calling verify_benchmark_integrity on tampered file must fail
    with pytest.raises(BenchmarkIntegrityError, match="Benchmark integrity violation! Checksum mismatch"):
        verify_benchmark_integrity(str(tampered_file))

    # Initializing suite with tampered dataset must fail
    with pytest.raises(BenchmarkIntegrityError):
        IndependentBenchmarkSuite(dataset_path=str(tampered_file))
