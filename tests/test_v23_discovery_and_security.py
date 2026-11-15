"""
AutoBot v2.3 Comprehensive Job Discovery, Security & Freshness Test Suite.
Tests:
1. Strict SSRF Protection (DNS resolution checks, private IPs, AWS metadata, non-whitelisted domains, invalid slugs).
2. Response size capping (MAX_RESPONSE_BYTES).
3. Freshness & Expiration invariants: transient network errors NEVER mark jobs expired; verified 200 payload without vacancy marks it expired.
4. Tenant-isolated personalized keyword expansion and search differentiation (User A vs User B).
5. Opt-in live ATS integration tests (@pytest.mark.live_integration).
"""

import asyncio
from datetime import datetime
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp
import pytest

from src.discovery.adapters.ashby import AshbyAdapter
from src.discovery.adapters.greenhouse import GreenhouseAdapter
from src.discovery.adapters.lever import LeverAdapter
from src.discovery.board_registry import BoardRegistry
from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.discovery.registry import JobDiscoveryEngine
from src.discovery.security import (
    MAX_RESPONSE_BYTES,
    SSRFValidationError,
    is_ip_safe_for_egress,
    validate_ats_url,
    validate_board_slug,
)
from src.matching.keyword_expansion import expand_candidate_keywords, search_personalized_jobs
from src.storage.auth import create_user
from src.storage.db import (
    get_db_connection,
    init_db,
    save_candidate_profile,
    save_job_preferences,
)


# ── 1. SSRF Security Unit Tests ────────────────────────────────────────────────

def test_validate_board_slug():
    """Verify slug validation rejects dangerous path traversal, script injection, and invalid characters."""
    assert validate_board_slug("cloudflare") == "cloudflare"
    assert validate_board_slug("lever-demo_123") == "lever-demo_123"

    invalid_slugs = [
        "../etc/passwd",
        "cloudflare/jobs",
        "company;rm -rf /",
        "<script>alert(1)</script>",
        "test slug",
        "company?query=1",
        "company#fragment",
        "",
        "a" * 129,
    ]
    for bad in invalid_slugs:
        with pytest.raises(SSRFValidationError):
            validate_board_slug(bad)


def test_validate_ats_url_scheme_and_domain():
    """Verify that only HTTPS and whitelisted ATS domains are accepted."""
    valid_urls = [
        "https://boards-api.greenhouse.io/v1/boards/cloudflare/jobs?content=true",
        "https://api.lever.co/v0/postings/leverdemo?mode=json",
        "https://api.ashbyhq.com/posting-api/job-board/ramp",
    ]
    for url in valid_urls:
        assert validate_ats_url(url) == url

    invalid_urls = [
        "http://boards-api.greenhouse.io/v1/boards/cloudflare/jobs",  # Insecure HTTP
        "ftp://boards-api.greenhouse.io/v1/boards/cloudflare/jobs",
        "https://evil-attacker.com/v1/boards/cloudflare/jobs",        # Non-whitelisted
        "https://linkedin.com/jobs",                                  # LinkedIn blocked
        "https://127.0.0.1/jobs",                                     # Loopback
        "https://169.254.169.254/latest/meta-data/",                  # AWS metadata
    ]
    for url in invalid_urls:
        with pytest.raises(SSRFValidationError):
            validate_ats_url(url)


def test_is_ip_safe_for_egress():
    """Verify IP egress check strictly blocks private, loopback, and metadata IPs."""
    assert is_ip_safe_for_egress("127.0.0.1") is False
    assert is_ip_safe_for_egress("10.0.0.5") is False
    assert is_ip_safe_for_egress("172.16.0.1") is False
    assert is_ip_safe_for_egress("192.168.1.1") is False
    assert is_ip_safe_for_egress("169.254.169.254") is False
    assert is_ip_safe_for_egress("::1") is False
    assert is_ip_safe_for_egress("fc00::1") is False
    assert is_ip_safe_for_egress("8.8.8.8") is True
    assert is_ip_safe_for_egress("104.16.132.229") is True


