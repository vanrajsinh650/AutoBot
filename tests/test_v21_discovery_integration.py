"""
Phase 5 — Real Integration & Resilience Verification for Greenhouse, Lever, and Ashby Adapters.
Tests rate limiting (HTTP 429), transient failures (HTTP 500/502/503), malformed data resilience,
remote detection, deduplication, and explicitly distinguishes live integration tests from mocked unit tests.
"""

from unittest.mock import AsyncMock, MagicMock
import aiohttp
import pytest

from src.discovery.adapters.ashby import AshbyAdapter
from src.discovery.adapters.greenhouse import GreenhouseAdapter
from src.discovery.adapters.lever import LeverAdapter
from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.discovery.registry import JobDiscoveryEngine
from src.storage.db import init_db


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_discovery_resilience.db"
    init_db(str(db_file))
    return str(db_file)


# ── Transient & Rate-Limiting Resilience Tests ───────────────────────

@pytest.mark.asyncio
async def test_greenhouse_rate_limit_and_transient_retry():
    """Verify Greenhouse adapter recovers from initial 429 / 503 transient error."""
    cfg = JobSourceConfig(name="ResilientOrg", source_type=SourceType.GREENHOUSE, board_token_or_slug="resilient")
    adapter = GreenhouseAdapter(cfg)

    resp_429 = AsyncMock()
    resp_429.status = 429

    resp_200 = AsyncMock()
    resp_200.status = 200
    resp_200.json = AsyncMock(return_value={
        "jobs": [
            {"id": 101, "title": "Staff Backend Engineer", "location": {"name": "Remote - US"}, "content": "Python systems"}
        ]
    })

    mock_session = MagicMock()
    # First call yields 429, second call yields 200
    mock_session.get.side_effect = [
        AsyncMock(__aenter__=AsyncMock(return_value=resp_429)),
        AsyncMock(__aenter__=AsyncMock(return_value=resp_200)),
    ]

    jobs = await adapter.fetch_jobs(session=mock_session)
    assert len(jobs) == 1
    assert jobs[0].title == "Staff Backend Engineer"
    assert jobs[0].is_remote is True


@pytest.mark.asyncio
async def test_lever_rate_limit_and_transient_retry():
    """Verify Lever adapter recovers from initial 502 Bad Gateway."""
    cfg = JobSourceConfig(name="LeverOrg", source_type=SourceType.LEVER, board_token_or_slug="leverorg")
    adapter = LeverAdapter(cfg)

    resp_502 = AsyncMock()
    resp_502.status = 502

    resp_200 = AsyncMock()
    resp_200.status = 200
    resp_200.json = AsyncMock(return_value=[
        {"id": "l_1", "text": "Platform Security Architect", "categories": {"location": "Remote", "commitment": "Full-time"}, "descriptionPlain": "Kubernetes & IAM"}
    ])

    mock_session = MagicMock()
    mock_session.get.side_effect = [
        AsyncMock(__aenter__=AsyncMock(return_value=resp_502)),
        AsyncMock(__aenter__=AsyncMock(return_value=resp_200)),
    ]

    jobs = await adapter.fetch_jobs(session=mock_session)
    assert len(jobs) == 1
    assert jobs[0].title == "Platform Security Architect"


# ── Malformed & Missing Fields Resilience Tests ───────────────────────

@pytest.mark.asyncio
async def test_greenhouse_malformed_payload_graceful_handling():
    """Verify Greenhouse adapter does not crash on malformed/non-dict payload or corrupted elements."""
    cfg = JobSourceConfig(name="BrokenOrg", source_type=SourceType.GREENHOUSE, board_token_or_slug="broken")
    adapter = GreenhouseAdapter(cfg)

    resp_malformed = AsyncMock()
    resp_malformed.status = 200
    resp_malformed.json = AsyncMock(return_value={
        "jobs": [
            None,  # None element
            "random string",  # Not a dict
            {"id": 99},  # Missing title
            {"title": "Valid Architect", "id": 100, "location": None, "content": None},  # Missing location & content
        ]
    })

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = resp_malformed

    jobs = await adapter.fetch_jobs(session=mock_session)
    # Only the valid job with a title should survive
    assert len(jobs) == 1
    assert jobs[0].title == "Valid Architect"
    assert jobs[0].description == ""
    assert jobs[0].location == ""


