"""
AutoBot Proof & Audit Verification Engine.
Responsible for:
1. Strict post-submission verification (positive confirmation detection vs. validation error detection).
2. Capturing timestamped visual proof screenshots for submitted applications.
3. Diagnosing and capturing blocker screenshots when applications require manual action.
4. Generating verifiable proof metadata for the Mission Control dashboard.
"""

import asyncio
from datetime import datetime
import html
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional, Tuple
from src.utils.logger import logger


PROOF_DIR = Path("logs/proofs")


def ensure_proof_dir() -> Path:
    """Ensure the proof directory exists."""
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    return PROOF_DIR


async def capture_proof_screenshot(
    page: Any,
    job_id: str,
    company: str,
    title: str,
    is_success: bool = True,
    reason: Optional[str] = None,
    status: str = "applied",
) -> Optional[str]:
    """
    Capture a verified screenshot with an embedded audit banner and return relative file path.
    Truthfully stamps:
    - '✅ AutoBot Application Submitted & Verified' for real submissions verified on confirmation pages.
    - '🔍 AutoBot Simulation (Dry Run)' for simulation runs (form filled with candidate info).
    - '⚠️ AutoBot Blocker Audit' for gated/blocked/failed submissions.
    """
    try:
        proof_dir = ensure_proof_dir()
        clean_id = re.sub(r"[^\w\-]", "_", str(job_id))
        
        is_dry_run = (status == "dry_run")
        if is_dry_run:
            suffix = "dry_run"
            banner_title = "🔍 AutoBot Simulation (Dry Run) — Form Filled"
            banner_bg = "#1E3A8A"
            banner_border = "#3B82F6"
        elif is_success:
            suffix = "confirmed"
            banner_title = "✅ AutoBot Application Submitted & Verified"
            banner_bg = "#064E3B"
            banner_border = "#10B981"
        else:
            suffix = "blocked"
            banner_title = "⚠️ AutoBot Blocker Audit"
            banner_bg = "#7F1D1D"
            banner_border = "#EF4444"

        filename = f"{clean_id}_{suffix}.png"
        filepath = proof_dir / filename

        # Wait briefly if page appears blank/still hydrating before capturing blocker screenshot
        if not is_success:
            for _ in range(4):
                try:
                    has_content = await page.evaluate(
                        "() => Boolean(document.body && (document.body.innerText || '').trim().length > 20)"
                    )
                    if has_content:
                        break
                except Exception:
                    break
                await asyncio.sleep(0.5)

        # If blocked or failed, highlight ALL visible error/unfilled required fields and scroll the first into view
        detected_issue = None
        if not is_success:
            try:
                detected_issue = await page.evaluate("""() => {
                    const issues = [];
                    const highlighted = new Set();
                    let firstElem = null;

                    const mark = (el, desc) => {
                        if (!el || highlighted.has(el)) return;
                        highlighted.add(el);
                        if (!firstElem) firstElem = el;
                        try {
                            el.style.outline = '3px solid #EF4444';
                            el.style.outlineOffset = '2px';
                            el.style.boxShadow = '0 0 14px rgba(239, 68, 68, 0.85)';
                        } catch (e) {}
                        if (desc && issues.length < 4 && !issues.includes(desc)) {
                            issues.push(desc);
                        }
                    };

                    const findLabelFor = (el) => {
                        if (!el) return '';
                        const labelledBy = el.getAttribute('aria-labelledby');
                        if (labelledBy) {
                            const lblEl = document.getElementById(labelledBy);
                            if (lblEl && lblEl.innerText) return lblEl.innerText.trim();
                        }
                        if (el.id) {
                            try {
                                const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`) || document.getElementById(`${el.id}-label`);
                                if (lbl && lbl.innerText) return lbl.innerText.trim();
                            } catch (e) {}
                        }
                        const parentSelectors = ['.application-question', '.ashby-application-form-field-entry', '[class*="question" i]', '.select', '.field', 'fieldset'];
                        for (const pSel of parentSelectors) {
                            const parent = el.closest(pSel);
                            if (parent) {
                                const lbl = parent.querySelector('.application-label, label, legend');
                                if (lbl && (lbl.innerText || '').trim()) return lbl.innerText.trim();
                            }
                        }
                        return (el.getAttribute('aria-label') || el.placeholder || el.name || el.id || '').trim();
                    };

                    // 1. Explicit validation errors visible on page
                    const errSelectors = [
                        '.field-error', '.error-message', '.invalid-feedback', '.form-error',
                        '.field-validation-error', '[class*="field__error"]', '[id$="-error"]',
                        '[aria-invalid="true"]', '.has-error', '[role="alert"]'
                    ];
                    for (const sel of errSelectors) {
                        const els = Array.from(document.querySelectorAll(sel));
                        for (const el of els) {
                            if (el.offsetWidth > 0 && el.offsetHeight > 0) {
                                const txt = (el.innerText || '').trim().replace(/\\s+/g, ' ');
                                const lbl = findLabelFor(el);
                                const summary = lbl && !txt.includes(lbl) ? `${lbl.slice(0, 45)}: ${txt.slice(0, 45)}` : (txt || lbl || 'Validation Error');
                                if (summary.trim()) {
                                    mark(el, summary.slice(0, 80));
                                }
                            }
                        }
                    }

                    // 2. Unfilled required inputs & selects & ARIA comboboxes still showing placeholder
                    const candidates = Array.from(document.querySelectorAll(
                        'input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="reset"]), ' +
                        'select, textarea, [role="combobox"], [aria-haspopup="listbox"], .select__control'
                    ));
                    for (const el of candidates) {
                        const role = el.getAttribute('role') || '';
                        const pEl = el.parentElement || el;
                        const wrap = pEl.closest('.select__control, .select__value-container, .select-shell') || pEl.closest('[class*="control" i]') || pEl;
                        const targetBox = (role === 'combobox' || (el.className || '').includes('select')) && wrap ? wrap : el;
                        if (targetBox.offsetWidth === 0 && targetBox.offsetHeight === 0 && el.offsetWidth === 0 && el.offsetHeight === 0) continue;
                        
                        const lblText = findLabelFor(el);
                        const isReq = Boolean(
                            el.required ||
                            el.getAttribute('aria-required') === 'true' ||
                            el.getAttribute('required') !== null ||
                            lblText.includes('*') ||
                            lblText.includes('✱') ||
                            Boolean(el.closest('.required, [class*="required" i], [class*="mandatory" i]'))
                        );

                        if (el.type === 'checkbox') {
                            if (isReq && !el.checked) {
                                mark(el.closest('label') || el, `${lblText.replace(/[*✱]/g, '').trim().slice(0, 50) || 'Required Checkbox'} (Unchecked)`);
                            }
                            continue;
                        }
                        if (el.type === 'file') {
                            if (isReq && !el.value) {
                                mark(el.closest('label, .field, [class*="upload" i]') || el, `${lblText.replace(/[*✱]/g, '').trim().slice(0, 50) || 'File Upload'} (Missing)`);
                            }
                            continue;
                        }
                        if (el.tagName === 'SELECT') {
                            const val = (el.value || '').trim();
                            const selectedText = el.selectedIndex >= 0 && el.options[el.selectedIndex] ? el.options[el.selectedIndex].text.trim() : '';
                            const isEmpty = !val || val === '0' || val === '-1' || selectedText.toLowerCase().startsWith('select') || selectedText.toLowerCase().startsWith('choose') || selectedText.startsWith('--');
                            if (isReq && isEmpty) {
                                mark(el, `${lblText.replace(/[*✱]/g, '').trim().slice(0, 50) || el.id || 'Dropdown'} (Unselected)`);
                            }
                            continue;
                        }
                        if (role === 'combobox' || (el.className || '').includes('select__input') || (el.className || '').includes('select__control')) {
                            // Check if React-Select single/multi value pill exists inside same wrapper
                            const outerWrap = pEl.closest('.select__control, .select__value-container, .select-shell') || wrap;
                            const singleVal = outerWrap ? outerWrap.querySelector('[class*="singleValue" i], [class*="single-value" i], .select__single-value, [class*="multiValue" i], [class*="multi-value" i], .select__multi-value') : null;
                            const textVal = singleVal ? (singleVal.innerText || '').trim() : '';
                            const isEmpty = !textVal || textVal.toLowerCase().startsWith('select') || textVal.toLowerCase().startsWith('choose');
                            if (isReq && isEmpty) {
                                mark(targetBox, `${lblText.replace(/[*✱]/g, '').trim().slice(0, 50) || el.id || 'Dropdown'} (Unselected)`);
                            }
                            continue;
                        }
                        // Standard text inputs, email, tel, textarea
                        const val = (el.value || '').trim();
                        if (isReq && !val) {
                            mark(el, `${lblText.replace(/[*✱]/g, '').trim().slice(0, 50) || el.name || el.id || 'Required Field'} (Empty)`);
                        }
                    }

                    if (firstElem) {
                        firstElem.scrollIntoView({ behavior: 'instant', block: 'center' });
                    }
                    return issues.length ? issues.join(' | ').slice(0, 180) : null;
                }""")
            except Exception:
                pass

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        safe_title = html.escape(str(title or ""), quote=True)
        safe_company = html.escape(str(company or ""), quote=True)
        subtext = f"Role: {safe_title} • Company: {safe_company} • {now_str}"
        if is_dry_run:
            subtext += "<br>Simulation Mode: Form fields filled with candidate profile. Submit button withheld by setting."
        elif not is_success:
            if reason:
                subtext += f"<br>Blocker: {html.escape(str(reason), quote=True)}"
            if detected_issue:
                subtext += f"<br>Unfilled / Error Fields: {html.escape(str(detected_issue), quote=True)}"

        # Determine full_page mode first so audit banner does not float across middle of form
        use_full_page = True
        try:
            page_height = await page.evaluate("() => document.body ? document.body.scrollHeight : 0")
            if page_height and page_height > 8000:
                use_full_page = False
        except Exception:
            use_full_page = True

        # Inject audit badge onto page before screenshot
        try:
            pos_css = (
                "b.style.position = 'relative'; b.style.margin = '12px auto'; b.style.maxWidth = '780px';"
                if use_full_page
                else "b.style.position = 'fixed'; b.style.bottom = '10px'; b.style.left = '50%'; b.style.transform = 'translateX(-50%)';"
            )
            inject_js = (
                "document.body ? (document.body.prepend ? document.body.prepend(b) : document.body.appendChild(b)) : document.documentElement.appendChild(b);"
                if use_full_page
                else "document.body ? document.body.appendChild(b) : document.documentElement.appendChild(b);"
            )
            await page.evaluate(f"""() => {{
                const existing = document.getElementById('autobot-audit-banner');
                if (existing) existing.remove();
                const b = document.createElement('div');
                b.id = 'autobot-audit-banner';
                {pos_css}
                b.style.backgroundColor = '{banner_bg}';
                b.style.color = '#FFFFFF';
                b.style.border = '1.5px solid {banner_border}';
                b.style.borderRadius = '6px';
                b.style.padding = '7px 14px';
                b.style.fontSize = '11.5px';
                b.style.fontFamily = 'monospace, sans-serif';
                b.style.zIndex = '2147483647';
                b.style.boxShadow = '0 4px 16px rgba(0,0,0,0.85)';
                b.style.textAlign = 'center';
                b.style.lineHeight = '1.35';
                b.style.pointerEvents = 'none';
                b.innerHTML = '<strong style="font-size:12px;">{banner_title}</strong><div style="font-size:10px; opacity:0.92; margin-top:2px;">{subtext}</div>';
                {inject_js}
            }}""")
            await asyncio.sleep(0.3)
        except Exception:
            pass

        await page.screenshot(path=str(filepath), full_page=use_full_page)
        logger.info(f"[proof-audit] 📸 Captured {suffix} proof screenshot: {filepath}")
        return f"logs/proofs/{filename}"
    except Exception as ex:
        logger.warning(f"[proof-audit] Failed to capture screenshot: {ex}")
        return None


