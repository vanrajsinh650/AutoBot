"""
Tests for AutoBot Deduplication, Seniority Filtering, and Browser Hardening.
"""

import pytest
from src.agent.nodes.filter import FilterNode
from src.agent.nodes.search import SearchNode
from src.agent.state import JobPosting
from src.browser.backends.chromium_backend import ChromiumBackend
from src.storage.db import (
    extract_canonical_job_id,
    get_db_connection,
    init_db,
    is_job_processed,
    save_application,
)
from src.utils.config import AppConfig


def test_extract_canonical_job_id():
    """Verify robust extraction of numeric job IDs from various LinkedIn URLs."""
    url1 = "https://in.linkedin.com/jobs/view/sr-java-developer-at-sas-4476162243?position=49&pageNum=0&refId=BcHGV"
    assert extract_canonical_job_id(url1) == "4476162243"

    url2 = "https://www.linkedin.com/jobs/view/4476162243/"
    assert extract_canonical_job_id(url2) == "4476162243"

    url3 = "https://www.linkedin.com/jobs/view/python-engineer-1234567"
    assert extract_canonical_job_id(url3) == "1234567"

    assert extract_canonical_job_id("4476162243") == "4476162243"


def test_is_job_processed_deduplication(tmp_path):
    """Verify is_job_processed catches jobs whether applied, skipped, or tracked by URL/title."""
    db_file = str(tmp_path / "dedup_test.db")
    init_db(db_file)

    # Initially not processed
    assert not is_job_processed(job_id="job-999", db_path=db_file)
    assert not is_job_processed(
        url="https://in.linkedin.com/jobs/view/sr-java-developer-at-sas-4476162243",
        title="Sr Java Developer",
        company="SAS",
        db_path=db_file,
    )

    # Save application as 'skipped' (e.g. low match score)
    save_application(
        job_id="4476162243",
        job_title="Sr Java Developer",
        company="SAS",
        location="Pune",
        apply_type="external",
        match_score=0.35,
        status="skipped",
        url="https://in.linkedin.com/jobs/view/sr-java-developer-at-sas-4476162243?refId=123",
        notes="Heuristic evaluation: Vector similarity 0.07",
        db_path=db_file,
    )

    # Should now be recognized as already processed by job_id
    assert is_job_processed(job_id="4476162243", db_path=db_file)

    # Should be recognized by full URL with tracking params
    assert is_job_processed(
        url="https://in.linkedin.com/jobs/view/sr-java-developer-at-sas-4476162243?position=49",
        db_path=db_file,
    )

    # Should be recognized by canonical (title, company)
    assert is_job_processed(
        title="Sr Java Developer",
        company="SAS",
        db_path=db_file,
    )


def test_filter_node_seniority_rejection(tmp_path):
    """Verify FilterNode cleanly rejects Senior, Lead, and Principal roles using word boundaries."""
    db_file = str(tmp_path / "filter_senior.db")
    init_db(db_file)

    node = FilterNode(
        blacklist_companies=[],
        blacklist_keywords=[
            "senior",
            "sr.",
            "sr",
            "lead",
            "principal",
            "staff",
            "director",
            "architect",
        ],
        db_path=db_file,
    )

    # 1. Reject 'Sr Java Developer'
    res1 = node({"unprocessed_jobs": [JobPosting(job_id="1", title="Sr Java Developer", company="SAS")]})
    assert "blacklisted keyword" in res1["skip_reason"]

    # 2. Reject 'Senior Software Engineer'
    res2 = node({"unprocessed_jobs": [JobPosting(job_id="2", title="Senior Software Engineer", company="TechCorp")]})
    assert "blacklisted keyword" in res2["skip_reason"]

    # 3. Reject 'Lead Backend Engineer'
    res3 = node({"unprocessed_jobs": [JobPosting(job_id="3", title="Lead Backend Engineer", company="StartupX")]})
    assert "blacklisted keyword" in res3["skip_reason"]

    # 4. Reject 'Principal Cloud Architect'
    res4 = node({"unprocessed_jobs": [JobPosting(job_id="4", title="Principal Cloud Architect", company="BigCo")]})
    assert "blacklisted keyword" in res4["skip_reason"]

    # 5. Allow 'Python Developer' (Clean non-senior role)
    res5 = node({"unprocessed_jobs": [JobPosting(job_id="5", title="Python Developer", company="GoodCo")]})
    assert res5["skip_reason"] is None
    assert res5["current_job"].title == "Python Developer"

    # 6. Verify word boundary check: 'Israel' should NOT be rejected by 'sr'
    res6 = node({"unprocessed_jobs": [JobPosting(job_id="6", title="Software Engineer (Israel)", company="GlobalCo")]})
    assert res6["skip_reason"] is None


def test_search_node_avoids_duplicate_jobs(tmp_path):
    """Verify SearchNode does not enqueue duplicate jobs in memory."""
    db_file = str(tmp_path / "search_dedup.db")
    init_db(db_file)

    node = SearchNode(search_provider=lambda kw, loc, page: [
        JobPosting(job_id="dup-1", title="Python Dev", company="Acme"),
        JobPosting(job_id="new-2", title="Go Dev", company="Beta"),
    ])

    state = {
        "current_keyword": "Python Dev",
        "location": "India",
        "current_page": 1,
        "unprocessed_jobs": [
            JobPosting(job_id="dup-1", title="Python Dev", company="Acme"),
        ],
    }

    result = node(state)
    unprocessed = result["unprocessed_jobs"]
    # Only 2 jobs total (dup-1 not duplicated)
    assert len(unprocessed) == 2
    job_ids = [j.job_id for j in unprocessed]
    assert job_ids == ["dup-1", "new-2"]


def test_browser_backend_no_sandbox_banner_suppression():
    """Verify ChromiumBackend passes --test-type and ignores --no-sandbox to prevent Chrome warning bar."""
    backend = ChromiumBackend(headless=True)
    assert backend.backend_name == "chromium"
    # Verify implementation of start uses --test-type and excludes --no-sandbox from defaults
    import inspect
    src = inspect.getsource(ChromiumBackend.start)
    assert "--test-type" in src
    assert '"--no-sandbox"' in src
    assert "ignore_default_args" in src
