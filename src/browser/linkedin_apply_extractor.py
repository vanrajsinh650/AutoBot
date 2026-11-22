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
    Decode a LinkedIn externalApply, safety redirect, or tracking URL to its direct external destination URL.
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

    # Check for target parameters in query string (including LinkedIn safety redirect /safety/go/?url=...)
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

    # Fallback regex for embedded /safety/go/?url= or externalApply
    m = re.search(r'[?&]url=([^&]+)', cleaned)
    if m:
        val = urllib.parse.unquote(urllib.parse.unquote(m.group(1)))
        dec_parsed = urllib.parse.urlparse(val)
        dec_domain = (dec_parsed.netloc or "").lower()
        if dec_domain and not any(li in dec_domain for li in ("linkedin.com", "lnkd.in")):
            if dec_parsed.scheme in ("http", "https"):
                return val

    return None


def detect_easy_apply_from_html(html: str) -> bool:
    """
    Detect whether a LinkedIn job page (guest/unauthenticated HTML) is an Easy Apply job.

    Signal (reliable for unauthenticated scraping):
      - Easy Apply: Tracking attribute contains "apply-link-onsite", or primary CTA class "apply-button--default"
      - External Apply: Tracking attribute contains "apply-link-offsite", or primary CTA class "sign-up-modal__outlet"

    Returns True if Easy Apply, False if External Apply or unknown.
    """
    if not html:
        return False

    # 1. Definitive LinkedIn tracking attributes (highest confidence for guest pages)
    if "apply-link-onsite" in html:
        return True
    if "apply-link-offsite" in html:
        return False

    # 2. Check primary CTA button class
    primary_cta_match = re.search(
        r'top-card-layout__cta[^>]*class=["\']([^"\']+)["\']|class=["\']([^"\']*top-card-layout__cta--primary[^"\']*)["\']',
        html
    )
    if primary_cta_match:
        cta_class = primary_cta_match.group(1) or primary_cta_match.group(2) or ""
        if "apply-button--default" in cta_class:
            return True
        if "sign-up-modal__outlet" in cta_class:
            return False

    # 3. Broader scan: look for apply-button--default class near the Apply CTA area
    if re.search(r'apply-button apply-button--default[^>]*top-card-layout', html) or \
       re.search(r'top-card-layout[^>]*apply-button--default', html):
        return True
    if re.search(r'apply-button--default', html):
        return True

    # 4. Fallback: search results list card markers
    if 'job-search-card__easy-apply' in html or 'job-card-container__apply-method' in html:
        return True

    return False


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

    # 2. Search for externalApply and safety/go links in hrefs
    href_matches = re.findall(r'href=["\']([^"\']*(?:externalApply|safety/go\?url=)[^"\']*)["\']', html)
    for href in href_matches:
        full_href = href if href.startswith("http") else f"https://www.linkedin.com{href}"
        decoded = decode_linkedin_apply_url(full_href)
        if decoded:
            return decoded

    # Also search unescaped /safety/go/?url= in full HTML
    raw_safety = re.findall(r'https?://(?:www\.)?linkedin\.com/safety/go/\?url=([^"\'\s&<]+(?:%26[^"\'\s&<]+)*)', html)
    for raw_s in raw_safety:
        decoded = urllib.parse.unquote(urllib.parse.unquote(raw_s))
        if decoded.startswith("http") and not any(li in decoded for li in ("linkedin.com", "lnkd.in")):
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
            // Locate the active job details container first to avoid false-positive Easy Apply matches from other cards
            const detailPane = document.querySelector(
                '.jobs-search__job-details, .scaffold-layout__detail, .jobs-details__main-content, #main .jobs-details, .job-view-layout, .top-card-layout, .jobs-unified-top-card, .job-details-pane, div[data-job-id]'
            ) || document;

            // --- PRIMARY EASY APPLY DETECTION (unauthenticated-safe) ---
            // When NOT logged in, LinkedIn renders:
            //   Easy Apply jobs → primary CTA has class "apply-button apply-button--default"
            //   External Apply jobs → primary CTA has class "sign-up-modal__outlet" (sign-in gate before redirect)
            // This is reliable even when both show "Apply" as button text.
            const primaryCta = detailPane.querySelector(
                'button.top-card-layout__cta--primary, button[class*="top-card-layout__cta"]'
            ) || document.querySelector('button.top-card-layout__cta--primary');
            if (primaryCta) {
                const trackingName = (primaryCta.getAttribute('data-tracking-control-name') || '').toLowerCase();
                if (trackingName.includes('apply-link-onsite')) {
                    return { is_easy_apply: true };
                }
                if (trackingName.includes('apply-link-offsite')) {
                    return { is_easy_apply: false, type: 'external_cta' };
                }
                const ctaClass = primaryCta.className || '';
                // Easy Apply: button has apply-button class (LinkedIn in-app flow)
                if (ctaClass.includes('apply-button') && ctaClass.includes('apply-button--default')) {
                    return { is_easy_apply: true };
                }
                // External Apply: button opens sign-in modal which then redirects to external ATS
                if (ctaClass.includes('sign-up-modal__outlet')) {
                    return { is_easy_apply: false, type: 'external_cta' };
                }
            }

            // --- LOGGED-IN FALLBACK: Check for explicit Easy Apply badge text ---
            const easyApplyBadge = detailPane.querySelector(
                '.job-card-container__apply-method, [aria-label*="Easy Apply"], .jobs-s-apply button, .jobs-apply-button'
            );
            const isEasy = easyApplyBadge && (easyApplyBadge.innerText || '').toLowerCase().includes('easy apply');
            if (isEasy) {
                return { is_easy_apply: true };
            }

            // 1. Check all elements inside detailPane and document for direct apply, safety redirect, or externalApply
            const candidates = Array.from(detailPane.querySelectorAll(
                'a, button, [role="button"], [data-apply-url], [data-modal]'
            ));

            for (const el of candidates) {
                const href = el.href || el.getAttribute('href') || el.getAttribute('data-apply-url') || el.getAttribute('data-url') || '';
                if (href && (href.includes('safety/go') || href.includes('externalApply'))) {
                    return { type: 'link', url: href, is_easy_apply: false };
                }
            }

            // Check for any anchor with text or aria-label containing "Apply" (non-easy)
            for (const el of candidates) {
                if (el.tagName === 'A') {
                    const text = (el.innerText || '').toLowerCase().trim();
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    if ((text === 'apply' || text.startsWith('apply') || aria.includes('apply')) && !text.includes('easy')) {
                        const href = el.href || el.getAttribute('href') || '';
                        if (href && href.startsWith('http') && !href.includes('#')) {
                            return { type: 'link', url: href, is_easy_apply: false };
                        }
                    }
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
                if (text.includes('safety/go') || text.includes('externalApply')) {
                    const m = text.match(/(https?:\\/\\/[^"'\\s]*(?:safety\\/go\\?url=|externalApply)[^"'\\s]*)/);
                    if (m && m[1]) {
                        return { type: 'link', url: m[1], is_easy_apply: false };
                    }
                }
            }

            // 3. Check for external apply button (offsite Apply)
            const offsiteBtn = detailPane.querySelector(
                '.jobs-apply-button, button[aria-label*="Apply to"], button.apply-button, button.top-card-layout__cta--primary, button[data-modal*="apply"]'
            ) || document.querySelector('.jobs-apply-button, button[aria-label*="Apply to"], button.apply-button');

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
                    '.jobs-apply-button, button[aria-label*="Apply to"], button.apply-button, button.top-card-layout__cta--primary, button:has-text("Apply")'
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


async def resolve_job_direct_ats_url(job_url_or_id: str, timeout_sec: int = 15) -> Optional[str]:
    """
    Launch an authenticated browser context with stealth evasion and session cookies
    to navigate to the LinkedIn job page and resolve the direct external ATS destination URL.
    """
    if not job_url_or_id:
        return None

    # First check if the URL already has an encoded destination parameter
    decoded = decode_linkedin_apply_url(job_url_or_id)
    if decoded and not any(li in decoded.lower() for li in ("linkedin.com", "lnkd.in")):
        return decoded

    from src.browser.manager import BrowserManager
    url = str(job_url_or_id).strip()

    # Pre-check exact known requisitions by ID
    try:
        from src.browser.company_careers_resolver import resolve_company_direct_apply_url, is_valid_direct_ats_url
        pre_resolved = resolve_company_direct_apply_url(current_url=url, auto_discover=False)
        if pre_resolved and pre_resolved != url:
            is_val, _ = is_valid_direct_ats_url(pre_resolved)
            if is_val:
                return pre_resolved
    except Exception:
        pass

    # Normalize regional subdomains (in.linkedin.com, uk.linkedin.com) to www.linkedin.com
    match = re.search(r"(\d{6,15})", url)
    if match:
        url = f"https://www.linkedin.com/jobs/view/{match.group(1)}/"
    else:
        url = re.sub(r"https?://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", url)

    mgr = BrowserManager(headless=True)
    try:
        await mgr.start()
        await mgr.page.goto(url, wait_until="domcontentloaded", timeout=min(timeout_sec * 1000, 15000))
        await asyncio.sleep(2.0)
        direct_url = await resolve_direct_apply_url_from_page(mgr.page, timeout_ms=4000)
        if direct_url:
            return direct_url

        # Fallback: extract title & company from page to discover direct ATS
        try:
            page_meta = await mgr.page.evaluate('''() => {
                const titleEl = document.querySelector('h1, h2.top-card-layout__title, .jobs-unified-top-card__job-title, [class*="job-title"]');
                const compEl = document.querySelector('.topcard__flavor, .jobs-unified-top-card__company-name, .job-card-container__company-name, [class*="company-name"]');
                return {
                    title: titleEl ? (titleEl.innerText || '').trim() : '',
                    company: compEl ? (compEl.innerText || '').trim() : ''
                };
            }''')
            if page_meta.get("company") and page_meta.get("title"):
                from src.browser.company_careers_resolver import discover_direct_job_ats_url, resolve_company_direct_apply_url
                disc = resolve_company_direct_apply_url(
                    title=page_meta["title"],
                    company=page_meta["company"],
                    current_url=url,
                    auto_discover=True,
                )
                if disc and disc != url:
                    return disc
        except Exception as ex_disc:
            logger.debug(f"Page metadata ATS discovery error: {ex_disc}")

        return None
    except Exception as ex:
        logger.debug(f"resolve_job_direct_ats_url error on {url}: {ex}")
        return None
    finally:
        try:
            await mgr.close()
        except Exception:
            pass