async def verify_submission_status(page: Any, timeout_ms: int = 5000) -> Dict[str, Any]:
    """
    Perform strict post-submit verification on the page.
    Determines whether the submission succeeded, was gated by an account login,
    failed with validation errors, or was challenged by anti-bot.
    """
    result = {
        "is_submitted": False,
        "status": "requires_manual",
        "reason_code": "UNKNOWN",
        "description": "Form was submitted but confirmation could not be verified automatically.",
        "confirmation_code": None,
    }

    try:
        # Give the page a short moment to transition or display AJAX confirmation
        await asyncio.sleep(1.5)

        current_url = ""
        try:
            current_url = (page.url or "").lower()
        except Exception:
            pass

        # 1. Check positive confirmation signals
        confirmation_keywords = [
            "you have successfully applied for",
            "successfully applied for",
            "successfully applied",
            "you have successfully applied",
            "thank you for applying",
            "thank you for your application",
            "application submitted",
            "application received",
            "we've received your application",
            "we have received your application",
            "your application has been received",
            "your application was submitted",
            "your application has been submitted",
            "your application has been sent",
            "your application was sent",
            "successfully submitted",
            "application complete",
            "application successful",
            "submission confirmed",
            "thanks for applying",
            "thanks for your interest",
            "we appreciate your interest",
            "we appreciate your application",
            "congratulations",
            "thank you, ",
            "thanks, ",
        ]

        page_content = ""
        try:
            page_content = await page.evaluate("() => document.body ? document.body.innerText.toLowerCase() : ''")
        except Exception:
            pass
        content_lower = str(page_content or "").lower()

        has_confirm_keyword = any(kw in content_lower for kw in confirmation_keywords)
        has_confirm_url = any(u in current_url for u in (
            "/applythankyou",
            "/confirmation",
            "/thank-you",
            "/thank_you",
            "/thankyou",
            "/submitted",
            "status=success",
        ))

        # Check for false positives: If page still has an 'Apply Now' or 'Submit Application' button and no real confirmation
        is_still_form = ("apply now" in content_lower or "submit application" in content_lower) and not has_confirm_keyword

        if (has_confirm_keyword or has_confirm_url) and not is_still_form:
            # Extract possible confirmation / reference code
            conf_code = None
            code_match = re.search(r"(?:confirmation|reference|application|req|requisition)\s*(?:#|number|id|code|reference)?\s*[:#]\s*([a-z0-9\-]{3,30})", content_lower, re.IGNORECASE)
            if code_match:
                conf_code = code_match.group(1).upper()

            result["is_submitted"] = True
            result["status"] = "applied"
            result["reason_code"] = "SUCCESS"
            result["description"] = f"Application submission verified on confirmation screen{f' (Ref: {conf_code})' if conf_code else ''}."
            result["confirmation_code"] = conf_code
            return result

        # 2. Check for Account Creation / Sign-In Requirement
        account_keywords = [
            "create an account to apply",
            "sign in to apply",
            "please sign in",
            "create account",
            "log in or sign up",
            "already have an account? sign in",
        ]
        is_account_url = any(k in current_url for k in ("/login", "/signin", "/candidate-account", "workdayjobs.com/en-us/user/login"))
        is_account_text = any(ak in content_lower for ak in account_keywords)

        if is_account_url or is_account_text:
            result["is_submitted"] = False
            result["status"] = "requires_manual"
            result["reason_code"] = "ACCOUNT_REQUIRED"
            result["description"] = "Company career portal requires candidate account registration or sign-in (e.g. Workday/Taleo account)."
            return result

        # 3. Check for Form Validation Errors FIRST (so validation failures aren't misclassified as CAPTCHA due to company names or footer badges)
        validation_error_selectors = [
            ".field-error",
            ".error-message",
            ".invalid-feedback",
            ".form-error",
            ".field-validation-error",
            "[class*='field__error']",
            "[id$='-error']",
            "[aria-invalid='true']",
            ".has-error",
            "[role='alert']",
            ":has-text('This field is required')",
            ":has-text('Please fill out this field')",
            ":has-text('Please upload your resume')",
            ":has-text('Please enter your location')",
            ":has-text('Please select')",
            ":has-text('Missing required')",
        ]
        found_error_text = []
        for v_sel in validation_error_selectors:
            try:
                err_els = await page.query_selector_all(v_sel)
                for el in err_els[:4]:
                    if await el.is_visible():
                        txt = (await el.inner_text()).strip().replace("\n", " ")
                        if txt and len(txt) < 100 and txt not in found_error_text:
                            found_error_text.append(txt)
            except Exception:
                continue

        if found_error_text:
            result["is_submitted"] = False
            result["status"] = "requires_manual"
            result["reason_code"] = "VALIDATION_ERROR"
            err_summary = "; ".join(found_error_text)
            result["description"] = f"Required fields or questions were unfulfilled: {err_summary[:140]}"
            return result

        # 4. Check for Security Challenge / CAPTCHA (never match bare company word 'cloudflare' or passive reCAPTCHA badge)
        captcha_keywords = [
            "verify you are human",
            "security check",
            "cloudflare turnstile",
            "attention required! | cloudflare",
            "checking your browser before accessing",
            "just a moment...",
            "hcaptcha",
            "ddos-guard",
            "robot or human",
        ]
        has_challenge_dom = False
        try:
            if hasattr(page, "query_selector"):
                ch_el = await page.query_selector(
                    "#challenge-running, #challenge-stage, #cf-please-wait, "
                    "iframe[src*='/bframe'], iframe[title*='hcaptcha' i], iframe[title*='challenge' i]"
                )
                if ch_el and await ch_el.is_visible():
                    has_challenge_dom = True
        except Exception:
            pass

        if has_challenge_dom or any(ck in content_lower for ck in captcha_keywords):
            result["is_submitted"] = False
            result["status"] = "challenge_detected"
            result["reason_code"] = "SECURITY_CHALLENGE"
            result["description"] = "Anti-bot CAPTCHA security challenge detected on portal."
            return result

        # 5. Check for Multi-step wizard
        multistep_indicators = [
            ":has-text('Step 2 of')",
            ":has-text('Step 3 of')",
            ":has-text('Page 2 of')",
            ":has-text('Questionnaire')",
            ":has-text('Self-Identification')",
        ]
        for m_sel in multistep_indicators:
            try:
                m_el = await page.query_selector(m_sel)
                if m_el and await m_el.is_visible():
                    result["is_submitted"] = False
                    result["status"] = "requires_manual"
                    result["reason_code"] = "MULTI_STEP_WIZARD"
                    result["description"] = "Application consists of a multi-step questionnaire wizard."
                    return result
            except Exception:
                continue

    except Exception as ex:
        logger.debug(f"[proof-audit] Verification inspection error: {ex}")

    return result
