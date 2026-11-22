"""
Tests for AutoBot Proof & Audit Verification Engine.
Verifies:
1. Positive submission confirmation detection on text and URL signals.
2. Extraction of confirmation and reference tracking codes.
3. Accurate diagnosis of Account Required, CAPTCHA, and validation error blockers.
4. Proof screenshot capture and watermark badge injection.
"""

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
        )
        assert proof_path is not None
        assert "test_job_123_confirmed.png" in proof_path
        page.screenshot.assert_awaited_once()
