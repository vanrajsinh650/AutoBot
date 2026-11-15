"""
Comprehensive verification and regression tests for AutoBot v2.
Covers multi-user data isolation, boundary matching, country resolution,
tracker status updates, and security authorization fixes.
"""

import json
import uuid
import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from src.discovery.models import EmploymentType, NormalizedJob, SourceType
from src.matching.eligibility import EligibilityEngine, EligibilityStatus, resolve_job_country
from src.matching.scorer import (
    DeterministicFitScorer,
    JobRequirementsExtracted,
)
from src.storage.auth import create_session, create_user, validate_session
from src.storage.db import (
    get_applications,
    init_db,
    is_already_applied,
    save_application,
    update_application_status,
)
from src.web.server import create_app


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_fixes.db"
    init_db(str(db_file))
    return str(db_file)


@pytest_asyncio.fixture
async def client():
    app = create_app()
    server = TestServer(app)
    c = TestClient(server)
    await c.start_server()
    yield c
    await c.close()


def test_multi_user_same_job_no_overwrite(temp_db):
    """Verify two users applying to the same job do not overwrite each other's data."""
    ok1, u1_id, _ = create_user("alice@example.com", "Password123!", db_path=temp_db)
    ok2, u2_id, _ = create_user("bob@example.com", "Password123!", db_path=temp_db)
    assert ok1 and ok2

    job_id = "common_posting_999"

    # User 1 applies for job_id
    save_application(
        job_id=job_id,
        job_title="Lead DevOps Engineer",
        company="GlobalTech",
        location="Remote",
        apply_type="Easy Apply",
        status="applied",
        match_score=0.88,
        url="https://example.com/job/common",
        user_id=u1_id,
        db_path=temp_db,
    )

    # User 2 applies for the EXACT SAME job_id
    save_application(
        job_id=job_id,
        job_title="Lead DevOps Engineer",
        company="GlobalTech",
        location="Remote",
        apply_type="Easy Apply",
        status="submitted",
        match_score=0.95,
        url="https://example.com/job/common",
        user_id=u2_id,
        db_path=temp_db,
    )

    # Assert both records exist independently
    u1_apps = get_applications(user_id=u1_id, db_path=temp_db)
    u2_apps = get_applications(user_id=u2_id, db_path=temp_db)

    assert len(u1_apps) == 1
    assert len(u2_apps) == 1

    # User 1's record must be untouched by User 2's insert
    assert u1_apps[0]["job_id"] == job_id
    assert u1_apps[0]["status"] == "applied"
    assert u1_apps[0]["match_score"] == 0.88

    # User 2's record reflects User 2's values
    assert u2_apps[0]["job_id"] == job_id
    assert u2_apps[0]["status"] == "submitted"
    assert u2_apps[0]["match_score"] == 0.95

    # Check is_already_applied per-user isolation
    assert is_already_applied(job_id, user_id=u1_id, db_path=temp_db) is True
    assert is_already_applied(job_id, user_id=u2_id, db_path=temp_db) is True
    assert is_already_applied(job_id, user_id=9999, db_path=temp_db) is False


def test_scorer_empty_required_skills():
    """Verify scorer does not crash with TypeError when job has empty required skills."""
    scorer = DeterministicFitScorer()

    candidate_profile = {
        "technical_skills": ["Python", "FastAPI", "Docker"],
        "target_roles": ["Backend Developer"],
        "years_of_experience": 3,
        "education": ["BS in Computer Science"],
    }

    job_reqs = JobRequirementsExtracted(
        required_skills=[],  # Empty required skills list
        preferred_skills=["Docker", "AWS"],
        responsibilities=["Build web services", "Maintain CI/CD pipelines"],
        min_years_experience=2,
    )

    # Slicing or indexing empty required skills must not raise TypeError
    prefs = {"target_roles": ["Backend Developer"]}
    eval_result = scorer.calculate_score(
        candidate_profile=candidate_profile,
        candidate_preferences=prefs,
        job_title="Backend Developer",
        job_reqs=job_reqs,
    )

    assert eval_result.overall_score >= 0.0
    assert eval_result.overall_score <= 100.0
    assert eval_result.required_skills_score >= 0.0
    assert "Required Skills:" in eval_result.explanation


