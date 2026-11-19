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


@pytest.mark.asyncio
async def test_api_search_live_endpoint(client: TestClient, auth_headers: dict, monkeypatch):
    """Verify /api/search/live endpoint triggers live Chrome search properly."""
    from unittest.mock import AsyncMock, patch

    mock_search = AsyncMock(return_value=[])
    mock_google = AsyncMock(return_value=[])
    with patch("src.browser.live_search.run_direct_chrome_search", mock_search), \
         patch("src.browser.live_search.run_direct_google_keyword_search", mock_google):
        resp = await client.post(
            "/api/search/live",
            json={"keyword": "Python Developer", "location": "India", "target": "google"},
            headers=auth_headers,
        )
        assert resp.status == 200
        data = await resp.json()
        assert data.get("success") is True
        assert "started" in data.get("message", "").lower()


@pytest.mark.asyncio
async def test_api_apply_portals_endpoint(client: TestClient, monkeypatch, tmp_path):
    """Verify /api/apply-portals returns categorized job applications and form links."""
    from src.storage.db import save_scraped_job

    db_file = tmp_path / "test_portals.db"
    monkeypatch.setenv("AUTOBOT_DB_PATH", str(db_file))

    # Save a LinkedIn Easy Apply job with full description and apply URL
    save_scraped_job(
        title="Senior Python Architect",
        company="LinkedIn Tech",
        location="Bengaluru, India",
        description="We are seeking an expert Python Architect with 8+ years experience in distributed microservices.",
        apply_url="https://in.linkedin.com/jobs/view/99998888/?apply=true",
        source_name="LinkedIn",
        is_easy_apply=True,
        job_id="li_arch_99",
        user_id=1,
        db_path=str(db_file),
    )

    # Save an external Greenhouse job with full description and direct Greenhouse apply form link
    save_scraped_job(
        title="Backend Engineer (Data)",
        company="Stripe",
        location="Remote",
        description="Join Stripe data infrastructure team building petabyte-scale event pipelines.",
        apply_url="https://boards.greenhouse.io/stripe/jobs/1234567",
        source_name="Greenhouse",
        is_easy_apply=False,
        job_id="gh_stripe_123",
        user_id=1,
        db_path=str(db_file),
    )

    # 1. Fetch all portals
    resp = await client.get("/api/apply-portals")
    assert resp.status == 200
    data = await resp.json()

    assert data["total"] == 2
    assert data["linkedin_count"] == 1
    assert data["external_count"] == 1
    assert "LinkedIn (Easy Apply)" in data["platforms"]
    assert "Greenhouse" in data["platforms"]

    # 2. Filter LinkedIn only
    li_resp = await client.get("/api/apply-portals?platform=linkedin")
    assert li_resp.status == 200
    li_data = await li_resp.json()
    assert len(li_data["jobs"]) == 1
    assert li_data["jobs"][0]["platform_category"] == "linkedin"
    assert "linkedin.com" in li_data["jobs"][0]["apply_url"]

    # 3. Filter External only
    ext_resp = await client.get("/api/apply-portals?platform=external")
    assert ext_resp.status == 200
    ext_data = await ext_resp.json()
    assert len(ext_data["jobs"]) == 1
    assert ext_data["jobs"][0]["platform_category"] == "external"
    assert "greenhouse.io" in ext_data["jobs"][0]["apply_url"]

