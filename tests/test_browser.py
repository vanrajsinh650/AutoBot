"""
Unit and integration tests for AutoBot v2.1 Browser & Computer Use Layer.
Verifies policy enforcement against LinkedIn automation, external ATS domain whitelisting,
anti-bot challenge detection halts, and session security.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.agent.state import JobPosting
from src.application.workflows import AntiBotChallengeDetected, LinkedInPolicyViolationError
from src.browser.bridge import BrowserBridge
from src.browser.easy_apply_actuator import EasyApplyActuator
from src.browser.external_apply_actuator import ExternalApplyActuator
from src.browser.manager import BrowserManager
from src.browser.navigator import LinkedInNavigator
from src.memory.form_rag import FormRAG
from src.memory.models import FormAnswer
from src.utils.config import AppConfig, EnvSettings


# ── Policy Enforcement Tests: LinkedIn Prohibition ───────────────────

@pytest.fixture(autouse=True)
def enable_strict_policy(monkeypatch):
    monkeypatch.setenv("AUTOBOT_STRICT_POLICY", "1")


def test_linkedin_navigator_strictly_prohibited():
    """Verify that attempting to initialize LinkedInNavigator raises LinkedInPolicyViolationError."""
    with pytest.raises(LinkedInPolicyViolationError) as exc_info:
        LinkedInNavigator()
    assert "Compliance Policy Violation" in str(exc_info.value)
    assert "prohibited" in str(exc_info.value).lower()


def test_easy_apply_actuator_strictly_prohibited():
    """Verify that attempting to initialize EasyApplyActuator raises LinkedInPolicyViolationError."""
    with pytest.raises(LinkedInPolicyViolationError) as exc_info:
        EasyApplyActuator()
    assert "Compliance Policy Violation" in str(exc_info.value)
    assert "prohibited" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_external_apply_actuator_prohibits_linkedin():
    """Verify that ExternalApplyActuator rejects any LinkedIn URLs with LinkedInPolicyViolationError."""
    context = AsyncMock()
    actuator = ExternalApplyActuator(
        context=context,
        form_rag=MagicMock(spec=FormRAG),
        cfg=AppConfig(),
    )

    linkedin_job = JobPosting(
        job_id="li_101",
        title="Backend Engineer",
        company="TechCo",
        url="https://www.linkedin.com/jobs/view/101",
    )

    with pytest.raises(LinkedInPolicyViolationError) as exc_info:
        await actuator.apply(linkedin_job)

    assert "Compliance Policy Violation" in str(exc_info.value)
    assert "strictly prohibited" in str(exc_info.value)
    # Ensure no browser tab was opened for LinkedIn
    context.new_page.assert_not_called()


@pytest.mark.asyncio
async def test_external_apply_actuator_rejects_unauthorized_domain():
    """Verify that ExternalApplyActuator rejects non-ATS domains."""
    context = AsyncMock()
    actuator = ExternalApplyActuator(
        context=context,
        form_rag=MagicMock(spec=FormRAG),
        cfg=AppConfig(),
    )

    random_job = JobPosting(
        job_id="rand_1",
        title="Software Engineer",
        company="Unknown",
        url="https://sketchy-random-site.biz/apply",
    )

    with pytest.raises(ValueError) as exc_info:
        await actuator.apply(random_job)

    assert "not authorized for automated ATS application" in str(exc_info.value)


@pytest.mark.asyncio
async def test_external_apply_actuator_authorized_ats_success(tmp_path):
    """Verify successful application flow on authorized ATS domain (Greenhouse)."""
    context = AsyncMock()
    tab = AsyncMock()
    tab.url = "https://boards.greenhouse.io/stripe/jobs/101"
    tab.title = AsyncMock(return_value="Careers at Stripe")
    tab.evaluate = AsyncMock(return_value="Apply for this job")
    context.new_page = AsyncMock(return_value=tab)

    submit_btn = AsyncMock()
    submit_btn.is_visible = AsyncMock(return_value=True)
    submit_btn.is_enabled = AsyncMock(return_value=True)

    tab.query_selector_all = AsyncMock(return_value=[])

    async def tab_query_selector(sel):
        if "submit" in sel.lower():
            return submit_btn
        return None

    tab.query_selector = AsyncMock(side_effect=tab_query_selector)

    form_rag = MagicMock(spec=FormRAG)
    form_rag.answer_question.return_value = FormAnswer(
        question="test", answer="Sarah", confidence=1.0, source="test"
    )

    resume_file = tmp_path / "resume.pdf"
    resume_file.write_bytes(b"%PDF-1.4 mock")

    actuator = ExternalApplyActuator(
        context=context,
        form_rag=form_rag,
        cfg=AppConfig(),
        resume_path=resume_file,
    )

    job = JobPosting(
        job_id="gh-1",
        title="Software Engineer",
        company="Stripe",
        url="https://boards.greenhouse.io/stripe/jobs/101",
        is_easy_apply=False,
    )

    result = await actuator.apply(job)
    assert result is True
    tab.close.assert_called_once()


@pytest.mark.asyncio
async def test_external_apply_halts_on_anti_bot_challenge():
    """Verify that detecting Cloudflare / CAPTCHA challenge halts immediately without solving."""
    context = AsyncMock()
    tab = AsyncMock()
    tab.url = "https://boards.greenhouse.io/challenge-running"
    context.new_page = AsyncMock(return_value=tab)

    actuator = ExternalApplyActuator(
        context=context,
        form_rag=MagicMock(spec=FormRAG),
        cfg=AppConfig(),
    )

    job = JobPosting(
        job_id="gh-challenge",
        title="Software Engineer",
        company="Acme",
        url="https://boards.greenhouse.io/acme/jobs/1",
    )

    with pytest.raises(AntiBotChallengeDetected) as exc_info:
        await actuator.apply(job)

    assert "Anti-bot challenge gate detected" in str(exc_info.value)


# ── BrowserBridge Compliance Tests ───────────────────────────────────

@pytest.mark.asyncio
async def test_browser_bridge_rejects_linkedin_jobs():
    """Verify BrowserBridge refuses automated execution for LinkedIn jobs."""
    bridge = BrowserBridge(
        form_rag=MagicMock(),
        cfg=AppConfig(),
        env=EnvSettings(),
    )
    bridge.manager = MagicMock()
    bridge.manager.page = AsyncMock()

    easy_job = JobPosting(job_id="1", title="Dev", company="A", is_easy_apply=True, url="https://linkedin.com/jobs/1")
    with pytest.raises(LinkedInPolicyViolationError) as exc_info:
        await bridge.application_executor(easy_job)

    assert "Compliance Policy Violation" in str(exc_info.value)


@pytest.mark.asyncio
async def test_browser_bridge_rejects_search_provider():
    """Verify BrowserBridge search provider raises LinkedInPolicyViolationError."""
    bridge = BrowserBridge(
        form_rag=MagicMock(),
        cfg=AppConfig(),
        env=EnvSettings(),
    )

    with pytest.raises(LinkedInPolicyViolationError):
        await bridge.search_provider("Python", "Remote", 1)


# ── Cookie & Session Security Tests ─────────────────────────────────

@pytest.mark.asyncio
async def test_browser_manager_strips_li_at_cookie(tmp_path):
    """Verify save_session_state removes li_at cookie and never persists it to disk."""
    session_file = tmp_path / "browser_state.json"
    manager = BrowserManager(cfg=AppConfig(), env=EnvSettings(), session_file=session_file)

    mock_context = AsyncMock()
    mock_context.cookies = AsyncMock(
        return_value=[
            {"name": "li_at", "value": "secret_session_token", "domain": ".linkedin.com"},
            {"name": "session_id", "value": "allowed_token", "domain": "example.com"},
        ]
    )
    mock_context.clear_cookies = AsyncMock()
    mock_context.storage_state = AsyncMock()
    manager.context = mock_context

    await manager.save_session_state()

    # Must clear prohibited li_at cookie
    mock_context.clear_cookies.assert_called_with(name="li_at", domain=".linkedin.com")
    mock_context.storage_state.assert_called_once_with(path=str(session_file))


# ── Human Interaction Simulation Tests ──────────────────────────────

@pytest.mark.asyncio
async def test_human_behavior_visual_click_with_bounding_box():
    """Verify visual_click performs smooth motion, animation, and element click."""
    from src.utils.human_behavior import visual_click

    page = AsyncMock()
    page.evaluate = AsyncMock()
    page.mouse = AsyncMock()
    page.mouse.move = AsyncMock()
    page.mouse.click = AsyncMock()

    element = AsyncMock()
    element.scroll_into_view_if_needed = AsyncMock()
    element.bounding_box = AsyncMock(return_value={"x": 100, "y": 200, "width": 80, "height": 30})
    element.click = AsyncMock()

    success = await visual_click(page, element, action_text="Testing visual click", delay_after=0.01)

    assert success is True
    element.click.assert_called_once()
    assert page.mouse.move.called
    assert page.evaluate.called


@pytest.mark.asyncio
async def test_human_behavior_visual_type():
    """Verify visual_type focuses element and types characters with keyboard."""
    from src.utils.human_behavior import visual_type

    page = AsyncMock()
    page.evaluate = AsyncMock()
    page.mouse = AsyncMock()
    page.keyboard = AsyncMock()
    page.keyboard.type = AsyncMock()

    element = AsyncMock()
    element.bounding_box = AsyncMock(return_value={"x": 50, "y": 50, "width": 120, "height": 25})
    element.click = AsyncMock()

    await visual_type(page, element, "Hello", action_text="Entering test text")

    element.click.assert_called_once()
    assert page.keyboard.type.call_count == len("Hello")


@pytest.mark.asyncio
async def test_human_behavior_visual_type_masks_password():
    """Verify visual_type masks password text in the floating action badge."""
    from src.utils.human_behavior import visual_type

    page = AsyncMock()
    page.evaluate = AsyncMock()
    page.mouse = AsyncMock()
    page.keyboard = AsyncMock()

    element = AsyncMock()
    element.bounding_box = AsyncMock(return_value={"x": 100, "y": 100, "width": 200, "height": 30})
    element.click = AsyncMock()

    await visual_type(page, element, "super_secret_pw", is_password=True)

    for call in page.evaluate.call_args_list:
        args = call[0]
        if len(args) > 1 and isinstance(args[1], list):
            for param in args[1]:
                if isinstance(param, str):
                    assert "super_secret_pw" not in param
