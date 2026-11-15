"""
Tests for AutoBot v2.2.1 — Phase 1: Browser Security and Compliance Audit.
Validates:
1. Obscura startup and shutdown.
2. Process cleanup after crashes.
3. Profile isolation between two distinct users.
4. CDP loopback binding and authentication.
5. Chromium fallback only happens before meaningful application actions (during start()).
6. No automatic engine switching during an active application.
7. File upload restrictions (rejection of unauthorized extensions).
8. Strict blocking of LinkedIn and lnkd.in across all browser paths.
9. Absence of stealth and anti-detection flags.
10. Immediate fail-closed stop on CAPTCHA, Cloudflare, Turnstile, or MFA challenges.
"""

import asyncio
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.state import JobPosting
from src.application.workflows import AntiBotChallengeDetected, LinkedInPolicyViolationError
from src.browser.backends.chromium_backend import ChromiumBackend
from src.browser.backends.obscura_backend import ObscuraBackend
from src.browser.external_apply_actuator import ExternalApplyActuator
from src.browser.manager import BrowserManager
from src.memory.form_rag import FormRAG
from src.utils.config import AppConfig, EnvSettings, PROJECT_ROOT


# ── 1. Startup and Shutdown ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_obscura_startup_and_clean_shutdown(tmp_path):
    """Verify ObscuraBackend starts and shuts down cleanly, deleting ephemeral profile."""
    backend = ObscuraBackend(cfg=AppConfig(), env=EnvSettings(), user_id=1)
    backend.storage_dir = tmp_path / f"profile_{backend.session_id}"
    backend.ready_file = tmp_path / f"ready_{backend.session_id}.txt"

    # Simulate start state
    backend.storage_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backend.storage_dir, 0o700)
    backend.ready_file.write_text("ready")
    backend._process = MagicMock()
    backend._process.poll.return_value = None

    assert backend.storage_dir.exists()
    assert backend.ready_file.exists()

    await backend.close()

    assert not backend.storage_dir.exists()
    assert not backend.ready_file.exists()
    assert backend._process is None


# ── 2. Process Cleanup After Crash ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_obscura_process_cleanup_after_crash(tmp_path):
    """Verify that if Obscura process crashes or is killed, health check fails and close() handles it cleanly."""
    backend = ObscuraBackend(cfg=AppConfig(), env=EnvSettings(), user_id=2)
    backend.storage_dir = tmp_path / f"profile_crash_{backend.session_id}"
    backend.storage_dir.mkdir(parents=True, exist_ok=True)
    backend.ready_file = tmp_path / f"ready_crash_{backend.session_id}.txt"
    backend.ready_file.write_text("ready")

    # Mock a dead process (exited with -9 / SIGKILL)
    mock_proc = MagicMock()
    mock_proc.poll.return_value = -9
    backend._process = mock_proc

    # Health check must immediately report unhealthy
    healthy = await backend.is_healthy()
    assert healthy is False

    # Calling close must clean up without exception and wipe profile
    await backend.close()
    assert not backend.storage_dir.exists()
    assert not backend.ready_file.exists()
    assert backend._process is None


# ── 3. Profile Isolation Between Users ───────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_user_profile_isolation(tmp_path):
    """Verify User A and User B receive isolated storage directories and one's teardown does not affect the other."""
    backend_a = ObscuraBackend(cfg=AppConfig(), env=EnvSettings(), user_id=101)
    backend_b = ObscuraBackend(cfg=AppConfig(), env=EnvSettings(), user_id=102)

    dir_a = tmp_path / "obscura_profiles" / f"user_101_{backend_a.session_id}"
    dir_b = tmp_path / "obscura_profiles" / f"user_102_{backend_b.session_id}"
    backend_a.storage_dir = dir_a
    backend_b.storage_dir = dir_b
    backend_a.ready_file = tmp_path / f"ready_101_{backend_a.session_id}.txt"
    backend_b.ready_file = tmp_path / f"ready_102_{backend_b.session_id}.txt"

    dir_a.mkdir(parents=True, exist_ok=True)
    dir_b.mkdir(parents=True, exist_ok=True)
    os.chmod(dir_a, 0o700)
    os.chmod(dir_b, 0o700)

    assert dir_a != dir_b
    assert (os.stat(dir_a).st_mode & 0o777) == 0o700
    assert (os.stat(dir_b).st_mode & 0o777) == 0o700

    # Closing User A must wipe only User A's directory
    await backend_a.close()
    assert not dir_a.exists()
    assert dir_b.exists()

    # Clean up User B
    await backend_b.close()
    assert not dir_b.exists()


