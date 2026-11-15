"""
Tests for AutoBot v2 Job Discovery Adapters, Normalization, and Deduplication.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.discovery.adapters.ashby import AshbyAdapter
from src.discovery.adapters.greenhouse import GreenhouseAdapter
from src.discovery.adapters.lever import LeverAdapter
from src.discovery.adapters.manual import ManualJobAdapter
from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.discovery.registry import JobDiscoveryEngine
from src.storage.db import init_db


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_discovery.db"
    init_db(str(db_file))
    return str(db_file)


@pytest.mark.asyncio
async def test_greenhouse_adapter_normalization():
    """Verify Greenhouse payload normalization, HTML stripping, remote & employment type detection."""
    cfg = JobSourceConfig(name="Stripe", source_type=SourceType.GREENHOUSE, board_token_or_slug="stripe")
    adapter = GreenhouseAdapter(cfg)

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "jobs": [
            {
                "id": 99881,
                "title": "Software Engineering Intern - Summer 2027",
                "location": {"name": "Remote, US"},
                "content": "<p>Join our <strong>infrastructure</strong> team building scalable APIs.</p>",
                "updated_at": "2026-11-10T00:00:00Z",
                "absolute_url": "https://boards.greenhouse.io/stripe/jobs/99881",
            }
        ]
    })

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    jobs = await adapter.fetch_jobs(session=mock_session)
    assert len(jobs) == 1
    job = jobs[0]

    assert job.stable_id == "greenhouse:stripe:99881"
    assert job.company == "Stripe"
    assert job.title == "Software Engineering Intern - Summer 2027"
    assert job.employment_type == EmploymentType.INTERNSHIP
    assert job.is_remote is True
    assert "<p>" not in job.description
    assert "infrastructure team building scalable APIs" in job.description
    assert job.fingerprint != ""


@pytest.mark.asyncio
async def test_lever_adapter_normalization():
    """Verify Lever published postings normalization and categories extraction."""
    cfg = JobSourceConfig(name="Figma", source_type=SourceType.LEVER, board_token_or_slug="figma")
    adapter = LeverAdapter(cfg)

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=[
        {
            "id": "lever_abc_1",
            "text": "Full-Stack Engineer, Core Systems",
            "categories": {
                "location": "San Francisco, CA",
                "commitment": "Full-time",
            },
            "descriptionPlain": "We are seeking a Full-Stack Engineer...",
            "description": "<p>We are seeking a Full-Stack Engineer...</p>",
            "hostedUrl": "https://jobs.lever.co/figma/lever_abc_1",
            "createdAt": 1700000000000,
        }
    ])

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    jobs = await adapter.fetch_jobs(session=mock_session)
    assert len(jobs) == 1
    job = jobs[0]

    assert job.stable_id == "lever:figma:lever_abc_1"
    assert job.company == "Figma"
    assert job.employment_type == EmploymentType.FULL_TIME
    assert job.location == "San Francisco, CA"
    assert job.application_url == "https://jobs.lever.co/figma/lever_abc_1"


@pytest.mark.asyncio
async def test_ashby_adapter_normalization():
    """Verify Ashby Job Board API normalization."""
    cfg = JobSourceConfig(name="OpenAI", source_type=SourceType.ASHBY, board_token_or_slug="openai")
    adapter = AshbyAdapter(cfg)

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "jobs": [
            {
                "id": "ashby_uuid_99",
                "title": "Platform Reliability Engineer",
                "location": "Remote",
                "employmentType": "FullTime",
                "descriptionPlain": "Build high availability clusters.",
                "jobUrl": "https://jobs.ashbyhq.com/openai/ashby_uuid_99",
                "publishedAt": "2026-11-12T12:00:00Z",
                "isRemote": True,
            }
        ]
    })

    mock_session = MagicMock()
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    jobs = await adapter.fetch_jobs(session=mock_session)
    assert len(jobs) == 1
    job = jobs[0]

    assert job.stable_id == "ashby:openai:ashby_uuid_99"
    assert job.is_remote is True
    assert job.employment_type == EmploymentType.FULL_TIME


def test_manual_and_linkedin_import_adapter():
    """Verify user-submitted job descriptions (including LinkedIn jobs) normalization."""
    adapter = ManualJobAdapter()

    job = adapter.import_job(
        title="Senior Python Backend Developer",
        company="Global Payments Inc",
        description="<h3>Role Responsibilities</h3><p>Design microservices in FastAPI and PostgreSQL.</p>",
        location="Bengaluru, India",
        application_url="https://www.linkedin.com/jobs/view/999111222/",
    )

    assert job.title == "Senior Python Backend Developer"
    assert job.company == "Global Payments Inc"
    assert job.source_type == SourceType.USER_IMPORT
    assert "FastAPI and PostgreSQL" in job.description
    assert "<h3>" not in job.description
    assert job.stable_id.startswith("manual:")


def test_deduplication_engine_stable_id_and_fingerprint(temp_db):
    """Verify deduplication avoids inserting duplicate jobs via stable ID and fingerprint fallback."""
    engine = JobDiscoveryEngine(db_path=temp_db)

    adapter = ManualJobAdapter()
    job1 = adapter.import_job(
        title="DevOps Engineer",
        company="CloudNet",
        description="Kubernetes, Terraform, AWS infrastructure management.",
        location="Remote",
    )

    # First persistence
    new1 = engine.persist_jobs([job1])
    assert len(new1) == 1

    # Attempting to persist the exact same job again must be deduplicated
    dup_new = engine.persist_jobs([job1])
    assert len(dup_new) == 0

    # Same job with slightly altered stable_id but identical content fingerprint
    job1_diff_id = adapter.import_job(
        title="DevOps Engineer",
        company="CloudNet",
        description="Kubernetes, Terraform, AWS infrastructure management.",
        location="Remote",
    )
    job1_diff_id.stable_id = "manual:different_fake_id_123"

    dup_fp = engine.persist_jobs([job1_diff_id])
    assert len(dup_fp) == 0
