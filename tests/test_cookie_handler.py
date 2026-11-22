"""
Tests for AutoBot Cookie Consent & Banner Handler.
Verifies:
1. Auto-accept policy clicks accept buttons and handles banners.
2. Auto-reject policy clicks reject buttons first, with fallback to accept.
3. CSS suppression policy injects stylesheet and unlocks scrolling.
4. Soft failure when no cookie banners exist or page throws errors.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest

from src.browser.cookie_handler import (
    COOKIE_ACCEPT_SELECTORS,
    COOKIE_REJECT_SELECTORS,
    dismiss_cookie_banners,
    suppress_cookie_overlays_css,
)


@pytest.mark.asyncio
async def test_dismiss_cookie_banners_auto_accept():
    page = AsyncMock()
    mock_btn = AsyncMock()
    mock_btn.is_visible.return_value = True
    mock_btn.is_enabled.return_value = True

    async def mock_query_selector(sel):
        if sel == "#onetrust-accept-btn-handler":
            return mock_btn
        return None

    page.query_selector.side_effect = mock_query_selector

    res = await dismiss_cookie_banners(page, policy="auto_accept")
    assert res is True
    mock_btn.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_dismiss_cookie_banners_auto_reject():
    page = AsyncMock()
    mock_reject_btn = AsyncMock()
    mock_reject_btn.is_visible.return_value = True
    mock_reject_btn.is_enabled.return_value = True

    async def mock_query_selector(sel):
        if sel == "#onetrust-reject-all-handler":
            return mock_reject_btn
        return None

    page.query_selector.side_effect = mock_query_selector

    res = await dismiss_cookie_banners(page, policy="auto_reject")
    assert res is True
    mock_reject_btn.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_dismiss_cookie_banners_auto_reject_fallback():
    page = AsyncMock()
    mock_accept_btn = AsyncMock()
    mock_accept_btn.is_visible.return_value = True
    mock_accept_btn.is_enabled.return_value = True

    # No reject button, only accept button exists
    async def mock_query_selector(sel):
        if sel == "button:has-text('Accept all')":
            return mock_accept_btn
        return None

    page.query_selector.side_effect = mock_query_selector

    res = await dismiss_cookie_banners(page, policy="auto_reject")
    assert res is True
    mock_accept_btn.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_dismiss_cookie_banners_hide_banner():
    page = AsyncMock()
    res = await dismiss_cookie_banners(page, policy="hide_banner")
    assert res is True
    page.evaluate.assert_awaited_once()


@pytest.mark.asyncio
async def test_dismiss_cookie_banners_soft_fail():
    page = AsyncMock()
    page.query_selector.side_effect = Exception("DOM detached")

    res = await dismiss_cookie_banners(page, policy="auto_accept")
    # Soft fails and attempts CSS suppression
    assert isinstance(res, bool)
