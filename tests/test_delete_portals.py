import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from src.web.server import create_app

from src.storage.db import (
    delete_all_portal_jobs,
    delete_portal_jobs,
    get_apply_portals,
    get_db_connection,
    init_db,
    save_scraped_job,
)


@pytest_asyncio.fixture
async def client():
    app = create_app()
    server = TestServer(app)
    c = TestClient(server)
    await c.start_server()
    yield c
    await c.close()


def test_delete_portal_jobs_individual(tmp_path):
    db_file = str(tmp_path / "test_delete_single.db")
    init_db(db_file)

    save_scraped_job(
        title="Role A",
        company="Company A",
        location="Remote",
        description="Desc A",
        apply_url="https://in.linkedin.com/jobs/view/111",
        job_id="job_a_111",
        user_id=1,
        db_path=db_file,
    )
    save_scraped_job(
        title="Role B",
        company="Company B",
        location="Remote",
        description="Desc B",
        apply_url="https://in.linkedin.com/jobs/view/222",
        job_id="job_b_222",
        user_id=1,
        db_path=db_file,
    )

    with get_db_connection(db_file) as conn:
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2

    # Delete Role A
    deleted = delete_portal_jobs(["job_a_111"], user_id=1, db_path=db_file)
    assert deleted == 1

    with get_db_connection(db_file) as conn:
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
        rem = conn.execute("SELECT stable_id FROM jobs").fetchone()[0]
        assert rem == "job_b_222"
        # Verify applications table is also cleaned up
        apps = conn.execute("SELECT count(*) FROM applications").fetchone()[0]
        assert apps == 1


def test_delete_portal_jobs_batch(tmp_path):
    db_file = str(tmp_path / "test_delete_batch.db")
    init_db(db_file)

    save_scraped_job("Role 1", "Comp 1", "Remote", "Desc", "https://url1", job_id="j1", db_path=db_file)
    save_scraped_job("Role 2", "Comp 2", "Remote", "Desc", "https://url2", job_id="j2", db_path=db_file)
    save_scraped_job("Role 3", "Comp 3", "Remote", "Desc", "https://url3", job_id="j3", db_path=db_file)

    deleted = delete_portal_jobs(["j1", "j2"], user_id=1, db_path=db_file)
    assert deleted == 2

    with get_db_connection(db_file) as conn:
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1


def test_delete_all_portal_jobs(tmp_path):
    db_file = str(tmp_path / "test_delete_all.db")
    init_db(db_file)

    save_scraped_job("Role 1", "Comp 1", "Remote", "Desc", "https://url1", job_id="j1", db_path=db_file)
    save_scraped_job("Role 2", "Comp 2", "Remote", "Desc", "https://url2", job_id="j2", db_path=db_file)

    deleted = delete_all_portal_jobs(user_id=1, db_path=db_file)
    assert deleted == 2

    with get_db_connection(db_file) as conn:
        assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM applications").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_api_delete_portals_endpoint_single(client: TestClient, monkeypatch, tmp_path):
    db_file = tmp_path / "test_api_delete.db"
    monkeypatch.setenv("AUTOBOT_DB_PATH", str(db_file))

    save_scraped_job(
        title="Developer One",
        company="TechCorp",
        location="Remote",
        description="FastAPI role",
        apply_url="https://in.linkedin.com/jobs/view/100",
        job_id="job_api_1",
        user_id=1,
        match_score=0.85,
        db_path=str(db_file),
    )

    resp = await client.post("/api/apply-portals/delete", json={"job_id": "job_api_1"})
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["deleted_count"] == 1


@pytest.mark.asyncio
async def test_api_delete_portals_endpoint_all(client: TestClient, monkeypatch, tmp_path):
    db_file = tmp_path / "test_api_delete_all.db"
    monkeypatch.setenv("AUTOBOT_DB_PATH", str(db_file))

    save_scraped_job("Role 1", "Comp 1", "Remote", "Desc", "https://url1", job_id="j1", user_id=1, db_path=str(db_file))
    save_scraped_job("Role 2", "Comp 2", "Remote", "Desc", "https://url2", job_id="j2", user_id=1, db_path=str(db_file))

    resp = await client.post("/api/apply-portals/delete", json={"all": True})
    assert resp.status == 200
    data = await resp.json()
    assert data["success"] is True
    assert data["deleted_count"] >= 2
