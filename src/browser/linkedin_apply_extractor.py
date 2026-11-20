"""
LinkedIn Apply URL Extractor for AutoBot.

Extracts the real, direct external application form links (e.g. JPMorgan's Oracle Cloud ATS,
Greenhouse, Lever, Workday, Amazon Jobs, etc.) behind LinkedIn's "Apply ↗" buttons,
cleanly separating them from in-app "Easy Apply" flows.
"""

import asyncio
from html import unescape
import json
import re
from typing import Any, Dict, List, Optional
import urllib.parse

from playwright.async_api import ElementHandle, Page
from src.utils.logger import logger


def decode_linkedin_apply_url(raw_url: str) -> Optional[str]:
    """
    Decode a LinkedIn externalApply or tracking URL to its direct external destination URL.
    Returns None if no external URL can be decoded or if the URL points to LinkedIn itself.
    """
    if not raw_url or not isinstance(raw_url, str):
        return None

    cleaned = unescape(raw_url).strip()
    # Unescape common JSON/URL escape sequences
    cleaned = cleaned.replace("\\/", "/").replace("\\u002F", "/").replace("\\u0026", "&")

    # If it is already a direct non-LinkedIn HTTP(S) URL, return it
    parsed = urllib.parse.urlparse(cleaned)
    domain = (parsed.netloc or "").lower()
    if domain and not any(li in domain for li in ("linkedin.com", "lnkd.in")):
        if parsed.scheme in ("http", "https"):
            return cleaned

    # Check for target parameters in query string
    qs = urllib.parse.parse_qs(parsed.query)
    for param in ("url", "dest", "target", "redirect", "session_redirect", "destination"):
        if param in qs and qs[param]:
            val = qs[param][0]
            # Handle possible multiple levels of URL encoding
            decoded = urllib.parse.unquote(val)
            if "%" in decoded:
                decoded = urllib.parse.unquote(decoded)
            decoded = unescape(decoded).replace("\\/", "/")
            dec_parsed = urllib.parse.urlparse(decoded)
            dec_domain = (dec_parsed.netloc or "").lower()
            if dec_domain and not any(li in dec_domain for li in ("linkedin.com", "lnkd.in")):
                if dec_parsed.scheme in ("http", "https"):
                    return decoded

    return None


def extract_company_apply_url_from_html(html: str) -> Optional[str]:
    """
    Search raw HTML source, embedded Voyager state, or JSON-LD for companyApplyUrl
    or decoded externalApply links.
    """
    if not html or not isinstance(html, str):
        return None

    # 1. Search for companyApplyUrl in embedded Voyager state or JSON models
    voyager_patterns = [
        r'companyApplyUrl["\']?\s*:\s*["\']([^"\']+)["\']',
        r'"\*?companyApplyUrl"\s*:\s*"([^"]+)"',
        r'applyMethod["\']?\s*:\s*\{[^}]*companyApplyUrl["\']?\s*:\s*["\']([^"\']+)["\']',
        r'offsiteApply["\']?\s*:\s*\{[^}]*url["\']?\s*:\s*["\']([^"\']+)["\']',
        r'applyUrl["\']?\s*:\s*["\']([^"\']+)["\']',
        r'customApplyUrl["\']?\s*:\s*["\']([^"\']+)["\']',
    ]
    for pat in voyager_patterns:
        match = re.search(pat, html)
        if match:
            raw_target = match.group(1)
            decoded = decode_linkedin_apply_url(raw_target)
            if decoded:
                return decoded

    # 2. Search for externalApply links in hrefs
    href_matches = re.findall(r'href=["\']([^"\']*externalApply[^"\']*)["\']', html)
    for href in href_matches:
        full_href = href if href.startswith("http") else f"https://www.linkedin.com{href}"
        decoded = decode_linkedin_apply_url(full_href)
        if decoded:
            return decoded

    # 3. Search for schema.org JobPosting JSON-LD
    try:
        json_ld_matches = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL)
        for block in json_ld_matches:
            try:
                data = json.loads(block)
                if isinstance(data, dict):
                    same_as = data.get("sameAs") or data.get("directApply") or data.get("url")
                    if same_as and isinstance(same_as, str):
                        decoded = decode_linkedin_apply_url(same_as)
                        if decoded:
                            return decoded
            except Exception:
                pass
    except Exception:
        pass

    return None