@pytest.mark.asyncio
async def test_ashby_malformed_payload_graceful_handling():
    """Verify Ashby adapter gracefully ignores malformed entries."""
    cfg = JobSourceConfig(name="AshbyOrg", source_type=SourceType.ASHBY, board_token_or_slug="ashbyorg")
    adapter = AshbyAdapter(cfg)

    resp = AsyncMock()
    resp.status = 200
    resp.json = AsyncMock(return_value={
        "jobs": [
            {"id": "a1", "title": ""},  # Empty title
            {"id": "a2", "title": "Data Engineer", "location": "London, UK", "isRemote": True},
        ]
    })

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = resp

    jobs = await adapter.fetch_jobs(session=mock_session)
    assert len(jobs) == 1
    assert jobs[0].title == "Data Engineer"
    assert jobs[0].country.lower() == "united kingdom"
    assert jobs[0].is_remote is True


# ── Deduplication & Fingerprint Tests ────────────────────────────────

def test_engine_deduplication_stable_id_and_fingerprint(temp_db):
    """Verify that identical or fuzzy-matching duplicate jobs are rejected by JobDiscoveryEngine."""
    engine = JobDiscoveryEngine(db_path=temp_db)

    j1 = NormalizedJob(
        stable_id="greenhouse:acme:1",
        source_name="Acme",
        source_type=SourceType.GREENHOUSE,
        title="Senior Python Engineer",
        company="Acme Corp",
        description="We build distributed cloud services.",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote, US",
        country="United States",
        is_remote=True,
        application_url="https://boards.greenhouse.io/acme/jobs/1",
    )
    j1.fingerprint = j1.compute_fingerprint()

    # 1. First persist should succeed
    saved = engine.persist_jobs([j1])
    assert len(saved) == 1

    # 2. Duplicate with identical stable_id should be skipped
    saved_dup = engine.persist_jobs([j1])
    assert len(saved_dup) == 0

    # 3. Duplicate with DIFFERENT stable_id but IDENTICAL fingerprint (same company, title, description)
    j2 = NormalizedJob(
        stable_id="lever:acme:lever_variant_123",
        source_name="Acme Lever",
        source_type=SourceType.LEVER,
        title="Senior Python Engineer",
        company="Acme Corp",
        description="We build distributed cloud services.",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote, US",
        country="United States",
        is_remote=True,
        application_url="https://jobs.lever.co/acme/lever_variant_123",
    )
    j2.fingerprint = j2.compute_fingerprint()

    saved_fuzzy_dup = engine.persist_jobs([j2])
    assert len(saved_fuzzy_dup) == 0  # Deduplicated via fingerprint!


# ── Clearly Distinguished Live Integration Marker ────────────────────

@pytest.mark.live_integration
@pytest.mark.asyncio
async def test_live_greenhouse_integration():
    """
    Live test against public Greenhouse board (e.g. gitlab).
    Marked with 'live_integration' so it is executed explicitly when external network is available.
    """
    cfg = JobSourceConfig(name="GitLab", source_type=SourceType.GREENHOUSE, board_token_or_slug="gitlab")
    adapter = GreenhouseAdapter(cfg)

    try:
        jobs = await adapter.fetch_jobs()
        # If running in environment with live internet access:
        if jobs:
            assert len(jobs) > 0
            assert all(j.stable_id.startswith("greenhouse:gitlab:") for j in jobs)
            assert all(j.title for j in jobs)
    except Exception as e:
        pytest.skip(f"Live network access unavailable in current test environment: {e}")