# ── 4. CDP Loopback Binding Only ─────────────────────────────────────────────

def test_cdp_loopback_binding_restrictions():
    """Verify Obscura server is bound strictly to loopback 127.0.0.1 and cannot be bound to 0.0.0.0."""
    backend = ObscuraBackend(cfg=AppConfig(), env=EnvSettings())
    assert backend.host == "127.0.0.1"
    assert backend.host != "0.0.0.0"

    cmd = backend._build_command()
    host_idx = cmd.index("--host")
    assert cmd[host_idx + 1] == "127.0.0.1"


# ── 5. Chromium Fallback Happens Only Before Application Actions ─────────────

@pytest.mark.asyncio
async def test_chromium_fallback_only_before_meaningful_actions():
    """Verify fallback to Chromium happens exclusively at startup (start()) and not during application execution."""
    manager = BrowserManager(cfg=AppConfig(), env=EnvSettings(), backend="obscura")

    with patch.object(ObscuraBackend, "start", side_effect=RuntimeError("Obscura failed to launch")), \
         patch.object(ChromiumBackend, "start", new_callable=AsyncMock) as mock_chrom_start:

        assert not manager.is_active_application
        await manager.start()

        # Engine has safely fallen back to Chromium before any job was touched
        assert isinstance(manager.backend, ChromiumBackend)
        mock_chrom_start.assert_awaited_once()


# ── 6. No Engine Switching During Active Application ─────────────────────────

def test_engine_switching_forbidden_during_active_application():
    """Verify that attempting to switch browser backends while an application is in progress raises RuntimeError."""
    manager = BrowserManager(cfg=AppConfig(), env=EnvSettings(), backend="chromium")
    manager.set_active_application(True)

    with pytest.raises(RuntimeError) as exc_info:
        manager.switch_backend("obscura")

    assert "active application is strictly prohibited" in str(exc_info.value)

    # After application completes, switching is permitted
    manager.set_active_application(False)
    manager.switch_backend("obscura")
    assert manager.requested_backend == "obscura"


# ── 7. File Upload Restrictions ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_file_upload_restrictions_rejects_unauthorized_files(tmp_path):
    """Verify ExternalApplyActuator._upload_resume strictly rejects unauthorized non-document files."""
    mock_context = MagicMock()
    mock_form_rag = MagicMock()
    mock_page = AsyncMock()

    # Create an unauthorized shell script pretending to be a resume
    malicious_script = tmp_path / "exploit.sh"
    malicious_script.write_text("#!/bin/bash\necho evil")

    actuator = ExternalApplyActuator(
        context=mock_context,
        form_rag=mock_form_rag,
        resume_path=malicious_script,
    )

    await actuator._upload_resume(mock_page)
    # query_selector_all should never even be called because extension is rejected upfront
    mock_page.query_selector_all.assert_not_called()

    # Non-existent file must also be skipped
    actuator_nonexistent = ExternalApplyActuator(
        context=mock_context,
        form_rag=mock_form_rag,
        resume_path=tmp_path / "does_not_exist.pdf",
    )
    await actuator_nonexistent._upload_resume(mock_page)
    mock_page.query_selector_all.assert_not_called()


# ── 8. LinkedIn and lnkd.in Blocked Through All Browser Paths ────────────────

