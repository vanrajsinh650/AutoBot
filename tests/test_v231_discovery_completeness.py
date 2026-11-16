"""
Unit and Integration Tests for Phase 2: Discovery Completeness & Authoritative Expiration.
Validates:
1. Lever multi-page pagination.
2. Partial syncs NEVER expire previously discovered jobs.
3. Authoritative syncs properly mark omitted jobs as expired.
4. Malformed items are skipped without discarding valid listings.
5. Duplicate handling across pages and sources.
6. Explicit sync-run tracking and audit logging in sync_runs table.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.discovery.adapters.ashby import AshbyAdapter
from src.discovery.adapters.greenhouse import GreenhouseAdapter
from src.discovery.adapters.lever import LeverAdapter
from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.discovery.registry import JobDiscoveryEngine
from src.storage.db import get_db_connection, init_db


@pytest.mark.asyncio
async def test_lever_adapter_multipage_pagination():
    """Verify Lever adapter paginates across multiple pages until end of results."""
    cfg = JobSourceConfig(name="Figma", source_type=SourceType.LEVER, board_token_or_slug="figma")
    adapter = LeverAdapter(cfg)

    # Page 1: 100 items (full page)
    page1_items = [
        {
            "id": f"lever_p1_{i}",
            "text": f"Software Engineer {i}",
            "categories": {"location": "San Francisco, CA", "commitment": "Full-time"},
            "descriptionPlain": f"Engineering role {i}",
            "hostedUrl": f"https://jobs.lever.co/figma/lever_p1_{i}",
        }
        for i in range(100)
    ]

    # Page 2: 25 items (< 100 items -> last page)
    page2_items = [
        {
            "id": f"lever_p2_{i}",
            "text": f"Data Engineer {i}",
            "categories": {"location": "Remote", "commitment": "Full-time"},
            "descriptionPlain": f"Data role {i}",
            "hostedUrl": f"https://jobs.lever.co/figma/lever_p2_{i}",
        }
        for i in range(25)
    ]

    mock_resp1 = AsyncMock()
    mock_resp1.status = 200
    mock_resp1.json = AsyncMock(return_value=page1_items)

    mock_resp2 = AsyncMock()
    mock_resp2.status = 200
    mock_resp2.json = AsyncMock(return_value=page2_items)

    mock_cm1 = MagicMock()
    mock_cm1.__aenter__ = AsyncMock(return_value=mock_resp1)
    mock_cm1.__aexit__ = AsyncMock(return_value=None)

    mock_cm2 = MagicMock()
    mock_cm2.__aenter__ = AsyncMock(return_value=mock_resp2)
    mock_cm2.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get.side_effect = [mock_cm1, mock_cm2]

    jobs, is_complete = await adapter.fetch_jobs_detailed(session=mock_session)

    assert len(jobs) == 125
    assert is_complete is True
    assert mock_session.get.call_count == 2


@pytest.mark.asyncio
async def test_partial_fetch_never_expires_previously_discovered_jobs(tmp_path):
    """
    CRITICAL INVARIANT:
    If a fetch is partial (is_complete=False) due to pagination timeout, partial network
    failure, or truncation, previously discovered jobs MUST NOT be marked expired.
    """
    db_file = str(tmp_path / "test_partial_expiration.db")
    init_db(db_file)
    engine = JobDiscoveryEngine(db_file)

    source = JobSourceConfig(name="Stripe", source_type=SourceType.GREENHOUSE, board_token_or_slug="stripe")

    job1 = NormalizedJob(
        stable_id="greenhouse:stripe:1",
        source_name="Stripe",
        source_type=SourceType.GREENHOUSE,
        title="Backend Engineer",
        company="Stripe",
        description="Python & Go payments.",
        application_url="https://boards.greenhouse.io/stripe/jobs/1",
    )
    job2 = NormalizedJob(
        stable_id="greenhouse:stripe:2",
        source_name="Stripe",
        source_type=SourceType.GREENHOUSE,
        title="Infra Engineer",
        company="Stripe",
        description="Kubernetes & AWS.",
        application_url="https://boards.greenhouse.io/stripe/jobs/2",
    )

    # Initial authoritative sync saves both jobs
    engine.persist_and_update_freshness(source, [job1, job2], is_complete=True)

    with get_db_connection(db_file) as conn:
        r1 = conn.execute("SELECT status FROM jobs WHERE stable_id = ?", (job1.stable_id,)).fetchone()
        r2 = conn.execute("SELECT status FROM jobs WHERE stable_id = ?", (job2.stable_id,)).fetchone()
        assert r1["status"] == "active"
        assert r2["status"] == "active"

    # Subsequent PARTIAL sync (e.g. only page 1 returned job2, page 2 failed -> is_complete=False)
    engine.persist_and_update_freshness(source, [job2], is_complete=False)

    # Verify job1 was NOT expired because sync was partial!
    with get_db_connection(db_file) as conn:
        r1 = conn.execute("SELECT status FROM jobs WHERE stable_id = ?", (job1.stable_id,)).fetchone()
        r2 = conn.execute("SELECT status FROM jobs WHERE stable_id = ?", (job2.stable_id,)).fetchone()
        assert r1["status"] == "active", "Partial sync must NOT expire previously discovered vacancies!"
        assert r2["status"] == "active"

        # Check sync_runs table logged this as 'partial'
        sync_run = conn.execute(
            "SELECT status, is_complete FROM sync_runs WHERE source_type = 'greenhouse' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert sync_run["status"] == "partial"
        assert sync_run["is_complete"] == 0


@pytest.mark.asyncio
async def test_authoritative_sync_properly_expires_omitted_jobs(tmp_path):
    """
    When an authoritative sync (is_complete=True) succeeds, any job previously active
    for that source that is absent from the authoritative result must be marked expired.
    """
    db_file = str(tmp_path / "test_auth_expiration.db")
    init_db(db_file)
    engine = JobDiscoveryEngine(db_file)

    source = JobSourceConfig(name="Stripe", source_type=SourceType.GREENHOUSE, board_token_or_slug="stripe")

    job1 = NormalizedJob(
        stable_id="greenhouse:stripe:10",
        source_name="Stripe",
        source_type=SourceType.GREENHOUSE,
        title="Backend Engineer",
        company="Stripe",
        description="Python & Go payments.",
        application_url="https://boards.greenhouse.io/stripe/jobs/10",
    )
    job2 = NormalizedJob(
        stable_id="greenhouse:stripe:20",
        source_name="Stripe",
        source_type=SourceType.GREENHOUSE,
        title="Infra Engineer",
        company="Stripe",
        description="Kubernetes & AWS.",
        application_url="https://boards.greenhouse.io/stripe/jobs/20",
    )

    engine.persist_and_update_freshness(source, [job1, job2], is_complete=True)

    # Next authoritative sync only returns job2 (job1 was legitimately filled or closed)
    engine.persist_and_update_freshness(source, [job2], is_complete=True)

    with get_db_connection(db_file) as conn:
        r1 = conn.execute("SELECT status FROM jobs WHERE stable_id = ?", (job1.stable_id,)).fetchone()
        r2 = conn.execute("SELECT status FROM jobs WHERE stable_id = ?", (job2.stable_id,)).fetchone()
        assert r1["status"] == "expired"
        assert r2["status"] == "active"

        sync_run = conn.execute(
            "SELECT status, is_complete, expired_jobs FROM sync_runs WHERE source_type = 'greenhouse' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert sync_run["status"] == "completed"
        assert sync_run["is_complete"] == 1
        assert sync_run["expired_jobs"] == 1


@pytest.mark.asyncio
async def test_malformed_individual_items_do_not_drop_valid_listings():
    """Verify malformed JSON items in ATS feeds are skipped without discarding valid items."""
    cfg = JobSourceConfig(name="Stripe", source_type=SourceType.GREENHOUSE, board_token_or_slug="stripe")
    adapter = GreenhouseAdapter(cfg)

    raw_jobs = [
        # Valid item 1
        {
            "id": 101,
            "title": "Software Engineer",
            "content": "<p>Build APIs</p>",
            "location": {"name": "Remote"},
        },
        # Malformed item: invalid non-dict, missing title
        {"id": 102, "title": ""},
        "not a dict",
        None,
        # Valid item 2
        {
            "id": 103,
            "title": "DevOps Engineer",
            "content": "<p>Terraform & CI/CD</p>",
            "location": {"name": "New York, NY"},
        },
    ]

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"jobs": raw_jobs})

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    jobs, is_complete = await adapter.fetch_jobs_detailed(session=mock_session)

    assert len(jobs) == 2
    assert jobs[0].stable_id == "greenhouse:stripe:101"
    assert jobs[1].stable_id == "greenhouse:stripe:103"
    assert is_complete is True


@pytest.mark.asyncio
async def test_deduplication_across_pages_and_sources(tmp_path):
    """Verify identical jobs or fingerprint duplicates across sources are cleanly deduplicated."""
    db_file = str(tmp_path / "test_dedup.db")
    init_db(db_file)
    engine = JobDiscoveryEngine(db_file)

    source1 = JobSourceConfig(name="Stripe", source_type=SourceType.GREENHOUSE, board_token_or_slug="stripe")
    source2 = JobSourceConfig(name="Stripe-Lever", source_type=SourceType.LEVER, board_token_or_slug="stripe")

    # Job 1 on Greenhouse
    job1 = NormalizedJob(
        stable_id="greenhouse:stripe:999",
        source_name="Stripe",
        source_type=SourceType.GREENHOUSE,
        title="Staff Security Engineer",
        company="Stripe",
        description="Lead application security architecture and cryptography.",
        application_url="https://boards.greenhouse.io/stripe/jobs/999",
    )
    job1.fingerprint = job1.compute_fingerprint()

    # Identical vacancy mirrored on Lever
    job2 = NormalizedJob(
        stable_id="lever:stripe:aaa-bbb-ccc",
        source_name="Stripe-Lever",
        source_type=SourceType.LEVER,
        title="Staff Security Engineer",
        company="Stripe",
        description="Lead application security architecture and cryptography.",
        application_url="https://jobs.lever.co/stripe/aaa-bbb-ccc",
    )
    job2.fingerprint = job2.compute_fingerprint()

    # Fingerprints should be identical
    assert job1.fingerprint == job2.fingerprint

    saved1 = engine.persist_and_update_freshness(source1, [job1], is_complete=True)
    saved2 = engine.persist_and_update_freshness(source2, [job2], is_complete=True)

    assert len(saved1) == 1
    assert len(saved2) == 0, "Second job must be recognized as duplicate by fingerprint and not inserted"

    with get_db_connection(db_file) as conn:
        rows = conn.execute("SELECT id, stable_id FROM jobs WHERE company = 'Stripe'").fetchall()
        assert len(rows) == 1
        assert rows[0]["stable_id"] == "greenhouse:stripe:999"
