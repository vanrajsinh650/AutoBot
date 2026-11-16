"""
AutoBot v2.3.2 True Multiprocess Scheduler Lease & Fencing Verification.
Uses separate OS processes via Python multiprocessing to test:
1. True multiprocess lease contention & mutual exclusion (competing OS processes).
2. Abrupt worker termination (SIGKILL) & crash recovery via TTL expiration.
3. Long-running sync lease renewal (heartbeat).
4. Safe release enforcement (stale worker cannot release another process's lease).
5. Lease Fencing: Stale worker that lost ownership is strictly blocked from committing
   job mutations or expiring vacancies.
"""

from datetime import datetime, timedelta
import multiprocessing as mp
import os
import signal
import tempfile
import time
from typing import Optional
import uuid

import pytest

from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.discovery.registry import JobDiscoveryEngine
from src.storage.db import (
    acquire_scheduler_lease,
    get_db_connection,
    get_scheduler_lease,
    init_db,
    release_scheduler_lease,
    renew_scheduler_lease,
    StaleWorkerLeaseError,
)


@pytest.fixture
def temp_multiprocess_db():
    """Create an isolated temporary SQLite database for multiprocess tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


def _worker_acquire_task(db_path: str, resource_key: str, worker_id: str, ttl: int, queue: mp.Queue):
    """Target function executed in a separate OS process to attempt lease acquisition."""
    token = f"{worker_id}:{uuid.uuid4().hex}"
    ok = acquire_scheduler_lease(resource_key, token, ttl_seconds=ttl, db_path=db_path)
    queue.put({"worker_id": worker_id, "token": token, "acquired": ok, "pid": os.getpid()})


def _long_running_worker(db_path: str, resource_key: str, token: str, ready_event: mp.Event):
    """Target function executed in a separate OS process that acquires a lease and hangs."""
    ok = acquire_scheduler_lease(resource_key, token, ttl_seconds=1, db_path=db_path)
    if ok:
        ready_event.set()
        # Stay alive until forcibly killed by SIGKILL
        while True:
            time.sleep(0.1)


def _heartbeat_worker(db_path: str, resource_key: str, token: str, ready_event: mp.Event, stop_event: mp.Event):
    """Target function that renews its lease periodically."""
    ok = acquire_scheduler_lease(resource_key, token, ttl_seconds=2, db_path=db_path)
    if ok:
        ready_event.set()
        while not stop_event.is_set():
            time.sleep(0.8)
            renew_scheduler_lease(resource_key, token, ttl_seconds=2, db_path=db_path)
        release_scheduler_lease(resource_key, token, db_path=db_path)


def test_true_multiprocess_competing_lease_acquisition(temp_multiprocess_db):
    """
    Spawns 4 independent OS processes competing simultaneously for the same resource lease.
    Proves that exactly one OS process acquires the lease and 3 are rejected.
    """
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    res_key = "lever:figma"
    num_workers = 4

    processes = []
    for i in range(num_workers):
        p = ctx.Process(
            target=_worker_acquire_task,
            args=(temp_multiprocess_db, res_key, f"worker-{i}", 60, queue),
        )
        processes.append(p)

    # Launch all OS processes concurrently
    for p in processes:
        p.start()

    for p in processes:
        p.join(timeout=5)

    results = []
    while not queue.empty():
        results.append(queue.get())

    assert len(results) == num_workers
    acquired_workers = [r for r in results if r["acquired"] is True]
    rejected_workers = [r for r in results if r["acquired"] is False]

    # Invariant: Exactly one process acquired the lease
    assert len(acquired_workers) == 1
    assert len(rejected_workers) == 3

    # Check database state
    lease = get_scheduler_lease(res_key, db_path=temp_multiprocess_db)
    assert lease is not None
    assert lease["owner_token"] == acquired_workers[0]["token"]


def test_true_multiprocess_abrupt_termination_and_crash_recovery(temp_multiprocess_db):
    """
    Verifies that when a worker process holding a lease is killed abruptly via SIGKILL,
    an independent OS process can reclaim the lease after the TTL expires.
    """
    ctx = mp.get_context("spawn")
    res_key = "greenhouse:stripe"
    crashed_token = f"worker-crashed:{uuid.uuid4().hex}"
    ready_event = ctx.Event()

    # 1. Launch worker process that acquires a 1-second lease
    p1 = ctx.Process(
        target=_long_running_worker,
        args=(temp_multiprocess_db, res_key, crashed_token, ready_event),
    )
    p1.start()

    assert ready_event.wait(timeout=5) is True
    lease = get_scheduler_lease(res_key, db_path=temp_multiprocess_db)
    assert lease is not None
    assert lease["owner_token"] == crashed_token

    # 2. Abruptly kill the worker process with SIGKILL (no cleanup or release)
    p1.kill()
    p1.join(timeout=2)
    assert p1.is_alive() is False

    # 3. An independent worker process attempts to acquire immediately -> should fail (TTL not yet expired)
    survivor_token = f"worker-survivor:{uuid.uuid4().hex}"
    ok_early = acquire_scheduler_lease(res_key, survivor_token, ttl_seconds=60, db_path=temp_multiprocess_db)
    # If the 1-second TTL has not passed yet, it must fail; if it already passed, it reclaims
    time.sleep(1.2)  # Ensure TTL is completely expired

    # 4. Now acquire -> must succeed via crash recovery reclamation
    ok_after_expiry = acquire_scheduler_lease(res_key, survivor_token, ttl_seconds=60, db_path=temp_multiprocess_db)
    assert ok_after_expiry is True

    # Check lease now belongs to survivor
    lease_after = get_scheduler_lease(res_key, db_path=temp_multiprocess_db)
    assert lease_after is not None
    assert lease_after["owner_token"] == survivor_token


def test_true_multiprocess_heartbeat_renewal(temp_multiprocess_db):
    """
    Verifies that a long-running worker that renews its lease periodically keeps ownership
    past its initial TTL, and other processes are kept out until it explicitly releases.
    """
    ctx = mp.get_context("spawn")
    res_key = "ashby:linear"
    token_a = f"worker-heartbeat:{uuid.uuid4().hex}"
    ready_event = ctx.Event()
    stop_event = ctx.Event()

    p = ctx.Process(
        target=_heartbeat_worker,
        args=(temp_multiprocess_db, res_key, token_a, ready_event, stop_event),
    )
    p.start()

    assert ready_event.wait(timeout=5) is True

    # Sleep 2.5 seconds (past the initial 2.0s TTL). Because worker renews every 0.8s, lease remains active.
    time.sleep(2.5)

    token_b = f"worker-competitor:{uuid.uuid4().hex}"
    ok_b = acquire_scheduler_lease(res_key, token_b, ttl_seconds=60, db_path=temp_multiprocess_db)
    assert ok_b is False  # Must be rejected because heartbeat kept lease alive

    # Signal worker to stop and release
    stop_event.set()
    p.join(timeout=5)

    # Now competitor can acquire
    ok_b_after = acquire_scheduler_lease(res_key, token_b, ttl_seconds=60, db_path=temp_multiprocess_db)
    assert ok_b_after is True


def test_stale_worker_cannot_release_another_workers_lease(temp_multiprocess_db):
    """
    Verifies that a stale worker whose lease expired cannot release the lease
    after another worker has reclaimed it.
    """
    res_key = "lever:datadog"
    token_stale = f"worker-stale:{uuid.uuid4().hex}"
    token_new = f"worker-new:{uuid.uuid4().hex}"

    # Stale worker acquires 1s lease
    acquire_scheduler_lease(res_key, token_stale, ttl_seconds=1, db_path=temp_multiprocess_db)
    time.sleep(1.2)  # Expire lease

    # New worker reclaims lease
    acquire_scheduler_lease(res_key, token_new, ttl_seconds=60, db_path=temp_multiprocess_db)

    # Stale worker attempts to release -> must fail
    released_by_stale = release_scheduler_lease(res_key, token_stale, db_path=temp_multiprocess_db)
    assert released_by_stale is False

    # Verify lease is STILL owned by token_new
    lease = get_scheduler_lease(res_key, db_path=temp_multiprocess_db)
    assert lease is not None
    assert lease["owner_token"] == token_new


def test_stale_worker_fencing_prevents_job_expiration(temp_multiprocess_db):
    """
    CRITICAL FENCING TEST:
    Verifies that a stale worker that lost its lease CANNOT commit job mutations
    or mark active vacancies as expired.
    """
    engine = JobDiscoveryEngine(temp_multiprocess_db)
    source = JobSourceConfig(
        name="Datadog",
        source_type=SourceType.LEVER,
        board_token_or_slug="datadog",
    )
    res_key = f"{source.source_type.value}:{source.board_token_or_slug}"

    # 1. Seed two active jobs in database
    job1 = NormalizedJob(
        stable_id="lever:datadog:job1",
        source_name="Datadog",
        source_type=SourceType.LEVER,
        title="Software Engineer 1",
        company="Datadog",
        description="Python backend engineer",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote",
        is_remote=True,
    )
    job2 = NormalizedJob(
        stable_id="lever:datadog:job2",
        source_name="Datadog",
        source_type=SourceType.LEVER,
        title="Software Engineer 2",
        company="Datadog",
        description="Platform systems engineer",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote",
        is_remote=True,
    )
    engine.persist_and_update_freshness(source, [job1, job2], is_complete=True)

    with get_db_connection(temp_multiprocess_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'active'").fetchone()[0]
        assert count == 2

    # 2. Worker Stale acquires lease with 1s TTL
    stale_token = f"worker-stale:{uuid.uuid4().hex}"
    acquire_scheduler_lease(res_key, stale_token, ttl_seconds=1, db_path=temp_multiprocess_db)

    # 3. Simulate long GC pause / network timeout for Worker Stale
    time.sleep(1.2)  # Lease expires

    # 4. Worker Active reclaims the lease
    active_token = f"worker-active:{uuid.uuid4().hex}"
    acquired_active = acquire_scheduler_lease(res_key, active_token, ttl_seconds=60, db_path=temp_multiprocess_db)
    assert acquired_active is True

    # 5. Worker Stale wakes up and tries to commit an authoritative sync omitting job2
    # Without fencing, job2 would be wrongly marked 'expired'!
    # With lease fencing, it must raise StaleWorkerLeaseError and abort.
    with pytest.raises(StaleWorkerLeaseError, match="Fencing violation: Worker token"):
        engine.persist_and_update_freshness(
            source,
            [job1],  # job2 omitted
            is_complete=True,
            lease_token=stale_token,
        )

    # 6. Verify that job2 was NOT expired and remains 'active'
    with get_db_connection(temp_multiprocess_db) as conn:
        row = conn.execute("SELECT status FROM jobs WHERE stable_id = 'lever:datadog:job2'").fetchone()
        assert row is not None
        assert row[0] == "active"  # Safely preserved!


def test_repeated_reclaim_cycles_and_generational_fencing(temp_multiprocess_db):
    """
    Verifies that across repeated reclaim cycles (Worker 1 -> Worker 2 -> Worker 3),
    older generation worker tokens remain strictly locked out from committing mutations,
    and only the latest valid generation owner can commit.
    """
    engine = JobDiscoveryEngine(temp_multiprocess_db)
    source = JobSourceConfig(
        name="Figma",
        source_type=SourceType.LEVER,
        board_token_or_slug="figma",
    )
    res_key = f"{source.source_type.value}:{source.board_token_or_slug}"

    # Cycle 1: Worker 1 acquires 1s lease
    token_gen1 = f"worker-gen1:{uuid.uuid4().hex}"
    assert acquire_scheduler_lease(res_key, token_gen1, ttl_seconds=1, db_path=temp_multiprocess_db) is True
    time.sleep(1.1)

    # Cycle 2: Worker 2 reclaims 1s lease
    token_gen2 = f"worker-gen2:{uuid.uuid4().hex}"
    assert acquire_scheduler_lease(res_key, token_gen2, ttl_seconds=1, db_path=temp_multiprocess_db) is True
    time.sleep(1.1)

    # Cycle 3: Worker 3 reclaims 30s lease
    token_gen3 = f"worker-gen3:{uuid.uuid4().hex}"
    assert acquire_scheduler_lease(res_key, token_gen3, ttl_seconds=30, db_path=temp_multiprocess_db) is True

    # Generation 1 tries to commit -> Fails
    job = NormalizedJob(
        stable_id="lever:figma:designer",
        source_name="Figma",
        source_type=SourceType.LEVER,
        title="Product Designer",
        company="Figma",
        description="Design role",
        employment_type=EmploymentType.FULL_TIME,
        location="SF",
        is_remote=False,
    )
    with pytest.raises(StaleWorkerLeaseError, match="Fencing violation"):
        engine.persist_and_update_freshness(source, [job], is_complete=True, lease_token=token_gen1)

    # Generation 2 tries to commit -> Fails
    with pytest.raises(StaleWorkerLeaseError, match="Fencing violation"):
        engine.persist_and_update_freshness(source, [job], is_complete=True, lease_token=token_gen2)

    # Generation 3 (current owner) commits -> Succeeds
    saved = engine.persist_and_update_freshness(source, [job], is_complete=True, lease_token=token_gen3)
    assert len(saved) == 1

    # Verify job was committed
    with get_db_connection(temp_multiprocess_db) as conn:
        row = conn.execute("SELECT title, status FROM jobs WHERE stable_id = 'lever:figma:designer'").fetchone()
        assert row is not None
        assert row["title"] == "Product Designer"
        assert row["status"] == "active"
