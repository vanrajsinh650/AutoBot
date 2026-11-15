"""
Unit and integration tests for AutoBot v2 Browser & Computer Use Layer.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.agent.state import JobPosting
from src.browser.bridge import BrowserBridge
from src.browser.easy_apply_actuator import EasyApplyActuator
from src.browser.external_apply_actuator import ExternalApplyActuator
from src.browser.manager import BrowserManager
from src.browser.navigator import LinkedInNavigator
from src.memory.form_rag import FormRAG
from src.memory.models import FieldType, FormAnswer
from src.utils.config import AppConfig, EnvSettings


# ── LinkedInNavigator URL & Parsing Tests ─────────────────────────

def test_navigator_build_search_url():
    """Verify search URL query parameter construction and pagination math."""
    cfg = AppConfig()
    cfg.search.date_posted = "week"
    cfg.search.remote = True
    cfg.search.experience_level = ["entry", "mid-senior"]

    env = EnvSettings()
    manager = MagicMock(spec=BrowserManager)
    nav = LinkedInNavigator(manager=manager, cfg=cfg, env=env)

    # Page 1
    url_p1 = nav.build_search_url("Python Developer", "India", page=1)
    assert "keywords=Python+Developer" in url_p1 or "keywords=Python%20Developer" in url_p1 or "keywords=Python Developer" in url_p1
    assert "location=India" in url_p1
    assert "start=0" in url_p1
    assert "f_TPR=r604800" in url_p1
    assert "f_WT=2" in url_p1
    assert "f_E=2%2C4" in url_p1

    # Page 3 (start offset must be 50)
    url_p3 = nav.build_search_url("Python Developer", "India", page=3)
    assert "start=50" in url_p3


@pytest.mark.asyncio
async def test_navigator_parse_job_card():
    """Verify metadata extraction from mock job card DOM element."""
    card = AsyncMock()
    card.get_attribute = AsyncMock(side_effect=lambda attr: "123456" if attr == "data-job-id" else "")

    title_el = AsyncMock()
    title_el.inner_text = AsyncMock(return_value="Backend Engineer\n")
    title_el.get_attribute = AsyncMock(return_value="/jobs/view/123456")

    comp_el = AsyncMock()
    comp_el.inner_text = AsyncMock(return_value="Acme Corp")

    loc_el = AsyncMock()
    loc_el.inner_text = AsyncMock(return_value="Bengaluru, Karnataka")

    easy_badge = AsyncMock()

    async def query_selector_side_effect(sel):
        if "description" in sel or "subtitle" in sel or "company" in sel:
            return comp_el
        if "metadata" in sel or "caption" in sel:
            return loc_el
        if "Easy Apply" in sel:
            return easy_badge
        if "title" in sel or "view" in sel or "link" in sel:
            return title_el
        return None

    card.query_selector = AsyncMock(side_effect=query_selector_side_effect)

    nav = LinkedInNavigator(manager=MagicMock(), cfg=AppConfig(), env=EnvSettings())
    job = await nav._parse_job_card(card)

    assert job is not None
    assert job.job_id == "123456"
    assert job.title == "Backend Engineer"
    assert job.company == "Acme Corp"
    assert job.location == "Bengaluru, Karnataka"
    assert job.is_easy_apply is True
    assert "https://www.linkedin.com/jobs/view/123456" in job.url


# ── EasyApplyActuator Tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_easy_apply_actuator_success_flow(tmp_path):
    """Verify multi-step form walking, field filling, and submit execution."""
    page = AsyncMock()

    # Easy Apply button
    easy_apply_btn = AsyncMock()
    easy_apply_btn.is_visible = AsyncMock(return_value=True)

    # Modal element
    modal_el = AsyncMock()

    # Submit button
    submit_btn = AsyncMock()
    submit_btn.is_visible = AsyncMock(return_value=True)
    submit_btn.is_enabled = AsyncMock(return_value=True)

    # Configure query_selector mock
    async def page_query_selector(sel):
        if "jobs-apply-button" in sel or "Easy Apply" in sel:
            return easy_apply_btn
        if "easy-apply-modal" in sel or "modal" in sel:
            return modal_el
        if "Submit application" in sel or "Submit" in sel:
            return submit_btn
        return None

    page.query_selector = AsyncMock(side_effect=page_query_selector)
    page.query_selector_all = AsyncMock(return_value=[])

    form_rag = MagicMock(spec=FormRAG)
    resume_file = tmp_path / "resume.pdf"
    resume_file.write_bytes(b"%PDF-1.4 mock resume")

    actuator = EasyApplyActuator(
        page=page,
        form_rag=form_rag,
        cfg=AppConfig(),
        resume_path=resume_file,
    )

    job = JobPosting(job_id="999", title="Dev", company="Co", url="https://linkedin.com/jobs/view/999")
    success = await actuator.apply(job)

    assert success is True
    submit_btn.click.assert_called_once()


@pytest.mark.asyncio
async def test_easy_apply_actuator_button_missing():
    """Verify graceful rejection when Easy Apply button is absent."""
    page = AsyncMock()
    page.query_selector = AsyncMock(return_value=None)

    actuator = EasyApplyActuator(
        page=page,
        form_rag=MagicMock(),
        cfg=AppConfig(),
    )

    job = JobPosting(job_id="888", title="Dev", company="Co", url="")
    success = await actuator.apply(job)
    assert success is False


# ── ExternalApplyActuator Tests ────────────────────────────────────

@pytest.mark.asyncio
async def test_external_apply_actuator(tmp_path):
    """Verify external portal navigation, field filling, and submit attempt."""
    context = AsyncMock()
    tab = AsyncMock()
    context.new_page = AsyncMock(return_value=tab)

    # Submit button
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
        question="test", answer="John", confidence=1.0, source="test"
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
        job_id="ext-1",
        title="Software Engineer",
        company="Stripe",
        url="https://stripe.com/jobs/apply",
        is_easy_apply=False,
    )

    result = await actuator.apply(job)
    assert result is True
    tab.close.assert_called_once()


# ── BrowserBridge Tests ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_browser_bridge_routing():
    """Verify BrowserBridge correctly routes Easy Apply vs External Apply."""
    bridge = BrowserBridge(
        form_rag=MagicMock(),
        cfg=AppConfig(),
        env=EnvSettings(),
    )

    # Mock actuators
    bridge.manager = MagicMock()
    bridge.manager.page = AsyncMock()
    bridge.easy_apply_actuator = AsyncMock()
    bridge.easy_apply_actuator.apply = AsyncMock(return_value=True)
    bridge.external_apply_actuator = AsyncMock()
    bridge.external_apply_actuator.apply = AsyncMock(return_value=True)

    # 1. Easy Apply Job
    easy_job = JobPosting(job_id="1", title="Dev", company="A", is_easy_apply=True)
    res1 = await bridge.application_executor(easy_job)
    assert res1 is True
    bridge.easy_apply_actuator.apply.assert_called_once()

    # 2. External Job
    ext_job = JobPosting(job_id="2", title="Dev", company="B", is_easy_apply=False)
    res2 = await bridge.application_executor(ext_job)
    assert res2 is True
    bridge.external_apply_actuator.apply.assert_called_once()


# ── Visual Cursor & Session Persistence Tests ───────────────────────

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
async def test_browser_manager_session_persistence(tmp_path):
    """Verify BrowserManager path initialization and session save calls."""
    session_file = tmp_path / "session" / "linkedin_state.json"
    manager = BrowserManager(
        cfg=AppConfig(),
        env=EnvSettings(),
        session_file=session_file,
    )

    assert manager.session_file == session_file
    assert manager.user_data_dir == session_file.parent / "user_data"

    # Mock context to verify save_session_state
    mock_context = AsyncMock()
    mock_context.storage_state = AsyncMock()
    mock_context.close = AsyncMock()
    manager.context = mock_context

    await manager.save_session_state()
    mock_context.storage_state.assert_called_once_with(path=str(session_file))

    # Test auto-save on close
    mock_context.storage_state.reset_mock()
    await manager.close()
    mock_context.storage_state.assert_called_once_with(path=str(session_file))
    mock_context.close.assert_called_once()


@pytest.mark.asyncio
async def test_navigator_is_authenticated_checks():
    """Verify is_authenticated recognizes li_at cookie and unauth walls."""
    manager = MagicMock(spec=BrowserManager)
    page = AsyncMock()
    manager.page = page

    nav = LinkedInNavigator(manager=manager, cfg=AppConfig(), env=EnvSettings())

    # Case 1: Authwall in URL -> False
    page.url = "https://www.linkedin.com/authwall"
    assert await nav.is_authenticated() is False

    # Case 2: Login URL -> False
    page.url = "https://www.linkedin.com/login"
    assert await nav.is_authenticated() is False

    # Case 3: On feed with li_at cookie -> True
    page.url = "https://www.linkedin.com/feed"
    page.context = AsyncMock()
    page.context.cookies = AsyncMock(return_value=[{"name": "li_at", "value": "AQED..."}])
    locator_mock = AsyncMock()
    locator_mock.count = AsyncMock(return_value=0)
    page.locator = MagicMock(return_value=locator_mock)

    assert await nav.is_authenticated() is True

    # Case 4: On feed with global nav in DOM -> True
    page.context.cookies = AsyncMock(return_value=[])
    locator_mock.count = AsyncMock(return_value=1)
    assert await nav.is_authenticated() is True


@pytest.mark.asyncio
async def test_navigator_open_jobs_section_visual_click():
    """Verify open_jobs_section locates Jobs nav item and clicks it with visual cursor."""
    manager = MagicMock(spec=BrowserManager)
    page = AsyncMock()
    page.url = "https://www.linkedin.com/feed/"
    manager.page = page

    jobs_link = AsyncMock()
    jobs_link.is_visible = AsyncMock(return_value=True)
    jobs_link.bounding_box = AsyncMock(return_value={"x": 500, "y": 30, "width": 60, "height": 40})
    jobs_link.click = AsyncMock()

    page.query_selector = AsyncMock(return_value=jobs_link)
    page.evaluate = AsyncMock()
    page.mouse = AsyncMock()
    page.mouse.move = AsyncMock()

    nav = LinkedInNavigator(manager=manager, cfg=AppConfig(), env=EnvSettings())
    await nav.open_jobs_section()

    jobs_link.click.assert_called_once()
    assert page.mouse.move.called


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

    # Check evaluate calls to ensure raw password is not sent to cursor badge text
    for call in page.evaluate.call_args_list:
        args = call[0]
        if len(args) > 1 and isinstance(args[1], list):
            for param in args[1]:
                if isinstance(param, str):
                    assert "super_secret_pw" not in param


@pytest.mark.asyncio
async def test_browser_manager_safe_session_save(tmp_path):
    """Verify save_session_state skips overwriting valid session if context lacks li_at."""
    session_file = tmp_path / "linkedin_state.json"
    session_file.write_text('{"cookies": [{"name": "li_at", "value": "valid_token"}]}')

    manager = BrowserManager(cfg=AppConfig(), env=EnvSettings(), session_file=session_file)
    mock_context = AsyncMock()
    # Context currently has NO li_at cookie
    mock_context.cookies = AsyncMock(return_value=[{"name": "some_cookie", "value": "123"}])
    mock_context.storage_state = AsyncMock()
    manager.context = mock_context

    # Attempt save with only_if_authenticated=True
    await manager.save_session_state(only_if_authenticated=True)

    # storage_state must NOT have been called, preserving disk session
    mock_context.storage_state.assert_not_called()
    assert "valid_token" in session_file.read_text()


