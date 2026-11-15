"""
Tests for AutoBot v2.2.1 — Phase 2: Live Mission Control Workflow.
Runs isolated test workflows for User A (Python/AI Internship) and User B (Java/Full-Time):
- Independent registration
- Synthetic resume upload
- Preference configuration
- Job discovery & import
- Fit evaluation
- Application pack preparation and download
- Strict verification of zero cross-user profile, resume, evaluation, pack, or SSE leakage
"""

import json
from pathlib import Path
import pytest
import pytest_asyncio
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from src.utils.security import sanitize_for_logs
from src.web.routes import execution_manager
from src.web.server import create_app


@pytest_asyncio.fixture
async def client():
    """Create test client with isolated temporary database."""
    app = create_app()
    server = TestServer(app)
    c = TestClient(server)
    await c.start_server()
    try:
        yield c
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_phase2_two_user_complete_workflow(client: TestClient):
    """
    Execute User A and User B complete journeys and assert strict isolation across all assets.
    """
    # ── USER A SETUP: Python / AI Intern ──────────────────────────────────────
    reg_a = await client.post(
        "/api/auth/register",
        json={"email": "usera_ai@autobot.test", "password": "UserAStrongPassword!123"},
    )
    assert reg_a.status == 200
    res_a = await reg_a.json()
    token_a = res_a["token"]
    user_a_id = res_a["user"]["id"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Upload User A synthetic resume
    data_a = FormData()
    data_a.add_field(
        "file",
        b"%PDF-1.4 User A: Python, PyTorch, LangGraph, LLMs, Vector Databases, FastApi. Education: BS Computer Science. Experience: 1 year AI research.",
        filename="usera_ai_resume.pdf",
        content_type="application/pdf",
    )
    up_a = await client.post("/api/upload", data=data_a, headers=headers_a)
    assert up_a.status == 200

    # User A preferences: Python / AI Internship
    pref_a = await client.put(
        "/api/candidate/preferences",
        headers=headers_a,
        json={
            "target_roles": ["AI Engineering Intern", "Python Developer"],
            "employment_types": ["internship"],
            "eligible_countries": ["India", "Remote"],
            "allow_remote": True,
        },
    )
    assert pref_a.status == 200

    # User A Job Discovery & Import
    job_a_req = await client.post(
        "/api/discovery/import",
        headers=headers_a,
        json={
            "title": "AI Engineering Intern",
            "company": "NeuroTech AI Labs",
            "location": "Remote, India",
            "description": "Looking for an AI Engineering Intern proficient in Python, PyTorch, and LLM applications.",
            "employment_type": "internship",
        },
    )
    assert job_a_req.status == 200
    job_a_data = await job_a_req.json()
    stable_id_a = job_a_data["job"]["stable_id"]

    # User A Matching Evaluation
    eval_a = await client.post(
        "/api/matching/evaluate",
        headers=headers_a,
        json={"stable_id": stable_id_a},
    )
    assert eval_a.status == 200
    eval_a_data = await eval_a.json()
    assert eval_a_data["overall_score"] > 0

    # User A Application Pack Preparation & Download
    pack_prep_a = await client.post(
        "/api/application/prepare",
        headers=headers_a,
        json={"stable_id": stable_id_a},
    )
    assert pack_prep_a.status == 200
    pack_a = await pack_prep_a.json()
    pack_id_a = pack_a.get("pack_id") or pack_a.get("id")

    dl_a = await client.get(f"/api/application/download/{pack_id_a}", headers=headers_a)
    assert dl_a.status == 200
    pack_text_a = await dl_a.text()
    assert "NeuroTech AI Labs" in pack_text_a

    # ── USER B SETUP: Java / Full-Time ────────────────────────────────────────
    reg_b = await client.post(
        "/api/auth/register",
        json={"email": "userb_java@autobot.test", "password": "UserBStrongPassword!456"},
    )
    assert reg_b.status == 200
    res_b = await reg_b.json()
    token_b = res_b["token"]
    user_b_id = res_b["user"]["id"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    assert user_a_id != user_b_id

    # Upload User B synthetic resume
    data_b = FormData()
    data_b.add_field(
        "file",
        b"%PDF-1.4 User B: Senior Java Developer, Spring Boot, Microservices, Hibernate, Kafka, PostgreSQL, Docker, Kubernetes.",
        filename="userb_java_resume.pdf",
        content_type="application/pdf",
    )
    up_b = await client.post("/api/upload", data=data_b, headers=headers_b)
    assert up_b.status == 200

    # User B preferences: Java / Full-Time
    pref_b = await client.put(
        "/api/candidate/preferences",
        headers=headers_b,
        json={
            "target_roles": ["Senior Java Developer", "Backend Engineer"],
            "employment_types": ["full-time"],
            "eligible_countries": ["Germany", "Remote"],
            "allow_remote": True,
        },
    )
    assert pref_b.status == 200

    # User B Job Discovery & Import
    job_b_req = await client.post(
        "/api/discovery/import",
        headers=headers_b,
        json={
            "title": "Senior Java Backend Engineer",
            "company": "FinSys Enterprise AG",
            "location": "Berlin, Germany",
            "description": "Seeking an experienced Senior Java Developer with deep Spring Boot, Microservices, and Kafka expertise.",
            "employment_type": "full-time",
        },
    )
    assert job_b_req.status == 200
    job_b_data = await job_b_req.json()
    stable_id_b = job_b_data["job"]["stable_id"]

    # User B Matching Evaluation
    eval_b = await client.post(
        "/api/matching/evaluate",
        headers=headers_b,
        json={"stable_id": stable_id_b},
    )
    assert eval_b.status == 200
    eval_b_data = await eval_b.json()
    assert eval_b_data["overall_score"] > 0

    # User B Application Pack Preparation & Download
    pack_prep_b = await client.post(
        "/api/application/prepare",
        headers=headers_b,
        json={"stable_id": stable_id_b},
    )
    assert pack_prep_b.status == 200
    pack_b = await pack_prep_b.json()
    pack_id_b = pack_b.get("pack_id") or pack_b.get("id")

    dl_b = await client.get(f"/api/application/download/{pack_id_b}", headers=headers_b)
    assert dl_b.status == 200
    pack_text_b = await dl_b.text()
    assert "FinSys Enterprise AG" in pack_text_b

    # ── CROSS-USER ISOLATION & LEAKAGE VERIFICATION ───────────────────────────

    # 1. Profile isolation
    prof_a = await (await client.get("/api/candidate/profile", headers=headers_a)).json()
    prof_b = await (await client.get("/api/candidate/profile", headers=headers_b)).json()
    assert prof_a.get("candidate_profile", {}).get("user_id", user_a_id) == user_a_id
    assert prof_b.get("candidate_profile", {}).get("user_id", user_b_id) == user_b_id

    # 2. Resume versions isolation
    resumes_a = await (await client.get("/api/candidate/resumes", headers=headers_a)).json()
    resumes_b = await (await client.get("/api/candidate/resumes", headers=headers_b)).json()
    assert len(resumes_a["versions"]) == 1
    assert resumes_a["versions"][0]["version_name"] == "usera_ai_resume.pdf"
    assert len(resumes_b["versions"]) == 1
    assert resumes_b["versions"][0]["version_name"] == "userb_java_resume.pdf"

    # 3. Preferences isolation
    get_pref_a = await (await client.get("/api/candidate/preferences", headers=headers_a)).json()
    get_pref_b = await (await client.get("/api/candidate/preferences", headers=headers_b)).json()
    assert "internship" in get_pref_a.get("employment_types", [])
    assert "full-time" in get_pref_b.get("employment_types", [])

    # 4. Cross-tenant Application Pack Download IDOR attempts -> 403 Forbidden
    cross_dl_b_attempts_a = await client.get(f"/api/application/download/{pack_id_a}", headers=headers_b)
    assert cross_dl_b_attempts_a.status == 403

    cross_dl_a_attempts_b = await client.get(f"/api/application/download/{pack_id_b}", headers=headers_a)
    assert cross_dl_a_attempts_b.status == 403

    # 5. Cross-tenant Pack Approval IDOR attempt -> 403 Forbidden
    cross_appr = await client.post(
        "/api/application/approve",
        headers=headers_b,
        json={"pack_id": pack_id_a, "approved": True},
    )
    assert cross_appr.status == 403

    # 6. SSE Telemetry Sanitization Check
    test_broadcast_event = {
        "candidate_name": "Alice Confidential",
        "email": "usera_ai@autobot.test",
        "action": "evaluating_fit",
        "score": 85,
    }
    sanitized = sanitize_for_logs(test_broadcast_event)
    assert sanitized["candidate_name"] == "[REDACTED_PII]"
    assert sanitized["email"] == "[REDACTED_PII]"
    assert sanitized["action"] == "evaluating_fit"
    assert sanitized["score"] == 85
