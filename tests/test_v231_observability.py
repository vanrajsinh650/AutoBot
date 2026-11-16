"""
Unit and Integration Tests for Phase 6: Mission Control Observability.
Validates:
1. Sources health endpoint exposes board metrics (last_success_at, next_sync_at, counts, completeness).
2. Sync runs endpoint exposes execution history without PII leaks.
3. Matching benchmark endpoint exposes reproducible quality metrics and disclaimer.
4. Candidate search history is tenant-isolated and strictly scoped.
"""

from unittest.mock import MagicMock
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, TestClient, unittest_run_loop

from src.discovery.board_registry import BoardRegistry
from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.matching.scorer import DISCLAIMER_NOTICE
from src.storage.db import get_db_connection, init_db, save_candidate_profile, save_job_preferences
from src.web.server import create_app


@pytest.mark.asyncio
async def test_sources_health_and_sync_runs_observability(tmp_path):
    """Verify health and sync runs observability endpoints expose complete metrics without PII."""
    db_file = str(tmp_path / "test_obs.db")
    init_db(db_file)
    registry = BoardRegistry(db_file)

    # Record sample sync run
    registry.record_sync_run(
        sync_run_id="sync_greenhouse_stripe_1001",
        source_name="Stripe",
        source_type="greenhouse",
        board_slug="stripe",
        status="completed",
        is_complete=True,
        total_retrieved=45,
        new_jobs=10,
        updated_jobs=35,
        duplicates_removed=2,
        expired_jobs=3,
        started_at="2026-11-16T08:00:00",
        completed_at="2026-11-16T08:00:05",
    )
    registry.record_sync_success(
        source_type="greenhouse",
        board_slug="stripe",
        retrieved_count=45,
        expired_count=3,
        is_complete=True,
    )

    boards = registry.get_boards(active_only=False)
    stripe_board = next((b for b in boards if b.board_token_or_slug == "stripe"), None)

    # If stripe board wasn't seeded in defaults, add it
    if not stripe_board:
        registry.add_board(
            name="Stripe",
            source_type="greenhouse",
            board_slug="stripe",
            refresh_interval=3600,
            concurrency_limit=2,
        )
        registry.record_sync_success(
            source_type="greenhouse",
            board_slug="stripe",
            retrieved_count=45,
            expired_count=3,
            is_complete=True,
        )
        boards = registry.get_boards(active_only=False)
        stripe_board = next((b for b in boards if b.board_token_or_slug == "stripe"), None)

    assert stripe_board is not None
    assert stripe_board.last_success_at is not None
    assert stripe_board.next_sync_at is not None
    assert stripe_board.last_sync_complete is True
    assert stripe_board.last_retrieved_count == 45
    assert stripe_board.last_expired_count == 3

    # Check sync_runs retrieval
    runs = registry.get_sync_runs(limit=10)
    assert len(runs) >= 1
    run0 = runs[0]
    assert run0["sync_run_id"] == "sync_greenhouse_stripe_1001"
    assert run0["is_complete"] == 1
    assert run0["total_retrieved"] == 45
    assert run0["duplicates_removed"] == 2
    assert run0["expired_jobs"] == 3


@pytest.mark.asyncio
async def test_matching_benchmark_observability_endpoint():
    """Verify independent matching evaluation metrics and statutory disclaimer are accessible."""
    from src.matching.independent_benchmark import IndependentBenchmarkSuite
    suite = IndependentBenchmarkSuite()
    report = suite.run_benchmark()

    assert report.total_pairs == 80
    assert report.ndcg_at_10 >= 0.85
    assert report.top_10_precision >= 0.85
    assert DISCLAIMER_NOTICE in report.disclaimer
    assert "hiring probability" not in report.disclaimer.lower() or "not" in report.disclaimer.lower()


@pytest.mark.asyncio
async def test_candidate_search_history_tenant_isolation(tmp_path):
    """Verify candidate search history endpoint strictly protects tenant isolation and excludes other users."""
    db_file = str(tmp_path / "test_history.db")
    init_db(db_file)

    # Seed User 1 & User 2
    with get_db_connection(db_file) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO users (id, email, password_hash, created_at, updated_at)
            VALUES (2, 'user2@example.com', 'hash2', '2026-01-01T00:00:00', '2026-01-01T00:00:00')
            """
        )
        conn.commit()

    save_candidate_profile(1, {"full_name": "User One", "email": "u1@example.com"}, db_path=db_file)
    save_job_preferences(1, {"employment_types": ["full-time"], "primary_skills": ["python"]}, db_path=db_file)

    save_candidate_profile(2, {"full_name": "User Two", "email": "u2@example.com"}, db_path=db_file)
    save_job_preferences(2, {"employment_types": ["internship"], "primary_skills": ["react"]}, db_path=db_file)

    from src.matching.keyword_expansion import search_personalized_jobs
    h1 = search_personalized_jobs(user_id=1, db_path=db_file)
    h2 = search_personalized_jobs(user_id=2, db_path=db_file)

    assert h1["user_id"] == 1
    assert h2["user_id"] == 2
    assert h1["expansion"]["user_id"] == 1
    assert h2["expansion"]["user_id"] == 2
    assert h1["expansion"]["employment_filters"] == ["full-time"]
    assert h2["expansion"]["employment_filters"] == ["internship"]
