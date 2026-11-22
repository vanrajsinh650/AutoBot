"""
Tests for Groq AI Form Intelligence Assistant.
Verifies apply button identification and intelligent field mapping.
"""

from unittest.mock import AsyncMock, patch
import pytest

from src.browser.groq_form_assistant import (
    identify_apply_button_with_groq,
    map_unrecognized_form_fields_with_groq,
)


@pytest.mark.asyncio
async def test_identify_apply_button_with_groq():
    mock_page = AsyncMock()
    mock_page.evaluate.return_value = [
        {"tag": "a", "text": "About Company", "aria": "", "href": "/about", "id": "nav_about", "dataPhAt": "", "dataAuto": ""},
        {"tag": "button", "text": "Apply Now", "aria": "Apply for Python Developer", "href": "", "id": "btn_apply_main", "dataPhAt": "apply-button", "dataAuto": ""},
        {"tag": "a", "text": "Share Job", "aria": "", "href": "#share", "id": "btn_share", "dataPhAt": "", "dataAuto": ""},
    ]

    mock_groq_response = {
        "best_index": 1,
        "selector_hint": "#btn_apply_main",
        "reason": "Button with text 'Apply Now' initiates the job application process.",
    }

    with patch("src.browser.groq_form_assistant.call_groq_json", return_value=mock_groq_response):
        selector = await identify_apply_button_with_groq(mock_page, "Python Developer")
        assert selector == "#btn_apply_main"


@pytest.mark.asyncio
async def test_map_unrecognized_form_fields_with_groq():
    mock_page = AsyncMock()
    mock_page.evaluate.return_value = [
        {"id": "field_981_fn", "name": "c_fname", "type": "text", "placeholder": "Given name", "label": "First name", "tag": "input"},
        {"id": "field_982_ln", "name": "c_lname", "type": "text", "placeholder": "Family name", "label": "Surname", "tag": "input"},
    ]

    mock_groq_response = {
        "mappings": [
            {"id": "field_981_fn", "field_type": "firstName", "fill_value": "Vanraj"},
            {"id": "field_982_ln", "field_type": "lastName", "fill_value": "Solanki"},
        ]
    }

    with patch("src.browser.groq_form_assistant.call_groq_json", return_value=mock_groq_response):
        candidate_info = {"first_name": "Vanraj", "last_name": "Solanki"}
        mappings = await map_unrecognized_form_fields_with_groq(mock_page, candidate_info)
        assert len(mappings) == 2
        assert mappings[0]["fill_value"] == "Vanraj"
        assert mappings[1]["fill_value"] == "Solanki"
