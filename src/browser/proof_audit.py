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

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        subtext = f"Role: {title} • Company: {company} • {now_str}"
        if is_dry_run:
            subtext += "<br>Simulation Mode: Form fields filled with candidate profile. Submit button withheld by setting."
        elif not is_success and reason:
            subtext += f"<br>Blocker: {reason}"

        # Inject audit badge onto page before screenshot
        try:
            await page.evaluate(f"""() => {{
                const existing = document.getElementById('autobot-audit-banner');
                if (existing) existing.remove();
                const b = document.createElement('div');
                b.id = 'autobot-audit-banner';
                b.style.position = 'fixed';
                b.style.top = '12px';
                b.style.left = '50%';
                b.style.transform = 'translateX(-50%)';
                b.style.backgroundColor = '{banner_bg}';
                b.style.color = '#FFFFFF';
                b.style.border = '2px solid {banner_border}';
                b.style.borderRadius = '8px';
                b.style.padding = '8px 18px';
                b.style.fontSize = '12.5px';
                b.style.fontFamily = 'monospace, sans-serif';
                b.style.zIndex = '2147483647';
                b.style.boxShadow = '0 8px 30px rgba(0,0,0,0.85)';
                b.style.textAlign = 'center';
                b.style.lineHeight = '1.4';
                b.innerHTML = '<strong style="font-size:14px;">{banner_title}</strong><div style="font-size:11px; opacity:0.95; margin-top:2px;">{subtext}</div>';
                document.body ? document.body.appendChild(b) : document.documentElement.appendChild(b);
            }}""")
            await asyncio.sleep(0.3)
        except Exception:
            pass

        # Capture screenshot
        await page.screenshot(path=str(filepath), full_page=False)
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

        # 3. Check for Security Challenge / CAPTCHA
        captcha_keywords = ["verify you are human", "security check", "cloudflare", "turnstile", "hcaptcha", "recaptcha", "ddos-guard"]
        if any(ck in content_lower for ck in captcha_keywords):
            result["is_submitted"] = False
            result["status"] = "challenge_detected"
            result["reason_code"] = "SECURITY_CHALLENGE"
            result["description"] = "Anti-bot CAPTCHA security challenge detected on portal."
            return result

        # 4. Check for Form Validation Errors
        validation_error_selectors = [
            ".error-message",
            ".invalid-feedback",
            ".form-error",
            ".field-validation-error",
            "[aria-invalid='true']",
            ".has-error",
            ":has-text('This field is required')",
            ":has-text('Please fill out this field')",
            ":has-text('Please upload your resume')",
        ]
        found_error_text = []
        for v_sel in validation_error_selectors:
            try:
                err_els = await page.query_selector_all(v_sel)
                for el in err_els[:3]:
                    if await el.is_visible():
                        txt = (await el.inner_text()).strip()
                        if txt and len(txt) < 80 and txt not in found_error_text:
                            found_error_text.append(txt)
            except Exception:
                continue

        if found_error_text:
            result["is_submitted"] = False
            result["status"] = "requires_manual"
            result["reason_code"] = "VALIDATION_ERROR"
            err_summary = "; ".join(found_error_text)
            result["description"] = f"Required fields or questions were unfulfilled: {err_summary[:120]}"
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
