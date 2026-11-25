"""
Tests for AutoBot Proof & Audit Verification Engine.
Verifies:
1. Positive submission confirmation detection on text and URL signals.
2. Extraction of confirmation and reference tracking codes.
3. Accurate diagnosis of Account Required, CAPTCHA, and validation error blockers.
4. Proof screenshot capture and watermark badge injection.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from src.browser.proof_audit import (
    capture_proof_screenshot,
    verify_submission_status,
)


@pytest.mark.asyncio
async def test_verify_submission_status_success_text():
    page = AsyncMock()
    page.url = "https://careers.company.com/jobs/123/applied"
    page.evaluate.return_value = "Thank you for applying! Your application has been received. Application Reference: REQ-98421"

    result = await verify_submission_status(page)
    assert result["is_submitted"] is True
    assert result["status"] == "applied"
    assert result["reason_code"] == "SUCCESS"
    assert result["confirmation_code"] == "REQ-98421"


@pytest.mark.asyncio
async def test_verify_submission_status_success_url():
    page = AsyncMock()
    page.url = "https://jobs.lever.co/company/456/confirmation"
    page.evaluate.return_value = "Submission complete"

    result = await verify_submission_status(page)
    assert result["is_submitted"] is True
    assert result["status"] == "applied"
    assert result["reason_code"] == "SUCCESS"


@pytest.mark.asyncio
async def test_verify_submission_status_account_required():
    page = AsyncMock()
    page.url = "https://company.wd1.myworkdayjobs.com/en-US/Careers/user/login"
    page.evaluate.return_value = "Sign in to apply or create an account"

    result = await verify_submission_status(page)
    assert result["is_submitted"] is False
    assert result["status"] == "requires_manual"
    assert result["reason_code"] == "ACCOUNT_REQUIRED"


@pytest.mark.asyncio
async def test_verify_submission_status_security_challenge():
    page = AsyncMock()
    page.url = "https://company.com/careers/apply"
    page.evaluate.return_value = "Verify you are human before proceeding. Cloudflare Turnstile."

    result = await verify_submission_status(page)
    assert result["is_submitted"] is False
    assert result["status"] == "challenge_detected"
    assert result["reason_code"] == "SECURITY_CHALLENGE"


@pytest.mark.asyncio
async def test_verify_submission_status_validation_error():
    page = AsyncMock()
    page.url = "https://company.com/apply"
    page.evaluate.return_value = "Application Form"

    err_el = AsyncMock()
    err_el.is_visible.return_value = True
    err_el.inner_text.return_value = "This field is required: Notice Period"

    async def mock_query_selector_all(sel):
        if sel == ":has-text('This field is required')":
            return [err_el]
        return []

    page.query_selector_all.side_effect = mock_query_selector_all

    result = await verify_submission_status(page)
    assert result["is_submitted"] is False
    assert result["status"] == "requires_manual"
    assert result["reason_code"] == "VALIDATION_ERROR"
    assert "Notice Period" in result["description"]


@pytest.mark.asyncio
async def test_verify_submission_status_proximus_phenom():
    page = AsyncMock()
    page.url = "https://jobs.proximus.com/be/en/applythankyou?status=success&jobSeqNo=PIHPROGBREQ19749EXTERNALENBE"
    page.evaluate.return_value = "Vanraj, you have successfully applied for: Python Developer, Mumbai, IND. Back to home. Back to job search."

    result = await verify_submission_status(page)
    assert result["is_submitted"] is True
    assert result["status"] == "applied"
    assert result["reason_code"] == "SUCCESS"


@pytest.mark.asyncio
async def test_capture_proof_screenshot(tmp_path):
    page = AsyncMock()
    page.screenshot = AsyncMock()
    page.evaluate = AsyncMock()

    with patch("src.browser.proof_audit.PROOF_DIR", tmp_path):
        proof_path = await capture_proof_screenshot(
            page=page,
            job_id="test_job_123",
            company="Acme Corp",
            title="Senior Python Engineer",
            is_success=True,
            status="applied",
        )
        assert proof_path is not None
        assert "test_job_123_confirmed.png" in proof_path
        page.screenshot.assert_awaited_once()

        # Test dry-run simulation proof
        dry_proof = await capture_proof_screenshot(
            page=page,
            job_id="test_job_456",
            company="Proximus",
            title="Python Developer",
            is_success=True,
            status="dry_run",
        )
        assert dry_proof is not None
        assert "test_job_456_dry_run.png" in dry_proof


@pytest.mark.asyncio
async def test_verify_submission_status_cloudflare_company_with_validation_errors():
    """Company name 'Cloudflare' or passive reCAPTCHA badge must not hide real validation errors."""
    page = AsyncMock()
    page.url = "https://boards.greenhouse.io/cloudflare/jobs/7579269"
    page.evaluate.return_value = "About Cloudflare. Cloudflare's Candidate Privacy Policy. Protected by reCAPTCHA."

    err_el = AsyncMock()
    err_el.is_visible.return_value = True
    err_el.inner_text.return_value = "Please enter your location"

    async def mock_qsa(sel):
        if sel == ".field-error":
            return [err_el]
        return []

    page.query_selector_all.side_effect = mock_qsa
    result = await verify_submission_status(page)
    assert result["is_submitted"] is False
    assert result["status"] == "requires_manual"
    assert result["reason_code"] == "VALIDATION_ERROR"
    assert "location" in result["description"].lower()


@pytest.mark.asyncio
async def test_capture_proof_screenshot_detects_unselected_comboboxes(monkeypatch, tmp_path):
    monkeypatch.setattr("src.browser.proof_audit.PROOF_DIR", tmp_path)
    page = AsyncMock()
    page.content.return_value = "<html><body>Form with unfilled dropdowns</body></html>"
    page.evaluate.return_value = "Are you currently based in Singapore (Unselected) | Sponsorship (Unselected)"
    page.screenshot = AsyncMock()

    proof_file = await capture_proof_screenshot(
        page,
        job_id="test_unselected_combo",
        company="Cloudflare",
        title="Security Engineer",
        is_success=False,
        reason="Application form submission incomplete",
        status="requires_manual",
    )
    assert proof_file is not None
    assert Path(proof_file).name == "test_unselected_combo_blocked.png"
    assert page.screenshot.called

