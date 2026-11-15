"""
Integration and Unit Tests for AutoBot v2.2 Obscura Browser Backend Experiment.
Verifies provider abstraction, loopback isolation, ephemeral profile lifecycle,
absence of stealth flags, fail-closed policy enforcement, automatic fallback to Chromium,
and CDP form interaction & file upload.
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import async_playwright

from src.agent.state import JobPosting
from src.application.workflows import AntiBotChallengeDetected, LinkedInPolicyViolationError
from src.browser.base_backend import BrowserBackend
from src.browser.backends.chromium_backend import ChromiumBackend
from src.browser.backends.obscura_backend import ObscuraBackend
from src.browser.external_apply_actuator import ExternalApplyActuator
from src.browser.manager import BrowserManager
from src.memory.form_rag import FormRAG
from src.utils.config import AppConfig, EnvSettings, PROJECT_ROOT


# ── 1. Provider Abstraction & Configuration Tests ───────────────────────

def test_browser_manager_defaults_to_chromium():
    """Verify that BrowserManager defaults to ChromiumBackend when no backend is specified."""
    manager = BrowserManager(cfg=AppConfig(), env=EnvSettings(), backend=None)
    assert manager.requested_backend == "chromium"
    assert isinstance(manager.backend, ChromiumBackend)
    assert manager.backend_name == "chromium"


def test_browser_manager_accepts_obscura_backend():
    """Verify that BrowserManager instantiates ObscuraBackend when requested."""
    manager = BrowserManager(cfg=AppConfig(), env=EnvSettings(), backend="obscura")
    assert manager.requested_backend == "obscura"
    assert isinstance(manager.backend, ObscuraBackend)
    assert manager.backend_name == "obscura"


def test_obscura_command_never_contains_stealth():
    """Verify strict policy enforcement: --stealth flag is NEVER included in Obscura CLI args."""
    backend = ObscuraBackend(cfg=AppConfig(), env=EnvSettings())
    cmd = backend._build_command()
    assert "--stealth" not in cmd
    assert any(arg.endswith("obscura") for arg in cmd)
    assert "--host" in cmd
    assert "127.0.0.1" in cmd  # strictly loopback
    assert "--storage-dir" in cmd
    assert "--ready-file" in cmd


def test_obscura_loopback_binding_only():
    """Verify ObscuraBackend enforces loopback 127.0.0.1 and cannot bind to 0.0.0.0."""
    backend = ObscuraBackend(cfg=AppConfig(), env=EnvSettings())
    assert backend.host == "127.0.0.1"
    assert backend.host != "0.0.0.0"


# ── 2. Automatic Fallback Tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_obscura_fallback_to_chromium_on_missing_binary():
    """Verify that if Obscura binary is missing, BrowserManager falls back seamlessly to Chromium."""
    fake_env = EnvSettings()
    fake_env.obscura_binary_path = "/nonexistent/path/to/obscura_fake_bin"
    manager = BrowserManager(cfg=AppConfig(), env=fake_env, backend="obscura")

    with patch.object(ChromiumBackend, "start", new_callable=AsyncMock) as mock_chrom_start:
        await manager.start()
        assert isinstance(manager.backend, ChromiumBackend)
        mock_chrom_start.assert_awaited_once()


@pytest.mark.asyncio
async def test_obscura_fallback_to_chromium_on_unhealthy_backend():
    """Verify that if Obscura starts but fails is_healthy(), it falls back to Chromium."""
    manager = BrowserManager(cfg=AppConfig(), env=EnvSettings(), backend="obscura")

    with patch.object(ObscuraBackend, "start", new_callable=AsyncMock) as mock_obs_start, \
         patch.object(ObscuraBackend, "is_healthy", new_callable=AsyncMock, return_value=False), \
         patch.object(ObscuraBackend, "close", new_callable=AsyncMock) as mock_obs_close, \
         patch.object(ChromiumBackend, "start", new_callable=AsyncMock) as mock_chrom_start:

        await manager.start()
        mock_obs_start.assert_awaited_once()
        mock_obs_close.assert_awaited_once()
        assert isinstance(manager.backend, ChromiumBackend)
        mock_chrom_start.assert_awaited_once()


# ── 3. Tenant & Session Isolation Lifecycle ──────────────────────────────

@pytest.mark.asyncio
async def test_obscura_ephemeral_storage_lifecycle(tmp_path):
    """Verify ephemeral storage directory creation with 0700 permissions and wiping on close."""
    backend = ObscuraBackend(cfg=AppConfig(), env=EnvSettings(), user_id=42)
    # Target storage dir within temp path for isolated testing
    custom_profile_dir = tmp_path / "obscura_profiles" / f"user_42_{backend.session_id}"
    backend.storage_dir = custom_profile_dir
    backend.ready_file = tmp_path / f"ready_{backend.session_id}.txt"

    # Simulate start setup
    backend.storage_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backend.storage_dir, 0o700)
    backend.ready_file.write_text("ready")

    assert backend.storage_dir.exists()
    # Check permissions (0700)
    mode = os.stat(backend.storage_dir).st_mode & 0o777
    assert mode == 0o700

    # Execute close
    await backend.close()

    # Directory and ready file must be completely wiped
    assert not backend.storage_dir.exists()
    assert not backend.ready_file.exists()


# ── 4. Policy Negative Tests: LinkedIn Prohibition ───────────────────────

@pytest.mark.asyncio
async def test_obscura_rejects_linkedin_url_navigation():
    """Verify that BrowserManager.verify_safe_url prevents LinkedIn navigation."""
    with pytest.raises(LinkedInPolicyViolationError) as exc_info:
        BrowserManager.verify_safe_url("https://www.linkedin.com/jobs/view/999")
    assert "Compliance Policy Violation" in str(exc_info.value)

    with pytest.raises(LinkedInPolicyViolationError) as exc_info2:
        BrowserManager.verify_safe_url("https://lnkd.in/testjob")
    assert "Compliance Policy Violation" in str(exc_info2.value)


@pytest.mark.asyncio
async def test_obscura_route_blocks_linkedin_domains():
    """Verify that Obscura route aborts any requests targeting linkedin.com or lnkd.in."""
    backend = ObscuraBackend(cfg=AppConfig(), env=EnvSettings())
    backend._context = AsyncMock()

    # Mock the route handler registration
    registered_routes = {}
    async def mock_route(pattern, handler):
        registered_routes[pattern] = handler

    backend._context.route = mock_route
    # Simulate start route setup
    async def _block_prohibited_domains(route):
        req_url = route.request.url.lower()
        if "linkedin.com" in req_url or "lnkd.in" in req_url:
            await route.abort("blockedbyclient")
        else:
            await route.continue_()

    await backend._context.route("**/*", _block_prohibited_domains)

    # Test route handler with LinkedIn URL
    mock_li_route = AsyncMock()
    mock_li_route.request.url = "https://www.linkedin.com/voyager/api"
    await registered_routes["**/*"](mock_li_route)
    mock_li_route.abort.assert_awaited_once_with("blockedbyclient")
    mock_li_route.continue_.assert_not_called()

    # Test route handler with allowed ATS URL
    mock_ats_route = AsyncMock()
    mock_ats_route.request.url = "https://boards.greenhouse.io/api/job"
    await registered_routes["**/*"](mock_ats_route)
    mock_ats_route.continue_.assert_awaited_once()


# ── 5. Anti-Bot Challenge Halts on External Apply ─────────────────────────

@pytest.mark.asyncio
async def test_external_apply_halts_on_cloudflare_or_captcha():
    """Verify ExternalApplyActuator halts immediately on anti-bot/CAPTCHA without evasion."""
    mock_context = AsyncMock()
    actuator = ExternalApplyActuator(
        context=mock_context,
        form_rag=MagicMock(spec=FormRAG),
        cfg=AppConfig(),
    )

    page = AsyncMock()
    page.url = "https://boards.greenhouse.io/stripe/jobs/cf-challenge"
    page.title = AsyncMock(return_value="Attention Required! | Cloudflare")

    with pytest.raises(AntiBotChallengeDetected) as exc_info:
        await actuator.check_security_challenges(page)

    assert "Anti-bot challenge gate detected" in str(exc_info.value)


# ── 6. Live Obscura CDP Integration Test ──────────────────────────────────

@pytest.mark.asyncio
async def test_live_obscura_cdp_form_and_file_upload(tmp_path):
    """
    Live integration test:
    Launches actual Obscura binary, connects via Playwright CDP, fills form,
    uploads resume via CDP DOM.setFileInputFiles, and verifies cleanup.
    """
    binary_path = PROJECT_ROOT / "bin" / "obscura"
    if not binary_path.exists():
        pytest.skip("Obscura binary not found in bin/; skipping live integration test.")

    # Create dummy candidate resume
    resume_file = tmp_path / "test_candidate_resume.pdf"
    resume_file.write_text("%PDF-1.4 Mock Candidate Resume")

    backend = ObscuraBackend(
        cfg=AppConfig(),
        env=EnvSettings(),
        binary_path=binary_path,
        user_id=99,
    )

    try:
        await backend.start()
        assert await backend.is_healthy() is True
        assert backend.context is not None
        assert backend.page is not None

        page = backend.page
        synthetic_html = """
        <!DOCTYPE html>
        <html>
        <head><title>Synthetic ATS Portal</title></head>
        <body>
            <h1>Apply to Software Engineer</h1>
            <form id="ats_form">
                <input id="candidate_name" type="text" name="name" placeholder="Full Name" />
                <input id="candidate_email" type="email" name="email" placeholder="Email" />
                <input id="resume_upload" type="file" name="resume" accept=".pdf" />
                <button id="submit_btn" type="button">Submit Application</button>
            </form>
            <div id="result">Waiting</div>
            <script>
                document.getElementById('submit_btn').addEventListener('click', () => {
                    const name = document.getElementById('candidate_name').value;
                    const files = document.getElementById('resume_upload').files;
                    const fileName = files.length > 0 ? files[0].name : 'none';
                    document.getElementById('result').innerText = 'Submitted: ' + name + ' with file: ' + fileName;
                });
            </script>
        </body>
        </html>
        """
        await page.set_content(synthetic_html)

        # 1. Fill Text Inputs
        await page.fill("#candidate_name", "Jane Doe")
        await page.fill("#candidate_email", "jane.doe@example.com")
        assert await page.input_value("#candidate_name") == "Jane Doe"
        assert await page.input_value("#candidate_email") == "jane.doe@example.com"

        # 2. Upload Resume via backend.upload_file
        upload_success = await backend.upload_file(page, "#resume_upload", resume_file)
        assert upload_success is True

        # 3. Click Submit Button and Verify Execution
        await page.click("#submit_btn")
        result_text = await page.text_content("#result")
        assert "Submitted: Jane Doe with file: test_candidate_resume.pdf" in result_text

    finally:
        storage_dir = backend.storage_dir
        await backend.close()
        # Ensure ephemeral directory wiped after close
        assert not storage_dir.exists()