async def resolve_direct_apply_url_from_page(page: Page, timeout_ms: int = 8000) -> Optional[str]:
    """
    Inspect the active LinkedIn page/panel in Playwright and extract the direct
    outbound external application form link (e.g. JPMorgan's Oracle Cloud ATS,
    Greenhouse, Lever, Workday).
    
    Returns:
        The direct destination URL string if found, or None if Easy Apply / unavailable.
    """
    try:
        # Step 1: In-page DOM inspection
        extracted_info = await page.evaluate("""() => {
            // Check for explicit Easy Apply first
            const easyApplyBadge = document.querySelector(
                '.job-card-container__apply-method, [aria-label*="Easy Apply"], .jobs-s-apply button, .jobs-apply-button'
            );
            const isEasy = easyApplyBadge && (easyApplyBadge.innerText || '').toLowerCase().includes('easy apply');
            if (isEasy) {
                return { is_easy_apply: true };
            }

            // 1. Check <a> tags for direct apply or externalApply
            const applyAnchors = Array.from(document.querySelectorAll(
                'a.apply-button, a.jobs-apply-button, a[data-tracking-control-name*="apply"], a.top-card-layout__cta--primary, a[href*="externalApply"]'
            ));
            for (const a of applyAnchors) {
                if (a.href) {
                    return { type: 'link', url: a.href, is_easy_apply: false };
                }
            }

            // 2. Check <code> tags (Voyager data) and script tags
            const codeTags = Array.from(document.querySelectorAll('code[id^="bpr-guid-"], script[type="application/ld+json"], script:not([src])'));
            for (const tag of codeTags) {
                const text = tag.textContent || '';
                if (text.includes('companyApplyUrl')) {
                    const m = text.match(/companyApplyUrl["']?\\s*:\\s*["']([^"']+)["']/);
                    if (m && m[1]) {
                        return { type: 'voyager', url: m[1], is_easy_apply: false };
                    }
                }
            }

            // 3. Check for external apply button (offsite Apply)
            const offsiteBtn = document.querySelector(
                '.jobs-apply-button, button[aria-label*="Apply to"], button.apply-button'
            );
            if (offsiteBtn) {
                const btnText = (offsiteBtn.innerText || '').toLowerCase();
                if (!btnText.includes('easy')) {
                    return { type: 'button', is_easy_apply: false };
                }
            }

            return null;
        }""")

        if not extracted_info:
            # Fallback: check page content with regex
            try:
                content = await page.content()
                from_content = extract_company_apply_url_from_html(content)
                if from_content:
                    return from_content
            except Exception:
                pass
            return None

        if extracted_info.get("is_easy_apply"):
            # This is an in-app LinkedIn Easy Apply role
            return None

        # Process link or voyager result
        candidate_url = extracted_info.get("url")
        if candidate_url:
            decoded = decode_linkedin_apply_url(candidate_url)
            if decoded:
                return decoded

            # If it's an externalApply link that hasn't decoded yet (e.g. without ?url=)
            if "externalapply" in candidate_url.lower():
                try:
                    # Resolve HTTP 302 redirect via Playwright request
                    resp = await page.request.get(candidate_url, max_redirects=0, timeout=timeout_ms)
                    loc = resp.headers.get("location")
                    if loc:
                        dec_loc = decode_linkedin_apply_url(loc)
                        if dec_loc:
                            return dec_loc
                except Exception as ex:
                    logger.debug(f"Redirect resolution error on {candidate_url}: {ex}")

        # Step 2: If it's a logged-in member button, click it while capturing popup
        if extracted_info.get("type") == "button":
            try:
                apply_button = await page.query_selector(
                    '.jobs-apply-button, button[aria-label*="Apply to"], button.apply-button'
                )
                if apply_button and await apply_button.is_visible():
                    btn_text = (await apply_button.inner_text()).lower()
                    if "easy" not in btn_text:
                        # Expect the popup window that opens to the company's ATS
                        async with page.expect_popup(timeout=timeout_ms) as popup_info:
                            await apply_button.click()
                        popup = await popup_info.value
                        try:
                            await popup.wait_for_load_state("domcontentloaded", timeout=min(timeout_ms, 5000))
                        except Exception:
                            pass

                        # Wait for URL redirect loop to settle on outbound company ATS
                        popup_url = popup.url or ""
                        for _ in range(10):
                            cur = popup.url or ""
                            if cur and not any(li in cur.lower() for li in ("linkedin.com", "lnkd.in")):
                                popup_url = cur
                                break
                            dec = decode_linkedin_apply_url(cur)
                            if dec:
                                popup_url = dec
                                break
                            await asyncio.sleep(0.4)

                        try:
                            await popup.close()
                        except Exception:
                            pass

                        # Dismiss the "Did you finish applying? Yes/No" prompt on parent LinkedIn page
                        try:
                            dismiss_btn = await page.query_selector(
                                "button:has-text('No'), button:has-text('Yes'), [data-control-name*='dismiss_apply']"
                            )
                            if dismiss_btn:
                                await dismiss_btn.click()
                        except Exception:
                            pass

                        decoded = decode_linkedin_apply_url(popup_url)
                        if decoded:
                            return decoded
                        if popup_url and not any(li in popup_url.lower() for li in ("linkedin.com", "lnkd.in")):
                            return popup_url
            except Exception as e:
                logger.debug(f"Popup capture on Apply button failed: {e}")

        # Step 3: Check raw page content as final safety net
        try:
            content = await page.content()
            return extract_company_apply_url_from_html(content)
        except Exception:
            return None

    except Exception as e:
        logger.debug(f"resolve_direct_apply_url_from_page error: {e}")
        return None
