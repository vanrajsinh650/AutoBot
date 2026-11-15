"""
Tests for AutoBot v2 Application Preparation and Compliance Workflows.
"""

import pytest

from src.application.preparation import ApplicationPreparationService
from src.application.workflows import (
    AntiBotChallengeDetected,
    ExternalATSWorkflowManager,
    HumanApprovalRequiredError,
    LinkedInPolicyViolationError,
    LinkedInWorkflowManager,
)
from src.discovery.models import EmploymentType, NormalizedJob, SourceType
from src.storage.db import (
    get_candidate_profile,
    init_db,
    is_already_applied,
    save_candidate_profile,
    save_job_preferences,
)


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_workflows.db"
    init_db(str(db_file))
    return str(db_file)


def test_truthful_tailoring_and_materials_preparation(temp_db):
    """Verify application pack materials are derived truthfully from candidate profile."""
    save_candidate_profile(
        user_id=1,
        profile={
            "full_name": "Sarah Connor",
            "technical_skills": ["Python", "FastAPI", "Docker", "PostgreSQL"],
            "headline": "Backend Engineer",
            "experience": [
                {
                    "role": "Software Engineer",
                    "company": "Cyberdyne",
                    "bullets": ["Engineered secure API microservices in Python and FastAPI"],
                }
            ],
            "education": [{"institution": "MIT", "details": ["B.S. CS"]}],
            "phone": "+1-555-0199",
        },
        db_path=temp_db,
    )

    job = NormalizedJob(
        stable_id="ats:greenhouse:101",
        source_name="Stripe",
        source_type=SourceType.GREENHOUSE,
        title="Backend Software Engineer",
        company="Stripe",
        description="Looking for Python engineers skilled in Docker and distributed databases.",
        employment_type=EmploymentType.FULL_TIME,
        location="Remote",
        application_url="https://boards.greenhouse.io/stripe/jobs/101",
        is_remote=True,
    )

    prep = ApplicationPreparationService(db_path=temp_db)
    pack = prep.prepare_application_pack(user_id=1, job=job)

    # 1. Summary mentions real skills
    assert "Python" in pack["tailored_resume_summary"]
    # 2. Cover letter is truthful and personalized
    assert "Sarah Connor" in pack["cover_letter"]
    assert "Stripe" in pack["cover_letter"]
    # 3. Screening questions drafted with review flags
    assert len(pack["question_drafts"]) > 0
    assert all(q["requires_review"] is True for q in pack["question_drafts"])
    # 4. Checklist includes validation tasks
    assert len(pack["missing_info_checklist"]) >= 4
    # 5. Defaults to unapproved
    assert pack["user_approved"] is False


def test_human_approval_enforcement(temp_db):
    """Verify assisted submission fails immediately if user has not explicitly approved the pack."""
    prep = ApplicationPreparationService(db_path=temp_db)
    ats_manager = ExternalATSWorkflowManager(db_path=temp_db)

    job = NormalizedJob(
        stable_id="ats:lever:figma:99",
        source_name="Figma",
        source_type=SourceType.LEVER,
        title="Infrastructure Engineer",
        company="Figma",
        description="Terraform & AWS",
        application_url="https://jobs.lever.co/figma/lever_1",
    )

    # Create unapproved pack
    pack = prep.prepare_application_pack(user_id=1, job=job)
    assert pack["user_approved"] is False

    # Attempting submission must raise HumanApprovalRequiredError
    with pytest.raises(HumanApprovalRequiredError):
        ats_manager.execute_assisted_application(user_id=1, job=job, pack=pack, dry_run=False)

    # Now approve pack
    prep.set_user_approval(user_id=1, pack_id=pack["id"], approved=True)
    pack["user_approved"] = True

    # Now assisted application should execute cleanly (in dry_run)
    res = ats_manager.execute_assisted_application(user_id=1, job=job, pack=pack, dry_run=True)
    assert res["success"] is True
    assert res["status"] == "dry_run"


def test_linkedin_browser_access_policy_violation():
    """Verify strict prohibition of automated browser interaction on LinkedIn."""
    # Policy check must throw on any LinkedIn URL
    with pytest.raises(LinkedInPolicyViolationError) as exc_info:
        LinkedInWorkflowManager.verify_no_automated_browser_access("https://www.linkedin.com/jobs/view/123456")
    assert "Compliance Policy Violation" in str(exc_info.value)

    # External ATS workflow also strictly refuses LinkedIn URLs
    manager = ExternalATSWorkflowManager()
    allowed, msg = manager.check_authorization("https://www.linkedin.com/jobs/view/123456")
    assert allowed is False
    assert "strictly prohibited" in msg


def test_linkedin_assisted_workflow_requires_confirmation(temp_db):
    """Verify LinkedIn applications are tracked ONLY after candidate confirms submission."""
    manager = LinkedInWorkflowManager(db_path=temp_db)

    job = manager.import_job(
        user_id=1,
        title="Systems Architect",
        company="Global Fin",
        description="Build low latency systems",
        application_url="https://www.linkedin.com/jobs/view/889900",
    )

    # Attempting to record submission without confirmation must fail
    res_unconfirmed = manager.record_submission(
        user_id=1,
        job_stable_id=job.stable_id,
        user_confirmed=False,
    )
    assert res_unconfirmed is False
    assert is_already_applied(job.stable_id, db_path=temp_db, user_id=1) is False

    # Recording with candidate explicit confirmation succeeds
    res_confirmed = manager.record_submission(
        user_id=1,
        job_stable_id=job.stable_id,
        user_confirmed=True,
        notes="Candidate confirmed Easy Apply completed in LinkedIn app",
    )
    assert res_confirmed is True
    assert is_already_applied(job.stable_id, db_path=temp_db, user_id=1) is True


def test_external_ats_captcha_mfa_stop(temp_db):
    """Verify execution halts immediately upon encountering CAPTCHA or MFA challenges."""
    manager = ExternalATSWorkflowManager(db_path=temp_db)

    job = NormalizedJob(
        stable_id="ats:greenhouse:captcha_job",
        source_name="TechCo",
        source_type=SourceType.GREENHOUSE,
        title="Developer",
        company="TechCo",
        description="Coding",
        application_url="https://boards.greenhouse.io/techco/jobs/1?challenge=recaptcha",
    )

    pack = {"id": 1, "user_approved": True}

    with pytest.raises(AntiBotChallengeDetected) as exc_info:
        manager.execute_assisted_application(
            user_id=1,
            job=job,
            pack=pack,
            simulated_challenge="Cloudflare Turnstile",
        )
    assert "challenge detected" in str(exc_info.value).lower()
