"""
Test suite for AutoBot universal multi-step form filling engine.
Validates iframe traversal, dropdown selections, radio groups, checkboxes, and multi-step progression.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.agent.state import JobPosting
from src.browser.external_apply_actuator import ExternalApplyActuator
from src.browser.groq_form_assistant import answer_question_with_groq
from src.memory.form_rag import FormRAG
from src.memory.models import FieldType, FormAnswer
from src.utils.config import AppConfig


@pytest.mark.asyncio
async def test_iframe_interactive_contexts():
    """Verify actuator finds elements inside child frames/iframes."""
    context = AsyncMock()
    page = AsyncMock()
    frame1 = AsyncMock()
    frame1.is_detached = MagicMock(return_value=False)
    page.main_frame = page
    page.frames = [page, frame1]

    actuator = ExternalApplyActuator(context=context, cfg=AppConfig())
    contexts = actuator._get_interactive_contexts(page)
    assert len(contexts) == 2
    assert contexts[0] == page
    assert contexts[1] == frame1


@pytest.mark.asyncio
async def test_checkbox_consent_filling():
    """Verify actuator checks required and terms/privacy checkboxes."""
    context = AsyncMock()
    page = AsyncMock()
    page.frames = []

    chk1 = AsyncMock()
    chk1.is_visible = AsyncMock(return_value=True)
    chk1.is_checked = AsyncMock(return_value=False)
    chk1.check = AsyncMock()

    page.query_selector_all = AsyncMock(return_value=[chk1])
    page.evaluate = AsyncMock(return_value={
        "text": "i agree to the privacy policy and data processing terms",
        "isRequired": True
    })

    actuator = ExternalApplyActuator(context=context, cfg=AppConfig())
    checked = await actuator._fill_checkboxes(page)
    assert checked == 1
    chk1.check.assert_called_once()


@pytest.mark.asyncio
async def test_radio_group_filling():
    """Verify actuator correctly answers and checks radio buttons."""
    context = AsyncMock()
    page = AsyncMock()
    page.frames = []

    radio_yes = AsyncMock()
    radio_yes.check = AsyncMock()

    page.evaluate = AsyncMock(return_value={
        "work_authorization": [
            {"id": "auth_yes", "label": "Yes", "value": "yes", "checked": False, "question": "Are you authorized to work in India?"},
            {"id": "auth_no", "label": "No", "value": "no", "checked": False, "question": "Are you authorized to work in India?"},
        ]
    })
    page.query_selector = AsyncMock(return_value=radio_yes)

    actuator = ExternalApplyActuator(context=context, cfg=AppConfig())
    filled = await actuator._fill_radio_groups(page)
    assert filled == 1
    radio_yes.check.assert_called_once()


@pytest.mark.asyncio
async def test_select_dropdown_filling():
    """Verify actuator selects matching option from select dropdown."""
    context = AsyncMock()
    page = AsyncMock()
    page.frames = []

    select_el = AsyncMock()
    select_el.is_visible = AsyncMock(return_value=True)
    select_el.select_option = AsyncMock()

    page.query_selector_all = AsyncMock(return_value=[select_el])
    page.evaluate = AsyncMock(return_value={
        "label": "Do you require visa sponsorship?",
        "options": [
            {"text": "Yes, I require visa sponsorship", "value": "yes"},
            {"text": "No, I do not require sponsorship", "value": "no"}
        ],
        "currentValue": ""
    })

    actuator = ExternalApplyActuator(context=context, cfg=AppConfig())
    filled = await actuator._fill_select_dropdowns(page)
    assert filled == 1
    select_el.select_option.assert_called_once_with(value="no")


def test_answer_question_with_groq_heuristics():
    """Verify answer_question_with_groq fast heuristics for work auth and sponsorship."""
    ans1 = answer_question_with_groq("Are you legally authorized to work in India?", options=["Yes", "No"])
    assert ans1 == "Yes"

    ans2 = answer_question_with_groq("Will you require visa sponsorship now or in the future?", options=["Yes", "No"])
    assert ans2 == "No"

    ans3 = answer_question_with_groq("Are you 18 years of age or older?", options=["Yes", "No"])
    assert ans3 == "Yes"


def test_safe_id_selector_and_real_candidate_profile():
    """Verify UUIDs starting with digits and bracketed IDs produce valid attribute selectors."""
    from src.browser.external_apply_actuator import _safe_id_selector, load_candidate_profile_info

    assert _safe_id_selector("first_name") == "#first_name"
    assert _safe_id_selector("642f7244-779f-447a") == '[id="642f7244-779f-447a"]'
    assert _safe_id_selector("question_17772254008[]") == '[id="question_17772254008[]"]'

    info = load_candidate_profile_info()
    assert "Vanraj" in info["full_name"]
    assert "Gokul" in info["university"]
    assert "BCA" in info["degree"] or "Computer Applications" in info["degree"]
