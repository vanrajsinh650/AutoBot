"""
Security Verification Suite for AutoBot v2.1 — Phase 3: Multi-Tenant Security & IDOR Elimination.
Verifies cross-tenant isolation, IDOR prevention on application packs and downloads,
path traversal prevention on resume uploads, and brute-force rate-limiting.
"""

from datetime import datetime
import json
from pathlib import Path
import uuid
import pytest
import pytest_asyncio
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from src.discovery.models import NormalizedJob, SourceType
from src.storage.auth import authenticate_user, create_session, create_user, reset_all_login_attempts
from src.storage.db import (
    get_db_connection,
    init_db,
    save_application,
    save_candidate_profile,
    save_job_preferences,
    save_resume_evidence,
    save_resume_version,
)
from src.web.server import create_app


@pytest_asyncio.fixture
async def client():
    """Create test client with isolated test database."""
    app = create_app()
    server = TestServer(app)
    c = TestClient(server)
    await c.start_server()
    yield c
    await c.close()


@pytest.fixture
def two_users():
    """Helper creating two distinct isolated users with tokens."""
    email_a = f"alice_{uuid.uuid4().hex[:6]}@example.com"
    email_b = f"bob_{uuid.uuid4().hex[:6]}@example.com"

    _, user_a, _ = create_user(email_a, "PasswordAlice123!")
    _, user_b, _ = create_user(email_b, "PasswordBob456!")

    token_a = create_session(user_id=user_a, email=email_a)
    token_b = create_session(user_id=user_b, email=email_b)

    return {
        "user_a": user_a,
        "email_a": email_a,
        "token_a": token_a,
        "headers_a": {"Authorization": f"Bearer {token_a}"},
        "user_b": user_b,
        "email_b": email_b,
        "token_b": token_b,
        "headers_b": {"Authorization": f"Bearer {token_b}"},
    }


@pytest.mark.asyncio
async def test_idor_application_pack_download_forbidden(client: TestClient, two_users):
    """Verify that User B cannot download User A's application pack (HTTP 403 Forbidden)."""
    headers_a = two_users["headers_a"]
    headers_b = two_users["headers_b"]

    # 1. User A imports a job
    import_resp = await client.post(
        "/api/discovery/import",
        headers=headers_a,
        json={
            "title": "Principal Architect",
            "company": "SecureCloud",
            "description": "Looking for Python, Distributed Systems, and Security specialists.",
        },
    )
    assert import_resp.status == 200
    job_data = await import_resp.json()
    stable_id = job_data["job"]["stable_id"]

    # 2. User A prepares an application pack
    prep_resp = await client.post(
        "/api/application/prepare",
        headers=headers_a,
        json={"stable_id": stable_id},
    )
    assert prep_resp.status == 200
    pack_data = await prep_resp.json()
    pack_id = pack_data["pack_id"]

    # 3. User A can download their own application pack
    dl_a = await client.get(f"/api/application/download/{pack_id}", headers=headers_a)
    assert dl_a.status == 200
    text_a = await dl_a.text()
    assert "SecureCloud" in text_a

    # 4. User B attempts to download User A's application pack (IDOR Attack)
    dl_b = await client.get(f"/api/application/download/{pack_id}", headers=headers_b)
    assert dl_b.status == 403
    err_b = await dl_b.json()
    assert "Forbidden" in err_b["error"] or "another candidate" in err_b["error"]


@pytest.mark.asyncio
async def test_idor_application_pack_approval_forbidden(client: TestClient, two_users):
    """Verify that User B cannot approve User A's application pack (HTTP 403 Forbidden)."""
    headers_a = two_users["headers_a"]
    headers_b = two_users["headers_b"]

    # User A imports and prepares pack
    import_resp = await client.post(
        "/api/discovery/import",
        headers=headers_a,
        json={
            "title": "Site Reliability Engineer",
            "company": "InfraCorp",
            "description": "Kubernetes and Python role.",
        },
    )
    assert import_resp.status == 200
    stable_id = (await import_resp.json())["job"]["stable_id"]

    prep_resp = await client.post(
        "/api/application/prepare",
        headers=headers_a,
        json={"stable_id": stable_id},
    )
    assert prep_resp.status == 200
    pack_id = (await prep_resp.json())["pack_id"]

    # User B attempts to approve User A's pack
    approve_b = await client.post(
        "/api/application/approve",
        headers=headers_b,
        json={"pack_id": pack_id, "approved": True},
    )
    assert approve_b.status == 403
    err_b = await approve_b.json()
    assert "Forbidden" in err_b["error"]


@pytest.mark.asyncio
async def test_cross_tenant_profile_and_preferences_isolation(client: TestClient, two_users):
    """Verify that profile and preference updates from User A never bleed into User B."""
    headers_a = two_users["headers_a"]
    headers_b = two_users["headers_b"]

    # User A sets proprietary profile and preferences
    await client.post(
        "/api/candidate/profile",
        headers=headers_a,
        json={"full_name": "Alice Secret Agent", "headline": "Top Secret Lead"},
    )
    await client.post(
        "/api/candidate/preferences",
        headers=headers_a,
        json={"target_roles": ["Secret Operative"], "min_salary": 250000},
    )

    # User B inspects their own profile and preferences
    resp_b_prof = await client.get("/api/candidate/profile", headers=headers_b)
    assert resp_b_prof.status == 200
    prof_b = await resp_b_prof.json()
    assert prof_b.get("full_name") != "Alice Secret Agent"
    assert prof_b.get("headline") != "Top Secret Lead"

    resp_b_prefs = await client.get("/api/candidate/preferences", headers=headers_b)
    assert resp_b_prefs.status == 200
    prefs_b = await resp_b_prefs.json()
    assert "Secret Operative" not in prefs_b.get("target_roles", [])
    assert prefs_b.get("min_salary", 0) != 250000


