"""
Phase 6 — Matching Quality, Skill Aliases, Negation, Scoring Formula & Evidence Reproducibility Tests.
"""

import pytest

from src.discovery.models import EmploymentType, NormalizedJob, SourceType
from src.matching.eligibility import EligibilityEngine, EligibilityStatus
from src.matching.evaluator import JobFitEvaluator, extract_requirements_heuristic
from src.matching.scorer import (
    DeterministicFitScorer,
    JobRequirementsExtracted,
    normalize_skill,
)
from src.storage.auth import create_user
from src.storage.db import (
    get_db_connection,
    init_db,
    save_candidate_profile,
    save_job_preferences,
)


def test_skill_aliases_and_abbreviations():
    """Verify skill alias normalization and match resolution."""
    assert normalize_skill("k8s") == "kubernetes"
    assert normalize_skill("Kubernetes") == "kubernetes"
    assert normalize_skill("Postgres") == "postgresql"
    assert normalize_skill("react.js") == "react"
    assert normalize_skill("golang") == "golang"
    assert normalize_skill("go") == "golang"

    # Alias matching
    assert DeterministicFitScorer._skill_matches("Kubernetes", "k8s") is True
    assert DeterministicFitScorer._skill_matches("k8s", "Kubernetes") is True
    assert DeterministicFitScorer._skill_matches("PostgreSQL", "postgres") is True
    assert DeterministicFitScorer._skill_matches("React", "react.js") is True
    assert DeterministicFitScorer._skill_matches("Go", "golang") is True


def test_abbreviation_false_positive_prevention():
    """Verify single-letter skills like 'C' or 'R' do not match arbitrary substrings."""
    # Exact single letters match only themselves
    assert DeterministicFitScorer._skill_matches("C", "C") is True
    assert DeterministicFitScorer._skill_matches("R", "R") is True

    # Single letters must NOT match words containing them
    assert DeterministicFitScorer._skill_matches("Docker", "C") is False
    assert DeterministicFitScorer._skill_matches("React", "R") is False
    assert DeterministicFitScorer._skill_matches("C", "Docker") is False

    # Java vs JavaScript separation
    assert DeterministicFitScorer._skill_matches("JavaScript", "Java") is False
    assert DeterministicFitScorer._skill_matches("Java", "JavaScript") is False


def test_negation_in_requirement_extraction():
    """Verify negated skill mentions are not extracted as required technical skills."""
    desc_with_negation = (
        "We are looking for a Senior Python Engineer. "
        "Experience with Docker and Kubernetes is required. "
        "No Java experience is needed. We do not require C++. "
        "Ruby is not required for this role."
    )
    reqs = extract_requirements_heuristic(desc_with_negation)

    # Positive requirements extracted
    assert any(s.lower() == "python" for s in reqs.required_skills)
    assert any(s.lower() == "docker" for s in reqs.required_skills)
    assert any(s.lower() == "kubernetes" for s in reqs.required_skills)

    # Negated skills must NOT be in required_skills
    assert not any(s.lower() == "java" for s in reqs.required_skills)
    assert not any(s.lower() == "c++" for s in reqs.required_skills)


def test_deterministic_scoring_formula_and_reproducibility(tmp_path):
    """
    Verify the Python scoring formula and prove that stored evaluation records
    reproduce the exact composite score mathematically from their sub-scores.
    Weights: 35% required, 25% responsibilities, 15% role, 15% exp/edu, 10% preferred.
    """
    db_file = str(tmp_path / "scoring_test.db")
    init_db(db_file)

    ok, user_id, _ = create_user("eval_candidate@example.com", "Pass123456!", db_path=db_file)
    assert ok is True

    # Set profile with Python and Docker
    save_candidate_profile(
        user_id,
        {
            "full_name": "Alex Mercer",
            "headline": "Senior Backend Architect",
            "technical_skills": ["Python", "Docker", "PostgreSQL", "FastAPI"],
            "experience": [
                {
                    "role": "Backend Engineer",
                    "company": "TechCorp",
                    "bullets": ["Designed scalable Python microservices and optimized PostgreSQL queries."],
                }
            ],
            "education": [{"degree": "B.S. Computer Science"}],
        },
        db_path=db_file,
    )

    save_job_preferences(
        user_id=user_id,
        prefs={
            "target_roles": ["Senior Backend Architect", "Python Engineer"],
            "allow_remote": True,
            "employment_types": ["full-time"],
        },
        db_path=db_file,
    )

    evaluator = JobFitEvaluator(db_path=db_file)
    job = NormalizedJob(
        stable_id="greenhouse:test:999",
        source_name="TestOrg",
        source_type=SourceType.GREENHOUSE,
        title="Senior Python Engineer",
        company="CloudCorp",
        description="We need Python, Docker, and Kubernetes experts with 3+ years experience. Build and scale REST APIs.",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote, US",
        country="United States",
        is_remote=True,
    )

    res = evaluator.evaluate_job(user_id=user_id, job=job)
    overall_score = res["overall_score"]

    # Retrieve stored evaluation from SQLite
    with get_db_connection(db_file) as conn:
        row = conn.execute("SELECT * FROM match_evaluations WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        assert row is not None

        req_score = row["required_skills_score"]
        resp_score = row["responsibilities_score"]
        role_score = row["target_role_score"]
        exp_score = row["experience_edu_score"]
        pref_score = row["preferred_skills_score"]
        stored_overall = row["overall_score"]

        # Mathematical reproduction
        reproduced_overall = round(
            (req_score * 0.35)
            + (resp_score * 0.25)
            + (role_score * 0.15)
            + (exp_score * 0.15)
            + (pref_score * 0.10),
            2,
        )

        assert abs(stored_overall - reproduced_overall) < 0.05
        assert abs(overall_score - stored_overall) < 0.05


def test_mandatory_missing_skill_penalty():
    """Verify that a candidate missing all required skills receives appropriate penalty."""
    candidate_profile = {
        "technical_skills": ["HTML", "CSS", "Photoshop"],
        "experience": [],
        "education": [],
    }
    candidate_preferences = {"target_roles": ["Frontend Designer"]}
    job_reqs = JobRequirementsExtracted(
        required_skills=["Rust", "Distributed Systems", "Raft"],
        preferred_skills=["C++"],
        responsibilities=["Implement distributed consensus algorithms"],
        min_years_experience=5.0,
    )

    breakdown = DeterministicFitScorer.calculate_score(
        candidate_profile=candidate_profile,
        candidate_preferences=candidate_preferences,
        job_title="Principal Systems Architect",
        job_reqs=job_reqs,
    )

    # 0% required skill coverage
    assert breakdown.required_skills_score == 0.0
    assert any("Missing Required Skill: Rust" in m for m in breakdown.missing_requirements)
    assert any("Missing Required Skill: Raft" in m for m in breakdown.missing_requirements)

    # Low overall composite score
    assert breakdown.overall_score < 40.0