def test_scorer_short_skill_boundaries():
    """Verify short skill names (C, R, Go) don't match substrings inside other words."""
    scorer = DeterministicFitScorer()

    # Candidate knows Docker, React, Security, Rust, GoDaddy (none are C, R, or Go)
    candidate_profile = {
        "technical_skills": ["Docker", "React", "Rust", "Security", "GoDaddy"],
        "target_roles": ["Software Engineer"],
        "years_of_experience": 2,
    }

    job_reqs = JobRequirementsExtracted(
        required_skills=["C", "R", "Go"],
        preferred_skills=[],
        responsibilities=["System programming"],
    )

    prefs = {"target_roles": ["Software Engineer"]}
    eval_result = scorer.calculate_score(
        candidate_profile=candidate_profile,
        candidate_preferences=prefs,
        job_title="Software Engineer",
        job_reqs=job_reqs,
    )

    # Substring matching must NOT match "C" in "Docker"/"React"/"Security"
    # or "R" in "React"/"Rust", or "Go" in "GoDaddy"
    assert not any("Required Skill:" in r for r in eval_result.matched_requirements)
    assert any("Missing Required Skill: C" in r for r in eval_result.missing_requirements)
    assert any("Missing Required Skill: R" in r for r in eval_result.missing_requirements)
    assert any("Missing Required Skill: Go" in r for r in eval_result.missing_requirements)
    assert eval_result.required_skills_score == 0.0

    # Now add explicit "C" and "Go"
    candidate_profile["technical_skills"].extend(["C", "Go"])
    eval_result2 = scorer.calculate_score(
        candidate_profile=candidate_profile,
        candidate_preferences=prefs,
        job_title="Software Engineer",
        job_reqs=job_reqs,
    )
    assert any("Required Skill: C" in r for r in eval_result2.matched_requirements)
    assert any("Required Skill: Go" in r for r in eval_result2.matched_requirements)
    assert any("Missing Required Skill: R" in r for r in eval_result2.missing_requirements)


def test_location_and_country_resolution():
    """Verify US state codes, tech cities, and country abbreviations resolve accurately."""
    assert resolve_job_country("San Francisco, CA") == "united states"
    assert resolve_job_country("New York, NY") == "united states"
    assert resolve_job_country("Austin, TX") == "united states"
    assert resolve_job_country("Seattle, WA") == "united states"
    assert resolve_job_country("Chicago, IL") == "united states"
    assert resolve_job_country("London, UK") == "united kingdom"
    assert resolve_job_country("Bengaluru, Karnataka, India") == "india"
    assert resolve_job_country("Berlin, Germany") == "germany"
    assert resolve_job_country("Toronto, ON, Canada") == "canada"
    assert resolve_job_country("Remote - US") == "united states"


def test_eligibility_city_state_formats():
    """Verify jobs with city/state locations are correctly identified as eligible."""
    job_sf = NormalizedJob(
        stable_id="sf:1",
        source_name="Greenhouse",
        source_type=SourceType.GREENHOUSE,
        title="Software Engineer",
        company="Stripe",
        description="Core infra",
        location="San Francisco, CA",
        country="United States",
        employment_type=EmploymentType.FULL_TIME,
        is_remote=False,
    )

    prefs_us = {
        "employment_types": ["full-time"],
        "eligible_countries": ["United States"],
    }

    status, fails, exp = EligibilityEngine.evaluate(job_sf, prefs_us)
    assert status == EligibilityStatus.ELIGIBLE
    assert len(fails) == 0

    prefs_de = {
        "employment_types": ["full-time"],
        "eligible_countries": ["Germany"],
    }
    status_de, fails_de, _ = EligibilityEngine.evaluate(job_sf, prefs_de)
    assert status_de == EligibilityStatus.INELIGIBLE
    assert any("Location mismatch" in f for f in fails_de)


