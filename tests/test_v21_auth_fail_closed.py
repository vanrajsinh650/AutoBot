"""
Security Regression Tests for AutoBot v2.1 — Phase 1: Authentication Fail-Closed.
Verifies that all protected endpoints reject unauthenticated requests with HTTP 401,
admin endpoints enforce 403 for non-admins, and sessions fail closed.
"""

from datetime import datetime, timedelta
import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from src.storage.auth import create_session, create_user, revoke_session
from src.storage.db import get_db_connection, init_db, save_candidate_profile
from src.web.server import create_app


@pytest_asyncio.fixture
async def client(monkeypatch):
    """Create test client with isolated database."""
    monkeypatch.setenv("AUTOBOT_STRICT_AUTH", "1")
    app = create_app()
    server = TestServer(app)
    c = TestClient(server)
    await c.start_server()
    yield c
    await c.close()


@pytest.mark.asyncio
async def test_public_endpoints_accessible_without_auth(client: TestClient):
    """Verify that only designated public endpoints are accessible anonymously."""
    # 1. UI Root
    resp = await client.get("/")
    assert resp.status == 200

    # 2. Static CSS
    resp = await client.get("/static/app.css")
    assert resp.status == 200

    # 3. Health / Status
    resp = await client.get("/api/status")
    assert resp.status == 200
    data = await resp.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_protected_endpoints_fail_closed_without_token(client: TestClient):
    """Verify that every protected endpoint returns HTTP 401 when unauthenticated."""
    protected_gets = [
        "/api/jobs",
        "/api/stats",
        "/api/profile",
        "/api/config",
        "/api/events",
        "/api/auth/me",
        "/api/candidate/profile",
        "/api/candidate/preferences",
        "/api/candidate/resumes",
        "/api/discovery/sources",
        "/api/discovery/jobs",
        "/api/application/download/1",
        "/api/tracker/events",
        "/api/privacy/audit-logs",
    ]

    for endpoint in protected_gets:
        resp = await client.get(endpoint)
        assert resp.status == 401, f"Expected 401 on GET {endpoint}, got {resp.status}"
        data = await resp.json()
        assert "error" in data or "Authentication required" in str(data)

    protected_posts = [
        ("/api/config", {"search": {}}),
        ("/api/run", {"dry_run": True}),
        ("/api/stop", {}),
        ("/api/discovery/sources", {"name": "test", "adapter": "manual", "base_url": "https://example.com"}),
        ("/api/discovery/run", {}),
        ("/api/discovery/import", {"title": "SWE", "company": "Co", "description": "Desc"}),
        ("/api/matching/evaluate", {"job_id": "job_1"}),
        ("/api/application/prepare", {"job_id": "job_1"}),
        ("/api/application/approve", {"pack_id": 1}),
        ("/api/tracker/status", {"job_id": "job_1", "status": "applied"}),
        ("/api/privacy/delete-account", {}),
    ]

    for endpoint, payload in protected_posts:
        resp = await client.post(endpoint, json=payload)
        assert resp.status == 401, f"Expected 401 on POST {endpoint}, got {resp.status}"


@pytest.mark.asyncio
async def test_invalid_and_revoked_tokens_return_401(client: TestClient):
    """Verify that invalid or revoked session tokens are rejected with HTTP 401."""
    # 1. Bogus token
    resp = await client.get("/api/jobs", headers={"Authorization": "Bearer bogus_token_xyz"})
    assert resp.status == 401

    # 2. Valid then revoked token
    success, user_id, _ = create_user("test_revocation@example.com", "SecurePass123!")
    assert success
    token = create_session(user_id=user_id, email="test_revocation@example.com")

    # Access succeeds with valid token
    resp_ok = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp_ok.status == 200

    # Revoke session
    revoke_session(token)

    # Access immediately fails with 401
    resp_revoked = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp_revoked.status == 401


@pytest.mark.asyncio
async def test_expired_token_returns_401(client: TestClient):
    """Verify that expired session tokens fail closed."""
    success, user_id, _ = create_user("test_expiry@example.com", "SecurePass123!")
    assert success
    token = create_session(user_id=user_id, email="test_expiry@example.com", ttl_hours=-1)

    resp = await client.get("/api/candidate/profile", headers={"Authorization": f"Bearer {token}"})
    assert resp.status == 401


@pytest.mark.asyncio
async def test_admin_authorization_on_config_modification(client: TestClient):
    """Verify that non-admin users receive HTTP 403 on configuration modification."""
    # Create standard candidate user (user_id > 1, is_admin = 0)
    success, user_id, _ = create_user("candidate_user@example.com", "SecurePass123!")
    assert success
    token = create_session(user_id=user_id, email="candidate_user@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Reading config is allowed for authenticated users
    resp_get = await client.get("/api/config", headers=headers)
    assert resp_get.status == 200

    # Modifying config is forbidden for non-admin candidates
    resp_post = await client.post("/api/config", headers=headers, json={"search": {"keywords": ["Hacked"]}})
    assert resp_post.status == 403
    data = await resp_post.json()
    assert "Administrator" in data["error"] or "Forbidden" in data["error"]


@pytest.mark.asyncio
async def test_agent_stop_ownership_authorization(client: TestClient):
    """Verify that a user cannot stop another user's agent execution unless admin."""
    from src.web.routes import execution_manager

    # User A starts agent
    success_a, user_a, _ = create_user("alice_agent@example.com", "SecurePass123!")
    token_a = create_session(user_id=user_a, email="alice_agent@example.com")

    # User B
    success_b, user_b, _ = create_user("bob_agent@example.com", "SecurePass123!")
    token_b = create_session(user_id=user_b, email="bob_agent@example.com")

    # Simulate active execution owned by User A
    execution_manager.is_running = True
    execution_manager.user_id = user_a

    # User B attempts to stop User A's execution
    resp_stop = await client.post("/api/stop", headers={"Authorization": f"Bearer {token_b}"})
    assert resp_stop.status == 403
    data = await resp_stop.json()
    assert "Cannot stop" in data["error"] or "Forbidden" in data["error"]

    # Reset
    execution_manager.is_running = False
    execution_manager.user_id = None
