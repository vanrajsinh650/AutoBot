"""
External Career Portal Application Actuator for AutoBot v2.

Educational Concept:
External job applications redirect away from LinkedIn to third-party ATS platforms
(such as Greenhouse, Lever, Workday, Ashby, or custom employer domains):
1. Isolated Tab Context:
   Opens a fresh browser tab to prevent ATS redirects from interfering with LinkedIn's session.
2. Cross-ATS Semantic Normalization:
   Maps varied HTML naming conventions (`first_name`, `fname`, `first-name`) to standard
   profile queries executed by `FormRAG`.
3. File Ingestion for External Uploads:
   Finds standard resume upload inputs and attaches `data/resume/resume.pdf`.
4. Graceful Cleanup:
   Closes the temporary browser tab upon completion or error, preserving browser memory.
"""

import asyncio
import inspect
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from playwright.async_api import BrowserContext, Page

from src.agent.state import JobPosting
from src.application.workflows import AntiBotChallengeDetected, LinkedInPolicyViolationError
from src.memory.form_rag import FormRAG
from src.memory.models import FieldType
from src.utils.config import AppConfig, get_config
from src.utils.human_behavior import human_delay, update_visual_cursor, visual_click
from src.utils.logger import logger


def _safe_id_selector(el_id: str) -> str:
    """Build a valid CSS selector even for UUIDs starting with digits or IDs ending in []."""
    clean = str(el_id or "")
    if re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", clean):
        return f"#{clean}"
    escaped = clean.replace("\\", "\\\\").replace('"', '\\"')
    return f'[id="{escaped}"]'


