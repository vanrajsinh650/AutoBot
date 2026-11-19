"""
Tests for AutoBot Contextual Sign-In Modal & Guest Popup Handler.

Verifies:
1. Detection and clicking of close ('X') icons on LinkedIn guest contextual sign-in modals.
2. Selector coverage for all modal dismiss button variants (aria-label, data-tracking, classes).
3. Escape key fallback and DOM cleanup.
4. Visual cursor integration when closing popups.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.browser.popup_handler import (
    CLOSE_BUTTON_SELECTORS,
    MODAL_CONTAINER_SELECTORS,
    dismiss_sign_in_popup,
    find_close_button,
    install_popup_observer,
    is_popup_present,
    recover_from_authwall,
)


@pytest.mark.asyncio
async def test_find_close_button_by_selector():
    page = AsyncMock()
    mock_btn = AsyncMock()
    mock_btn.is_visible.return_value = True

    async def mock_query_selector(sel):
        if sel == "button.contextual-sign-in-modal__modal-dismiss":
            return mock_btn
        return None

    page.query_selector.side_effect = mock_query_selector

    btn = await find_close_button(page)
    assert btn == mock_btn


@pytest.mark.asyncio
async def test_find_close_button_by_aria_fallback():
    page = AsyncMock()
    page.query_selector.return_value = None

    btn1 = AsyncMock()
    btn1.get_attribute.return_value = "Search"
    btn1.is_visible.return_value = True

    btn2 = AsyncMock()
    btn2.get_attribute.return_value = "Dismiss"
    btn2.is_visible.return_value = True

    page.query_selector_all.return_value = [btn1, btn2]

    btn = await find_close_button(page)
    assert btn == btn2


@pytest.mark.asyncio
async def test_is_popup_present():
    page = AsyncMock()
    # When button is found
    mock_btn = AsyncMock()
    mock_btn.is_visible.return_value = True
    page.query_selector.return_value = mock_btn

    assert await is_popup_present(page) is True

    # When no button and no container
    page.query_selector.return_value = None
    page.query_selector_all.return_value = []
    assert await is_popup_present(page) is False


@pytest.mark.asyncio
async def test_dismiss_sign_in_popup_success():
    page = AsyncMock()
    mock_btn = AsyncMock()
    mock_btn.is_visible.side_effect = [True, False, False]
    mock_btn.bounding_box.return_value = {"x": 500, "y": 150, "width": 40, "height": 40}

    # First call returns button, second call (verification) returns None (dismissed)
    page.query_selector.side_effect = [mock_btn, None, None, None, None, None]
    page.query_selector_all.return_value = []
    page.evaluate.return_value = True

    with patch("src.utils.human_behavior.smooth_move_cursor", new_callable=AsyncMock) as mock_cursor, \
         patch("src.utils.human_behavior.update_visual_cursor", new_callable=AsyncMock) as mock_badge:
        result = await dismiss_sign_in_popup(page, use_visual_cursor=True)

    assert result is True
    mock_btn.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_dismiss_sign_in_popup_fallback_escape():
    page = AsyncMock()
    mock_btn = AsyncMock()
    mock_btn.is_visible.return_value = True
    mock_btn.click.side_effect = Exception("Element obscured")
    mock_btn.bounding_box.return_value = None

    # First query returns button, subsequent checks show container still present until Escape
    call_count = 0
    async def mock_query(sel):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return mock_btn
        return None

    page.query_selector.side_effect = mock_query
    page.query_selector_all.return_value = []
    page.evaluate.return_value = False
    page.keyboard = AsyncMock()

    result = await dismiss_sign_in_popup(page, use_visual_cursor=False, max_retries=1)

    page.keyboard.press.assert_awaited_with("Escape")


@pytest.mark.asyncio
async def test_install_popup_observer():
    page = AsyncMock()
    await install_popup_observer(page)
    page.evaluate.assert_awaited_once()


def test_selector_coverage():
    # Verify exact selectors matching the user's screenshot
    assert any("contextual-sign-in-modal" in s for s in CLOSE_BUTTON_SELECTORS)
    assert any("modal_dismiss" in s for s in CLOSE_BUTTON_SELECTORS)
    assert any("Dismiss" in s for s in CLOSE_BUTTON_SELECTORS)
    assert any(".modal--contextual-sign-in" in s for s in MODAL_CONTAINER_SELECTORS)


@pytest.mark.asyncio
async def test_recover_from_authwall_with_job_id():
    page = AsyncMock()
    page.url = "https://www.linkedin.com/authwall?trk=qf&original_referer=&sessionRedirect=https%3A%2F%2Fin.linkedin.com%2Fjobs%2Fview%2Fpython-engineer-4488500119"
    page.query_selector.return_value = None
    page.query_selector_all.return_value = []
    page.evaluate.return_value = False

    recovered = await recover_from_authwall(page, keyword="Python", location="India")

    assert recovered is True
    page.goto.assert_awaited_once()
    called_url = page.goto.call_args[0][0]
    assert "currentJobId=4488500119" in called_url
    assert page.goto.call_args[1].get("referer") == "https://www.google.com/"


@pytest.mark.asyncio
async def test_recover_from_authwall_not_authwall():
    page = AsyncMock()
    page.url = "https://www.linkedin.com/jobs/view/12345"
    recovered = await recover_from_authwall(page)
    assert recovered is False
    page.goto.assert_not_awaited()

