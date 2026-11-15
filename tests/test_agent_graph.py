"""
Unit and integration tests for AutoBot v2 LangGraph Agent State Machine.
"""

from typing import List
import pytest

from src.agent.edges import after_advance_edge, after_record_edge, should_apply_edge
from src.agent.graph import build_job_agent_graph, create_initial_state, run_agent
from src.agent.nodes.advance import AdvanceNode
from src.agent.nodes.apply import ApplyNode
from src.agent.nodes.evaluate import EvaluateNode
from src.agent.nodes.filter import FilterNode
from src.agent.nodes.record import RecordNode
from src.agent.nodes.search import SearchNode
from src.agent.state import AgentState, ApplicationOutcome, JobPosting
from src.memory.models import JobMatchEvaluation
from src.storage.db import (
    end_session,
    get_stats,
    init_db,
    is_already_applied,
    save_application,
    start_session,
)
from src.utils.config import AppConfig


# ── Storage / DB Unit Tests ────────────────────────────────────────

def test_storage_database_operations(tmp_path):
    """Verify SQLite CRUD, deduplication, and session tracking."""
    db_file = str(tmp_path / "test_storage.db")
    init_db(db_file)

    session_id = start_session(db_file)
    assert session_id is not None

    # Initially not applied
    assert not is_already_applied("job-101", db_path=db_file)

    # Save applied job
    save_application(
        job_id="job-101",
        job_title="Backend Engineer",
        company="Stripe",
        location="Remote",
        apply_type="easy_apply",
        match_score=0.92,
        status="applied",
        url="https://linkedin.com/jobs/view/101",
        notes="High match",
        db_path=db_file,
    )

    # Now deduplication should catch it
    assert is_already_applied("job-101", db_path=db_file)

    # Save skipped job
    save_application(
        job_id="job-102",
        job_title="Staff Manager",
        company="OldCorp",
        location="NY",
        apply_type="external",
        match_score=0.30,
        status="skipped",
        url="https://linkedin.com/jobs/view/102",
        notes="Blacklisted company",
        db_path=db_file,
    )

    stats = get_stats(db_file)
    assert stats["applied"] == 1
    assert stats["skipped"] == 1

    end_session(session_id, applied=1, skipped=1, failed=0, db_path=db_file)


# ── Node Unit Tests ────────────────────────────────────────────────

def test_search_node():
    """Verify SearchNode discovers and appends jobs to unprocessed_jobs."""
    mock_jobs = [
        JobPosting(job_id="1", title="Python Engineer", company="CorpA"),
        JobPosting(job_id="2", title="FastAPI Engineer", company="CorpB"),
    ]

    def mock_provider(kw, loc, page):
        return mock_jobs

    node = SearchNode(search_provider=mock_provider)
    initial_state = {
        "current_keyword": "Python",
        "location": "India",
        "current_page": 1,
        "unprocessed_jobs": [],
    }

    result = node(initial_state)
    assert len(result["unprocessed_jobs"]) == 2
    assert result["unprocessed_jobs"][0].job_id == "1"


def test_filter_node(tmp_path):
    """Verify FilterNode checks duplicate jobs, company blacklists, and keyword blacklists."""
    db_file = str(tmp_path / "test_filter.db")
    init_db(db_file)

    # Seed an already applied job
    save_application(
        job_id="applied-1",
        job_title="Old Job",
        company="SomeCo",
        location="Remote",
        apply_type="easy_apply",
        match_score=0.8,
        status="applied",
        url="",
        db_path=db_file,
    )

    node = FilterNode(
        blacklist_companies=["BlacklistedCorp"],
        blacklist_keywords=["15+ years", "Principal"],
        db_path=db_file,
    )

    # 1. Test already applied
    state_applied = {
        "unprocessed_jobs": [JobPosting(job_id="applied-1", title="Dev", company="SafeCo")],
    }
    res1 = node(state_applied)
    assert "Already applied" in res1["skip_reason"]

    # 2. Test blacklisted company
    state_blk_comp = {
        "unprocessed_jobs": [JobPosting(job_id="valid-2", title="Dev", company="BlacklistedCorp")],
    }
    res2 = node(state_blk_comp)
    assert "matches blacklist" in res2["skip_reason"]

    # 3. Test blacklisted keyword in title
    state_blk_kw = {
        "unprocessed_jobs": [JobPosting(job_id="valid-3", title="Principal Architect", company="SafeCo")],
    }
    res3 = node(state_blk_kw)
    assert "blacklisted keyword" in res3["skip_reason"]

    # 4. Test clean qualifying job
    state_clean = {
        "unprocessed_jobs": [JobPosting(job_id="valid-4", title="Python Engineer", company="GoodCo")],
    }
    res4 = node(state_clean)
    assert res4["skip_reason"] is None
    assert res4["current_job"].job_id == "valid-4"