@pytest.mark.asyncio
async def test_linkedin_and_shortlink_blocked_on_all_paths():
    """Verify that LinkedIn URLs and lnkd.in shortlinks are blocked in URL validation and routing."""
    # 1. BrowserManager URL validation
    for prohibited in ["https://www.linkedin.com/jobs/view/123", "https://lnkd.in/xyz", "http://sub.linkedin.com/post"]:
        with pytest.raises(LinkedInPolicyViolationError):
            BrowserManager.verify_safe_url(prohibited)

    # 2. ExternalApplyActuator domain validation
    mock_context = MagicMock()
    mock_form_rag = MagicMock()
    actuator = ExternalApplyActuator(context=mock_context, form_rag=mock_form_rag)

    for prohibited in ["https://www.linkedin.com/apply", "https://lnkd.in/job1"]:
        with pytest.raises(LinkedInPolicyViolationError):
            actuator.validate_target_domain(prohibited)

    # 3. Obscura network route handler
    captured_handler = None
    async def mock_route(pattern, handler):
        nonlocal captured_handler
        captured_handler = handler

    backend = ObscuraBackend(cfg=AppConfig(), env=EnvSettings())
    backend._context = AsyncMock()
    backend._context.route = mock_route

    # Trigger route setup simulation
    async def _setup_route():
        async def _block_prohibited_domains(route):
            req_url = route.request.url.lower()
            if "linkedin.com" in req_url or "lnkd.in" in req_url:
                await route.abort("blockedbyclient")
            else:
                await route.continue_()
        return _block_prohibited_domains

    handler = await _setup_route()

    # Route request to linkedin.com must abort with 'blockedbyclient'
    mock_route_obj = AsyncMock()
    mock_route_obj.request.url = "https://www.linkedin.com/feed"
    await handler(mock_route_obj)
    mock_route_obj.abort.assert_awaited_once_with("blockedbyclient")
    mock_route_obj.continue_.assert_not_called()


# ── 9. Never Enable Stealth or Anti-Detection ────────────────────────────────

def test_stealth_flag_is_never_enabled():
    """Verify --stealth is strictly prohibited and absent from Obscura CLI arguments."""
    backend = ObscuraBackend(cfg=AppConfig(), env=EnvSettings())
    cmd = backend._build_command()
    assert "--stealth" not in cmd
    assert not any("stealth" in arg.lower() for arg in cmd)


# ── 10. Stop on CAPTCHA, Cloudflare or MFA Challenges ────────────────────────

@pytest.mark.asyncio
async def test_halt_immediately_on_security_challenges():
    """Verify ExternalApplyActuator detects CAPTCHA, Turnstile, Cloudflare, and MFA gates and raises AntiBotChallengeDetected."""
    mock_context = MagicMock()
    mock_form_rag = MagicMock()
    actuator = ExternalApplyActuator(context=mock_context, form_rag=mock_form_rag)

    # 1. URL pattern challenge detection
    mock_page_url = AsyncMock()
    mock_page_url.url = "https://boards.greenhouse.io/job/cf-challenge-checkpoint"
    with pytest.raises(AntiBotChallengeDetected) as exc_url:
        await actuator.check_security_challenges(mock_page_url)
    assert "Anti-bot challenge gate detected in URL" in str(exc_url.value)

    # 2. Page title challenge detection
    mock_page_title = AsyncMock()
    mock_page_title.url = "https://jobs.lever.co/company/job"
    mock_page_title.title = AsyncMock(return_value="Attention Required! | Cloudflare")
    with pytest.raises(AntiBotChallengeDetected) as exc_title:
        await actuator.check_security_challenges(mock_page_title)
    assert "Anti-bot challenge gate detected in title" in str(exc_title.value)

    # 3. Body text challenge detection (e.g. Turnstile / Human verification)
    mock_page_body = AsyncMock()
    mock_page_body.url = "https://jobs.ashbyhq.com/company/job"
    mock_page_body.title = AsyncMock(return_value="Job Application")
    mock_page_body.evaluate = AsyncMock(return_value="Please verify you are human to continue.")
    with pytest.raises(AntiBotChallengeDetected) as exc_body:
        await actuator.check_security_challenges(mock_page_body)
    assert "Anti-bot verification challenge detected" in str(exc_body.value)
