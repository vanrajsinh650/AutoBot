"""
Tests for AutoBot v2 Eligibility Filtering and Deterministic 0–100 Resume Fit Scoring.
"""

import pytest

from src.discovery.models import EmploymentType, NormalizedJob, SourceType
from src.matching.eligibility import EligibilityEngine, EligibilityStatus
from src.matching.evaluator import JobFitEvaluator
from src.matching.scorer import (
    DISCLAIMER_NOTICE,
    DeterministicFitScorer,
    JobRequirementsExtracted,
)
from src.storage.db import init_db, save_candidate_profile, save_job_preferences


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_matching.db"
    init_db(str(db_file))
    return str(db_file)


def test_internship_and_fulltime_filtering():
    """Verify strict employment type eligibility classification."""
    # Job 1: Internship
    job_intern = NormalizedJob(
        stable_id="test:1",
        source_name="Test",
        source_type=SourceType.MANUAL,
        title="Software Engineer Intern",
        company="StartupX",
        description="Internship for students",
        employment_type=EmploymentType.INTERNSHIP,
        location="Remote",
        is_remote=True,
    )

    # Job 2: Full-Time
    job_full = NormalizedJob(
        stable_id="test:2",
        source_name="Test",
        source_type=SourceType.MANUAL,
        title="Backend Engineer",
        company="TechInc",
        description="Full-time role",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote",
        is_remote=True,
    )

    # Case A: Candidate prefers INTERNSHIP ONLY
    prefs_intern_only = {"employment_types": ["internship"], "eligible_countries": ["India", "Remote"]}
    st1, fails1, _ = EligibilityEngine.evaluate(job_intern, prefs_intern_only)
    assert st1 == EligibilityStatus.ELIGIBLE
    assert len(fails1) == 0

    st2, fails2, exp2 = EligibilityEngine.evaluate(job_full, prefs_intern_only)
    assert st2 == EligibilityStatus.INELIGIBLE
    assert any("internship only" in f for f in fails2)

    # Case B: Candidate prefers FULL-TIME ONLY
    prefs_full_only = {"employment_types": ["full-time"], "eligible_countries": ["India", "Remote"]}
    st3, fails3, _ = EligibilityEngine.evaluate(job_intern, prefs_full_only)
    assert st3 == EligibilityStatus.INELIGIBLE
    assert any("full-time only" in f for f in fails3)

    st4, fails4, _ = EligibilityEngine.evaluate(job_full, prefs_full_only)
    assert st4 == EligibilityStatus.ELIGIBLE


def test_country_eligibility_filters():
    """Verify location matching and geographic boundary rules."""
    prefs = {
        "employment_types": ["full-time"],
        "eligible_countries": ["India"],
    }

    # On-site role in Germany -> Ineligible
    job_de = NormalizedJob(
        stable_id="test:de",
        source_name="Test",
        source_type=SourceType.MANUAL,
        title="Software Engineer",
        company="BerlinSoft",
        description="On-site in Berlin",
        employment_type=EmploymentType.FULL_TIME,
        location="Berlin, Germany",
        country="Germany",
        is_remote=False,
    )
    status_de, fails_de, _ = EligibilityEngine.evaluate(job_de, prefs)
    assert status_de == EligibilityStatus.INELIGIBLE
    assert any("Germany" in f or "Location mismatch" in f for f in fails_de)

    # On-site role in India -> Eligible
    job_in = NormalizedJob(
        stable_id="test:in",
        source_name="Test",
        source_type=SourceType.MANUAL,
        title="Software Engineer",
        company="IndiTech",
        description="Office in Bengaluru",
        employment_type=EmploymentType.FULL_TIME,
        location="Bengaluru, India",
        country="India",
        is_remote=False,
    )
    status_in, fails_in, _ = EligibilityEngine.evaluate(job_in, prefs)
    assert status_in == EligibilityStatus.ELIGIBLE

    # Unknown location -> Uncertain
    job_unknown = NormalizedJob(
        stable_id="test:unk",
        source_name="Test",
        source_type=SourceType.MANUAL,
        title="Software Engineer",
        company="Stealth",
        description="Confidential project",
        employment_type=EmploymentType.FULL_TIME,
        location="",
        is_remote=False,
    )
    status_unk, _, exp_unk = EligibilityEngine.evaluate(job_unknown, prefs)
    assert status_unk == EligibilityStatus.UNCERTAIN