def test_evaluate_node():
    """Verify EvaluateNode triggers semantic evaluation and applies min_match_score threshold."""
    class MockMatcher:
        min_match_score = 0.60

        def evaluate_job(self, job_title, company, job_description):
            if "Senior" in job_title:
                return JobMatchEvaluation(
                    job_title=job_title,
                    company=company,
                    match_score=0.85,
                    is_match=True,
                    summary_reason="Great fit",
                )
            return JobMatchEvaluation(
                job_title=job_title,
                company=company,
                match_score=0.40,
                is_match=False,
                summary_reason="Poor fit",
            )

    node = EvaluateNode(matcher=MockMatcher())

    # High match test
    state_match = {
        "current_job": JobPosting(job_id="1", title="Senior Python Dev", company="A"),
        "min_match_score": 0.60,
        "skip_reason": None,
    }
    res_high = node(state_match)
    assert res_high["skip_reason"] is None
    assert res_high["current_evaluation"].is_match is True

    # Low match test
    state_low = {
        "current_job": JobPosting(job_id="2", title="Junior Intern", company="B"),
        "min_match_score": 0.60,
        "skip_reason": None,
    }
    res_low = node(state_low)
    assert "below threshold" in res_low["skip_reason"]


def test_apply_node():
    """Verify ApplyNode handles dry_run and live execution."""
    job = JobPosting(job_id="1", title="Backend Lead", company="TechInc")

    # 1. Dry run
    node_dry = ApplyNode()
    res_dry = node_dry({"current_job": job, "dry_run": True, "applied_count": 0})
    assert res_dry["last_outcome"] == ApplicationOutcome.DRY_RUN
    assert res_dry["applied_count"] == 1

    # 2. Live with mock executor success
    node_live = ApplyNode(executor=lambda j, cl: True)
    res_live = node_live({"current_job": job, "dry_run": False, "applied_count": 5})
    assert res_live["last_outcome"] == ApplicationOutcome.APPLIED
    assert res_live["applied_count"] == 6

    # 3. Live with mock executor failure
    node_fail = ApplyNode(executor=lambda j, cl: False)
    res_fail = node_fail({"current_job": job, "dry_run": False, "failed_count": 2})
    assert res_fail["last_outcome"] == ApplicationOutcome.FAILED
    assert res_fail["failed_count"] == 3


def test_record_node(tmp_path):
    """Verify RecordNode saves result to database, updates counts, and resets registers."""
    db_file = str(tmp_path / "test_record.db")
    init_db(db_file)
    node = RecordNode(db_path=db_file)

    job = JobPosting(job_id="j1", title="Software Eng", company="Acme")
    eval_res = JobMatchEvaluation(
        job_title="Software Eng",
        company="Acme",
        match_score=0.90,
        is_match=True,
    )

    state = {
        "current_job": job,
        "current_evaluation": eval_res,
        "last_outcome": ApplicationOutcome.APPLIED,
        "skipped_count": 0,
        "history": [],
    }

    result = node(state)
    assert result["current_job"] is None
    assert result["current_evaluation"] is None
    assert len(result["history"]) == 1
    assert result["history"][0].status == ApplicationOutcome.APPLIED

    # Check persistence in DB
    assert is_already_applied("j1", db_path=db_file)


def test_advance_node():
    """Verify AdvanceNode pages through results and steps across search keywords."""
    node = AdvanceNode()

    # 1. Step to next page
    state_page = {
        "current_page": 1,
        "max_pages": 3,
        "keywords": ["Python", "Rust"],
        "keyword_index": 0,
        "current_keyword": "Python",
    }
    res1 = node(state_page)
    assert res1["current_page"] == 2
    assert res1["is_complete"] is False

    # 2. Pages exhausted, step to next keyword
    state_kw = {
        "current_page": 3,
        "max_pages": 3,
        "keywords": ["Python", "Rust"],
        "keyword_index": 0,
        "current_keyword": "Python",
    }
    res2 = node(state_kw)
    assert res2["current_page"] == 1
    assert res2["keyword_index"] == 1
    assert res2["current_keyword"] == "Rust"
    assert res2["is_complete"] is False

    # 3. Everything exhausted
    state_done = {
        "current_page": 3,
        "max_pages": 3,
        "keywords": ["Python", "Rust"],
        "keyword_index": 1,
        "current_keyword": "Rust",
    }
    res3 = node(state_done)
    assert res3["is_complete"] is True