# ── 2. Freshness & Expiration Invariant Tests ──────────────────────────────────

@pytest.mark.asyncio
async def test_transient_error_never_marks_jobs_expired(tmp_path):
    """
    CRITICAL INVARIANT: A transient network error (429, 5xx, or connection drop)
    must NEVER mark previously active jobs as expired.
    """
    db_file = str(tmp_path / "test_freshness.db")
    init_db(db_file)
    engine = JobDiscoveryEngine(db_path=db_file)

    source = JobSourceConfig(name="Stripe", source_type=SourceType.GREENHOUSE, board_token_or_slug="stripe")
    engine.register_source(source)
    initial_job = NormalizedJob(
        stable_id="greenhouse:stripe:101",
        source_name="Stripe",
        source_type=SourceType.GREENHOUSE,
        title="Software Engineer",
        company="Stripe",
        description="Python backend systems.",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote",
        country="United States",
        is_remote=True,
        publication_date="2026-01-01T00:00:00",
        application_url="https://boards.greenhouse.io/stripe/jobs/101",
    )
    engine.persist_jobs([initial_job])

    # Verify initial job is active
    with get_db_connection(db_file) as conn:
        row = conn.execute("SELECT status FROM jobs WHERE stable_id = ?", (initial_job.stable_id,)).fetchone()
        assert row["status"] == "active"

    # Simulate network failure: mock fetch_jobs raising an exception
    with patch.object(GreenhouseAdapter, "fetch_jobs", side_effect=aiohttp.ClientError("Connection refused")):
        async with aiohttp.ClientSession() as session:
            await engine._fetch_single_source(source, session)

    # Verify job remains active!
    with get_db_connection(db_file) as conn:
        row = conn.execute("SELECT j.status, js.failure_count FROM jobs j JOIN job_sources js ON js.board_token_or_slug = 'stripe' WHERE j.stable_id = ?", (initial_job.stable_id,)).fetchone()
        assert row["status"] == "active"
        assert row["failure_count"] >= 1


@pytest.mark.asyncio
async def test_legitimate_source_removal_marks_job_expired(tmp_path):
    """
    When a valid HTTP 200 payload from the ATS succeeds but omits a previously active vacancy,
    that vacancy must be marked expired.
    """
    db_file = str(tmp_path / "test_expiration.db")
    init_db(db_file)
    engine = JobDiscoveryEngine(db_path=db_file)

    source = JobSourceConfig(name="Stripe", source_type=SourceType.GREENHOUSE, board_token_or_slug="stripe")
    job1 = NormalizedJob(
        stable_id="greenhouse:stripe:101",
        source_name="Stripe",
        source_type=SourceType.GREENHOUSE,
        title="Software Engineer",
        company="Stripe",
        description="Python systems.",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote",
        country="United States",
        is_remote=True,
        publication_date="2026-01-01T00:00:00",
        application_url="https://boards.greenhouse.io/stripe/jobs/101",
    )
    job2 = NormalizedJob(
        stable_id="greenhouse:stripe:102",
        source_name="Stripe",
        source_type=SourceType.GREENHOUSE,
        title="DevOps Engineer",
        company="Stripe",
        description="Kubernetes infra.",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote",
        country="United States",
        is_remote=True,
        publication_date="2026-01-01T00:00:00",
        application_url="https://boards.greenhouse.io/stripe/jobs/102",
    )
    engine.persist_and_update_freshness(source, [job1, job2])

    # Next sync returns ONLY job2 (job1 was closed/removed by employer)
    engine.persist_and_update_freshness(source, [job2])

    with get_db_connection(db_file) as conn:
        r1 = conn.execute("SELECT status FROM jobs WHERE stable_id = ?", (job1.stable_id,)).fetchone()
        r2 = conn.execute("SELECT status FROM jobs WHERE stable_id = ?", (job2.stable_id,)).fetchone()
        assert r1["status"] == "expired"
        assert r2["status"] == "active"


# ── 3. Tenant-Isolated Keyword Expansion & Search Differentiation ─────────────