@pytest.mark.asyncio
async def test_cross_tenant_resume_versions_and_evidence_isolation(client: TestClient, two_users):
    """Verify that resume versions and evidence chunks are isolated per tenant."""
    user_a = two_users["user_a"]
    user_b = two_users["user_b"]
    headers_a = two_users["headers_a"]
    headers_b = two_users["headers_b"]

    # Seed User A resume version and evidence in SQLite
    v_id = save_resume_version(
        user_id=user_a,
        version_name="alice_classified_resume.pdf",
        file_path="/tmp/alice_resume.pdf",
        file_hash="dummy_hash_alice",
        parsed_data={"skills": ["Quantum Cryptography"]},
    )
    save_resume_evidence(
        user_id=user_a,
        resume_version_id=v_id,
        section="skills",
        content="Quantum Cryptography and Zero-Knowledge Proofs",
        metadata={"experience_years": 8},
    )

    # User A sees 1 version
    res_a = await client.get("/api/candidate/resumes", headers=headers_a)
    assert res_a.status == 200
    versions_a = (await res_a.json())["versions"]
    assert len(versions_a) == 1
    assert versions_a[0]["version_name"] == "alice_classified_resume.pdf"

    # User B sees 0 versions
    res_b = await client.get("/api/candidate/resumes", headers=headers_b)
    assert res_b.status == 200
    versions_b = (await res_b.json())["versions"]
    assert len(versions_b) == 0


@pytest.mark.asyncio
async def test_cross_tenant_application_history_isolation(client: TestClient, two_users):
    """Verify that applications and tracker events cannot leak across tenants."""
    user_a = two_users["user_a"]
    headers_a = two_users["headers_a"]
    headers_b = two_users["headers_b"]

    # Save application for User A
    save_application(
        job_id="job_private_alice",
        job_title="Defense Engineer",
        company="Lockheed",
        location="Classified",
        apply_type="manual",
        match_score=0.99,
        status="applied",
        url="https://example.com/apply",
        notes="Interview scheduled",
        user_id=user_a,
    )

    # User A sees 1 job
    jobs_a = await client.get("/api/jobs", headers=headers_a)
    assert jobs_a.status == 200
    assert (await jobs_a.json())["total"] == 1

    # User B sees 0 jobs
    jobs_b = await client.get("/api/jobs", headers=headers_b)
    assert jobs_b.status == 200
    assert (await jobs_b.json())["total"] == 0


@pytest.mark.asyncio
async def test_resume_upload_path_traversal_protection(client: TestClient, two_users):
    """Verify that uploading with traversal characters in filename does not escape user directory."""
    headers_a = two_users["headers_a"]
    user_a = two_users["user_a"]

    data = FormData()
    data.add_field(
        "file",
        b"%PDF-1.4 dummy pdf content",
        filename="../../../etc/evil_passwd.pdf",
        content_type="application/pdf",
    )

    resp = await client.post("/api/upload", data=data, headers=headers_a)
    assert resp.status == 200
    result = await resp.json()
    assert result["success"] is True

    # Filename must be sanitized to basename
    assert result["filename"] == "evil_passwd.pdf"
    assert ".." not in result["filename"]

    # Destination path must strictly reside in user_a's directory
    saved_path = Path(result["path"]).resolve()
    expected_dir = (Path("data/users") / str(user_a) / "resumes").resolve()
    assert str(saved_path).startswith(str(expected_dir))


def test_brute_force_rate_limiting():
    """Verify that excessive failed login attempts trigger account lockout."""
    reset_all_login_attempts()
    target_email = "victim@example.com"
    create_user(target_email, "CorrectPass123!")

    # 1. First 4 failed attempts are rejected with invalid password
    for i in range(4):
        ok, _, msg = authenticate_user(target_email, f"WrongPass_{i}")
        assert ok is False
        assert msg == "Invalid email or password."

    # 2. Fifth failed attempt records the 5th attempt
    ok, _, msg = authenticate_user(target_email, "WrongPass_5")
    assert ok is False

    # 3. Sixth attempt is blocked by brute-force lockout
    ok, _, msg = authenticate_user(target_email, "WrongPass_6")
    assert ok is False
    assert "temporarily locked" in msg

    # Even the correct password is now blocked until lockout window passes
    ok_corr, _, msg_corr = authenticate_user(target_email, "CorrectPass123!")
    assert ok_corr is False
    assert "temporarily locked" in msg_corr

    # Clean up
    reset_all_login_attempts()


@pytest.mark.asyncio
async def test_globally_shared_jobs_contain_no_candidate_pii(client: TestClient, two_users):
    """Verify that GET /api/discovery/jobs returns only job vacancies without private candidate data."""
    headers_a = two_users["headers_a"]
    headers_b = two_users["headers_b"]

    # User A imports a public job
    await client.post(
        "/api/discovery/import",
        headers=headers_a,
        json={
            "title": "Cloud Architect",
            "company": "Amazon",
            "description": "AWS cloud infrastructure role.",
            "location": "Seattle, WA",
        },
    )

    # User B queries discovered jobs
    resp_b = await client.get("/api/discovery/jobs", headers=headers_b)
    assert resp_b.status == 200
    jobs = (await resp_b.json())["jobs"]
    assert len(jobs) >= 1

    for job in jobs:
        # Check that no candidate fields exist in the job record
        assert "user_id" not in job
        assert "candidate_name" not in job
        assert "resume_summary" not in job
        assert "email" not in job
        assert "phone" not in job
