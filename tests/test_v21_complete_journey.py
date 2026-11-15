"""
Phase 7 — End-to-End Isolated Multi-User Workflow Test.
Verifies complete end-to-end lifecycle for two independent candidates:
registration -> resume upload -> preferences -> discovery -> match evaluation ->
application pack generation -> approval -> pack download -> status tracking ->
cross-tenant boundary assertions & GDPR account deletion isolation.
"""

from pathlib import Path
import pytest
import pytest_asyncio
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

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
async def test_complete_isolated_two_user_journey(client: TestClient):
    """
    Run complete isolated candidate journey for Alice and Bob in parallel.
    Assert zero cross-tenant leakage across every touchpoint.
    """
    # ── 1. REGISTRATION ──────────────────────────────────────────────
    resp_a = await client.post(
        "/api/auth/register",
        json={"email": "alice_e2e@example.com", "password": "AliceStrongPassword!123"},
    )
    assert resp_a.status == 200
    resp_a_json = await resp_a.json()
    token_a = resp_a_json["token"]
    user_a_id = resp_a_json["user"]["id"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    resp_b = await client.post(
        "/api/auth/register",
        json={"email": "bob_e2e@example.com", "password": "BobStrongPassword!123"},
    )
    assert resp_b.status == 200
    resp_b_json = await resp_b.json()
    token_b = resp_b_json["token"]
    user_b_id = resp_b_json["user"]["id"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    assert user_a_id != user_b_id

    # ── 2. RESUME UPLOAD ─────────────────────────────────────────────
    # Alice uploads Python/Distributed Systems resume
    data_a = FormData()
    data_a.add_field(
        "file",
        b"%PDF-1.4 Alice Mercer Resume: Python, Distributed Systems, Cloud Architecture",
        filename="alice_resume.pdf",
        content_type="application/pdf",
    )
    up_a = await client.post("/api/upload", data=data_a, headers=headers_a)
    assert up_a.status == 200
    assert (await up_a.json())["filename"] == "alice_resume.pdf"

    # Bob uploads Mobile/Frontend resume
    data_b = FormData()
    data_b.add_field(
        "file",
        b"%PDF-1.4 Bob Jenkins Resume: React, TypeScript, Mobile UI/UX",
        filename="bob_resume.pdf",
        content_type="application/pdf",
    )
    up_b = await client.post("/api/upload", data=data_b, headers=headers_b)
    assert up_b.status == 200
    assert (await up_b.json())["filename"] == "bob_resume.pdf"

    # Verify resume isolation
    resumes_a = await (await client.get("/api/candidate/resumes", headers=headers_a)).json()
    resumes_b = await (await client.get("/api/candidate/resumes", headers=headers_b)).json()
    assert len(resumes_a["versions"]) == 1
    assert resumes_a["versions"][0]["version_name"] == "alice_resume.pdf"
    assert len(resumes_b["versions"]) == 1
    assert resumes_b["versions"][0]["version_name"] == "bob_resume.pdf"

    # ── 3. PREFERENCES ───────────────────────────────────────────────
    pref_a = await client.put(
        "/api/candidate/preferences",
        headers=headers_a,
        json={"target_roles": ["Principal Architect"], "eligible_countries": ["United States"], "allow_remote": True},
    )
    assert pref_a.status == 200

    pref_b = await client.put(
        "/api/candidate/preferences",
        headers=headers_b,
        json={"target_roles": ["Frontend Developer"], "eligible_countries": ["United Kingdom"], "allow_remote": False},
    )
    assert pref_b.status == 200

    # ── 4. JOB DISCOVERY & IMPORT ─────────────────────────────────────
    import_a = await client.post(
        "/api/discovery/import",
        headers=headers_a,
        json={
            "title": "Principal Distributed Systems Architect",
            "company": "CloudMatrix Inc",
            "description": "Looking for Python, Distributed Systems, and High Availability engineers. Remote US.",
            "location": "Remote, US",
        },
    )
    assert import_a.status == 200
    stable_id_a = (await import_a.json())["job"]["stable_id"]

    import_b = await client.post(
        "/api/discovery/import",
        headers=headers_b,
        json={
            "title": "Senior Frontend Developer",
            "company": "DesignHub UK",
            "description": "Looking for React, TypeScript, and CSS specialists in London.",
            "location": "London, UK",
        },
    )
    assert import_b.status == 200
    stable_id_b = (await import_b.json())["job"]["stable_id"]

    # ── 5. MATCH EVALUATION ───────────────────────────────────────────
    eval_a = await client.post(
        "/api/matching/evaluate",
        headers=headers_a,
        json={"stable_id": stable_id_a},
    )
    assert eval_a.status == 200
    eval_data_a = await eval_a.json()
    assert eval_data_a["overall_score"] > 0
    assert "NOTICE:" in eval_data_a["explanation"]

    eval_b = await client.post(
        "/api/matching/evaluate",
        headers=headers_b,
        json={"stable_id": stable_id_b},
    )
    assert eval_b.status == 200
    eval_data_b = await eval_b.json()
    assert eval_data_b["overall_score"] > 0

    # ── 6. APPLICATION PACK PREPARATION & APPROVAL ────────────────────
    pack_res_a = await client.post(
        "/api/application/prepare",
        headers=headers_a,
        json={"stable_id": stable_id_a},
    )
    assert pack_res_a.status == 200
    pack_a = await pack_res_a.json()
    pack_a_id = pack_a.get("pack_id") or pack_a.get("id")
    assert pack_a["user_approved"] is False

    # Alice explicitly reviews and approves her pack
    appr_a = await client.post(
        "/api/application/approve",
        headers=headers_a,
        json={"pack_id": pack_a_id, "approved": True},
    )
    assert appr_a.status == 200

    pack_res_b = await client.post(
        "/api/application/prepare",
        headers=headers_b,
        json={"stable_id": stable_id_b},
    )
    assert pack_res_b.status == 200
    pack_b = await pack_res_b.json()
    pack_b_id = pack_b.get("pack_id") or pack_b.get("id")

    # ── 7. CROSS-TENANT IDOR ATTEMPTS (MUST BE BLOCKED) ───────────────
    # Bob attempts to download Alice's pack -> 403 Forbidden
    bob_dl_alice = await client.get(f"/api/application/download/{pack_a_id}", headers=headers_b)
    assert bob_dl_alice.status == 403

    # Bob attempts to approve Alice's pack -> 403 Forbidden
    bob_appr_alice = await client.post(
        "/api/application/approve",
        headers=headers_b,
        json={"pack_id": pack_a_id, "approved": True},
    )
    assert bob_appr_alice.status == 403

    # Alice successfully downloads her own pack
    alice_dl_own = await client.get(f"/api/application/download/{pack_a_id}", headers=headers_a)
    assert alice_dl_own.status == 200
    alice_pack_content = await alice_dl_own.text()
    assert "CloudMatrix Inc" in alice_pack_content

    # ── 8. APPLICATION TRACKER ISOLATION ──────────────────────────────
    # Alice records submission
    stat_a = await client.post(
        "/api/tracker/status",
        headers=headers_a,
        json={"job_id": stable_id_a, "status": "submitted", "notes": "Submitted via company portal"},
    )
    assert stat_a.status == 200

    # Bob records interview
    stat_b = await client.post(
        "/api/tracker/status",
        headers=headers_b,
        json={"job_id": stable_id_b, "status": "interview", "notes": "Technical screen scheduled"},
    )
    assert stat_b.status == 200

    # Alice sees only Alice's tracker history
    events_a = await (await client.get("/api/tracker/events", headers=headers_a)).json()
    assert any(e.get("status") == "submitted" for e in events_a.get("events", []))
    assert not any(e.get("status") == "interview" for e in events_a.get("events", []))

    # Bob sees only Bob's tracker history
    events_b = await (await client.get("/api/tracker/events", headers=headers_b)).json()
    assert any(e.get("status") == "interview" for e in events_b.get("events", []))
    assert not any(e.get("status") == "submitted" for e in events_b.get("events", []))

    # ── 9. GDPR RIGHT TO ERASURE ISOLATION ────────────────────────────
    # Alice requests deletion of all personal data
    del_a = await client.post("/api/privacy/delete-account", headers=headers_a)
    assert del_a.status == 200

    # Alice's session is now revoked (HTTP 401)
    revoked_resp = await client.get("/api/candidate/profile", headers=headers_a)
    assert revoked_resp.status == 401

    # Bob's account and data remain 100% healthy and accessible
    bob_still_alive = await client.get("/api/candidate/profile", headers=headers_b)
    assert bob_still_alive.status == 200
    bob_dl_own = await client.get(f"/api/application/download/{pack_b_id}", headers=headers_b)
    assert bob_dl_own.status == 200
