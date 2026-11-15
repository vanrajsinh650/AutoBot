"""
Tests for AutoBot v2.2.1 — Phase 5: Mission Control Browser UI & Health Telemetry.
Verifies:
1. GET /api/browser/health returns active engine (Chromium default), process status, timestamp, fallback status, and experimental status.
2. GET /api/status incorporates browser_health telemetry.
3. POST /api/browser/configure rejects unauthenticated access (401).
4. POST /api/browser/configure rejects non-admin users (403 Forbidden).
5. POST /api/browser/configure blocks engine switching during active application run (400).
6. Admin can enable experimental backend and switch engine when idle.
7. HTML/CSS/JS assets contain telemetry badge and admin controls.
"""

from pathlib import Path
import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

from src.storage.auth import create_user
from src.storage.db import get_db_connection, init_db
from src.web.routes import _SYSTEM_BROWSER_HEALTH, execution_manager
from src.web.server import create_app


@pytest_asyncio.fixture
async def client():
    """Create test client with isolated database."""
    app = create_app()
    server = TestServer(app)
    c = TestClient(server)
    await c.start_server()
    # Reset browser health to default state between test runs
    _SYSTEM_BROWSER_HEALTH["active_engine"] = "chromium"
    _SYSTEM_BROWSER_HEALTH["default_engine"] = "chromium"
    _SYSTEM_BROWSER_HEALTH["experimental_enabled"] = False
    _SYSTEM_BROWSER_HEALTH["fallback_active"] = False
    _SYSTEM_BROWSER_HEALTH["process_status"] = "ready"
    execution_manager.is_running = False

    try:
        yield c
    finally:
        execution_manager.is_running = False
        await c.close()


@pytest.mark.asyncio
async def test_browser_health_endpoint_defaults_to_chromium(client: TestClient):
    """Verify /api/browser/health returns Chromium by default and Obscura disabled."""
    resp = await client.get("/api/browser/health")
    assert resp.status == 200
    data = await resp.json()

    assert data["active_engine"] == "chromium"
    assert data["default_engine"] == "chromium"
    assert data["process_status"] in ("ready", "idle")
    assert "last_health_check" in data
    assert data["fallback_status"] == "standby"
    assert data["fallback_active"] is False

    exp = data["experimental_backend"]
    assert exp["name"] == "obscura"
    assert exp["version"] == "0.2.7"
    assert exp["enabled"] is False
    assert exp["status"] == "disabled"


@pytest.mark.asyncio
async def test_status_endpoint_incorporates_browser_health(client: TestClient):
    """Verify /api/status includes nested browser_health dictionary."""
    resp = await client.get("/api/status")
    assert resp.status == 200
    data = await resp.json()

    assert "browser_health" in data
    bh = data["browser_health"]
    assert bh["active_engine"] == "chromium"
    assert bh["default_engine"] == "chromium"


@pytest.mark.asyncio
async def test_browser_configure_security_restrictions(client: TestClient):
    """Verify authentication and administrator-only role enforcement."""
    # 1. Unauthenticated request -> 401
    unauth_resp = await client.post(
        "/api/browser/configure",
        json={"engine": "obscura", "experimental_enabled": True},
    )
    assert unauth_resp.status == 401

    # 2. Non-admin regular user (user_id >= 2 without is_admin) -> 403 Forbidden
    reg_resp = await client.post(
        "/api/auth/register",
        json={"email": "regular_user@example.com", "password": "UserPassword!123"},
    )
    assert reg_resp.status == 200
    token_regular = (await reg_resp.json())["token"]
    headers_reg = {"Authorization": f"Bearer {token_regular}"}

    forbidden_resp = await client.post(
        "/api/browser/configure",
        headers=headers_reg,
        json={"engine": "obscura", "experimental_enabled": True},
    )
    assert forbidden_resp.status == 403
    assert "restricted to system administrators" in (await forbidden_resp.json())["error"]


@pytest.mark.asyncio
async def test_browser_configure_blocks_mid_application_switching(client: TestClient):
    """Verify switching engine during active agent execution is blocked (HTTP 400)."""
    # Create admin user
    adm_resp = await client.post(
        "/api/auth/register",
        json={"email": "admin_test@example.com", "password": "AdminPassword!123"},
    )
    assert adm_resp.status == 200
    adm_data = await adm_resp.json()
    token_adm = adm_data["token"]
    user_id = adm_data["user"]["id"]

    # Grant admin privilege in database
    import os
    db_path = os.environ.get("AUTOBOT_DB_PATH")
    with get_db_connection(db_path) as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
        conn.commit()

    headers_admin = {"Authorization": f"Bearer {token_adm}"}

    # Simulate active application run
    execution_manager.is_running = True
    try:
        blocked_resp = await client.post(
            "/api/browser/configure",
            headers=headers_admin,
            json={"engine": "obscura", "experimental_enabled": True},
        )
        assert blocked_resp.status == 400
        assert "active application run is strictly prohibited" in (await blocked_resp.json())["error"]
    finally:
        execution_manager.is_running = False


@pytest.mark.asyncio
async def test_admin_can_configure_experimental_obscura_when_idle(client: TestClient):
    """Verify admin can enable experimental mode and switch engine when idle."""
    adm_resp = await client.post(
        "/api/auth/register",
        json={"email": "admin_idle@example.com", "password": "AdminPassword!123"},
    )
    adm_data = await adm_resp.json()
    token_adm = adm_data["token"]
    user_id = adm_data["user"]["id"]

    import os
    db_path = os.environ.get("AUTOBOT_DB_PATH")
    with get_db_connection(db_path) as conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
        conn.commit()

    headers_admin = {"Authorization": f"Bearer {token_adm}"}

    # 1. Attempting to select Obscura while experimental_enabled is False -> 400
    bad_req = await client.post(
        "/api/browser/configure",
        headers=headers_admin,
        json={"engine": "obscura", "experimental_enabled": False},
    )
    assert bad_req.status == 400

    # 2. Legitimate admin enablement
    ok_req = await client.post(
        "/api/browser/configure",
        headers=headers_admin,
        json={"engine": "obscura", "experimental_enabled": True},
    )
    assert ok_req.status == 200
    res_data = await ok_req.json()
    assert res_data["browser_health"]["active_engine"] == "obscura"
    assert res_data["browser_health"]["experimental_backend"]["enabled"] is True


def test_mission_control_static_ui_markup_presence():
    """Verify index.html, app.css, and app.js contain the browser health badge and admin controls."""
    html = Path("src/web/static/index.html").read_text(encoding="utf-8")
    assert "browser-health-pill" in html
    assert "browser-engine-text" in html
    assert "browser-proc-status" in html
    assert "browser-fallback-badge" in html
    assert "admin-browser-config-card" in html
    assert "cfg-browser-engine" in html
    assert "cfg-experimental-browser-toggle" in html

    css = Path("src/web/static/app.css").read_text(encoding="utf-8")
    assert ".browser-health-badge" in css
    assert ".browser-pulse-dot" in css
    assert ".badge-fallback-ok" in css
    assert ".badge-fallback-triggered" in css

    js = Path("src/web/static/app.js").read_text(encoding="utf-8")
    assert "updateBrowserHealthUI" in js
    assert "saveBrowserConfiguration" in js
    assert "/api/browser/configure" in js