@pytest.mark.asyncio
async def test_delete_account_security_and_protection(client: TestClient):
    """Verify unauthenticated delete fails (401) and system user 1 is protected (403)."""
    # 1. Unauthenticated request must return 401
    resp_unauth = await client.post("/api/privacy/delete-account")
    assert resp_unauth.status == 401

    # 2. Authenticated user 1 attempt must return 403 (system user protected)
    session_user1 = create_session(user_id=1, email="system@autobot.internal")
    resp_sys = await client.post(
        "/api/privacy/delete-account",
        headers={"Authorization": f"Bearer {session_user1}"},
    )
    assert resp_sys.status == 403

    # 3. Create regular user and authenticate
    eph_email = f"ephemeral_{uuid.uuid4().hex[:8]}@example.com"
    reg_resp = await client.post(
        "/api/auth/register",
        json={"email": eph_email, "password": "SecurePassword123!"},
    )
    assert reg_resp.status == 200
    reg_data = await reg_resp.json()
    user_token = reg_data["token"]

    # 4. Regular user deleting their own account succeeds
    del_resp = await client.post(
        "/api/privacy/delete-account",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert del_resp.status == 200
    del_data = await del_resp.json()
    assert del_data["success"] is True


@pytest.mark.asyncio
async def test_update_application_status_tracker(client: TestClient):
    """Verify application status transitions (interview, offer, rejected) via API."""
    unique_email = f"tracker_{uuid.uuid4().hex[:8]}@example.com"
    reg_resp = await client.post(
        "/api/auth/register",
        json={"email": unique_email, "password": "Password123!"},
    )
    assert reg_resp.status == 200
    token = (await reg_resp.json())["token"]
    sess = validate_session(token)
    user_id = sess["user_id"]
    headers = {"Authorization": f"Bearer {token}"}

    # Save an application first
    job_id = f"test_job_{uuid.uuid4().hex[:6]}"
    save_application(
        job_id=job_id,
        job_title="Backend Engineer",
        company="StatusCorp",
        location="Remote",
        apply_type="Easy Apply",
        status="submitted",
        match_score=0.85,
        url="https://example.com/status-1",
        user_id=user_id,
        db_path="logs/autobot.db",
    )

    # Transition to interview
    resp_interview = await client.post(
        "/api/tracker/status",
        headers=headers,
        json={"job_id": job_id, "status": "interview", "notes": "HR screen passed"},
    )
    assert resp_interview.status == 200
    data_int = await resp_interview.json()
    assert data_int["status"] == "interview"

    # Transition to offer
    resp_offer = await client.post(
        "/api/tracker/status",
        headers=headers,
        json={"job_id": job_id, "status": "offer", "notes": "Received offer"},
    )
    assert resp_offer.status == 200

    # Invalid status should return 400
    resp_bad = await client.post(
        "/api/tracker/status",
        headers=headers,
        json={"job_id": job_id, "status": "invalid_status_xyz"},
    )
    assert resp_bad.status == 400


@pytest.mark.asyncio
async def test_application_pack_download_and_explanation(client: TestClient):
    """Verify application pack download endpoint and match explanation retrieval."""
    unique_email = f"pack_{uuid.uuid4().hex[:8]}@example.com"
    reg_resp = await client.post(
        "/api/auth/register",
        json={"email": unique_email, "password": "Password123!"},
    )
    assert reg_resp.status == 200
    token = (await reg_resp.json())["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Import job
    import_resp = await client.post(
        "/api/discovery/import",
        headers=headers,
        json={
            "title": "Senior Python Architect",
            "company": "FastScale",
            "location": "Remote",
            "description": "Looking for Python, FastAPI, and Distributed Systems expertise.",
        },
    )
    stable_id = (await import_resp.json())["job"]["stable_id"]

    # Prepare pack
    prep_resp = await client.post(
        "/api/application/prepare",
        headers=headers,
        json={"stable_id": stable_id},
    )
    assert prep_resp.status == 200
    prep_data = await prep_resp.json()
    pack_id = prep_data["id"]

    # Verify job match explanation is present
    assert "job_match_explanation" in prep_data
    assert len(prep_data["job_match_explanation"]) > 0

    # Download pack (JSON)
    dl_resp = await client.get(
        f"/api/application/download/{pack_id}?format=json",
        headers=headers,
    )
    assert dl_resp.status == 200
    assert "attachment" in dl_resp.headers.get("Content-Disposition", "")
    dl_data = await dl_resp.json()
    assert dl_data["id"] == pack_id
    assert dl_data["job_match_explanation"] == prep_data["job_match_explanation"]

    # Download pack (Plain Text)
    dl_text_resp = await client.get(
        f"/api/application/download/{pack_id}",
        headers=headers,
    )
    assert dl_text_resp.status == 200
    text_val = await dl_text_resp.text()
    assert "=== AUTOBOT APPLICATION PACK ===" in text_val
    assert "JOB MATCH EXPLANATION" in text_val
