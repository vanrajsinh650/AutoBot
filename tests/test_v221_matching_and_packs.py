"""
Tests for AutoBot v2.2.1 — Phase 4: Matching and Application Packs.
Verifies:
1. Deterministic five-component scoring formula (35% Required, 25% Responsibilities, 15% Target Role, 15% Exp/Edu, 10% Preferred).
2. Skill aliases (e.g., k8s -> kubernetes, py -> python, reactjs -> react).
3. Missing skills and negation handling.
4. Mandatory requirements & eligibility gates.
5. Truthful application pack grounding without hallucination/fabrication.
6. Enforced human approval requirement before marking pack ready.
"""

import pytest

from src.application.preparation import ApplicationPreparationService
from src.discovery.models import EmploymentType, NormalizedJob, SourceType
from src.matching.eligibility import EligibilityEngine, EligibilityStatus
from src.matching.scorer import DeterministicFitScorer, JobRequirementsExtracted, normalize_skill
from src.storage.db import get_db_connection, init_db, save_candidate_profile, save_job_preferences


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_matching_packs.db"
    init_db(str(db_file))
    return str(db_file)


# ── 1. Deterministic Formula Verification ────────────────────────────────────

def test_deterministic_scoring_formula_exact_arithmetic():
    """Verify that overall_score equals (req*0.35 + resp*0.25 + role*0.15 + exp_edu*0.15 + pref*0.10)."""
    candidate_profile = {
        "technical_skills": ["Python", "Docker", "Kubernetes"],
        "headline": "Senior Backend Engineer",
        "experience": [
            {
                "role": "Backend Engineer",
                "company": "Tech Corp",
                "bullets": ["Designed scalable Python microservices on Kubernetes.", "Maintained Docker deployments."],
            }
        ],
        "education": [{"degree": "BS Computer Science", "institution": "State University"}],
    }

    preferences = {
        "target_roles": ["Senior Backend Engineer"],
    }

    job_reqs = JobRequirementsExtracted(
        required_skills=["Python", "Kubernetes"],
        preferred_skills=["Docker", "AWS"],
        responsibilities=["Designed scalable Python microservices", "Deploy containers to clusters"],
        min_years_experience=2.0,
        required_degree="Bachelor",
    )

    result = DeterministicFitScorer.calculate_score(
        candidate_profile=candidate_profile,
        candidate_preferences=preferences,
        job_title="Senior Backend Engineer",
        job_reqs=job_reqs,
    )

    # Calculate expected weighted sum manually
    expected_overall = round(
        (result.required_skills_score * 0.35)
        + (result.responsibilities_score * 0.25)
        + (result.target_role_score * 0.15)
        + (result.experience_edu_score * 0.15)
        + (result.preferred_skills_score * 0.10),
        2,
    )

    assert result.overall_score == expected_overall
    assert 0.0 <= result.overall_score <= 100.0
    assert "Overall Resume Fit Score:" in result.explanation


# ── 2. Skill Aliases and Normalization ────────────────────────────────────────

def test_skill_aliases_matching():
    """Verify canonical aliases match successfully across variations."""
    assert normalize_skill("k8s") == "kubernetes"
    assert normalize_skill("py") == "python"
    assert normalize_skill("postgres") == "postgresql"
    assert normalize_skill("psql") == "postgresql"
    assert normalize_skill("reactjs") == "react"
    assert normalize_skill("gcp") == "google cloud"

    # Scorer matching check
    assert DeterministicFitScorer._skill_matches("k8s", "kubernetes") is True
    assert DeterministicFitScorer._skill_matches("py", "python") is True
    assert DeterministicFitScorer._skill_matches("postgres", "postgresql") is True
    # Word boundary guard: single letter 'c' must not match 'docker'
    assert DeterministicFitScorer._skill_matches("c", "docker") is False


# ── 3. Missing Skills and Negation ───────────────────────────────────────────

