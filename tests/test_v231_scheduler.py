"""
Unit and Integration Tests for Phase 3: Recurring Synchronization.
Validates:
1. Refresh interval consumption and due status checks.
2. Prevention of concurrent duplicate syncs on the same board.
3. Bounded exponential backoff with jitter on failures.
4. Source failure isolation (error on one board never halts others).
5. Graceful startup, shutdown, and restart recovery.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.discovery.registry import FetchSourceResult
from src.discovery.scheduler import DiscoveryScheduler
from src.storage.db import get_db_connection, init_db


@pytest.mark.asyncio
async def test_scheduler_due_detection_and_restart_recovery(tmp_path):
    """Verify scheduler detects due boards, respects future schedules, and handles restart recovery."""
    db_file = str(tmp_path / "test_due.db")
    init_db(db_file)
    scheduler = DiscoveryScheduler(db_file)

    now = datetime.now()
    past_iso = datetime.fromtimestamp(now.timestamp() - 3600).isoformat()
    future_iso = datetime.fromtimestamp(now.timestamp() + 3600).isoformat()

    # Board 1: No previous sync (due immediately)
    b1 = JobSourceConfig(name="New Board", source_type=SourceType.GREENHOUSE, board_token_or_slug="new_board")
    assert scheduler.is_due_for_sync(b1) is True

    # Board 2: Scheduled in the past (overdue -> restart recovery)
    b2 = JobSourceConfig(
        name="Overdue Board",
        source_type=SourceType.LEVER,
        board_token_or_slug="overdue",
        next_sync_at=past_iso,
    )
    assert scheduler.is_due_for_sync(b2) is True

    # Board 3: Scheduled in the future (not due)
    b3 = JobSourceConfig(
        name="Future Board",
        source_type=SourceType.ASHBY,
        board_token_or_slug="future",
        next_sync_at=future_iso,
    )
    assert scheduler.is_due_for_sync(b3) is False

    # Board 4: Paused board (never due)
    b4 = JobSourceConfig(
        name="Paused Board",
        source_type=SourceType.GREENHOUSE,
        board_token_or_slug="paused",
        status="paused",
    )
    assert scheduler.is_due_for_sync(b4) is False


@pytest.mark.asyncio
async def test_scheduler_prevents_concurrent_duplicate_syncs(tmp_path):
    """Verify that multiple concurrent calls to sync the same board are locked and safely skipped."""
    db_file = str(tmp_path / "test_concurrency.db")
    init_db(db_file)
    scheduler = DiscoveryScheduler(db_file)

    board = JobSourceConfig(name="Figma", source_type=SourceType.LEVER, board_token_or_slug="figma")

    sync_started = asyncio.Event()
    sync_proceed = asyncio.Event()

    async def slow_fetch(src, session):
        sync_started.set()
        await sync_proceed.wait()
        return FetchSourceResult(src, [], None, is_complete=True)

    with patch.object(scheduler.engine, "_fetch_single_source", side_effect=slow_fetch):
        mock_session = MagicMock()
        task1 = asyncio.create_task(scheduler.sync_board(board, mock_session, force=True))
        await sync_started.wait()

        # Second sync attempted while first is actively running
        res2 = await scheduler.sync_board(board, mock_session, force=True)
        assert res2 is None, "Concurrent sync must be skipped when board lock is held"

        # Release task 1
        sync_proceed.set()
        res1 = await task1
        assert res1 is not None
        assert res1.is_complete is True


def test_scheduler_bounded_exponential_backoff():
    """Verify exponential backoff calculation increases with failures and remains bounded with jitter."""
    scheduler = DiscoveryScheduler()
    refresh_interval = 3600

    delays = [scheduler.calculate_backoff(fc, refresh_interval) for fc in range(8)]

    # Must be strictly increasing on average
    assert delays[0] < delays[3] < delays[5]

    # Delays must have jitter (not exact integers)
    assert any(d % 1 != 0 for d in delays)

    # Delay must not exceed refresh_interval + max jitter (3.0s)
    for d in delays:
        assert d <= refresh_interval + 3.0


@pytest.mark.asyncio
async def test_scheduler_failure_isolation(tmp_path):
    """Verify failure or exception on one board never stops or crashes sync of another board."""
    db_file = str(tmp_path / "test_isolation.db")
    init_db(db_file)
    scheduler = DiscoveryScheduler(db_file)

    b_fail = JobSourceConfig(name="Failing Co", source_type=SourceType.GREENHOUSE, board_token_or_slug="fail_co")
    b_pass = JobSourceConfig(name="Healthy Co", source_type=SourceType.LEVER, board_token_or_slug="healthy_co")

    healthy_job = NormalizedJob(
        stable_id="lever:healthy_co:1",
        source_name="Healthy Co",
        source_type=SourceType.LEVER,
        title="Software Engineer",
        company="Healthy Co",
        description="Great engineering team.",
        application_url="https://jobs.lever.co/healthy_co/1",
    )

    async def mock_fetch(src, session):
        if src.board_token_or_slug == "fail_co":
            raise RuntimeError("503 Service Unavailable from ATS")
        return FetchSourceResult(src, [healthy_job], None, is_complete=True)

    with patch.object(scheduler.engine, "_fetch_single_source", side_effect=mock_fetch):
        mock_session = MagicMock()

        res_fail = await scheduler.sync_board(b_fail, mock_session, force=True)
        res_pass = await scheduler.sync_board(b_pass, mock_session, force=True)

        assert res_fail is not None
        assert res_fail.error is not None
        assert res_fail.is_complete is False

        assert res_pass is not None
        assert res_pass.error is None
        assert res_pass.is_complete is True
        assert len(res_pass.jobs) == 1

        # Healthy job must be in database
        with get_db_connection(db_file) as conn:
            row = conn.execute("SELECT status FROM jobs WHERE stable_id = ?", (healthy_job.stable_id,)).fetchone()
            assert row["status"] == "active"


@pytest.mark.asyncio
async def test_scheduler_graceful_lifecycle(tmp_path):
    """Verify start and stop lifecycle methods manage background task cleanly without leaks."""
    db_file = str(tmp_path / "test_lifecycle.db")
    init_db(db_file)
    scheduler = DiscoveryScheduler(db_file, poll_interval_sec=0.1)

    with patch.object(scheduler, "run_sync_cycle", new_callable=AsyncMock) as mock_cycle:
        mock_cycle.return_value = []
        scheduler.start()
        assert scheduler._running is True
        assert scheduler._task is not None

        await asyncio.sleep(0.2)
        assert mock_cycle.call_count >= 1

        await scheduler.stop()
        assert scheduler._running is False
        assert scheduler._task.done()