# ── Edge Routing Tests ─────────────────────────────────────────────

def test_routing_edges():
    """Verify conditional edge routing decisions."""
    # should_apply_edge
    assert should_apply_edge({"skip_reason": "blacklist"}) == "record"
    assert should_apply_edge({
        "skip_reason": None,
        "current_evaluation": JobMatchEvaluation(
            job_title="", company="", match_score=0.8, is_match=True
        ),
    }) == "apply"
    assert should_apply_edge({
        "skip_reason": None,
        "current_evaluation": JobMatchEvaluation(
            job_title="", company="", match_score=0.4, is_match=False
        ),
    }) == "record"

    # after_record_edge
    assert after_record_edge({"applied_count": 10, "max_applications": 10}) == "end"
    assert after_record_edge({
        "applied_count": 2,
        "max_applications": 10,
        "unprocessed_jobs": [JobPosting(job_id="2", title="", company="")],
    }) == "filter"
    assert after_record_edge({
        "applied_count": 2,
        "max_applications": 10,
        "unprocessed_jobs": [],
    }) == "advance"

    # after_advance_edge
    assert after_advance_edge({"is_complete": True}) == "end"
    assert after_advance_edge({"is_complete": False}) == "search"


# ── End-to-End LangGraph Execution Tests ───────────────────────────

def test_compiled_graph_full_execution(tmp_path):
    """Verify the assembled LangGraph runs end-to-end, filters, applies, and terminates."""
    db_file = str(tmp_path / "test_graph.db")
    init_db(db_file)

    class StubMatcher:
        min_match_score = 0.60

        def evaluate_job(self, job_title, company, job_description):
            is_match = "Python" in job_title
            return JobMatchEvaluation(
                job_title=job_title,
                company=company,
                match_score=0.85 if is_match else 0.40,
                is_match=is_match,
                summary_reason="Match" if is_match else "Mismatch",
            )

    def stub_search_provider(kw, loc, page):
        if page == 1:
            return [
                JobPosting(job_id="101", title="Python Engineer", company="Google"),
                JobPosting(job_id="102", title="Java Legacy", company="LegacyCorp"),
            ]
        return []

    graph = build_job_agent_graph(
        matcher=StubMatcher(),
        search_provider=stub_search_provider,
        blacklist_companies=["BlacklistedCorp"],
        blacklist_keywords=["10+ years"],
        db_path=db_file,
    )

    initial_state = {
        "keywords": ["Python"],
        "keyword_index": 0,
        "current_keyword": "Python",
        "location": "Remote",
        "current_page": 1,
        "max_pages": 1,
        "unprocessed_jobs": [],
        "current_job": None,
        "current_evaluation": None,
        "skip_reason": None,
        "applied_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "max_applications": 5,
        "min_match_score": 0.60,
        "dry_run": True,
        "history": [],
        "status_message": "Init",
        "is_complete": False,
    }

    final_state = graph.invoke(initial_state)

    # 1 job should have been applied (Python Engineer), 1 skipped (Java Legacy)
    assert final_state["applied_count"] == 1
    assert final_state["skipped_count"] == 1
    assert len(final_state["history"]) == 2

    # Database must reflect the recorded applications
    stats = get_stats(db_file)
    assert stats["dry_run"] == 1
    assert stats["skipped"] == 1


@pytest.mark.asyncio
async def test_run_agent_dry_run_entrypoint(tmp_path):
    """Verify run_agent high-level entrypoint completes cleanly with summary telemetry."""
    db_file = str(tmp_path / "test_run_agent.db")

    mock_jobs = [
        JobPosting(job_id="201", title="Python Backend Lead", company="Meta"),
    ]

    class MockQualifyingMatcher:
        min_match_score = 0.50

        def evaluate_job(self, job_title, company, job_description):
            return JobMatchEvaluation(
                job_title=job_title,
                company=company,
                match_score=0.95,
                is_match=True,
                summary_reason="Direct match",
            )

    cfg = AppConfig()
    cfg.search.keywords = ["Backend"]
    cfg.agent.max_pages = 1
    cfg.apply.max_applications = 1

    final_state = await run_agent(
        cfg=cfg,
        dry_run=True,
        search_provider=lambda kw, loc, p: mock_jobs,
        matcher=MockQualifyingMatcher(),
        db_path=db_file,
    )

    assert final_state["applied_count"] == 1
    assert is_already_applied("201", db_path=db_file)
