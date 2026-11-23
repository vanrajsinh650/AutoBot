"""
Unit tests for Automated Portal Application Runner (portal_applicator.py).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.browser.portal_applicator import apply_to_portals
from src.storage.db import init_db, save_scraped_job


@pytest.mark.asyncio
async def test_apply_to_portals_empty_list():
    """Verify applying with empty list returns clean failure summary without error."""
    res = await apply_to_portals(job_ids=[], user_id=1)
    assert res["success"] is False
    assert res["total"] == 0
    assert res["succeeded"] == 0


@pytest.mark.asyncio
async def test_apply_to_portals_missing_jobs(tmp_path):
    """Verify nonexistent jobs in database are safely handled."""
    db_file = str(tmp_path / "empty_test.db")
    init_db(db_file)

    res = await apply_to_portals(job_ids=["nonexistent_999"], user_id=1, db_path=db_file)
    assert res["success"] is False
    assert res["total"] == 0


@pytest.mark.asyncio
async def test_apply_to_portals_success_flow(tmp_path, monkeypatch):
    """Verify successful automated application updates status and returns summary."""
    db_file = str(tmp_path / "apply_test.db")
    init_db(db_file)

    save_scraped_job(
        title="Agent Systems Engineer",
        company="Ramp",
        location="Remote (US)",
        description="Build stateful agent systems and autonomous workflows.",
        apply_url="https://jobs.ashbyhq.com/ramp/1234-5678",
        source_name="Ashby",
        is_easy_apply=False,
        job_id="ashby_ramp_01",
        user_id=1,
        db_path=db_file,
    )

    mock_actuator = MagicMock()
    mock_actuator.apply = AsyncMock(return_value=True)

    mock_browser_mgr = MagicMock()
    mock_browser_mgr.start = AsyncMock()
    mock_browser_mgr.close = AsyncMock()
    mock_browser_mgr.context = MagicMock()

    with patch("src.browser.portal_applicator.BrowserManager", return_value=mock_browser_mgr), \
         patch("src.browser.portal_applicator.ExternalApplyActuator", return_value=mock_actuator):

        notifications = []
        def _cb(lvl, msg, meta):
            notifications.append((lvl, msg, meta))

        res = await apply_to_portals(
            job_ids=["ashby_ramp_01"],
            user_id=1,
            dry_run=True,
            headless=True,
            progress_callback=_cb,
            db_path=db_file,
        )

        assert res["success"] is True
        assert res["total"] == 1
        assert res["succeeded"] == 1
        assert res["failed"] == 0
        assert len(res["results"]) == 1
        assert res["results"][0]["status"] == "dry_run"
        assert res["results"][0]["company"] == "Ramp"

        # Verify progress callback was invoked
        assert len(notifications) > 0
        assert any(n[0] == "success" for n in notifications)


@pytest.mark.asyncio
async def test_apply_to_portals_linkedin_easy_apply_flow(tmp_path):
    """Verify autonomous LinkedIn Easy Apply flow invokes EasyApplyActuator and succeeds."""
    db_file = str(tmp_path / "easy_apply_test.db")
    init_db(db_file)

    save_scraped_job(
        title="Full Stack Python Engineer",
        company="TechCorp",
        location="Remote",
        description="Build Python and React applications.",
        apply_url="https://www.linkedin.com/jobs/view/999888777/",
        source_name="LinkedIn Easy Apply",
        is_easy_apply=True,
        job_id="li_easy_001",
        user_id=1,
        db_path=db_file,
    )

    mock_easy_actuator = MagicMock()
    mock_easy_actuator.apply = AsyncMock(return_value=True)

    mock_page = AsyncMock()
    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser_mgr = MagicMock()
    mock_browser_mgr.start = AsyncMock()
    mock_browser_mgr.close = AsyncMock()
    mock_browser_mgr.context = mock_context

    with patch("src.browser.portal_applicator.BrowserManager", return_value=mock_browser_mgr), \
         patch("src.browser.portal_applicator.EasyApplyActuator", return_value=mock_easy_actuator):

        notifications = []
        def _cb(lvl, msg, meta):
            notifications.append((lvl, msg, meta))

        res = await apply_to_portals(
            job_ids=["li_easy_001"],
            user_id=1,
            dry_run=True,
            headless=True,
            progress_callback=_cb,
            db_path=db_file,
        )

        assert res["success"] is True
        assert res["total"] == 1
        assert res["succeeded"] == 1
        assert res["results"][0]["status"] == "dry_run"
        mock_easy_actuator.apply.assert_awaited_once()


@pytest.mark.asyncio
async def test_apply_to_portals_linkedin_external_direct_resolution_flow(tmp_path):
    """Verify LinkedIn external job extracts direct company ATS link and runs ExternalApplyActuator."""
    db_file = str(tmp_path / "ext_resolve_test.db")
    init_db(db_file)

    # Encoded outbound external apply URL from LinkedIn
    outbound_encoded = "https://www.linkedin.com/jobs/view/externalApply/4147053526/?url=https%3A%2F%2Fjpmc.fa.oraclecloud.com%2FhcmUI%2FCandidateExperience%2Fen%2Fsites%2FCX_1001%2Fjob%2F210582046"

    save_scraped_job(
        title="Software Engineer III - Java Fullstack",
        company="JPMorganChase",
        location="Hyderabad, Telangana, India",
        description="Java, React, AWS, Microservices application engineering.",
        apply_url=outbound_encoded,
        source_name="LinkedIn",
        is_easy_apply=False,
        job_id="jpmc_ext_001",
        user_id=1,
        db_path=db_file,
    )

    mock_ext_actuator = MagicMock()
    mock_ext_actuator.apply = AsyncMock(return_value=True)

    mock_page = AsyncMock()
    mock_context = MagicMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser_mgr = MagicMock()
    mock_browser_mgr.start = AsyncMock()
    mock_browser_mgr.close = AsyncMock()
    mock_browser_mgr.context = mock_context

    with patch("src.browser.portal_applicator.BrowserManager", return_value=mock_browser_mgr), \
         patch("src.browser.portal_applicator.ExternalApplyActuator", return_value=mock_ext_actuator):

        notifications = []
        def _cb(lvl, msg, meta):
            notifications.append((lvl, msg, meta))

        res = await apply_to_portals(
            job_ids=["jpmc_ext_001"],
            user_id=1,
            dry_run=True,
            headless=True,
            progress_callback=_cb,
            db_path=db_file,
        )

        assert res["success"] is True
        assert res["total"] == 1
        assert res["succeeded"] == 1
        # ExternalApplyActuator was called with the decoded Oracle Cloud URL, NOT LinkedIn
        mock_ext_actuator.apply.assert_awaited_once()
        called_url = mock_ext_actuator.apply.call_args[1]["apply_url"]
        assert "oraclecloud.com" in called_url
        assert "linkedin.com" not in called_url


@pytest.mark.asyncio
async def test_apply_preserves_genuine_match_score(tmp_path):
    """Verify that applying to a job preserves its genuine match score (e.g. 44%) and does not overwrite with 0.90."""
    db_file = str(tmp_path / "score_test.db")
    init_db(db_file)

    save_scraped_job(
        title="AI Automation Engineer",
        company="RecruitBots AI",
        location="Remote",
        description="Position: AI Automation Engineer at RecruitBots AI.",
        apply_url="https://jobs.ashbyhq.com/recruitbots/123",
        source_name="Ashby",
        is_easy_apply=False,
        job_id="rb_01",
        user_id=1,
        match_score=0.44,
        db_path=db_file,
    )

    mock_actuator = MagicMock()
    mock_actuator.apply = AsyncMock(return_value=True)

    mock_browser_mgr = MagicMock()
    mock_browser_mgr.start = AsyncMock()
    mock_browser_mgr.close = AsyncMock()
    mock_browser_mgr.context = MagicMock()

    with patch("src.browser.portal_applicator.BrowserManager", return_value=mock_browser_mgr), \
         patch("src.browser.portal_applicator.ExternalApplyActuator", return_value=mock_actuator):

        res = await apply_to_portals(
            job_ids=["rb_01"],
            user_id=1,
            dry_run=True,
            headless=True,
            db_path=db_file,
        )

        assert res["success"] is True

        from src.storage.db import get_apply_portals, get_db_connection
        with get_db_connection(db_file) as conn:
            row = conn.execute("SELECT match_score FROM applications WHERE job_id = 'rb_01'").fetchone()
            assert row is not None
            # Must remain 0.44, NOT corrupted to 0.90!
            assert row["match_score"] == 0.44, f"Expected 0.44, got {row['match_score']}"


@pytest.mark.asyncio
async def test_apply_skips_login_gated_portal_when_configured(tmp_path):
    """Verify that when a portal requires candidate account creation/sign-in, it skips with ACCOUNT_REQUIRED."""
    db_file = str(tmp_path / "login_skip_test.db")
    init_db(db_file)

    save_scraped_job(
        title="Integration Test Engineer",
        company="Philips",
        location="Bangalore",
        description="Position: Integration Test Engineer at Philips.",
        apply_url="https://philips.wd3.myworkdayjobs.com/jobs-and-careers/job/584997-1",
        source_name="Workday",
        is_easy_apply=False,
        job_id="philips_wd_01",
        user_id=1,
        match_score=0.88,
        db_path=db_file,
    )

    mock_actuator = MagicMock()
    # Actuator returns False and sets last_outcome with ACCOUNT_REQUIRED
    mock_actuator.apply = AsyncMock(return_value=False)
    mock_actuator.last_outcome = {
        "success": False,
        "status": "requires_manual",
        "reason_code": "ACCOUNT_REQUIRED",
        "description": "Company career portal requires candidate account registration or sign-in (e.g. Workday/Taleo account).",
        "proof_screenshot": "/tmp/proof_workday.png",
    }

    mock_browser_mgr = MagicMock()
    mock_browser_mgr.start = AsyncMock()
    mock_browser_mgr.close = AsyncMock()
    mock_browser_mgr.context = MagicMock()

    with patch("src.browser.portal_applicator.BrowserManager", return_value=mock_browser_mgr), \
         patch("src.browser.portal_applicator.ExternalApplyActuator", return_value=mock_actuator):

        res = await apply_to_portals(
            job_ids=["philips_wd_01"],
            user_id=1,
            dry_run=True,
            headless=True,
            db_path=db_file,
        )

        assert res["total"] == 1
        from src.storage.db import get_db_connection
        with get_db_connection(db_file) as conn:
            row = conn.execute("SELECT status, failure_reason FROM applications WHERE job_id = 'philips_wd_01'").fetchone()
            assert row is not None
            assert row["status"] == "requires_manual"
            assert "account" in row["failure_reason"].lower()