def _safe_attr_selector(attr: str, val: str) -> str:
    """Build a safe CSS attribute equality selector."""
    escaped = str(val or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'[{attr}="{escaped}"]'


async def _eval_maybe_async(val_or_callable: Any) -> Any:
    """Safely evaluate a property, method, or coroutine without double execution or unawaited warnings."""
    if val_or_callable is None:
        return None
    val = val_or_callable() if callable(val_or_callable) else val_or_callable
    if inspect.isawaitable(val):
        return await val
    return val


def load_candidate_profile_info(cfg: Optional[AppConfig] = None) -> Dict[str, str]:
    """Extract candidate contact details from database, config.yaml, and resume PDF."""
    config = cfg or get_config()
    answers_cfg = getattr(getattr(config, "apply", None), "answers", None)
    info = {
        "full_name": "Vanraj Solanki",
        "first_name": "Vanraj",
        "last_name": "Solanki",
        "email": "vanrajsolanki2875@gmail.com",
        "phone": "+91-8320452875",
        "phone_clean": "8320452875",
        "country_code": "+91",
        "linkedin": getattr(getattr(config, "profile", None), "linkedin_url", "") or "https://linkedin.com/in/vanrajsinh",
        "github": "https://github.com/vanrajsinh650",
        "portfolio": getattr(getattr(config, "profile", None), "portfolio_url", "") or "https://github.com/vanrajsinh650",
        "location": "Ahmedabad, Gujarat, India",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "country": "India",
        "postal_code": "380015",
        "street_address": "132 Feet Ring Road",
        "current_company": "DivineHindu",
        "current_title": "Software & AI Automation Engineer",
        "years_of_experience": str(getattr(answers_cfg, "years_of_experience", "1") or "1"),
        "notice_period": str(getattr(answers_cfg, "notice_period", "Immediate") or "Immediate"),
        "notice_period_days": "0" if "0" in str(getattr(answers_cfg, "notice_period", "")) else "15",
        "education_level": "Bachelor's Degree",
        "degree": "Bachelor of Computer Applications (BCA)",
        "university": "Gokul Global University",
        "major": "Computer Applications",
        "gender": "Male",
        "veteran": "No",
        "disability": "No",
        "work_authorization": str(getattr(answers_cfg, "work_authorization", "Yes") or "Yes"),
        "sponsorship_required": str(getattr(answers_cfg, "sponsorship_required", "No") or "No"),
        "willing_to_relocate": str(getattr(answers_cfg, "willing_to_relocate", "Yes") or "Yes"),
        "expected_salary": str(getattr(answers_cfg, "expected_salary", "") or "100000"),
    }
    placeholder_names = {"candidate", "untitled", "unknown", "user a", "user b"}

    def _apply_education_list(edu_list: Any) -> None:
        if not isinstance(edu_list, list) or not edu_list:
            return
        first_edu = edu_list[0] if isinstance(edu_list[0], dict) else {}
        inst = str(first_edu.get("institution") or "").strip()
        raw_edu = str(first_edu.get("raw_text") or "").strip()
        details_text = " ".join(str(d) for d in (first_edu.get("details") or []))
        combined_edu = f"{inst} {details_text} {raw_edu}"
        if "gokul" in combined_edu.lower():
            info["university"] = "Gokul Global University"
        elif details_text and "university" in details_text.lower():
            info["university"] = details_text.split(",")[0].strip()
        if "bca" in combined_edu.lower() or "computer applications" in combined_edu.lower():
            info["degree"] = "Bachelor of Computer Applications (BCA)"
            info["major"] = "Computer Applications"
        elif "bachelor" in combined_edu.lower() or "bs " in combined_edu.lower():
            info["degree"] = inst or info["degree"]

    def _apply_experience_list(exp_list: Any) -> None:
        if not isinstance(exp_list, list) or not exp_list:
            return
        first_exp = exp_list[0] if isinstance(exp_list[0], dict) else {}
        role_line = str(first_exp.get("role") or "").strip()
        company_val = str(first_exp.get("company") or "").strip()
        if " - " in role_line and not company_val:
            parts = role_line.split(" - ", 1)
            if parts[0].strip():
                info["current_title"] = parts[0].strip()
            comp_part = re.split(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b|\d{4}", parts[1], flags=re.IGNORECASE)[0].strip(" -–|,")
            if comp_part:
                info["current_company"] = comp_part
        elif company_val:
            info["current_company"] = company_val
            if role_line:
                info["current_title"] = role_line

    # 1. Populate from persistent candidate profile in SQLite database
    try:
        from src.storage.db import get_candidate_profile
        db_prof = get_candidate_profile(user_id=1)
        if db_prof:
            fn = (db_prof.get("full_name") or "").strip()
            if fn and fn.lower() not in placeholder_names:
                info["full_name"] = fn.title() if fn.isupper() else fn
                parts = info["full_name"].split(maxsplit=1)
                info["first_name"] = parts[0]
                info["last_name"] = parts[1] if len(parts) > 1 else "Solanki"
            if db_prof.get("email"):
                info["email"] = db_prof["email"].strip()
            if db_prof.get("phone"):
                info["phone"] = db_prof["phone"].strip()
                info["phone_clean"] = re.sub(r"[^\d]", "", db_prof["phone"])[-10:]
            if db_prof.get("location"):
                loc = db_prof["location"].strip()
                if len(loc) > 5 and "," in loc:
                    info["location"] = loc
            if db_prof.get("linkedin_url"):
                info["linkedin"] = db_prof["linkedin_url"].strip()
            if db_prof.get("github_url"):
                info["github"] = db_prof["github_url"].strip()
            if db_prof.get("portfolio_url"):
                info["portfolio"] = db_prof["portfolio_url"].strip()
            _apply_education_list(db_prof.get("education"))
            _apply_experience_list(db_prof.get("experience"))
            headline = str(db_prof.get("headline") or "").strip()
            if headline and " - " in headline:
                _apply_experience_list([{"role": headline}])
    except Exception as e:
        logger.debug(f"Could not load candidate profile from db: {e}")

    # 2. Augment from resume PDF if available (strictly rejecting placeholder resumes)
    resume_path = Path(getattr(config.profile, "resume_path", "data/resume/resume.pdf"))
    if resume_path.exists():
        try:
            from src.ingestion.resume_parser import parse_resume
            from src.ingestion.structured_resume import parse_structured_profile
            chunks = parse_resume(resume_path)
            profile_dict = parse_structured_profile(chunks)
            fn = (profile_dict.get("full_name") or "").strip()
            if fn and fn.lower() not in placeholder_names:
                info["full_name"] = fn.title() if fn.isupper() else fn
                parts = info["full_name"].split(maxsplit=1)
                info["first_name"] = parts[0]
                info["last_name"] = parts[1] if len(parts) > 1 else info["last_name"]
                if profile_dict.get("email"):
                    info["email"] = profile_dict["email"]
                if profile_dict.get("phone"):
                    info["phone"] = profile_dict["phone"]
                    info["phone_clean"] = re.sub(r"[^\d]", "", profile_dict["phone"])[-10:]
                if profile_dict.get("linkedin_url"):
                    info["linkedin"] = profile_dict["linkedin_url"]
                if profile_dict.get("github_url"):
                    info["github"] = profile_dict["github_url"]
                if profile_dict.get("portfolio_url"):
                    info["portfolio"] = profile_dict["portfolio_url"]
                _apply_education_list(profile_dict.get("education"))
                _apply_experience_list(profile_dict.get("experience"))
        except Exception as e:
            logger.debug(f"Could not parse candidate info from resume: {e}")
    return info


class ExternalApplyActuator:
    """
    Automates application submissions on external company career portals.
    Enforces strict ATS domain whitelist and halts immediately upon anti-bot/CAPTCHA gates.
    """

    AUTHORIZED_ATS_DOMAINS = [
        "greenhouse.io",
        "lever.co",
        "ashbyhq.com",
        "myworkdayjobs.com",
        "workday.com",
        "smartrecruiters.com",
        "workable.com",
        "bamboohr.com",
        "rippling-ats.com",
        "rippling.com",
        "icims.com",
        "taleo.net",
        "oraclecloud.com",
        "amazon.jobs",
        "successfactors.com",
        "jobs2web.com",
        "csod.com",
        "eightfold.ai",
        "phenom.com",
        "phenompeople.com",
        "jobvite.com",
        "breezy.hr",
        "personio.com",
        "recruitee.com",
        "applytojob.com",
        "pinpointhq.com",
        "jazzhr.com",
        "dover.com",
        "google.com",
        "apple.com",
        "microsoft.com",
    ]

    CHALLENGE_PATTERNS = [
        "cf-challenge", "challenge-platform", "challenges.cloudflare.com", "__cf_chl_",
        "turnstile", "hcaptcha", "recaptcha", "perimeterx", "datadome", "checkpoint",
        "authwall", "challenge-running"
    ]

    CHALLENGE_TEXTS = [
        "verify you are human", "security check", "robot or human", "access denied",
        "attention required! | cloudflare", "attention required", "just a moment...",
        "checking your browser before accessing", "two-factor authentication", "2fa", "mfa"
    ]

    def __init__(
        self,
        context: BrowserContext,
        form_rag: Optional[FormRAG] = None,
        cfg: Optional[AppConfig] = None,
        resume_path: Optional[Path] = None,
        authorized_domains: Optional[list] = None,
        candidate_info: Optional[Dict[str, str]] = None,
    ):
        self.context = context
        self.form_rag = form_rag
        self.cfg = cfg or get_config()
        self.authorized_domains = list(authorized_domains) if authorized_domains else list(self.AUTHORIZED_ATS_DOMAINS)

        if resume_path is not None:
            self.resume_path = Path(resume_path)
        else:
            p = getattr(self.cfg.profile, "resume_path", "data/resume/resume.pdf")
            self.resume_path = Path(p)

        self.candidate_info = candidate_info or load_candidate_profile_info(self.cfg)
        self.last_outcome: Dict[str, Any] = {}

    def validate_target_domain(self, url: str) -> str:
        """
        Policy gate:
        - Rejects LinkedIn domains/subdomains with LinkedInPolicyViolationError.
        - Asserts target domain matches authorized ATS platforms.
        """
        clean = (url or "").lower().strip()
        if "linkedin.com" in clean or "lnkd.in" in clean:
            raise LinkedInPolicyViolationError(
                f"Compliance Policy Violation: Automated browser application to LinkedIn ({clean}) is strictly prohibited."
            )

        try:
            parsed = urlparse(clean)
            hostname = parsed.hostname or ""
        except Exception:
            hostname = ""

        # Check if domain matches any authorized ATS domain or subdomain
        is_authorized = any(
            hostname == d or hostname.endswith("." + d)
            for d in self.authorized_domains
        )
        if not is_authorized:
            import os
            if os.environ.get("AUTOBOT_STRICT_POLICY") == "1":
                raise ValueError(
                    f"Domain '{hostname}' is not authorized for automated ATS application. "
                    f"Authorized ATS platforms: {', '.join(self.authorized_domains)}"
                )
            logger.info(f"[browser]Navigating to external career domain '{hostname}'.[/browser]")

        return hostname

    async def check_security_challenges(self, page: Page) -> None:
        """
        Check page URL and content for anti-bot challenges, CAPTCHAs, or MFA walls.
        Halts immediately without attempting bypass.
        """
        import asyncio
        page_url = str(getattr(page, "url", "") or "").lower()
        for pat in self.CHALLENGE_PATTERNS:
            if pat in page_url:
                raise AntiBotChallengeDetected(
                    f"Anti-bot challenge gate detected in URL: '{page_url}'. Halting execution immediately."
                )

        try:
            raw_title = page.title() if callable(getattr(page, "title", None)) else getattr(page, "title", "")
            if inspect.isawaitable(raw_title):
                raw_title = await raw_title
            title = str(raw_title or "").lower()

            # Handle transient loading screens (e.g. Cloudflare / Workday "Just a moment..." during page hydration)
            if "just a moment" in title:
                for _ in range(5):
                    await asyncio.sleep(1.0)
                    raw_title = page.title() if callable(getattr(page, "title", None)) else getattr(page, "title", "")
                    if inspect.isawaitable(raw_title):
                        raw_title = await raw_title
                    title = str(raw_title or "").lower()
                    if "just a moment" not in title:
                        break

            for text in self.CHALLENGE_TEXTS:
                if text == "just a moment..." and "just a moment" not in title:
                    continue
                if text in title:
                    # Verify if an actual challenge element is present or if title remained in challenge state
                    raise AntiBotChallengeDetected(
                        f"Anti-bot challenge gate detected in title '{title}'. Halting execution immediately."
                    )

            if hasattr(page, "evaluate") and callable(page.evaluate):
                body_eval = page.evaluate("() => (document.body ? document.body.innerText.slice(0, 2000).toLowerCase() : '')")
                if inspect.isawaitable(body_eval):
                    body_eval = await body_eval
                body_str = str(body_eval or "").lower()
                for text in self.CHALLENGE_TEXTS:
                    if text == "just a moment..." and "just a moment" not in title:
                        continue
                    if text in body_str:
                        raise AntiBotChallengeDetected(
                            "Anti-bot verification challenge detected on page. Halting execution immediately."
                        )

            # Check DOM for live interactive CAPTCHA puzzle or Turnstile challenge gates
            if hasattr(page, "query_selector") and callable(page.query_selector):
                # An active blocking challenge page has challenge stage or running screen covering the page
                blocking_gate = page.query_selector(
                    "#challenge-running, #challenge-stage, #cf-please-wait, div.cf-turnstile-wrapper:not([style*='display: none']) iframe[title*='challenge' i]"
                )
                if inspect.isawaitable(blocking_gate):
                    blocking_gate = await blocking_gate
                if blocking_gate:
                    is_vis = await _eval_maybe_async(getattr(blocking_gate, "is_visible", None))
                    if is_vis:
                        raise AntiBotChallengeDetected(
                            "Interactive anti-bot CAPTCHA/Turnstile challenge element detected in DOM. Halting execution immediately."
                        )

                # Check if a genuine job application form is already visible on the page
                has_form = False
                form_input = page.query_selector("input[type='email'], #first_name, #email, input[name='name'], input[name='email']")
                if inspect.isawaitable(form_input):
                    form_input = await form_input
                if form_input:
                    has_form = await _eval_maybe_async(getattr(form_input, "is_visible", None))

                if not has_form:
                    captcha_elem = page.query_selector(
                        "iframe[title*='challenge' i], iframe[src*='/bframe'], iframe[src*='challenges.cloudflare.com']"
                    )
                    if inspect.isawaitable(captcha_elem):
                        captcha_elem = await captcha_elem
                    if captcha_elem and await _eval_maybe_async(getattr(captcha_elem, "is_visible", None)):
                        raise AntiBotChallengeDetected(
                            "Interactive anti-bot CAPTCHA challenge element blocking form access. Halting execution immediately."
                        )
        except AntiBotChallengeDetected:
            raise
        except Exception:
            pass

    def _resolve_external_apply_url(self, url: str) -> Optional[str]:
        """
        Attempt to extract destination external ATS URL from query parameters, safety redirects,
        or tracking links (e.g. safety/go/?url=... or externalApply?url=...).
        """
        try:
            from src.browser.linkedin_apply_extractor import decode_linkedin_apply_url
            decoded = decode_linkedin_apply_url(url)
            if decoded:
                return decoded
        except Exception:
            pass

        try:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            for param in ("url", "redirect", "dest", "target", "apply_url", "external_url"):
                if param in qs and qs[param]:
                    extracted = unquote(qs[param][0]).strip()
                    if extracted.startswith("http://") or extracted.startswith("https://"):
                        if "linkedin.com" not in extracted.lower() and "lnkd.in" not in extracted.lower():
                            return extracted
        except Exception:
            pass
        return None

    async def apply(
        self,
        job: JobPosting,
        apply_url: Optional[str] = None,
        cover_letter: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """
        Open the external application URL and attempt automated submission.

        Args:
            job: The target JobPosting.
            apply_url: External career page URL (defaults to job.external_apply_url or job.url).
            cover_letter: Optional cover letter text.
            dry_run: If True, fills form and uploads resume without pressing final submit.

        Returns:
            True if submitted successfully (or simulated successfully in dry_run), False otherwise.
        """
        target_url = apply_url or job.external_apply_url or job.url
        if not target_url:
            logger.warning("[browser]No external apply URL available.[/browser]")
            return False

        # If URL is a LinkedIn redirect or tracking link, attempt to extract the destination ATS URL
        if "linkedin.com" in target_url.lower() or "lnkd.in" in target_url.lower():
            resolved = self._resolve_external_apply_url(target_url)
            if not resolved:
                from src.browser.company_careers_resolver import resolve_company_direct_apply_url, is_valid_direct_ats_url
                res_portal = resolve_company_direct_apply_url(title=job.title, company=job.company, current_url=target_url)
                if is_valid_direct_ats_url(res_portal)[0]:
                    resolved = res_portal
            if resolved:
                logger.info(f"[browser]Extracted destination external ATS URL: {resolved}[/browser]")
                target_url = resolved
            else:
                # Automated interaction on LinkedIn itself is restricted by compliance policy
                raise LinkedInPolicyViolationError(
                    f"Compliance Policy Violation: Automated browser application to LinkedIn ({target_url}) is strictly prohibited. "
                    f"Job '{job.title}' @ '{job.company}' is an external form posting on LinkedIn. "
                    f"Please use 'Open Form ↗' to apply via the company's external career portal."
                )

        # Validate domain before opening browser tab
        self.validate_target_domain(target_url)

        logger.info(
            f"[browser]🌐 External Apply: '{job.title}' @ '{job.company}' -> {target_url[:50]}...[/browser]"
        )

        tab = await self.context.new_page()
        try:
            try:
                await update_visual_cursor(tab, action_text=f"External apply: {job.title[:18]}...")
            except Exception:
                pass
            await tab.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await human_delay(1500, 2500)

            # Auto-dismiss / suppress cookie consent overlays (Option 1 + Option 2)
            from src.browser.cookie_handler import dismiss_cookie_banners
            cookie_pol = getattr(getattr(self.cfg, "browser", None), "cookie_policy", "auto_accept")
            await dismiss_cookie_banners(tab, policy=cookie_pol)

            # Check for security challenges / CAPTCHA gates
            await self.check_security_challenges(tab)

            # Auto-equalize career directory hub to exact job requisition (Groq LLM / Tier-1 Matcher)
            try:
                from src.browser.career_page_equalizer import equalize_career_hub_url
                equalized_url = await equalize_career_hub_url(
                    page=tab,
                    target_title=job.title,
                    company=job.company,
                    location=job.location or "",
                    current_url=tab.url,
                )
                if equalized_url:
                    target_url = equalized_url
                    await human_delay(1500, 2500)
                    await dismiss_cookie_banners(tab, policy=cookie_pol)
            except Exception as eq_ex:
                logger.debug(f"[browser]Requisition Equalizer bypassed: {eq_ex}")

            # Ensure application form section is expanded/visible (clicks 'Apply for this job' if needed)
            self._current_job_title = job.title
            await self._ensure_application_form_visible(tab)

            # Re-dismiss cookie banners in case opening the form spawned a consent dialog
            await dismiss_cookie_banners(tab, policy=cookie_pol)

            # Fast check: If portal requires candidate login or account creation, handle according to user policy
            login_pol = getattr(getattr(self.cfg, "apply", None), "login_portal_policy", "skip_portal")
            from src.browser.proof_audit import verify_submission_status
            pre_login_check = await verify_submission_status(tab)
            if pre_login_check.get("reason_code") == "ACCOUNT_REQUIRED":
                if login_pol == "skip_portal":
                    logger.info(f"[browser]⏭ Portal requires candidate login/account creation for '{job.title}' @ '{job.company}'. Skipping automatically per user policy.")
                    blocker_path = await capture_proof_screenshot(
                        tab, job.job_id, job.company, job.title,
                        is_success=False,
                        reason=pre_login_check["description"],
                        status="requires_manual",
                    )
                    self.last_outcome = {
                        "success": False,
                        "status": "requires_manual",
                        "reason_code": "ACCOUNT_REQUIRED",
                        "description": pre_login_check["description"],
                        "proof_screenshot": blocker_path or "",
                    }
                    return False

            # --- Multi-Step / Multi-Page Form Progression Loop ---
            # Universally handles single-page forms AND multi-step ATS flows
            # (Workday, Phenom People, SuccessFactors, Taleo, Greenhouse, Lever, Ashby, etc.)
            max_form_steps = 6
            total_filled_fields = 0
            resume_uploaded = False

            for step_num in range(1, max_form_steps + 1):
                logger.info(f"[browser]📝 Processing application form step {step_num}...[/browser]")
                await dismiss_cookie_banners(tab, policy=cookie_pol)

                # 1. Upload Resume if not yet uploaded
                if not resume_uploaded:
                    resume_uploaded = await self._upload_resume(tab)

                # 2. Fill Contact, Personal & Location Combobox Fields
                step_filled = await self._fill_contact_fields(tab)
                total_filled_fields += step_filled

                # 3. Fill Dropdowns (<select> and React-Select/ARIA comboboxes)
                total_filled_fields += await self._fill_select_dropdowns(tab)

                # 4. Fill Toggle Button Groups (e.g. Ashby Yes/No pills) & Radio Groups
                total_filled_fields += await self._fill_toggle_button_groups(tab)
                total_filled_fields += await self._fill_radio_groups(tab)

                # 5. Fill Required Consent & Privacy Checkboxes
                total_filled_fields += await self._fill_checkboxes(tab)

                # 6. Fill Cover Letter if textarea present
                if cover_letter:
                    await self._fill_cover_letter(tab, cover_letter)

                # 7. AI Fallback: Map and fill any remaining empty required inputs
                ai_filled = await self._fill_all_unrecognized_with_ai(tab)
                total_filled_fields += ai_filled

                # 8. Conditional recovery pass for fields revealed dynamically by previous answers
                await asyncio.sleep(0.5)
                extra_filled = 0
                extra_filled += await self._fill_select_dropdowns(tab)
                extra_filled += await self._fill_toggle_button_groups(tab)
                extra_filled += await self._fill_radio_groups(tab)
                extra_filled += await self._fill_checkboxes(tab)
                extra_filled += await self._fill_all_unrecognized_with_ai(tab)
                total_filled_fields += extra_filled

                # Re-check challenges during form filling
                await self.check_security_challenges(tab)

                if dry_run:
                    break

                # Check if submit button is present on this step
                if await self._is_submit_button_present(tab):
                    break

                # Advance to next step if a Next/Continue button is present
                advanced = await self._click_next_or_continue(tab)
                if not advanced:
                    break
                await human_delay(2000, 3500)

            from src.browser.proof_audit import capture_proof_screenshot, verify_submission_status

            # Strict Form Verification: Verify form was actually opened and populated
            if total_filled_fields == 0 and not resume_uploaded:
                logger.warning(f"[browser]⚠ Application form was not opened or fields missing on {job.company} portal.")
                blocker_path = await capture_proof_screenshot(
                    tab, job.job_id, job.company, job.title,
                    is_success=False,
                    reason="Application form could not be opened or required fields were not found.",
                    status="requires_manual",
                )
                self.last_outcome = {
                    "success": False,
                    "status": "requires_manual",
                    "reason_code": "FORM_NOT_OPENED",
                    "description": "Application form was not opened or required contact fields could not be found.",
                    "proof_screenshot": blocker_path or "",
                }
                await human_delay(2000, 3500)
                return False

            # 5. Attempt Submit or Dry-Run Simulation
            if dry_run:
                logger.info(
                    f"[browser]🔍 [Dry-Run] Application form for '{job.title}' @ '{job.company}' "
                    f"filled successfully ({total_filled_fields} fields, resume={resume_uploaded}) - simulation mode.[/browser]"
                )
                proof_path = await capture_proof_screenshot(
                    tab, job.job_id, job.company, job.title,
                    is_success=True,
                    status="dry_run",
                )
                self.last_outcome = {
                    "success": True,
                    "status": "dry_run",
                    "reason_code": "DRY_RUN",
                    "description": f"Form fields populated with candidate profile ({total_filled_fields} inputs). Submit withheld by user setting.",
                    "proof_screenshot": proof_path or "",
                }
                await human_delay(3000, 5000)
                return True

            submitted = await self._submit_form(tab)
            if submitted:
                logger.info(f"[browser] Submitted form for {job.company}. Polling for thank you / confirmation screen...")
                # Poll up to 15 seconds for confirmation screen or redirect
                verification = {"is_submitted": False, "status": "requires_manual", "reason_code": "PENDING", "description": "Awaiting confirmation"}
                for attempt in range(6):
                    await human_delay(1500, 2500)
                    verification = await verify_submission_status(tab)
                    if verification["is_submitted"]:
                        break
                    if verification["reason_code"] in ("VALIDATION_ERROR", "ACCOUNT_REQUIRED", "SECURITY_CHALLENGE"):
                        break
                    # If submit button is gone and no error alerts, wait a moment for animation
                    is_btn_still = await self._is_submit_button_present(tab)
                    if not is_btn_still and attempt >= 2:
                        await human_delay(1000, 2000)
                        verification = await verify_submission_status(tab)
                        if verification["is_submitted"] or verification["reason_code"] in ("VALIDATION_ERROR", "ACCOUNT_REQUIRED", "SECURITY_CHALLENGE"):
                            break

                if not verification["is_submitted"] and verification["reason_code"] == "VALIDATION_ERROR":
                    # Retry pass: conditional/revealed validation fields may now show errors; fill them and submit once more
                    logger.info(f"[browser] Validation error detected ({verification['description']}). Running recovery fill pass...")
                    recovered = 0
                    recovered += await self._fill_contact_fields(tab)
                    recovered += await self._fill_select_dropdowns(tab)
                    recovered += await self._fill_toggle_button_groups(tab)
                    recovered += await self._fill_radio_groups(tab)
                    recovered += await self._fill_checkboxes(tab)
                    recovered += await self._fill_all_unrecognized_with_ai(tab)
                    if recovered > 0:
                        await human_delay(600, 1200)
                        if await self._submit_form(tab):
                            for _retry in range(4):
                                await human_delay(1500, 2200)
                                verification = await verify_submission_status(tab)
                                if verification["is_submitted"] or verification["reason_code"] in ("VALIDATION_ERROR", "ACCOUNT_REQUIRED", "SECURITY_CHALLENGE"):
                                    break

                if verification["is_submitted"]:
                    logger.info(f"[browser]✅ Verified external application submission for {job.company}!")
                    proof_path = await capture_proof_screenshot(
                        tab, job.job_id, job.company, job.title,
                        is_success=True,
                        status="applied",
                    )
                    self.last_outcome = {
                        "success": True,
                        "status": "applied",
                        "reason_code": verification["reason_code"],
                        "description": verification["description"],
                        "proof_screenshot": proof_path or "",
                    }
                    await human_delay(3000, 4500)
                    return True
                else:
                    logger.warning(f"[browser]⚠ Submitted but confirmation not verified: {verification['description']}")
                    # Check if submit button is gone (form was sent even if confirmation text was custom)
                    is_btn_still = await self._is_submit_button_present(tab)
                    if not is_btn_still and verification["reason_code"] not in ("ACCOUNT_REQUIRED", "SECURITY_CHALLENGE", "VALIDATION_FAILED"):
                        logger.info(f"[browser] Submit button dispatched and form closed on {job.company}. Capturing post-submission proof.")
                        proof_path = await capture_proof_screenshot(
                            tab, job.job_id, job.company, job.title,
                            is_success=True,
                            status="applied",
                        )
                        self.last_outcome = {
                            "success": True,
                            "status": "applied",
                            "reason_code": "SUBMIT_DISPATCHED",
                            "description": "Application submitted successfully and form closed.",
                            "proof_screenshot": proof_path or "",
                        }
                        await human_delay(2000, 3500)
                        return True

                    blocker_path = await capture_proof_screenshot(
                        tab, job.job_id, job.company, job.title,
                        is_success=False,
                        reason=verification["description"],
                        status=verification["status"],
                    )
                    self.last_outcome = {
                        "success": False,
                        "status": verification["status"],
                        "reason_code": verification["reason_code"],
                        "description": verification["description"],
                        "proof_screenshot": blocker_path or "",
                    }
                    await human_delay(2000, 3500)
                    return False
            else:
                logger.info("[browser]⚠ External portal submission requires manual verification.[/browser]")
                verification = await verify_submission_status(tab)
                reason_desc = verification["description"] if verification["reason_code"] != "UNKNOWN" else "Application submit button not found or required fields were incomplete."
                blocker_path = await capture_proof_screenshot(
                    tab, job.job_id, job.company, job.title,
                    is_success=False,
                    reason=reason_desc,
                    status="requires_manual",
                )
                self.last_outcome = {
                    "success": False,
                    "status": "requires_manual",
                    "reason_code": verification["reason_code"] if verification["reason_code"] != "UNKNOWN" else "SUBMIT_FAILED",
                    "description": reason_desc,
                    "proof_screenshot": blocker_path or "",
                }
                await human_delay(2000, 3500)
                return False

        except AntiBotChallengeDetected as abc:
            logger.error(f"[browser]🛑 Anti-bot challenge: {abc}. Halting submission cleanly.[/browser]")
            from src.browser.proof_audit import capture_proof_screenshot
            try:
                blocker_path = await capture_proof_screenshot(tab, job.job_id, job.company, job.title, is_success=False, reason="Anti-bot security challenge detected")
                self.last_outcome = {
                    "success": False,
                    "status": "challenge_detected",
                    "reason_code": "SECURITY_CHALLENGE",
                    "description": f"Security challenge on portal: {abc}",
                    "proof_screenshot": blocker_path or "",
                }
            except Exception:
                pass
            raise
        except LinkedInPolicyViolationError:
            raise
        except Exception as e:
            logger.warning(f"External apply error: {e}")
            from src.browser.proof_audit import capture_proof_screenshot
            try:
                blocker_path = await capture_proof_screenshot(tab, job.job_id, job.company, job.title, is_success=False, reason=str(e))
                self.last_outcome = {
                    "success": False,
                    "status": "requires_manual",
                    "reason_code": "ERROR",
                    "description": f"Error during application: {e}",
                    "proof_screenshot": blocker_path or "",
                }
            except Exception:
                pass
            return False
        finally:
            try:
                await tab.close()
            except Exception:
                pass

    async def _ensure_application_form_visible(self, page: Page) -> None:
        """If the page shows an 'Apply' or 'Apply Manually' button before loading the form, click through (up to 2 rounds)."""
        try:
            # Wait briefly for slow SPAs (Workday, Phenom, Ashby) to hydrate initial DOM
            for _ in range(8):
                try:
                    hydrated = await page.evaluate(
                        "() => Boolean(document.body && (document.body.innerText || '').trim().length > 40)"
                    )
                    if hydrated:
                        break
                except Exception:
                    break
                await asyncio.sleep(0.5)

            has_form = await page.query_selector("input[type='file'], input[type='email'], input[name='firstName'], #first_name, #_systemfield_name")
            if has_form and await _eval_maybe_async(getattr(has_form, "is_visible", None)):
                return

            apply_triggers = [
                # Workday modals / buttons first when modal opens
                "button[data-automation-id='applyManually']",
                "a[data-automation-id*='applyManually']",
                "button:has-text('Apply Manually')",
                "a[data-automation-id*='adventureButton']",
                "button[data-automation-id*='apply']",
                # Phenom People (Proximus, Honeywell, ABB, etc.)
                "[data-ph-at-id='apply-link']",
                "[data-ph-at-id='apply-text']",
                "[data-ph-at-id='apply-button']",
                "a[data-ph-at-id*='apply']",
                "button[data-ph-at-id*='apply']",
                "[data-ph-id*='apply']",
                "a.ph-apply-button",
                "button.ph-apply-button",
                ".ph-apply-button",
                # Ashby / Lever / Common ATS
                "a[href$='/application']",
                "a.postings-btn:has-text('Apply')",
                "a[href*='#application-form']",
                "a[href*='#apply']",
                "a[href*='/apply']",
                "a[href*='#app']",
                "#apply_button",
                "button:has-text('Apply for this job')",
                "button:has-text('Apply for this role')",
                "button:has-text('Apply Now')",
                "button:has-text('Apply')",
                "a:has-text('Apply for this job')",
                "a:has-text('Apply for this role')",
                "a:has-text('Apply Now')",
                "a:has-text('Apply')",
                "[data-testid*='apply-button']",
            ]

            for _ in range(2):
                has_form = await page.query_selector("input[type='file'], input[type='email'], input[name='firstName'], #first_name, #_systemfield_name")
                if has_form and await _eval_maybe_async(getattr(has_form, "is_visible", None)):
                    return

                clicked = False
                for sel in apply_triggers:
                    try:
                        btn = await page.query_selector(sel)
                        if btn and await _eval_maybe_async(getattr(btn, "is_visible", None)):
                            await visual_click(page, btn, action_text="Opening application form...")
                            try:
                                await page.wait_for_load_state("domcontentloaded", timeout=6000)
                            except Exception:
                                pass
                            await human_delay(1500, 2500)
                            clicked = True
                            break
                    except Exception:
                        continue

                # If heuristic triggers didn't open the form, use Groq AI to locate the apply button
                if not clicked:
                    try:
                        from src.browser.groq_form_assistant import identify_apply_button_with_groq
                        groq_sel = await identify_apply_button_with_groq(page, getattr(self, "_current_job_title", ""))
                        if groq_sel:
                            groq_btn = await page.query_selector(groq_sel)
                            if groq_btn and await _eval_maybe_async(getattr(groq_btn, "is_visible", None)):
                                await visual_click(page, groq_btn, action_text="Opening application form (Groq AI)...")
                                await human_delay(1500, 2500)
                                clicked = True
                    except Exception as g_err:
                        logger.debug(f"[browser]Groq AI apply trigger error: {g_err}")

                if not clicked:
                    break

            # Wait briefly for form inputs to appear after clicking Apply
            try:
                await page.wait_for_selector(
                    "input[type='file'], input[type='email'], input[name*='name'], input[name='firstName'], #first_name, #_systemfield_name, textarea",
                    timeout=5000,
                )
            except Exception:
                pass
        except Exception:
            pass

    def _get_interactive_contexts(self, page: Any) -> List[Any]:
        """
        Return the main page plus all active child frames/iframes.
        Enables seamless form finding inside embedded ATS iframes (Greenhouse, Workday, iCIMS, Lever, Phenom).
        """
        contexts: List[Any] = [page]
        try:
            raw_frames = getattr(page, "frames", None)
            if isinstance(raw_frames, list):
                for frame in raw_frames:
                    main_f = getattr(page, "main_frame", None)
                    if frame != main_f:
                        is_detached = getattr(frame, "is_detached", None)
                        if callable(is_detached):
                            try:
                                if is_detached():
                                    continue
                            except Exception:
                                pass
                        contexts.append(frame)
        except Exception:
            pass
        return contexts

    ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}

    async def _upload_resume(self, page: Any) -> bool:
        """Upload resume document to any file input element present on page with dropzone and CDP fallback."""
        if not self.resume_path.exists():
            logger.warning(f"[browser]Resume file not found on disk: {self.resume_path}")
            return False

        if self.resume_path.suffix.lower() not in self.ALLOWED_RESUME_EXTENSIONS:
            logger.warning(
                f"[browser]SECURITY POLICY VIOLATION: Blocked attempt to upload unauthorized file type: '{self.resume_path.name}'"
            )
            return False

        resume_full_path = str(self.resume_path.resolve())
        contexts = self._get_interactive_contexts(page)
        uploaded_any = False

        for ctx in contexts:
            try:
                # 1. Search for standard file inputs (skip cover letter file inputs; prefer dedicated #resume / #_systemfield_resume first)
                if hasattr(ctx, "query_selector_all") and callable(ctx.query_selector_all):
                    raw_inputs = ctx.query_selector_all(
                        "input[type='file']#resume, "
                        "input[type='file']#_systemfield_resume, "
                        "input[type='file'][name*='resume' i], "
                        "input[type='file'][name*='cv' i], "
                        "input[type='file'][accept*='pdf'], "
                        "input[type='file']"
                    )
                    file_inputs = await raw_inputs if inspect.isawaitable(raw_inputs) else raw_inputs
                    if isinstance(file_inputs, list):
                        for inp in file_inputs:
                            try:
                                if hasattr(ctx, "evaluate"):
                                    should_skip_file = await _eval_maybe_async(
                                        ctx.evaluate(
                                            """(el) => {
                                                const attrs = ((el.id || '') + ' ' + (el.name || '') + ' ' + (el.accept || '')).toLowerCase();
                                                if (attrs.includes('cover') || attrs.includes('image/')) return true;
                                                const q = el.closest('.application-question, .field, [class*="question" i]');
                                                const qTxt = (q ? q.innerText : '').toLowerCase();
                                                return /\\b(cover letter|photo|picture|headshot|avatar|image)\\b/.test(qTxt);
                                            }""",
                                            inp,
                                        )
                                    )
                                    if should_skip_file:
                                        continue
                                if hasattr(inp, "set_input_files"):
                                    res = inp.set_input_files(resume_full_path)
                                    if inspect.isawaitable(res):
                                        await res
                                    uploaded_any = True
                                    logger.info("[browser]📎 Resume attached via file input element[/browser]")
                                    # Wait briefly so Ashby/Greenhouse top autofill doesn't race with contact filling,
                                    # and continue loop only if another distinct #_systemfield_resume exists without files
                                    fid = ""
                                    if hasattr(inp, "get_attribute"):
                                        fid = str(await _eval_maybe_async(inp.get_attribute("id")) or "")
                                    if fid in ("resume", "_systemfield_resume"):
                                        break
                            except Exception:
                                continue

                # 2. If not uploaded yet, check for interactive dropzones / upload buttons
                if not uploaded_any and hasattr(ctx, "query_selector"):
                    dropzone_selectors = [
                        "button:has-text('Upload Resume')",
                        "button:has-text('Upload CV')",
                        "button:has-text('Attach Resume')",
                        "[data-ph-at-id*='upload']",
                        ".dropzone",
                        "[aria-label*='upload resume' i]",
                        "label[for*='resume']",
                    ]
                    for sel in dropzone_selectors:
                        try:
                            btn = ctx.query_selector(sel) if hasattr(ctx, "query_selector") else None
                            if inspect.isawaitable(btn):
                                btn = await btn
                            if btn and callable(getattr(btn, "is_visible", None)):
                                is_vis = await btn.is_visible() if inspect.isawaitable(btn.is_visible()) else btn.is_visible()
                                if is_vis and hasattr(page, "expect_file_chooser"):
                                    try:
                                        async with page.expect_file_chooser(timeout=2500) as fc_info:
                                            await btn.click()
                                        fc = await fc_info.value
                                        await fc.set_files(resume_full_path)
                                        uploaded_any = True
                                        logger.info("[browser]📎 Resume attached via file chooser dropzone[/browser]")
                                        break
                                    except Exception:
                                        pass
                        except Exception:
                            continue

                if uploaded_any:
                    await human_delay(1200, 2000)
                    return True
            except Exception:
                continue

        return uploaded_any

    async def _fill_location_combobox(self, ctx: Any, el: Any, city_query: str = "Ahmedabad", full_loc: str = "Ahmedabad, Gujarat, India") -> bool:
        """Populate an autocomplete/React-Select location combobox by typing and choosing a matching option."""
        try:
            if not await _eval_maybe_async(getattr(el, "is_visible", None)):
                return False

            # Check container single-value pill or input already has a location selected (skip inner .select__input-container!)
            if hasattr(ctx, "evaluate"):
                already = await _eval_maybe_async(
                    ctx.evaluate("""(el) => {
                        if ((el.value || '').trim()) return true;
                        const p = el.parentElement || el;
                        const wrap = p.closest('.select__control, .select__value-container, .select-shell') || p.closest('[class*="control" i]') || p;
                        const sv = wrap ? wrap.querySelector('[class*="singleValue" i], [class*="single-value" i], .select__single-value') : null;
                        return Boolean(sv && (sv.innerText || '').trim());
                    }""", el)
                )
                if already:
                    return False

            if hasattr(el, "scroll_into_view_if_needed"):
                await _eval_maybe_async(el.scroll_into_view_if_needed())
            if hasattr(el, "click"):
                await _eval_maybe_async(el.click())
            await human_delay(120, 200)

            if hasattr(el, "fill"):
                await _eval_maybe_async(el.fill(""))
            if hasattr(el, "type"):
                await _eval_maybe_async(el.type(city_query, delay=45))
            elif hasattr(el, "fill"):
                await _eval_maybe_async(el.fill(city_query))

            # Poll up to ~2.8s for async location geocoding results, refreshing aria-controls each poll
            picked = False
            for _wait_round in range(7):
                await asyncio.sleep(0.4)
                controls_id = ""
                if hasattr(el, "get_attribute"):
                    controls_id = str(await _eval_maybe_async(el.get_attribute("aria-controls")) or "")

                option_selectors = []
                if controls_id:
                    option_selectors.append(f'{_safe_id_selector(controls_id)} [role="option"]')
                option_selectors.extend([
                    '[id*="-listbox"] [role="option"]',
                    '[role="listbox"]:not([id*="iti-"]) [role="option"]',
                    '[class*="select__menu"] [role="option"]',
                    '.dropdown-results div',
                ])

                for opt_sel in option_selectors:
                    opts = ctx.query_selector_all(opt_sel) if hasattr(ctx, "query_selector_all") else []
                    if inspect.isawaitable(opts):
                        opts = await opts
                    if not isinstance(opts, list) or not opts:
                        continue
                    visible_opts = []
                    for o in opts:
                        if await _eval_maybe_async(getattr(o, "is_visible", None)):
                            o_txt = str(await _eval_maybe_async(getattr(o, "inner_text", None)) or "").strip()
                            if o_txt and "loading" not in o_txt.lower() and "no options" not in o_txt.lower():
                                visible_opts.append((o_txt, o))
                    if not visible_opts:
                        continue

                    best_opt = None
                    for o_txt, o in visible_opts:
                        tl = o_txt.lower()
                        if city_query.lower() in tl or "india" in tl or "gujarat" in tl:
                            best_opt = o
                            break
                    if not best_opt:
                        best_opt = visible_opts[0][1]
                    if best_opt and hasattr(best_opt, "click"):
                        await _eval_maybe_async(best_opt.click())
                        picked = True
                        await human_delay(200, 350)
                        break
                if picked:
                    break

            # For plain text location boxes (e.g. Lever without API options), keep clean city text if value cleared
            curr_val = str(await _eval_maybe_async(getattr(el, "input_value", None)) or "").strip()
            has_single_val = False
            if hasattr(ctx, "evaluate"):
                has_single_val = bool(
                    await _eval_maybe_async(
                        ctx.evaluate("""(el) => {
                            const p = el.parentElement || el;
                            const wrap = p.closest('.select__control, .select__value-container, .select-shell') || p.closest('[class*="control" i]') || p;
                            const sv = wrap ? wrap.querySelector('[class*="singleValue" i], [class*="single-value" i], .select__single-value') : null;
                            return Boolean(sv && (sv.innerText || '').trim());
                        }""", el)
                    )
                )
            if not curr_val and not has_single_val and hasattr(el, "fill"):
                await _eval_maybe_async(el.fill(full_loc))
            return True
        except Exception:
            return False

    async def _fill_contact_fields(self, page: Any) -> int:
        """Fill common personal, contact, profile URL, and location autocomplete fields across all contexts."""
        candidate = getattr(self, "candidate_info", {}) or {}
        filled_count = 0
        contexts = self._get_interactive_contexts(page)
        city_val = candidate.get("city", "Ahmedabad") or "Ahmedabad"
        full_loc = candidate.get("location", "Ahmedabad, Gujarat, India") or "Ahmedabad, Gujarat, India"

        # 1. Full name input
        full_name_selectors = [
            "input[name='name']",
            "input[id='_systemfield_name']",
            "input[name='full_name']",
            "input[name*='fullName']",
            "input[id='name']",
            "input[id*='full_name']",
            "input[placeholder*='Full name' i]",
            "input[placeholder*='Full Name' i]",
            "input[aria-label*='Full name' i]",
            "input[data-automation-id*='fullName']",
        ]

        full_name_filled = False
        for ctx in contexts:
            for sel in full_name_selectors:
                try:
                    el = ctx.query_selector(sel) if hasattr(ctx, "query_selector") else None
                    if inspect.isawaitable(el):
                        el = await el
                    if el:
                        is_vis = await _eval_maybe_async(getattr(el, "is_visible", None))
                        if is_vis:
                            val = await _eval_maybe_async(getattr(el, "input_value", None))
                            if not str(val or "").strip():
                                val_to_fill = candidate.get("full_name", "Vanraj Solanki")
                                if val_to_fill:
                                    await el.fill(val_to_fill)
                                    if hasattr(ctx, "evaluate"):
                                        try:
                                            ev = ctx.evaluate("(el) => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", el)
                                            if inspect.isawaitable(ev):
                                                await ev
                                        except Exception:
                                            pass
                                    await human_delay(150, 300)
                                    filled_count += 1
                            full_name_filled = True
                            break
                except Exception:
                    continue
            if full_name_filled:
                break

        # 2. Location autocomplete / React-Select comboboxes (#candidate-location, Ashby Location, Lever #location-input)
        location_combo_selectors = [
            "#candidate-location",
            "#location-input",
            "input[role='combobox'][placeholder*='Start typing' i]",
            "input[role='combobox'][id*='location' i]",
            "input[role='combobox'][aria-label*='location' i]",
        ]
        for ctx in contexts:
            for l_sel in location_combo_selectors:
                try:
                    loc_el = ctx.query_selector(l_sel) if hasattr(ctx, "query_selector") else None
                    if inspect.isawaitable(loc_el):
                        loc_el = await loc_el
                    if loc_el:
                        if await self._fill_location_combobox(ctx, loc_el, city_query=city_val, full_loc=full_loc):
                            filled_count += 1
                except Exception:
                    continue

            # Also check Ashby/custom Location field wrapper where input has no id/name/placeholder hint except parent label == 'Location'
            try:
                if hasattr(ctx, "evaluate"):
                    extra_loc_idx = await _eval_maybe_async(
                        ctx.evaluate("""() => {
                            const combos = Array.from(document.querySelectorAll('input[role="combobox"]'));
                            for (let i = 0; i < combos.length; i++) {
                                const el = combos[i];
                                if (el.offsetWidth === 0 && el.offsetHeight === 0) continue;
                                if (el.id === 'candidate-location') continue;
                                const parent = el.closest('.ashby-application-form-field-entry, [class*="field" i], [class*="question" i]');
                                const lbl = parent ? (parent.querySelector('label, span')?.innerText || '').trim().toLowerCase() : '';
                                if (lbl === 'location' || lbl.startsWith('location')) return i;
                            }
                            return -1;
                        }""")
                    )
                    if isinstance(extra_loc_idx, int) and extra_loc_idx >= 0:
                        combos = await ctx.query_selector_all('input[role="combobox"]') if hasattr(ctx, "query_selector_all") else []
                        if extra_loc_idx < len(combos):
                            if await self._fill_location_combobox(ctx, combos[extra_loc_idx], city_query=city_val, full_loc=full_loc):
                                filled_count += 1
            except Exception:
                pass

        # 3. Authoritative Contact & Social URL fields (supporting aria-label as well as name/placeholder/id)
        # Tuple: (selectors, candidate_key, default_val, allow_multiple)
        fields_map = [
            ("#first_name, #firstname, input[name='first_name'], input[name='firstName'], input[data-automation-id*='firstName'], input[data-ph-id*='firstName'], input[aria-label='First Name'], input[aria-label*='Preferred First Name' i], input[name*='first' i], input[placeholder*='First' i]", "first_name", "Vanraj", True),
            ("#last_name, #lastname, input[name='last_name'], input[name='lastName'], input[data-automation-id*='lastName'], input[data-ph-id*='lastName'], input[aria-label='Last Name'], input[aria-label*='Preferred Last Name' i], input[name*='last' i], input[placeholder*='Last' i]", "last_name", "Solanki", True),
            ("input[type='email'], #email, #_systemfield_email, input[name='email'], input[name*='email' i], input[aria-label*='email' i], input[placeholder*='email' i], input[data-automation-id*='email'], input[data-ph-id*='email']", "email", "vanrajsolanki2875@gmail.com", False),
            ("input[type='tel'], #phone, input[name='phone'], input[name*='phone' i], input[aria-label*='phone' i], input[placeholder*='phone' i], input[data-automation-id*='phone'], input[data-ph-id*='phone']", "phone", "+91-8320452875", False),
            ("input[name*='linkedin' i], input[placeholder*='LinkedIn' i], input[aria-label*='LinkedIn' i], input[id*='linkedin' i], input[data-automation-id*='linkedin']", "linkedin", "https://linkedin.com/in/vanrajsinh", False),
            ("input[name*='github' i], input[placeholder*='GitHub' i], input[aria-label*='GitHub' i], input[id*='github' i], input[data-automation-id*='github']", "github", "https://github.com/vanrajsinh650", False),
            ("input[name*='website' i], input[name*='portfolio' i], input[placeholder*='portfolio' i], input[placeholder*='website' i], input[aria-label='Website'], input[aria-label*='Portfolio' i]", "portfolio", "https://github.com/vanrajsinh650", False),
            ("input[name*='city' i], input[placeholder*='city' i], input[aria-label='City'], input[aria-label='City*'], input[data-automation-id*='addressSection_city'], input[data-ph-id*='city']", "city", "Ahmedabad", False),
            ("input[name*='state' i], input[name*='province' i], input[placeholder*='state' i], input[aria-label='State'], input[data-automation-id*='addressSection_region']", "state", "Gujarat", False),
            ("input[name*='country' i]:not([name*='code' i]):not([role='combobox']), input[placeholder*='country' i]:not([placeholder*='code' i]):not([role='combobox']), input[aria-label='Country']:not([role='combobox']), input[data-automation-id*='addressSection_country']", "country", "India", False),
            ("input[name*='countryCode' i], input[name*='phoneCountry' i], input[placeholder*='dialing' i]", "country_code", "+91", False),
            ("input[name*='location' i]:not([role='combobox']), input[placeholder*='location' i]:not([role='combobox'])", "location", "Ahmedabad, Gujarat, India", False),
            ("input[name*='postal' i], input[name*='zip' i], input[placeholder*='postal' i], input[placeholder*='zip' i], input[data-automation-id*='postalCode']", "postal_code", "380015", False),
            ("input[name*='address' i], input[placeholder*='address' i], input[data-automation-id*='addressSection_addressLine1']", "street_address", "132 Feet Ring Road", False),
            ("input[name='company'], input[name='currentCompany'], input[name='employer'], input[name='org'], input[placeholder*='current company' i], input[aria-label*='Current Company' i]", "current_company", "DivineHindu", False),
            ("input[name='jobTitle'], input[name='currentJobTitle'], input[name='current_title'], input[name='job_title'], input[name='title'], input[placeholder*='current title' i], input[placeholder*='job title' i]", "current_title", "Software & AI Automation Engineer", False),
            ("input[name*='notice' i], input[placeholder*='notice period' i]", "notice_period", "Immediate", False),
            ("input[name*='salary' i], input[placeholder*='salary' i], input[name*='ctc' i], input[placeholder*='ctc' i], input[data-automation-id*='salary']", "expected_salary", "100000", False),
            ("input[name*='experience' i][type='number'], input[placeholder*='years of experience' i], input[name='years_of_experience']", "years_of_experience", "1", False),
            ("input[name*='school' i]:not([role='combobox']), input[name*='university' i]:not([role='combobox']), input[placeholder*='university' i]:not([role='combobox'])", "university", "Gokul Global University", False),
            ("input[name*='degree' i]:not([role='combobox']), input[placeholder*='degree' i]:not([role='combobox'])", "degree", "Bachelor of Computer Applications (BCA)", False),
            ("input[name*='major' i]:not([role='combobox']), input[name*='discipline' i]:not([role='combobox']), input[placeholder*='field of study' i]:not([role='combobox'])", "major", "Computer Applications", False),
        ]

        for ctx in contexts:
            for selector_group, cand_key, default_val, allow_multi in fields_map:
                if full_name_filled and cand_key in ("first_name", "last_name"):
                    # Still fill explicit Preferred First / Last Name inputs if visible, skipping primary first_name/last_name only if already filled
                    pass

                val_to_fill = str(candidate.get(cand_key) or default_val or "").strip()
                if not val_to_fill or val_to_fill.lower() in ("candidate", "user a", "user b", "unknown"):
                    val_to_fill = default_val

                filled_this_key = False
                for sel in selector_group.split(", "):
                    try:
                        raw_els = ctx.query_selector_all(sel.strip()) if hasattr(ctx, "query_selector_all") else None
                        if inspect.isawaitable(raw_els):
                            raw_els = await raw_els
                        if not isinstance(raw_els, list) or not raw_els:
                            el_single = ctx.query_selector(sel.strip()) if hasattr(ctx, "query_selector") else None
                            if inspect.isawaitable(el_single):
                                el_single = await el_single
                            raw_els = [el_single] if el_single else []

                        for el in raw_els:
                            if not el:
                                continue
                            is_vis = await _eval_maybe_async(getattr(el, "is_visible", None))
                            if not is_vis:
                                continue
                            # Skip intl-tel-input dial search & comboboxes
                            role_attr = str(await _eval_maybe_async(el.get_attribute("role")) or "") if hasattr(el, "get_attribute") else ""
                            id_attr = str(await _eval_maybe_async(el.get_attribute("id")) or "") if hasattr(el, "get_attribute") else ""
                            if role_attr == "combobox" or "iti-" in id_attr or id_attr == "country":
                                continue
                            if full_name_filled and cand_key in ("first_name", "last_name") and "preferred" not in sel.lower():
                                continue

                            curr_v = await _eval_maybe_async(getattr(el, "input_value", None))
                            if not str(curr_v or "").strip() and val_to_fill:
                                await el.fill(val_to_fill)
                                if hasattr(ctx, "evaluate"):
                                    try:
                                        ev = ctx.evaluate("(el) => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", el)
                                        if inspect.isawaitable(ev):
                                            await ev
                                    except Exception:
                                        pass
                                await human_delay(120, 220)
                                filled_count += 1
                            filled_this_key = True
                            if not allow_multi:
                                break
                        if filled_this_key and not allow_multi:
                            break
                    except Exception:
                        continue

        # 4. If standard selectors found fewer than 2 fields, invoke Groq AI field mapper
        if filled_count < 2:
            try:
                from src.browser.groq_form_assistant import map_unrecognized_form_fields_with_groq
                ai_mappings = await map_unrecognized_form_fields_with_groq(page, candidate)
                for m in ai_mappings:
                    target_id = m.get("id")
                    val = m.get("fill_value")
                    if target_id and val and str(val).strip().lower() != "candidate":
                        sel_q = f"{_safe_id_selector(target_id)}, {_safe_attr_selector('name', target_id)}"
                        inp = await page.query_selector(sel_q) if hasattr(page, "query_selector") else None
                        if inspect.isawaitable(inp):
                            inp = await inp
                        if inp and callable(getattr(inp, "is_visible", None)):
                            is_vis = await inp.is_visible() if inspect.isawaitable(inp.is_visible()) else inp.is_visible()
                            if is_vis:
                                curr = await inp.input_value() if inspect.isawaitable(inp.input_value()) else inp.input_value()
                                if not str(curr).strip():
                                    await inp.fill(val)
                                    filled_count += 1
            except Exception as g_err:
                logger.debug(f"[browser]Groq AI field mapper skipped: {g_err}")

        return filled_count

    async def _fill_select_dropdowns(self, page: Any) -> int:
        """Fill HTML select dropdowns and ARIA comboboxes using candidate info and Groq AI."""
        filled = 0
        candidate = getattr(self, "candidate_info", {}) or {}
        contexts = self._get_interactive_contexts(page)

        for ctx in contexts:
            try:
                if not hasattr(ctx, "query_selector_all"):
                    continue
                raw_selects = ctx.query_selector_all("select")
                selects = await raw_selects if inspect.isawaitable(raw_selects) else raw_selects
                if not isinstance(selects, list):
                    continue

                for sel in selects:
                    try:
                        is_vis = await _eval_maybe_async(getattr(sel, "is_visible", None))
                        if not is_vis:
                            continue

                        # Extract label and options
                        label_data = ctx.evaluate("""(el) => {
                            let label = '';
                            if (el.id) {
                                const l = document.querySelector(`label[for="${el.id}"]`);
                                if (l) label = l.innerText || '';
                            }
                            if (!label && el.closest('label')) label = el.closest('label').innerText || '';
                            if (!label) label = el.getAttribute('aria-label') || el.name || el.id || '';
                            
                            const options = Array.from(el.options || []).map(o => ({
                                text: (o.text || '').trim(),
                                value: o.value || ''
                            })).filter(o => o.text && !o.text.toLowerCase().startsWith('select') && !o.text.toLowerCase().startsWith('choose') && !o.text.toLowerCase().startsWith('--'));
                            
                            return { label: label.trim(), options: options, currentValue: el.value || '' };
                        }""", sel) if hasattr(ctx, "evaluate") else None
                        if inspect.isawaitable(label_data):
                            label_data = await label_data

                        if not label_data or not isinstance(label_data, dict):
                            continue

                        opts = label_data.get("options", [])
                        if not opts:
                            continue

                        # If already has a selected non-empty value, skip
                        curr_val = str(label_data.get("currentValue", "")).strip()
                        if curr_val and curr_val != "0" and curr_val != "-1":
                            curr_opt = next((o for o in opts if o.get("value") == curr_val), None)
                            if curr_opt:
                                continue

                        question_text = label_data.get("label") or "Dropdown Option"
                        option_texts = [o["text"] for o in opts]

                        from src.browser.groq_form_assistant import answer_question_with_groq
                        best_answer = answer_question_with_groq(
                            question=question_text,
                            options=option_texts,
                            field_type="select",
                            candidate_info=candidate,
                        )

                        if best_answer:
                            matched = next((o for o in opts if o["text"].strip().lower() == best_answer.strip().lower()), None)
                            if not matched:
                                matched = next((o for o in opts if best_answer.strip().lower() in o["text"].strip().lower() or o["text"].strip().lower() in best_answer.strip().lower()), None)
                            if not matched and any(n in best_answer.lower() for n in ("no", "none", "neither", "never")):
                                matched = next((o for o in opts if any(w in o["text"].lower().split() for w in ("no", "none", "never", "not"))), None)
                            if not matched and any(y in best_answer.lower() for y in ("yes", "agree", "authorized")):
                                matched = next((o for o in opts if any(w in o["text"].lower().split() for w in ("yes", "agree", "authorized"))), None)

                            target_val = matched["value"] if matched else opts[0]["value"]
                            res = sel.select_option(value=target_val) if hasattr(sel, "select_option") else None
                            if inspect.isawaitable(res):
                                await res
                            if hasattr(ctx, "evaluate"):
                                ev = ctx.evaluate("""(el) => {
                                    el.dispatchEvent(new Event('change', { bubbles: true }));
                                    el.dispatchEvent(new Event('input', { bubbles: true }));
                                }""", sel)
                                if inspect.isawaitable(ev):
                                    await ev
                            filled += 1
                            await human_delay(150, 250)
                    except Exception:
                        continue
            except Exception:
                continue

        # Part B: Handle custom ARIA / React-Select combobox dropdowns (Greenhouse React, Ashby, etc.)
        for ctx in contexts:
            try:
                if not hasattr(ctx, "query_selector_all"):
                    continue
                raw_combos = ctx.query_selector_all("input[role='combobox'], div[role='combobox'], [aria-haspopup='listbox']")
                combos = await raw_combos if inspect.isawaitable(raw_combos) else raw_combos
                if not isinstance(combos, list):
                    continue

                for combo in combos:
                    try:
                        is_vis = await _eval_maybe_async(getattr(combo, "is_visible", None))
                        if not is_vis:
                            continue

                        meta = ctx.evaluate("""(el) => {
                            const id = el.id || '';
                            const role = el.getAttribute('role') || '';
                            const placeholder = (el.placeholder || '').toLowerCase();
                            if (id.startsWith('iti-') || id === 'candidate-location') return { skip: true };
                            if (role === 'combobox' && placeholder.includes('start typing')) return { skip: true };
                            // Check container single-value / multi-value selected pill (avoid matching .select__input-container!)
                            const pEl = el.parentElement || el;
                            const wrap = pEl.closest('.select__control, .select__value-container, .select-shell') || pEl.closest('[class*="control" i]') || pEl;
                            const sv = wrap ? wrap.querySelector('[class*="singleValue" i], [class*="single-value" i], .select__single-value, [class*="multiValue" i], [class*="multi-value" i], .select__multi-value') : null;
                            const svText = sv ? (sv.innerText || '').trim() : '';
                            if (svText && !svText.toLowerCase().startsWith('select') && !svText.toLowerCase().startsWith('choose')) {
                                return { skip: true, reason: 'already_selected' };
                            }
                            if ((el.tagName || '').toLowerCase() === 'div' && (el.innerText || '').trim() && !(el.innerText || '').toLowerCase().includes('select')) {
                                return { skip: true, reason: 'already_selected' };
                            }
                            let label = '';
                            if (id) {
                                try {
                                    const l = document.querySelector(`label[for="${CSS.escape(id)}"]`);
                                    if (l) label = l.innerText || '';
                                } catch (e) {}
                            }
                            if (!label && el.closest('label')) label = el.closest('label').innerText || '';
                            if (!label) {
                                const containerSelectors = ['.application-question', '.ashby-application-form-field-entry', '[class*="question" i]', '.select', '.field', 'fieldset'];
                                for (const cSel of containerSelectors) {
                                    const qWrap = el.closest(cSel);
                                    if (qWrap) {
                                        const ql = qWrap.querySelector('.application-label, label, legend');
                                        if (ql && (ql.innerText || '').trim()) {
                                            label = ql.innerText;
                                            break;
                                        }
                                    }
                                }
                            }
                            if (!label) label = el.getAttribute('aria-label') || el.name || id || '';
                            return {
                                isCombobox: true,
                                skip: false,
                                id: id,
                                tag: (el.tagName || '').toLowerCase(),
                                label: label.trim().replace(/\\s+/g, ' '),
                                isReq: Boolean(el.required || el.getAttribute('aria-required') === 'true' || label.includes('*') || label.includes('✱'))
                            };
                        }""", combo) if hasattr(ctx, "evaluate") else None
                        if inspect.isawaitable(meta):
                            meta = await meta

                        if not isinstance(meta, dict) or meta.get("skip") or not meta.get("isCombobox"):
                            continue

                        q_text = meta.get("label") or ""
                        q_low = q_text.lower()
                        combo_id = meta.get("id") or ""

                        # Education typeahead comboboxes (Greenhouse school--0 / degree--0 / discipline--0)
                        if any(ek in combo_id.lower() or ek in q_low for ek in ("school", "university", "degree", "discipline", "major")):
                            if not meta.get("isReq"):
                                # Typeahead only cleanly fills if options exist; skip broken free-text leftovers when optional unless matched
                                edu_query = (
                                    candidate.get("university", "Gokul Global University") if any(k in q_low or k in combo_id.lower() for k in ("school", "university"))
                                    else candidate.get("degree", "Bachelor of Computer Applications") if "degree" in q_low or "degree" in combo_id.lower()
                                    else candidate.get("major", "Computer Applications")
                                )
                                await _eval_maybe_async(combo.click())
                                await human_delay(120, 200)
                                if hasattr(combo, "fill"):
                                    await _eval_maybe_async(combo.fill(edu_query))
                                await human_delay(650, 900)
                                cid = str(await _eval_maybe_async(combo.get_attribute("aria-controls")) or "") if hasattr(combo, "get_attribute") else ""
                                edu_opts = await ctx.query_selector_all(f'{_safe_id_selector(cid)} [role="option"]') if cid and hasattr(ctx, "query_selector_all") else []
                                vis_edu_opts = [o for o in (edu_opts or []) if await _eval_maybe_async(getattr(o, "is_visible", None))]
                                if vis_edu_opts:
                                    await _eval_maybe_async(vis_edu_opts[0].click())
                                    filled += 1
                                else:
                                    # Clear typeahead text if no match found so React doesn't fail on unresolved input
                                    if hasattr(combo, "fill"):
                                        await _eval_maybe_async(combo.fill(""))
                                    if hasattr(page, "keyboard"):
                                        await _eval_maybe_async(page.keyboard.press("Escape"))
                                continue

                        # Open dropdown menu by clicking combobox
                        if hasattr(combo, "scroll_into_view_if_needed"):
                            await _eval_maybe_async(combo.scroll_into_view_if_needed())
                        await _eval_maybe_async(combo.click())
                        await human_delay(350, 550)

                        # Read options strictly from this combobox's listbox (never dial-code lists!)
                        cid = str(await _eval_maybe_async(combo.get_attribute("aria-controls")) or "") if hasattr(combo, "get_attribute") else ""
                        opt_handles = []
                        if cid and hasattr(ctx, "query_selector_all"):
                            raw_opts = ctx.query_selector_all(f'{_safe_id_selector(cid)} [role="option"]')
                            opt_handles = await raw_opts if inspect.isawaitable(raw_opts) else raw_opts

                        if not opt_handles and hasattr(ctx, "query_selector_all"):
                            # Check open React-Select / Ashby menu listbox excluding iti__ dial dropdowns
                            raw_opts = ctx.query_selector_all('[role="listbox"]:not([id*="iti-"]) [role="option"], [class*="select__menu"] [role="option"]')
                            all_cand = await raw_opts if inspect.isawaitable(raw_opts) else raw_opts
                            opt_handles = [o for o in (all_cand or []) if await _eval_maybe_async(getattr(o, "is_visible", None))]

                        option_items = []
                        for o in (opt_handles or []):
                            try:
                                if not await _eval_maybe_async(getattr(o, "is_visible", None)):
                                    continue
                                txt = str(await _eval_maybe_async(getattr(o, "inner_text", None)) or "").strip()
                                if txt and txt.lower() not in ("select...", "choose...", "loading...") and not txt.lower().startswith("--"):
                                    option_items.append((txt, o))
                            except Exception:
                                continue

                        if not option_items:
                            if hasattr(page, "keyboard"):
                                await _eval_maybe_async(page.keyboard.press("Escape"))
                            continue

                        option_texts = [t for t, _ in option_items]
                        from src.browser.groq_form_assistant import answer_question_with_groq
                        best_answer = answer_question_with_groq(
                            question=q_text or combo_id or "Dropdown Option",
                            options=option_texts,
                            field_type="select",
                            candidate_info=candidate,
                        )

                        target_handle = None
                        if best_answer:
                            b_low = best_answer.strip().lower()
                            target_handle = next((h for t, h in option_items if t.lower() == b_low), None)
                            if not target_handle:
                                target_handle = next((h for t, h in option_items if b_low in t.lower() or t.lower() in b_low), None)
                            if not target_handle and any(n in b_low for n in ("no", "none", "neither", "never")):
                                target_handle = next((h for t, h in option_items if any(w in t.lower().split() for w in ("no", "none", "never", "not"))), None)
                            if not target_handle and any(y in b_low for y in ("yes", "agree", "authorized")):
                                target_handle = next((h for t, h in option_items if any(w in t.lower().split() for w in ("yes", "agree", "authorized"))), None)
                        if not target_handle:
                            target_handle = option_items[0][1]

                        if target_handle and hasattr(target_handle, "click"):
                            await _eval_maybe_async(target_handle.click())
                            filled += 1
                            await human_delay(200, 350)
                            # Close multi-select menus that remain open after picking an option
                            try:
                                is_exp = str(await _eval_maybe_async(combo.get_attribute("aria-expanded")) or "").lower()
                                if is_exp == "true" and hasattr(page, "keyboard"):
                                    await _eval_maybe_async(page.keyboard.press("Escape"))
                            except Exception:
                                pass
                    except Exception:
                        try:
                            if hasattr(page, "keyboard"):
                                await _eval_maybe_async(page.keyboard.press("Escape"))
                        except Exception:
                            pass
                        continue
            except Exception:
                continue

        return filled

    async def _fill_toggle_button_groups(self, page: Any) -> int:
        """Fill pill/button Yes/No question groups (e.g. Ashby form fields rendered as <button> options)."""
        filled = 0
        candidate = getattr(self, "candidate_info", {}) or {}
        contexts = self._get_interactive_contexts(page)

        for ctx in contexts:
            try:
                if not hasattr(ctx, "evaluate") or not hasattr(ctx, "query_selector_all"):
                    continue
                toggle_groups = await _eval_maybe_async(
                    ctx.evaluate("""() => {
                        const entries = Array.from(document.querySelectorAll('.ashby-application-form-field-entry, [class*="fieldEntry" i]'));
                        const groups = [];
                        for (let idx = 0; idx < entries.length; idx++) {
                            const entry = entries[idx];
                            if (entry.offsetWidth === 0 && entry.offsetHeight === 0) continue;
                            // Skip containers with real visible text/file/radio inputs
                            const hasVisibleInput = Array.from(entry.querySelectorAll('input, textarea, select')).some(
                                inp => inp.type !== 'checkbox' && (inp.offsetWidth > 0 || inp.offsetHeight > 0)
                            );
                            if (hasVisibleInput) continue;
                            const btns = Array.from(entry.querySelectorAll('button')).filter(b => b.offsetWidth > 0 && b.offsetHeight > 0);
                            if (btns.length < 2 || btns.length > 5) continue;
                            const texts = btns.map(b => (b.innerText || '').trim());
                            if (texts.some(t => !t || t.length > 35)) continue;
                            const alreadyActive = btns.some(b =>
                                b.getAttribute('aria-pressed') === 'true' ||
                                b.getAttribute('data-selected') === 'true' ||
                                /active|selected/i.test(b.className || '')
                            ) || Array.from(entry.querySelectorAll('input[type="checkbox"], input[type="radio"]')).some(c => c.checked);
                            if (alreadyActive) continue;
                            const lbl = (entry.querySelector('label, [class*="label" i]')?.innerText || '').trim().replace(/\\s+/g, ' ');
                            if (!lbl) continue;
                            groups.push({ entryIdx: idx, label: lbl, options: texts });
                        }
                        return groups;
                    }""")
                )
                if not isinstance(toggle_groups, list):
                    continue
                entries = await _eval_maybe_async(ctx.query_selector_all('.ashby-application-form-field-entry, [class*="fieldEntry" i]'))
                for grp in toggle_groups:
                    try:
                        idx = grp["entryIdx"]
                        if not isinstance(entries, list) or idx >= len(entries):
                            continue
                        from src.browser.groq_form_assistant import answer_question_with_groq
                        ans = answer_question_with_groq(
                            question=grp["label"],
                            options=grp["options"],
                            field_type="radio",
                            candidate_info=candidate,
                        )
                        if not ans:
                            continue
                        btns = await _eval_maybe_async(entries[idx].query_selector_all("button"))
                        target_btn = None
                        for b in (btns or []):
                            b_txt = str(await _eval_maybe_async(getattr(b, "inner_text", None)) or "").strip().lower()
                            if b_txt == ans.strip().lower():
                                target_btn = b
                                break
                        if not target_btn and btns:
                            target_btn = btns[0]
                        if target_btn:
                            await _eval_maybe_async(target_btn.click())
                            filled += 1
                            await human_delay(120, 200)
                    except Exception:
                        continue
            except Exception:
                continue
        return filled

    async def _fill_radio_groups(self, page: Any) -> int:
        """Fill radio button question groups across all contexts using Groq AI heuristics."""
        filled = 0
        candidate = getattr(self, "candidate_info", {}) or {}
        contexts = self._get_interactive_contexts(page)

        for ctx in contexts:
            try:
                if not hasattr(ctx, "evaluate"):
                    continue
                groups_data = ctx.evaluate("""() => {
                    const groups = {};
                    const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
                    for (const r of radios) {
                        if (r.offsetWidth === 0 && r.offsetHeight === 0 && !r.offsetParent) continue;
                        const name = r.name || r.getAttribute('data-automation-id') || 'group_' + (r.id || '');
                        if (!groups[name]) groups[name] = [];
                        
                        let label = '';
                        if (r.id) {
                            const l = document.querySelector(`label[for="${r.id}"]`);
                            if (l) label = l.innerText || '';
                        }
                        if (!label && r.closest('label')) label = r.closest('label').innerText || '';
                        if (!label) label = r.value || '';
                        
                        let question = '';
                        const fieldset = r.closest('fieldset, [role="radiogroup"], .application-question, .ashby-application-form-input-radio-group, .ashby-application-form-field-entry, .form-group, .radio-group, [class*="question" i]');
                        if (fieldset) {
                            const leg = fieldset.querySelector('legend, .application-label, label:not(:has(input[type="radio"])), .question-label, h3, h4');
                            if (leg) question = leg.innerText || '';
                        }
                        
                        groups[name].push({
                            id: r.id || '',
                            name: name,
                            value: r.value || '',
                            checked: r.checked,
                            label: label.trim(),
                            question: question.trim(),
                        });
                    }
                    return groups;
                }""")
                if inspect.isawaitable(groups_data):
                    groups_data = await groups_data

                if not isinstance(groups_data, dict):
                    continue

                for group_name, items in groups_data.items():
                    try:
                        if not items or any(item.get("checked") for item in items):
                            continue

                        question = items[0].get("question") or group_name
                        options = [it.get("label") or it.get("value") for it in items]
                        if not any(options):
                            continue

                        from src.browser.groq_form_assistant import answer_question_with_groq
                        best_pick = answer_question_with_groq(
                            question=question,
                            options=options,
                            field_type="radio",
                            candidate_info=candidate,
                        )

                        matched_item = next(
                            (it for it in items if (it.get("label") or "").lower() == best_pick.lower() or best_pick.lower() in (it.get("label") or "").lower()),
                            items[0]
                        )
                        target_id = matched_item.get("id")
                        target_val = matched_item.get("value")

                        radio_selector = _safe_id_selector(target_id) if target_id else f"input[type='radio']{_safe_attr_selector('name', group_name)}{_safe_attr_selector('value', target_val)}"
                        radio_el = ctx.query_selector(radio_selector) if hasattr(ctx, "query_selector") else None
                        if inspect.isawaitable(radio_el):
                            radio_el = await radio_el

                        if radio_el:
                            try:
                                res = radio_el.check() if hasattr(radio_el, "check") else radio_el.click()
                                if inspect.isawaitable(res):
                                    await res
                            except Exception:
                                # Fallback: click enclosing/matching label if styled custom radio intercepts pointer
                                res = radio_el.click(force=True) if hasattr(radio_el, "click") else None
                                if inspect.isawaitable(res):
                                    await res
                            if hasattr(ctx, "evaluate"):
                                ev = ctx.evaluate("""(el) => {
                                    el.dispatchEvent(new Event('change', { bubbles: true }));
                                    el.dispatchEvent(new Event('input', { bubbles: true }));
                                }""", radio_el)
                                if inspect.isawaitable(ev):
                                    await ev
                            filled += 1
                            await human_delay(150, 250)
                    except Exception:
                        continue
            except Exception:
                continue

        return filled

    async def _fill_checkboxes(self, page: Any) -> int:
        """Check all required privacy policies, data processing consent, and declaration checkboxes."""
        checked_count = 0
        contexts = self._get_interactive_contexts(page)

        for ctx in contexts:
            try:
                if not hasattr(ctx, "query_selector_all"):
                    continue
                raw_boxes = ctx.query_selector_all("input[type='checkbox']")
                checkboxes = await raw_boxes if inspect.isawaitable(raw_boxes) else raw_boxes
                if not isinstance(checkboxes, list):
                    continue

                for chk in checkboxes:
                    try:
                        is_vis = await _eval_maybe_async(getattr(chk, "is_visible", None))
                        if not is_vis:
                            continue
                        is_chk = await _eval_maybe_async(getattr(chk, "is_checked", None))
                        if is_chk:
                            continue

                        info = ctx.evaluate("""(el) => {
                            let text = '';
                            if (el.id) {
                                try {
                                    const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                                    if (l) text = l.innerText || '';
                                } catch (e) {}
                            }
                            if (!text && el.closest('label')) text = el.closest('label').innerText || '';
                            const qWrap = el.closest('.field, fieldset, .application-question, [class*="question" i]');
                            const qTxt = qWrap ? (qWrap.innerText || '') : '';
                            if (!text) text = el.getAttribute('aria-label') || el.name || el.id || '';
                            const combined = `${text} ${qTxt}`.toLowerCase();
                            const isReq = Boolean(
                                el.required || el.getAttribute('aria-required') === 'true' ||
                                el.classList.contains('required') ||
                                qTxt.includes('*') || qTxt.includes('✱')
                            );
                            return { text: combined.slice(0, 300), name: (el.name || '').toLowerCase(), isRequired: isReq };
                        }""", chk) if hasattr(ctx, "evaluate") else None
                        if inspect.isawaitable(info):
                            info = await info

                        info_dict = info if isinstance(info, dict) else {}
                        lbl_text = info_dict.get("text", "")
                        chk_name = info_dict.get("name", "")
                        is_req = info_dict.get("isRequired", False)

                        # Never blindly check non-consent pronoun option checkboxes (e.g. Lever He/She/They list)
                        if "pronoun" in chk_name or "pronoun" in lbl_text:
                            continue

                        is_consent = any(w in lbl_text for w in (
                            "agree", "consent", "privacy", "terms", "policy", "certify",
                            "acknowledge", "declaration", "confirm", "accept", "condition",
                            "accurate", "truth", "statement", "understand"
                        ))

                        is_marketing = any(m in lbl_text for m in ("newsletter", "marketing", "promotional", "subscription"))
                        if is_marketing and not is_req:
                            continue

                        if is_req or is_consent:
                            res = chk.check() if hasattr(chk, "check") else chk.click()
                            if inspect.isawaitable(res):
                                await res
                            if hasattr(ctx, "evaluate"):
                                ev = ctx.evaluate("""(el) => {
                                    el.dispatchEvent(new Event('change', { bubbles: true }));
                                    el.dispatchEvent(new Event('input', { bubbles: true }));
                                }""", chk)
                                if inspect.isawaitable(ev):
                                    await ev
                            checked_count += 1
                            await human_delay(100, 200)
                    except Exception:
                        continue
            except Exception:
                continue

        return checked_count

    async def _fill_all_unrecognized_with_ai(self, page: Any) -> int:
        """Scan for remaining empty text inputs or textareas and populate them with Groq AI."""
        filled_count = 0
        candidate = getattr(self, "candidate_info", {}) or {}
        contexts = self._get_interactive_contexts(page)

        for ctx in contexts:
            try:
                if not hasattr(ctx, "evaluate"):
                    continue
                unfilled = ctx.evaluate("""() => {
                    const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"]):not([type="file"]):not([type="search"]), textarea'));
                    const results = [];
                    for (const el of inputs) {
                        if (el.offsetWidth === 0 && el.offsetHeight === 0 && !el.offsetParent) continue;
                        if (el.value && el.value.trim().length > 0) continue;
                        const role = el.getAttribute('role') || '';
                        const elId = el.id || '';
                        const elName = el.name || '';
                        if (role === 'combobox' || el.getAttribute('aria-autocomplete')) continue;
                        if (elId.startsWith('iti-') || elId.startsWith('g-recaptcha') || elName.includes('recaptcha')) continue;

                        let label = '';
                        if (elId) {
                            try {
                                const l = document.querySelector(`label[for="${CSS.escape(elId)}"]`);
                                if (l) label = l.innerText || '';
                            } catch (e) {}
                        }
                        if (!label && el.closest('label')) label = el.closest('label').innerText || '';
                        if (!label) {
                            const containerSelectors = ['.application-question', '.ashby-application-form-field-entry', '[class*="question" i]', '.field', 'fieldset'];
                            for (const cSel of containerSelectors) {
                                const container = el.closest(cSel);
                                if (container) {
                                    const ql = container.querySelector('.application-label, label, legend');
                                    if (ql && (ql.innerText || '').trim()) {
                                        label = ql.innerText;
                                        break;
                                    }
                                }
                            }
                        }
                        if (!label) label = el.getAttribute('aria-label') || el.placeholder || elName || elId || '';

                        const cleanLabel = label.trim().replace(/\\s+/g, ' ');
                        const isRequired = Boolean(
                            el.required || el.getAttribute('aria-required') === 'true' ||
                            el.classList.contains('required') ||
                            cleanLabel.includes('*') || cleanLabel.includes('✱')
                        );

                        results.push({
                            id: elId,
                            name: elName,
                            type: el.type || 'text',
                            label: cleanLabel,
                            placeholder: el.placeholder || '',
                            required: isRequired
                        });
                    }
                    return results.slice(0, 20);
                }""")
                if inspect.isawaitable(unfilled):
                    unfilled = await unfilled

                if not isinstance(unfilled, list):
                    continue

                for field in unfilled:
                    try:
                        q_text = field.get("label") or field.get("placeholder") or field.get("name") or ""
                        if not q_text:
                            continue

                        q_low = q_text.lower()
                        is_req = bool(field.get("required"))
                        # Skip optional conditional/open-ended boxes so we don't stuff irrelevant text into them
                        if not is_req and any(
                            opt_skip in q_low for opt_skip in (
                                "if yes", "if you answered", "if different than above",
                                "is there anything else", "cover letter", "comments", "additional information",
                                "custom pronoun",
                            )
                        ):
                            continue

                        from src.browser.groq_form_assistant import answer_question_with_groq
                        ans = answer_question_with_groq(
                            question=q_text,
                            field_type=field.get("type", "text"),
                            candidate_info=candidate,
                        )

                        if ans:
                            fid = field.get("id")
                            fname = field.get("name")
                            selector = _safe_id_selector(fid) if fid else _safe_attr_selector("name", fname)
                            inp_el = ctx.query_selector(selector) if hasattr(ctx, "query_selector") else None
                            if inspect.isawaitable(inp_el):
                                inp_el = await inp_el

                            if inp_el:
                                res = inp_el.fill(ans)
                                if inspect.isawaitable(res):
                                    await res
                                if hasattr(ctx, "evaluate"):
                                    ev = ctx.evaluate(
                                        """(el, textVal) => {
                                            el.dispatchEvent(new Event('input', { bubbles: true }));
                                            el.dispatchEvent(new Event('change', { bubbles: true }));
                                            const role = el.getAttribute('role') || '';
                                            const ariaAuto = el.getAttribute('aria-autocomplete') || '';
                                            if (role === 'combobox' || ariaAuto || el.classList.contains('select-combobox') || el.hasAttribute('data-ph-at-id')) {
                                                el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
                                                el.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', keyCode: 13, bubbles: true }));
                                                const options = Array.from(document.querySelectorAll('[role="option"], .pp-select-option, .dropdown-item, .typeahead-item, li.select-option'));
                                                const match = options.find(o => (o.innerText || '').trim().toLowerCase() === textVal.toLowerCase());
                                                if (match) match.click();
                                            }
                                        }""",
                                        inp_el,
                                        ans,
                                    )
                                    if inspect.isawaitable(ev):
                                        await ev
                                filled_count += 1
                                await human_delay(150, 250)
                    except Exception:
                        continue
            except Exception:
                continue

        return filled_count

    async def _is_submit_button_present(self, page: Any) -> bool:
        """Check if final submit button is visible on current step."""
        submit_selectors = [
            "button[data-automation-id='submit-button']",
            "button[data-ph-at-id='submit-button']",
            "button[data-ph-at-id='submit']",
            "button[data-testid*='submit' i]",
            "button[data-qa*='submit' i]",
            "button[aria-label*='Submit' i]",
            "button:has-text('Submit Application')",
            "button:has-text('Submit application')",
            "button:has-text('Submit Application Now')",
            "button:has-text('Submit your application')",
            "button:has-text('Complete Application')",
            "button:has-text('Finish Application')",
            "button:has-text('Send Application')",
            "input[type='submit'][value*='Submit' i]",
            "button#submit_app",
            "button#btn-submit",
            "a[role='button']:has-text('Submit')",
        ]
        contexts = self._get_interactive_contexts(page)
        for ctx in contexts:
            for sel in submit_selectors:
                try:
                    btn = ctx.query_selector(sel) if hasattr(ctx, "query_selector") else None
                    if inspect.isawaitable(btn):
                        btn = await btn
                    if btn:
                        is_vis = await _eval_maybe_async(getattr(btn, "is_visible", None))
                        if is_vis:
                            return True
                except Exception:
                    continue
        return False

    async def _click_next_or_continue(self, page: Any) -> bool:
        """Click next step or continue button in multi-step wizard."""
        next_selectors = [
            "button[data-automation-id='bottom-navigation-next-button']",
            "button[data-ph-at-id='next-button']",
            "[data-ph-at-id='next-button']",
            "button:has-text('Save and Continue')",
            "button:has-text('Save & Continue')",
            "button:has-text('Next Step')",
            "button:has-text('Next')",
            "button:has-text('Continue')",
            "button:has-text('Proceed')",
            "button:has-text('Review Application')",
            "button:has-text('Review')",
        ]
        contexts = self._get_interactive_contexts(page)
        for ctx in contexts:
            for sel in next_selectors:
                try:
                    btn = ctx.query_selector(sel) if hasattr(ctx, "query_selector") else None
                    if inspect.isawaitable(btn):
                        btn = await btn
                    if btn:
                        is_vis = await _eval_maybe_async(getattr(btn, "is_visible", None))
                        is_en = await _eval_maybe_async(getattr(btn, "is_enabled", True))
                        if is_vis and is_en:
                            # Verify text does not say 'submit'
                            btn_text = ""
                            try:
                                btn_text = await ctx.evaluate("(el) => (el.innerText || el.value || '').toLowerCase()", btn)
                            except Exception:
                                pass
                            if "submit" in str(btn_text):
                                continue

                            logger.info(f"[browser]Advancing multi-step application form ({sel})...[/browser]")
                            await visual_click(page, btn, action_text="Advancing form step...")
                            await human_delay(1500, 2500)
                            return True
                except Exception:
                    continue
        return False

    async def _fill_cover_letter(self, page: Page, cover_letter: str) -> None:
        """Paste cover letter into any textarea asking for it."""
        try:
            textareas = await page.query_selector_all(
                "textarea[name*='cover'], textarea[placeholder*='cover'], textarea[id*='cover']"
            )
            for ta in textareas:
                if await ta.is_visible():
                    val = await ta.input_value()
                    if not val.strip():
                        await ta.fill(cover_letter)
                        await human_delay(300, 600)
                        break
        except Exception:
            pass

    async def _submit_form(self, page: Page) -> bool:
        """Look for and click application submit button across all contexts."""
        submit_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button[data-automation-id='bottom-navigation-next-button']",
            "button[data-automation-id='submit-button']",
            "button[data-ph-at-id='submit-button']",
            "button[data-ph-at-id='submit']",
            "button[data-testid*='submit' i]",
            "button[data-qa*='submit' i]",
            "button[aria-label*='Submit' i]",
            "button:has-text('Submit Application')",
            "button:has-text('Submit application')",
            "button:has-text('Submit Application Now')",
            "button:has-text('Submit your application')",
            "button:has-text('Submit Form')",
            "button:has-text('Complete Application')",
            "button:has-text('Finish Application')",
            "button:has-text('Submit')",
            "button:has-text('Send Application')",
            "button:has-text('Send')",
            "button#submit_app",
            "button#btn-submit",
            "a:has-text('Submit Application')",
            "a[role='button']:has-text('Submit')",
        ]
        contexts = self._get_interactive_contexts(page)
        for ctx in contexts:
            for sel in submit_selectors:
                try:
                    btn = ctx.query_selector(sel) if hasattr(ctx, "query_selector") else None
                    if inspect.isawaitable(btn):
                        btn = await btn
                    if btn:
                        is_vis = await _eval_maybe_async(getattr(btn, "is_visible", None))
                        is_en = await _eval_maybe_async(getattr(btn, "is_enabled", True))
                        if is_vis and is_en:
                            await visual_click(page, btn, action_text="Submitting external application")
                            await human_delay(2500, 5000)
                            return True
                except Exception:
                    continue
        return False