def test_deterministic_scoring_exact_python_math():
    """
    Verify the 0-100 fit score follows the mathematical formula:
    35% required + 25% responsibilities + 15% target role + 15% experience/edu + 10% preferred.
    """
    candidate_profile = {
        "technical_skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "Git"],
        "primary_skills": ["Python", "FastAPI"],
        "secondary_skills": ["PostgreSQL", "Docker"],
        "headline": "Senior Backend Engineer",
        "experience": [
            {
                "role": "Senior Backend Engineer",
                "company": "CloudWorks",
                "bullets": [
                    "Built microservices in Python and FastAPI",
                    "Maintained PostgreSQL databases and Docker containers",
                ],
            },
            {
                "role": "Software Developer",
                "company": "AppTech",
                "bullets": ["Developed REST APIs and unit tests"],
            },
        ],
        "education": [{"institution": "Tech University", "details": ["B.S. in Computer Science"]}],
    }

    candidate_prefs = {
        "target_roles": ["Senior Backend Engineer", "Python Developer"],
    }

    job_reqs = JobRequirementsExtracted(
        required_skills=["Python", "FastAPI", "Docker"],  # 3 of 3 match -> 100% * 0.35 = 35.0
        preferred_skills=["Kubernetes", "AWS"],            # 0 of 2 match -> 0% * 0.10 = 0.0
        responsibilities=["Built microservices in Python", "Maintained databases"],
        min_years_experience=3.0,
        required_degree="bachelor",
    )

    breakdown = DeterministicFitScorer.calculate_score(
        candidate_profile=candidate_profile,
        candidate_preferences=candidate_prefs,
        job_title="Senior Backend Engineer",
        job_reqs=job_reqs,
    )

    # Assert individual scores
    assert breakdown.required_skills_score == 100.0
    assert breakdown.preferred_skills_score == 0.0
    assert breakdown.target_role_score == 100.0

    # Assert composite calculation
    expected_composite = (
        (breakdown.required_skills_score * 0.35)
        + (breakdown.responsibilities_score * 0.25)
        + (breakdown.target_role_score * 0.15)
        + (breakdown.experience_edu_score * 0.15)
        + (breakdown.preferred_skills_score * 0.10)
    )
    assert abs(breakdown.overall_score - round(expected_composite, 2)) < 0.01

    # Assert missing requirements tracking
    assert any("Kubernetes" in r for r in breakdown.missing_requirements)


def test_missing_evidence_and_disclaimer(temp_db):
    """Verify that evaluations properly record missing skills and include non-ATS disclaimer."""
    evaluator = JobFitEvaluator(db_path=temp_db)

    # Register candidate with limited skills
    save_candidate_profile(
        user_id=1,
        profile={
            "full_name": "Junior Dev",
            "technical_skills": ["HTML", "CSS"],
            "headline": "Frontend Junior",
            "experience": [],
        },
        db_path=temp_db,
    )

    job = NormalizedJob(
        stable_id="job:ml_lead",
        source_name="Test",
        source_type=SourceType.MANUAL,
        title="Principal AI Research Engineer",
        company="DeepAI Labs",
        description="Requires 10+ years experience in PyTorch, CUDA, distributed training, and C++.",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote",
        is_remote=True,
    )

    evaluation = evaluator.evaluate_job(user_id=1, job=job)

    # Missing requirements must be populated
    assert len(evaluation["missing_requirements"]) > 0

    # Score must be low
    assert evaluation["overall_score"] < 50.0

    # Notice disclaimer must exist
    assert "NOTICE:" in evaluation["explanation"]
    assert "NOT a hiring probability" in evaluation["explanation"]
    assert DISCLAIMER_NOTICE == evaluation["disclaimer"]
