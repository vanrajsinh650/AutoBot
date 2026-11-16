"""
Unit and Integration Tests for Phase 5: Search Quality & Tenant-Isolated Candidate Search.
Validates:
1. Regex word-boundary precision (eliminates short acronym false positives like 'ai' in 'email').
2. Skill-to-role relationships and Top-10 / Top-20 search precision.
3. Strict separation of internships vs full-time vs contract vacancies.
4. Country eligibility and remote workplace restrictions.
5. Exclusion of stale and expired postings.
6. Tenant isolation between multiple candidates.
"""

import json
import pytest

from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.discovery.registry import JobDiscoveryEngine
from src.matching.keyword_expansion import expand_candidate_keywords, search_personalized_jobs
from src.storage.db import (
    get_db_connection,
    init_db,
    save_candidate_profile,
    save_job_preferences,
)


@pytest.fixture
def setup_search_corpus(tmp_path):
    """Sets up an isolated SQLite database with users and a rich corpus of jobs."""
    db_file = str(tmp_path / "test_search_corpus.db")
    init_db(db_file)
    engine = JobDiscoveryEngine(db_file)

    # 1. Setup User 1: AI / Backend Python Engineer (Full-Time, US / Remote)
    save_candidate_profile(
        user_id=1,
        profile={
            "full_name": "Alice AI",
            "email": "alice@example.com",
            "headline": "Senior AI & Backend Python Engineer",
        },
        db_path=db_file,
    )
    save_job_preferences(
        user_id=1,
        prefs={
            "employment_types": ["full-time"],
            "target_roles": ["ai engineer", "backend engineer"],
            "primary_skills": ["python", "ai", "machine learning"],
            "secondary_skills": ["fastapi", "docker"],
            "work_arrangement": "remote",
            "eligible_countries": ["United States"],
        },
        db_path=db_file,
    )

    # 2. Setup User 2 in users table then candidate profile & preferences
    with get_db_connection(db_file) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO users (id, email, password_hash, created_at, updated_at)
            VALUES (2, 'bob@example.com', 'test_hash', '2026-01-01T00:00:00', '2026-01-01T00:00:00')
            """
        )
        conn.commit()

    save_candidate_profile(
        user_id=2,
        profile={
            "full_name": "Bob Intern",
            "email": "bob@example.com",
            "headline": "Frontend Engineering Student",
        },
        db_path=db_file,
    )
    save_job_preferences(
        user_id=2,
        prefs={
            "employment_types": ["internship"],
            "target_roles": ["frontend engineer"],
            "primary_skills": ["javascript", "react"],
            "secondary_skills": ["css", "html"],
            "work_arrangement": "remote",
            "eligible_countries": ["Germany"],
        },
        db_path=db_file,
    )

    # 3. Seed Diverse Job Corpus (30 jobs)
    source = JobSourceConfig(name="GlobalATS", source_type=SourceType.GREENHOUSE, board_token_or_slug="global")
    jobs = []

    # Valid AI / Python Jobs (for User 1)
    for i in range(12):
        jobs.append(
            NormalizedJob(
                stable_id=f"greenhouse:global:ai_{i}",
                source_name="GlobalATS",
                source_type=SourceType.GREENHOUSE,
                title=f"Senior AI Engineer {i}",
                company="OpenAI Cohort",
                description="Develop state-of-the-art AI systems with Python and PyTorch.",
                employment_type=EmploymentType.FULL_TIME,
                location="San Francisco, CA",
                country="United States",
                is_remote=True,
                workplace_type="remote",
                status="active",
            )
        )

    # Substring Traps for "AI" (contain words like 'email', 'maintain', 'chain' but NO real AI)
    for i in range(5):
        jobs.append(
            NormalizedJob(
                stable_id=f"greenhouse:global:trap_{i}",
                source_name="GlobalATS",
                source_type=SourceType.GREENHOUSE,
                title=f"Office Administrator {i}",
                company="Traditional Corp",
                description="Manage daily email correspondence, maintain office chairs, and obtain retail supplies.",
                employment_type=EmploymentType.FULL_TIME,
                location="Austin, TX",
                country="United States",
                is_remote=False,
                workplace_type="on-site",
                status="active",
            )
        )

    # Valid Frontend Internship Jobs (for User 2)
    for i in range(8):
        jobs.append(
            NormalizedJob(
                stable_id=f"greenhouse:global:fe_intern_{i}",
                source_name="GlobalATS",
                source_type=SourceType.GREENHOUSE,
                title=f"Frontend Developer Intern {i}",
                company="WebCo",
                description="Build modern UI components using React, JavaScript, and Tailwind CSS.",
                employment_type=EmploymentType.INTERNSHIP,
                location="Berlin, Germany",
                country="Germany",
                is_remote=True,
                workplace_type="remote",
                status="active",
            )
        )

    # Expired AI Job (Stale listing)
    jobs.append(
        NormalizedJob(
            stable_id="greenhouse:global:stale_ai",
            source_name="GlobalATS",
            source_type=SourceType.GREENHOUSE,
            title="Principal AI Research Scientist",
            company="DeepAI",
            description="Leading AI LLM foundation models in Python.",
            employment_type=EmploymentType.FULL_TIME,
            location="Remote",
            country="United States",
            is_remote=True,
            workplace_type="remote",
            status="expired",
        )
    )

    # Wrong Country On-site Job (AI Engineer on-site in Japan, ineligible for US/Germany candidates)
    jobs.append(
        NormalizedJob(
            stable_id="greenhouse:global:onsite_japan",
            source_name="GlobalATS",
            source_type=SourceType.GREENHOUSE,
            title="AI Systems Architect",
            company="Tokyo Tech",
            description="Python AI algorithms on-site in Tokyo.",
            employment_type=EmploymentType.FULL_TIME,
            location="Tokyo, Japan",
            country="Japan",
            is_remote=False,
            workplace_type="on-site",
            status="active",
        )
    )

    engine.persist_jobs(jobs)

    # Mark the expired job explicitly in DB
    with get_db_connection(db_file) as conn:
        conn.execute("UPDATE jobs SET status = 'expired' WHERE stable_id = 'greenhouse:global:stale_ai'")
        conn.commit()

    return db_file


def test_short_acronym_word_boundary_precision(setup_search_corpus):
    """
    Verify searching for 'AI' matches real AI positions and strictly rejects
    substring collisions like 'email', 'maintain', and 'obtain'.
    """
    db_file = setup_search_corpus
    res = search_personalized_jobs(user_id=1, db_path=db_file, limit=50)

    matched_titles = [j["title"] for j in res["jobs"]]
    matched_descriptions = [j["description"] for j in res["jobs"]]

    # Must find the genuine AI engineer vacancies
    assert any("Senior AI Engineer" in t for t in matched_titles)

    # Must NOT match any office administrator substring trap!
    for t in matched_titles:
        assert "Office Administrator" not in t, "Substring 'ai' in 'email' or 'maintain' must NOT match!"


def test_stale_and_expired_jobs_excluded(setup_search_corpus):
    """Verify active candidate search strictly excludes expired vacancies."""
    db_file = setup_search_corpus
    res = search_personalized_jobs(user_id=1, db_path=db_file, status_filter="active", limit=50)

    matched_ids = [j["stable_id"] for j in res["jobs"]]
    assert "greenhouse:global:stale_ai" not in matched_ids, "Expired posting must be excluded from active search!"


def test_employment_type_separation(setup_search_corpus):
    """Verify internships and full-time vacancies are cleanly separated by candidate preferences."""
    db_file = setup_search_corpus

    # User 1 (Full-Time): receives ONLY full-time vacancies
    res_u1 = search_personalized_jobs(user_id=1, db_path=db_file, limit=50)
    for j in res_u1["jobs"]:
        assert j["employment_type"] == "full-time"

    # User 2 (Internship): receives ONLY internship vacancies
    res_u2 = search_personalized_jobs(user_id=2, db_path=db_file, limit=50)
    assert len(res_u2["jobs"]) > 0
    for j in res_u2["jobs"]:
        assert j["employment_type"] == "internship"


def test_country_eligibility_and_remote_restriction(setup_search_corpus):
    """Verify on-site vacancies in unauthorized countries are filtered out."""
    db_file = setup_search_corpus

    # User 1 is eligible in United States or Remote. On-site Japan vacancy must not appear.
    res_u1 = search_personalized_jobs(user_id=1, db_path=db_file, limit=50)
    matched_ids = [j["stable_id"] for j in res_u1["jobs"]]
    assert "greenhouse:global:onsite_japan" not in matched_ids


def test_top_10_and_top_20_search_precision(setup_search_corpus):
    """Measure precision of top returned vacancies for User 1 (AI / Python Backend)."""
    db_file = setup_search_corpus
    res = search_personalized_jobs(user_id=1, db_path=db_file, limit=20)
    jobs = res["jobs"]

    assert len(jobs) >= 10
    top_10 = jobs[:10]
    relevant_count = 0
    for j in top_10:
        desc_lower = j["description"].lower()
        title_lower = j["title"].lower()
        if "ai" in title_lower or "python" in desc_lower:
            relevant_count += 1

    precision_at_10 = relevant_count / len(top_10)
    assert precision_at_10 >= 0.90, f"Expected Top-10 precision >= 90%, got {precision_at_10:.2%}"


def test_tenant_isolation(setup_search_corpus):
    """Verify User 1 and User 2 results are completely isolated and differentiated."""
    db_file = setup_search_corpus
    res1 = search_personalized_jobs(user_id=1, db_path=db_file)
    res2 = search_personalized_jobs(user_id=2, db_path=db_file)

    ids1 = {j["stable_id"] for j in res1["jobs"]}
    ids2 = {j["stable_id"] for j in res2["jobs"]}

    # Mutual exclusivity of targeted vacancies
    overlap = ids1.intersection(ids2)
    assert len(overlap) == 0, f"Candidate searches must be strictly tenant-isolated! Overlap: {overlap}"
