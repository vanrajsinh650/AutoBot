"""
AutoBot Universal Cookie Consent & Banner Handler.
Automatically detects, dismisses, or suppresses GDPR / ePrivacy cookie banners
(OneTrust, Cookiebot, Didomi, Klaro, TrustArc, Axeptio, Usercentrics, and custom banners)
so career application forms are never obstructed by overlay dialogs.
"""

import asyncio
from typing import Any, List, Optional
from src.utils.logger import logger


COOKIE_ACCEPT_SELECTORS: List[str] = [
    # OneTrust
    "#onetrust-accept-btn-handler",
    "button#onetrust-accept-btn-handler",
    # Cookiebot
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    # Didomi
    "#didomi-notice-agree-button",
    # Usercentrics / Klaro / Axeptio / TrustArc
    "button[data-testid='uc-accept-all-button']",
    "#axeptio_btn_acceptAll",
    "#truste-consent-button",
    "button.trustarc-agree-btn",
    "button[data-role='b-ac']",
    "button.cm__btn--primary",
    # Standard Text Heuristics (Multi-language)
    "button:has-text('Accept all cookies')",
    "[role='button']:has-text('Accept all cookies')",
    "button:has-text('Accept all')",
    "[role='button']:has-text('Accept all')",
    "button:has-text('Accept All')",
    "[role='button']:has-text('Accept All')",
    "button:has-text('Accept Cookies')",
    "button:has-text('Accept cookies')",
    "button:has-text('Allow all cookies')",
    "[role='button']:has-text('Allow all cookies')",
    "button:has-text('Allow all')",
    "button:has-text('Allow All')",
    "button:has-text('I agree')",
    "button:has-text('I Agree')",
    "button:has-text('Agree & Continue')",
    "button:has-text('Accept & Continue')",
    "button:has-text('Agree & proceed')",
    "button:has-text('Alle akzeptieren')",
    "button:has-text('Tout accepter')",
    "button:has-text('Accepter tout')",
    "button:has-text('Accepteren')",
    # Attribute & ID Heuristics
    "button[id*='accept' i][id*='cookie' i]",
    "button[class*='accept' i][class*='cookie' i]",
    "button[data-testid*='cookie-accept' i]",
    "button[aria-label*='accept all' i]",
    "button[aria-label*='accept cookies' i]",
    "a:has-text('Accept all cookies')",
    "a:has-text('Accept all')",
    "a:has-text('Allow all')",
]

COOKIE_REJECT_SELECTORS: List[str] = [
    # OneTrust
    "#onetrust-reject-all-handler",
    "button#onetrust-reject-all-handler",
    # Cookiebot
    "#CybotCookiebotDialogBodyButtonDecline",
    # Didomi
    "#didomi-notice-disagree-button",
    # Standard Text Heuristics
    "button:has-text('Reject all')",
    "[role='button']:has-text('Reject all')",
    "button:has-text('Reject All')",
    "[role='button']:has-text('Reject All')",
    "button:has-text('Decline all')",
    "button:has-text('Decline All')",
    "button:has-text('Refuse all')",
    "button:has-text('Only necessary')",
    "button:has-text('Essential cookies only')",
    "button:has-text('Nur notwendige')",
    "button:has-text('Refuser tout')",
    # Attribute & ID Heuristics
    "button[id*='reject' i][id*='cookie' i]",
    "button[data-testid*='cookie-reject' i]",
    "button[aria-label*='reject all' i]",
    "a:has-text('Reject all')",
    "a:has-text('Reject All')",
]

COOKIE_CONTAINER_SELECTORS: List[str] = [
    "#onetrust-consent-sdk",
    ".onetrust-pc-dark-filter",
    "#CybotCookiebotDialog",
    "#CybotCookiebotDialogBodyUnderlay",
    "#didomi-host",
    "#didomi-popup",
    "div[id*='cookie-banner' i]",
    "div[class*='cookie-banner' i]",
    "div[id*='cookie-consent' i]",
    "div[class*='cookie-consent' i]",
    "div[id*='consent-banner' i]",
    "div[class*='consent-banner' i]",
    "div[aria-label*='cookie' i][role='dialog']",
    ".cookie-notice",
    ".cookie-banner",
    ".cookies-banner",
    ".cc-window",
    "#truste-consent-track",
]