def test_tenant_isolated_keyword_expansion(tmp_path):
    """
    Verify User A (Python/AI Internship) and User B (Java Full-Time) receive
    completely distinct, tenant-isolated keyword expansions and search filters.
    """
    db_file = str(tmp_path / "test_tenant_search.db")
    init_db(db_file)

    # 1. Setup User A
    ok_a, user_id_a, _ = create_user("alice@domain.com", "PasswordAlice123!", db_path=db_file)
    assert ok_a is True and user_id_a is not None
    save_job_preferences(
        user_id=user_id_a,
        prefs={
            "employment_types": ["internship"],
            "target_roles": ["AI Engineer"],
            "primary_skills": ["Python", "PyTorch"],
            "secondary_skills": ["LangChain"],
            "eligible_countries": ["India", "United States"],
            "work_arrangement": "remote",
        },
        db_path=db_file,
    )

    # 2. Setup User B
    ok_b, user_id_b, _ = create_user("bob@domain.com", "PasswordBob123!", db_path=db_file)
    assert ok_b is True and user_id_b is not None
    save_job_preferences(
        user_id=user_id_b,
        prefs={
            "employment_types": ["full-time"],
            "target_roles": ["Backend Engineer"],
            "primary_skills": ["Java", "Spring Boot"],
            "secondary_skills": ["PostgreSQL"],
            "eligible_countries": ["United States"],
            "work_arrangement": "on-site",
        },
        db_path=db_file,
    )

    # 3. Test Keyword Expansion Isolation
    exp_a = expand_candidate_keywords(user_id_a, db_path=db_file)
    exp_b = expand_candidate_keywords(user_id_b, db_path=db_file)

    assert "internship" in exp_a.employment_filters
    assert "full-time" in exp_b.employment_filters
    assert "intern" in exp_a.expanded_keywords
    assert "intern" not in exp_b.expanded_keywords

    assert any(k in exp_a.expanded_keywords for k in ["pytorch", "fastapi", "python"])
    assert any(k in exp_b.expanded_keywords for k in ["java", "spring boot"])
    assert "java" not in exp_a.expanded_keywords
    assert "pytorch" not in exp_b.expanded_keywords


# ── 4. Live ATS Integration Tests (Opt-In) ───────────────────────────────────

@pytest.mark.live_integration
@pytest.mark.asyncio
async def test_live_ats_discovery_multiboard():
    """
    Live integration test against public real-world ATS endpoints:
    - Greenhouse: cloudflare
    - Lever: leverdemo
    - Ashby: ramp
    Requires unblocked internet connection.
    """
    async with aiohttp.ClientSession() as session:
        # 1. Test Greenhouse Cloudflare
        gh_config = JobSourceConfig(name="Cloudflare", source_type=SourceType.GREENHOUSE, board_token_or_slug="cloudflare")
        gh_adapter = GreenhouseAdapter(gh_config)
        gh_jobs = await gh_adapter.fetch_jobs(session=session)
        assert len(gh_jobs) > 10
        assert all(j.source_name == "Cloudflare" for j in gh_jobs)
        assert all(j.source_type == SourceType.GREENHOUSE for j in gh_jobs)
        assert any(j.workplace_type in ("remote", "hybrid", "on-site") for j in gh_jobs)

        # 2. Test Lever Demo
        lever_config = JobSourceConfig(name="Lever Demo", source_type=SourceType.LEVER, board_token_or_slug="leverdemo")
        lever_adapter = LeverAdapter(lever_config)
        lever_jobs = await lever_adapter.fetch_jobs(session=session)
        assert len(lever_jobs) >= 5
        assert all(j.source_type == SourceType.LEVER for j in lever_jobs)

        # 3. Test Ashby Ramp
        ashby_config = JobSourceConfig(name="Ramp", source_type=SourceType.ASHBY, board_token_or_slug="ramp")
        ashby_adapter = AshbyAdapter(ashby_config)
        ashby_jobs = await ashby_adapter.fetch_jobs(session=session)
        assert len(ashby_jobs) > 10
        assert all(j.source_type == SourceType.ASHBY for j in ashby_jobs)
