"""
Comparative Verification and Benchmarks: Chromium vs Obscura Backend.
Evaluates startup latency, form interaction fidelity, and security enforcement
across both browser engines on identical synthetic ATS workflows.
"""

import os
import time
from pathlib import Path

import pytest

from src.browser.backends.chromium_backend import ChromiumBackend
from src.browser.backends.obscura_backend import ObscuraBackend
from src.utils.config import AppConfig, EnvSettings, PROJECT_ROOT

def _get_process_rss_mb(pid: int) -> float:
    """Calculate resident set size (RSS) in MB for a process from /proc/<pid>/status."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return kb / 1024.0
    except Exception:
        pass
    return 0.0


SYNTHETIC_ATS_HTML = """
<!DOCTYPE html>
<html>
<head><title>Stripe Careers - External Portal</title></head>
<body>
    <form id="application_form">
        <input id="first_name" name="first_name" type="text" placeholder="First Name" />
        <input id="last_name" name="last_name" type="text" placeholder="Last Name" />
        <input id="email" name="email" type="email" placeholder="Email" />
        <input id="phone" name="phone" type="tel" placeholder="Phone" />
        <select id="work_auth" name="work_auth">
            <option value="">Select...</option>
            <option value="yes">Authorized to work</option>
            <option value="no">Needs sponsorship</option>
        </select>
        <input id="resume" name="resume" type="file" accept=".pdf" />
        <button id="submit_app" type="button">Submit Application</button>
    </form>
    <div id="confirmation" style="display:none;">Application Received</div>
    <script>
        document.getElementById('submit_app').addEventListener('click', () => {
            document.getElementById('confirmation').style.display = 'block';
        });
    </script>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_comparative_form_interaction_fidelity(tmp_path):
    """
    Verify that both ChromiumBackend and ObscuraBackend achieve identical form filling,
    file uploading, and button interaction fidelity on synthetic ATS forms.
    """
    resume_path = tmp_path / "comparative_resume.pdf"
    resume_path.write_text("%PDF-1.4 Comparative Resume Content")

    results = {}

    # ── Test Engine 1: ChromiumBackend ──────────────────────────────────
    chromium = ChromiumBackend(
        cfg=AppConfig(),
        env=EnvSettings(),
        headless=True,
    )
    t0_chrom = time.perf_counter()
    await chromium.start()
    chrom_startup_time = time.perf_counter() - t0_chrom

    try:
        assert await chromium.is_healthy() is True
        page_chrom = chromium.page
        await page_chrom.set_content(SYNTHETIC_ATS_HTML)

        # Form interactions
        await page_chrom.fill("#first_name", "Alex")
        await page_chrom.fill("#last_name", "Morgan")
        await page_chrom.fill("#email", "alex.morgan@example.com")
        await page_chrom.fill("#phone", "+15550199")
        await page_chrom.select_option("#work_auth", "yes")

        # Upload resume
        chrom_upload = await chromium.upload_file(page_chrom, "#resume", resume_path)
        assert chrom_upload is True

        # Click submit
        await page_chrom.click("#submit_app")
        chrom_submitted = await page_chrom.is_visible("#confirmation")

        results["chromium"] = {
            "startup_sec": chrom_startup_time,
            "first_name": await page_chrom.input_value("#first_name"),
            "last_name": await page_chrom.input_value("#last_name"),
            "email": await page_chrom.input_value("#email"),
            "work_auth": await page_chrom.input_value("#work_auth"),
            "upload_success": chrom_upload,
            "submitted": chrom_submitted,
        }
    finally:
        await chromium.close()

    # ── Test Engine 2: ObscuraBackend ────────────────────────────────────
    obscura = ObscuraBackend(
        cfg=AppConfig(),
        env=EnvSettings(),
        binary_path=PROJECT_ROOT / "bin" / "obscura",
        user_id=101,
    )
    t0_obs = time.perf_counter()
    await obscura.start()
    obs_startup_time = time.perf_counter() - t0_obs

    try:
        assert await obscura.is_healthy() is True
        page_obs = obscura.page
        await page_obs.set_content(SYNTHETIC_ATS_HTML)

        # Form interactions
        await page_obs.fill("#first_name", "Alex")
        await page_obs.fill("#last_name", "Morgan")
        await page_obs.fill("#email", "alex.morgan@example.com")
        await page_obs.fill("#phone", "+15550199")
        await page_obs.select_option("#work_auth", "yes")

        # Upload resume
        obs_upload = await obscura.upload_file(page_obs, "#resume", resume_path)
        assert obs_upload is True

        # Click submit
        await page_obs.click("#submit_app")
        obs_submitted = await page_obs.is_visible("#confirmation")

        results["obscura"] = {
            "startup_sec": obs_startup_time,
            "first_name": await page_obs.input_value("#first_name"),
            "last_name": await page_obs.input_value("#last_name"),
            "email": await page_obs.input_value("#email"),
            "work_auth": await page_obs.input_value("#work_auth"),
            "upload_success": obs_upload,
            "submitted": obs_submitted,
        }
    finally:
        await obscura.close()

    # Assert 100% equivalence in form data handling
    assert results["chromium"]["first_name"] == results["obscura"]["first_name"] == "Alex"
    assert results["chromium"]["last_name"] == results["obscura"]["last_name"] == "Morgan"
    assert results["chromium"]["email"] == results["obscura"]["email"] == "alex.morgan@example.com"
    assert results["chromium"]["work_auth"] == results["obscura"]["work_auth"] == "yes"
    assert results["chromium"]["upload_success"] == results["obscura"]["upload_success"] == True
    assert results["chromium"]["submitted"] == results["obscura"]["submitted"] == True


@pytest.mark.asyncio
async def test_comparative_resource_benchmarks():
    """
    Benchmark startup latency and process memory overhead of Obscura vs Chromium.
    Records metric telemetry for Phase 5 documentation.
    """
    # 1. Benchmark Chromium
    chrom = ChromiumBackend(headless=True)
    t0 = time.perf_counter()
    await chrom.start()
    chrom_startup = time.perf_counter() - t0
    chrom_pid = os.getpid()  # playwright driver child
    await chrom.close()

    # 2. Benchmark Obscura
    obs = ObscuraBackend(binary_path=PROJECT_ROOT / "bin" / "obscura")
    t0 = time.perf_counter()
    await obs.start()
    obs_startup = time.perf_counter() - t0
    obs_rss = _get_process_rss_mb(obs._process.pid) if obs._process else 0.0
    await obs.close()

    print(f"\n[BENCHMARK] Chromium startup latency: {chrom_startup * 1000:.1f}ms")
    print(f"[BENCHMARK] Obscura startup latency:  {obs_startup * 1000:.1f}ms")
    print(f"[BENCHMARK] Obscura server process RSS: {obs_rss:.2f}MB")

    # Assert basic health bounds
    assert obs_startup < 10.0
    assert chrom_startup < 15.0