async def suppress_cookie_overlays_css(page: Any) -> bool:
    """
    Inject global CSS rules to immediately hide stubborn cookie overlays,
    modals, and backdrops, while unlocking body/html scrolling.
    """
    try:
        await page.evaluate("""() => {
            if (document.getElementById('autobot-cookie-suppress-style')) return;
            const style = document.createElement('style');
            style.id = 'autobot-cookie-suppress-style';
            style.innerHTML = `
                #onetrust-consent-sdk,
                .onetrust-pc-dark-filter,
                #CybotCookiebotDialog,
                #CybotCookiebotDialogBodyUnderlay,
                #didomi-host,
                #didomi-popup,
                #didomi-notice,
                [id*="cookie-banner" i],
                [class*="cookie-banner" i],
                [id*="cookie-consent" i],
                [class*="cookie-consent" i],
                [id*="consent-banner" i],
                [class*="consent-banner" i],
                [id*="cookieNotice" i],
                [class*="cookieNotice" i],
                .cc-window,
                .cookie-notice,
                .cookies-banner,
                #truste-consent-track,
                .truste_overlay,
                .truste_box_overlay {
                    display: none !important;
                    visibility: hidden !important;
                    opacity: 0 !important;
                    pointer-events: none !important;
                    z-index: -9999 !important;
                }
                body, html {
                    overflow: auto !important;
                    overflow-y: auto !important;
                    position: static !important;
                }
            `;
            document.head ? document.head.appendChild(style) : document.documentElement.appendChild(style);
            
            // Also reset overflow on body and html directly
            try {
                if (document.body) {
                    document.body.style.overflow = 'auto';
                    document.body.style.position = 'static';
                }
                if (document.documentElement) {
                    document.documentElement.style.overflow = 'auto';
                }
            } catch (e) {}
        }""")
        return True
    except Exception as ex:
        logger.debug(f"[cookie-handler] CSS suppression error: {ex}")
        return False


async def dismiss_cookie_banners(
    page: Any,
    policy: str = "auto_accept",
    timeout_ms: int = 1500,
) -> bool:
    """
    Check for and dismiss or suppress cookie consent dialogs on the current page.

    Args:
        page: Playwright Page object.
        policy: 'auto_accept' (click accept all), 'auto_reject' (click reject all if available),
                or 'hide_banner' (pure CSS suppression).
        timeout_ms: Maximum time in ms to scan for interactive buttons.

    Returns:
        True if any cookie banner button was clicked or container suppressed, False otherwise.
    """
    policy = (policy or "auto_accept").lower().strip()
    handled = False

    if policy == "hide_banner":
        return await suppress_cookie_overlays_css(page)

    # 1. Choose primary target selectors based on user policy
    target_selectors = COOKIE_ACCEPT_SELECTORS if policy != "auto_reject" else COOKIE_REJECT_SELECTORS
    fallback_selectors = COOKIE_ACCEPT_SELECTORS if policy == "auto_reject" else []

    # 2. Fast scan for clickable buttons
    for sel in target_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                is_enabled = True
                try:
                    is_enabled = await btn.is_enabled()
                except Exception:
                    pass
                if is_enabled:
                    logger.info(f"[cookie-handler] 🍪 Detected cookie consent button ('{sel}'). Clicking to dismiss...")
                    try:
                        await btn.click(timeout=1000)
                    except Exception:
                        await page.evaluate("(el) => el.click()", btn)
                    handled = True
                    await asyncio.sleep(0.3)
                    break
        except Exception:
            continue

    # 3. If policy was auto_reject but no reject button found, fallback to accept
    if not handled and fallback_selectors:
        for sel in fallback_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    logger.info(f"[cookie-handler] 🍪 Fallback: Clicking cookie accept button ('{sel}')...")
                    try:
                        await btn.click(timeout=1000)
                    except Exception:
                        await page.evaluate("(el) => el.click()", btn)
                    handled = True
                    await asyncio.sleep(0.3)
                    break
            except Exception:
                continue

    # 4. Check if any persistent overlay container remains visible and suppress it via CSS
    try:
        has_blocking_overlay = False
        for c_sel in COOKIE_CONTAINER_SELECTORS[:6]:
            c_el = await page.query_selector(c_sel)
            if c_el and await c_el.is_visible():
                has_blocking_overlay = True
                break
        
        if has_blocking_overlay or not handled:
            suppressed = await suppress_cookie_overlays_css(page)
            if suppressed:
                handled = True
    except Exception:
        pass

    return handled
