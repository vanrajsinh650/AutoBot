"""
Unit & Integration Tests for AutoBot v2 Web Dashboard (aiohttp).
"""

import pytest
import pytest_asyncio
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from src.storage.db import DEFAULT_DB_PATH, init_db, save_application
from src.web.routes import execution_manager
from src.web.server import create_app


@pytest_asyncio.fixture
async def client():
    """Create test client for aiohttp web server."""
    app = create_app()
    server = TestServer(app)
    c = TestClient(server)
    await c.start_server()
    yield c
    await c.close()


@pytest_asyncio.fixture
async def auth_headers():
    """Create a valid session for user 1 (admin)."""
    from src.storage.auth import create_session
    token = create_session(user_id=1, email="admin@autobot.local")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_index_page(client: TestClient):
    """Verify single-page application dashboard is served."""
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "AutoBot" in text
    assert "LangGraph State Machine Pipeline" in text
    assert "data-view=\"mission\"" in text
    assert "data-view=\"applications\"" in text


@pytest.mark.asyncio
async def test_static_assets(client: TestClient):
    """Verify static CSS and JS assets are served properly."""
    css_resp = await client.get("/static/app.css")
    assert css_resp.status == 200
    css_text = await css_resp.text()
    assert "--primary:" in css_text

    js_resp = await client.get("/static/app.js")
    assert js_resp.status == 200
    js_text = await js_resp.text()
    assert "Mission Control" in js_text


@pytest.mark.asyncio
async def test_api_status(client: TestClient):
    """Verify /api/status telemetry endpoint."""
    resp = await client.get("/api/status")
    assert resp.status == 200
    data = await resp.json()

    assert "status" in data
    assert "current_node" in data
    assert "resume_found" in data
    assert "stats" in data
    assert "llm_provider" in data
    assert data["resume_found"] is True


@pytest.mark.asyncio
async def test_api_stats(client: TestClient, auth_headers: dict):
    """Verify /api/stats aggregate counts endpoint."""
    resp = await client.get("/api/stats", headers=auth_headers)
    assert resp.status == 200
    data = await resp.json()

    for key in ("applied", "skipped", "dry_run", "failed", "total"):
        assert key in data
        assert isinstance(data[key], int)


@pytest.mark.asyncio
async def test_api_jobs_pagination_and_filter(client: TestClient, auth_headers: dict):
    """Verify /api/jobs endpoint with search and status filtering."""
    init_db()

    save_application(
        job_id="web_job_1",
        job_title="Web Platform Architect",
        company="WebCorp",
        location="Remote",
        apply_type="Easy Apply",
        match_score=0.92,
        status="applied",
        url="https://linkedin.com/jobs/view/web1",
        notes="Applied cleanly via web test",
        user_id=1,
    )

    # 1. Fetch all
    resp = await client.get("/api/jobs", headers=auth_headers)
    assert resp.status == 200
    data = await resp.json()
    assert data["total"] >= 1
    assert any(j["company"] == "WebCorp" for j in data["jobs"])

    # 2. Filter by search query
    resp_search = await client.get("/api/jobs?q=WebCorp", headers=auth_headers)
    data_search = await resp_search.json()
    assert data_search["total"] >= 1
    assert data_search["jobs"][0]["company"] == "WebCorp"

    # 3. Filter by status
    resp_applied = await client.get("/api/jobs?status=applied", headers=auth_headers)
    data_applied = await resp_applied.json()
    assert all(j["status"] == "applied" for j in data_applied["jobs"])


@pytest.mark.asyncio
async def test_api_config_get_and_save(client: TestClient, auth_headers: dict):
    """Verify /api/config GET and POST roundtrip."""
    # 1. GET
    resp = await client.get("/api/config", headers=auth_headers)
    assert resp.status == 200
    cfg = await resp.json()
    assert "search" in cfg
    assert "profile" in cfg

    # 2. POST update
    original_location = cfg.get("search", {}).get("location", "Remote")
    cfg["search"]["location"] = "San Francisco, CA"

    post_resp = await client.post("/api/config", json=cfg, headers=auth_headers)
    assert post_resp.status == 200
    post_data = await post_resp.json()
    assert post_data.get("success") is True

    # Verify update persisted
    verify_resp = await client.get("/api/config", headers=auth_headers)
    verify_cfg = await verify_resp.json()
    assert verify_cfg["search"]["location"] == "San Francisco, CA"

    # Restore original location
    cfg["search"]["location"] = original_location
    await client.post("/api/config", json=cfg, headers=auth_headers)


@pytest.mark.asyncio
async def test_api_profile(client: TestClient, auth_headers: dict):
    """Verify /api/profile parses resume sections and chunks."""
    resp = await client.get("/api/profile", headers=auth_headers)
    assert resp.status == 200
    data = await resp.json()

    assert data["found"] is True
    assert data["total_chunks"] > 0
    assert "sections" in data
    assert isinstance(data["sections"], dict)
    assert "skills" in data["sections"] or "experience" in data["sections"]


@pytest.mark.asyncio
async def test_api_stop_when_idle(client: TestClient, auth_headers: dict):
    """Verify /api/stop returns 400 when no active execution task is running."""
    execution_manager.is_running = False
    execution_manager.active_task = None

    resp = await client.post("/api/stop", headers=auth_headers)
    assert resp.status == 400
    data = await resp.json()
    assert "No active execution to stop" in data.get("error", "")


@pytest.mark.asyncio
async def test_execution_manager_broadcast():
    """Verify event broadcasting stores logs in backlog buffer."""
    initial_count = len(execution_manager.recent_logs)
    execution_manager.broadcast("test_evt", {"test_key": "test_val"})
    assert len(execution_manager.recent_logs) == initial_count + 1
    last_log = execution_manager.recent_logs[-1]
    assert last_log["type"] == "test_evt"
    assert last_log["data"]["test_key"] == "test_val"


@pytest.mark.asyncio
async def test_api_upload_resume(client: TestClient, auth_headers: dict):
    """Verify /api/upload handles resume document uploads."""
    # 1. Invalid extension
    data = FormData()
    data.add_field("file", b"fake binary", filename="bad.exe", content_type="application/octet-stream")
    resp_bad = await client.post("/api/upload", data=data, headers=auth_headers)
    assert resp_bad.status == 400
    err = await resp_bad.json()
    assert "Unsupported file format" in err.get("error", "")

    # 2. Valid PDF upload
    from pathlib import Path
    sample_pdf = Path("data/resume/resume.pdf")
    if sample_pdf.exists():
        with open(sample_pdf, "rb") as f:
            pdf_bytes = f.read()
        valid_data = FormData()
        valid_data.add_field("file", pdf_bytes, filename="uploaded_test_resume.pdf", content_type="application/pdf")
        resp_ok = await client.post("/api/upload", data=valid_data, headers=auth_headers)
        assert resp_ok.status == 200
        result = await resp_ok.json()
        assert result.get("success") is True
        assert result.get("chunks_count", 0) > 0


@pytest.mark.asyncio
async def test_api_logout(client: TestClient, auth_headers: dict):
    """Verify /api/logout clears session state cleanly."""
    resp = await client.post("/api/logout", headers=auth_headers)
    assert resp.status == 200
    data = await resp.json()
    assert data.get("success") is True
    assert data.get("success") is True