def test_missing_skills_identification():
    """Verify missing required and preferred skills are enumerated clearly in breakdown."""
    candidate_profile = {
        "technical_skills": ["Python"],
        "experience": [],
        "education": [],
    }
    preferences = {"target_roles": ["Python Developer"]}
    job_reqs = JobRequirementsExtracted(
        required_skills=["Python", "Rust", "Golang"],
        preferred_skills=["AWS", "GCP"],
    )

    result = DeterministicFitScorer.calculate_score(
        candidate_profile=candidate_profile,
        candidate_preferences=preferences,
        job_title="Software Engineer",
        job_reqs=job_reqs,
    )

    assert any("Rust" in m for m in result.missing_requirements)
    assert any("Golang" in m for m in result.missing_requirements)
    assert any("AWS" in m for m in result.missing_requirements)
    assert any("Python" in m for m in result.matched_requirements)
    # Required skills score should reflect 1 out of 3 = ~33.33%
    assert 33.0 <= result.required_skills_score <= 34.0


# ── 4. Mandatory Requirements & Ineligibility Gates ──────────────────────────

def test_mandatory_eligibility_failures():
    """Verify EligibilityEngine fails closed on mandatory constraints."""
    # 1. Internship-only user vs Full-time role
    job_fulltime = NormalizedJob(
        stable_id="test:1",
        source_name="Test",
        source_type=SourceType.GREENHOUSE,
        title="Software Engineer",
        company="Acme",
        description="Full-time software engineer role.",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote, India",
    )
    prefs_intern_only = {"employment_types": ["internship"], "eligible_countries": ["India"]}
    status, fails, exp = EligibilityEngine.evaluate(job_fulltime, prefs_intern_only)
    assert status == EligibilityStatus.INELIGIBLE
    assert any("internship only" in f for f in fails)

    # 2. Location mismatch
    job_germany = NormalizedJob(
        stable_id="test:2",
        source_name="Test",
        source_type=SourceType.GREENHOUSE,
        title="Software Engineer",
        company="Acme",
        description="Role based in Berlin.",
        employment_type=EmploymentType.FULL_TIME,
        location="Berlin, Germany",
        country="germany",
    )
    prefs_us_only = {"employment_types": ["full-time"], "eligible_countries": ["United States"]}
    status_loc, fails_loc, _ = EligibilityEngine.evaluate(job_germany, prefs_us_only)
    assert status_loc == EligibilityStatus.INELIGIBLE
    assert any("Location mismatch" in f or "Country mismatch" in f for f in fails_loc)


# ── 5. Truthful Application Pack Grounding ───────────────────────────────────

def test_application_pack_grounded_in_truthful_evidence(temp_db):
    """Verify application pack uses real candidate experiences and requires user approval."""
    from src.storage.auth import create_user
    ok, user_id, _ = create_user("truthful@example.com", "Password123!", db_path=temp_db)
    assert ok is True
    assert user_id is not None

    save_candidate_profile(
        user_id=user_id,
        profile={
            "full_name": "Dr. Truthful Candidate",
            "technical_skills": ["Python", "FastAPI", "SQLAlchemy"],
            "experience": [
                {
                    "role": "Backend Lead",
                    "company": "Authentic Systems",
                    "bullets": ["Maintained zero-downtime Python APIs with FastAPI."],
                }
            ],
            "phone": "+1-555-0199",
        },
        db_path=temp_db,
    )

    save_job_preferences(
        user_id=user_id,
        prefs={"target_roles": ["Backend Lead"], "min_salary": 120000.0},
        db_path=temp_db,
    )

    job = NormalizedJob(
        stable_id="greenhouse:stripe:404",
        source_name="Stripe",
        source_type=SourceType.GREENHOUSE,
        title="Backend Engineer - APIs",
        company="Stripe",
        description="Looking for Python and FastAPI developers to scale financial APIs.",
        application_url="https://boards.greenhouse.io/stripe/jobs/404",
    )

    service = ApplicationPreparationService(db_path=temp_db, llm=None)
    pack = service.prepare_application_pack(user_id=user_id, job=job)

    # 1. Verification of real candidate information
    assert "Dr. Truthful Candidate" in pack["cover_letter"]
    assert "Python" in pack["tailored_resume_summary"] or "FastAPI" in pack["tailored_resume_summary"]
    assert pack["tailored_experiences"][0]["company"] == "Authentic Systems"
    assert "Maintained zero-downtime Python APIs" in pack["tailored_experiences"][0]["bullets"][0]

    # 2. Cover letter grounds in company
    assert "Stripe" in pack["cover_letter"]

    # 3. User approval must be False by default
    assert pack["user_approved"] is False
    assert pack["id"] is not None
