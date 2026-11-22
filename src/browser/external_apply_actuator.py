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

import inspect
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Page

from src.agent.state import JobPosting
from src.application.workflows import AntiBotChallengeDetected, LinkedInPolicyViolationError
from src.memory.form_rag import FormRAG
from src.memory.models import FieldType
from src.utils.config import AppConfig, get_config
from src.utils.human_behavior import human_delay, update_visual_cursor, visual_click
from src.utils.logger import logger


async def _eval_maybe_async(val_or_callable: Any) -> Any:
    """Safely evaluate a property, method, or coroutine without double execution or unawaited warnings."""
    if val_or_callable is None:
        return None
    val = val_or_callable() if callable(val_or_callable) else val_or_callable
    if inspect.isawaitable(val):
        return await val
    return val


def load_candidate_profile_info(cfg: Optional[AppConfig] = None) -> Dict[str, str]:
    """Extract candidate contact details from resume PDF or application configuration."""
    config = cfg or get_config()
    info = {
        "full_name": "Vanraj Solanki",
        "first_name": "Vanraj",
        "last_name": "Solanki",
        "email": "vanrajsolanki2875@gmail.com",
        "phone": "+91-8320452875",
        "phone_clean": "8320452875",
        "country_code": "+91",
        "linkedin": "https://linkedin.com/in/vanrajsinh",
        "github": "https://github.com/vanrajsinh650",
        "portfolio": "https://github.com/vanrajsinh650",
        "location": getattr(config.search, "location", "India"),
        "city": "Ahmedabad",
        "state": "Gujarat",
        "country": "India",
        "postal_code": "380015",
        "street_address": "132 Feet Ring Road",
        "current_company": "Software Engineer",
        "current_title": "Software & Automation Engineer",
        "years_of_experience": "3",
        "notice_period": "Immediate",
        "notice_period_days": "15",
        "education_level": "Bachelor's Degree",
        "degree": "Bachelor of Engineering (B.E.)",
        "university": "Gujarat Technological University",
        "major": "Computer Engineering",
        "gender": "Male",
        "veteran": "No",
        "disability": "No",
        "work_authorization": "Yes",
        "sponsorship_required": "No",
    }
    resume_path = Path(getattr(config.profile, "resume_path", "data/resume/resume.pdf"))
    if resume_path.exists():
        try:
            from src.ingestion.resume_parser import parse_resume
            from src.ingestion.structured_resume import parse_structured_profile
            chunks = parse_resume(resume_path)
            profile_dict = parse_structured_profile(chunks)
            if profile_dict.get("full_name"):
                info["full_name"] = profile_dict["full_name"]
                parts = profile_dict["full_name"].split(maxsplit=1)
                info["first_name"] = parts[0]
                info["last_name"] = parts[1] if len(parts) > 1 else ""
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
            if profile_dict.get("location"):
                info["location"] = profile_dict["location"]
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
                captcha_elem = page.query_selector(
                    "iframe[title*='challenge' i], "
                    "iframe[src*='/bframe'], "
                    "iframe[src*='challenges.cloudflare.com'], "
                    "#challenge-running, #challenge-stage"
                )
                if inspect.isawaitable(captcha_elem):
                    captcha_elem = await captcha_elem
                if captcha_elem:
                    is_vis = captcha_elem.is_visible() if callable(getattr(captcha_elem, "is_visible", None)) else True
                    if inspect.isawaitable(is_vis):
                        is_vis = await is_vis
                    if is_vis:
                        raise AntiBotChallengeDetected(
                            "Interactive anti-bot CAPTCHA/Turnstile challenge element detected in DOM. Halting execution immediately."
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

                # 2. Fill Contact and Personal Fields
                step_filled = await self._fill_contact_fields(tab)
                total_filled_fields += step_filled

                # 3. Fill Dropdowns (<select> and custom comboboxes)
                await self._fill_select_dropdowns(tab)

                # 4. Fill Radio Groups (Work Auth, Visa, Screening questions)
                await self._fill_radio_groups(tab)

                # 5. Fill Required Consent & Privacy Checkboxes
                await self._fill_checkboxes(tab)

                # 6. Fill Cover Letter if textarea present
                if cover_letter:
                    await self._fill_cover_letter(tab, cover_letter)

                # 7. AI Fallback: Map and fill any remaining empty required inputs
                ai_filled = await self._fill_all_unrecognized_with_ai(tab)
                total_filled_fields += ai_filled

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
                # Wait for post-submission transition / AJAX navigation
                await human_delay(3000, 6000)
                # Strictly verify post-submit confirmation on the page!
                verification = await verify_submission_status(tab)
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
        """If the page shows an 'Apply' or 'Apply for this job' button before loading the form, click it."""
        try:
            has_form = await page.query_selector("input[type='file'], input[type='email'], input[name='firstName']")
            if has_form and await has_form.is_visible():
                return

            apply_triggers = [
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
                # Workday
                "a[data-automation-id*='adventureButton']",
                "a[data-automation-id*='applyManually']",
                "button[data-automation-id*='apply']",
                # Common ATS
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
            clicked = False
            for sel in apply_triggers:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
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
                        if groq_btn and await groq_btn.is_visible():
                            await visual_click(page, groq_btn, action_text="Opening application form (Groq AI)...")
                            await human_delay(1500, 2500)
                except Exception as g_err:
                    logger.debug(f"[browser]Groq AI apply trigger error: {g_err}")

            # Wait briefly for form inputs to appear after clicking Apply
            try:
                await page.wait_for_selector(
                    "input[type='file'], input[type='email'], input[name*='name'], input[name='firstName'], textarea",
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
                # 1. Search for standard file inputs
                if hasattr(ctx, "query_selector_all") and callable(ctx.query_selector_all):
                    raw_inputs = ctx.query_selector_all(
                        "input[type='file'][accept*='pdf'], "
                        "input[type='file'][name*='resume' i], "
                        "input[type='file'][name*='cv' i], "
                        "input[type='file']"
                    )
                    file_inputs = await raw_inputs if inspect.isawaitable(raw_inputs) else raw_inputs
                    if isinstance(file_inputs, list):
                        for inp in file_inputs:
                            try:
                                if hasattr(inp, "set_input_files"):
                                    res = inp.set_input_files(resume_full_path)
                                    if inspect.isawaitable(res):
                                        await res
                                    uploaded_any = True
                                    logger.info("[browser]📎 Resume attached via file input element[/browser]")
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
                    try:
                        if hasattr(ctx, "evaluate"):
                            ev = ctx.evaluate("""() => {
                                document.querySelectorAll("input[type='file']").forEach(el => {
                                    el.dispatchEvent(new Event('change', { bubbles: true }));
                                    el.dispatchEvent(new Event('input', { bubbles: true }));
                                });
                            }""")
                            if inspect.isawaitable(ev):
                                await ev
                    except Exception:
                        pass
                    await human_delay(1200, 2000)
                    return True
            except Exception:
                continue

        return uploaded_any

    async def _fill_contact_fields(self, page: Any) -> int:
        """Fill common personal and contact fields across all interactive contexts. Returns count of fields filled."""
        candidate = getattr(self, "candidate_info", {}) or {}
        filled_count = 0
        contexts = self._get_interactive_contexts(page)

        # 1. Full name input
        full_name_selectors = [
            "input[name='name']",
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
                                val_to_fill = ""
                                if self.form_rag:
                                    try:
                                        ans = self.form_rag.answer_question("Full Name", field_type=FieldType.TEXT)
                                        val_to_fill = ans.answer
                                    except Exception:
                                        pass
                                if not val_to_fill:
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

        # 2. Comprehensive fields map (supporting Workday, Phenom, Greenhouse, Lever, Ashby, Taleo)
        fields_map = [
            ("input[name*='first' i], input[placeholder*='First' i], input[data-automation-id*='firstName'], input[data-ph-id*='firstName'], input[name='firstName'], #first_name, #firstname", "First Name", candidate.get("first_name", "Vanraj")),
            ("input[name*='last' i], input[placeholder*='Last' i], input[data-automation-id*='lastName'], input[data-ph-id*='lastName'], input[name='lastName'], #last_name, #lastname", "Last Name", candidate.get("last_name", "Solanki")),
            ("input[type='email'], input[name*='email' i], input[placeholder*='email' i], input[data-automation-id*='email'], input[data-ph-id*='email'], input[name='email'], #email", "Email Address", candidate.get("email", "vanrajsolanki2875@gmail.com")),
            ("input[type='tel'], input[name*='phone' i], input[placeholder*='phone' i], input[data-automation-id*='phone'], input[data-ph-id*='phone'], input[name='phone'], #phone", "Phone Number", candidate.get("phone", "+91-8320452875")),
            ("input[name*='linkedin' i], input[placeholder*='LinkedIn' i], input[id*='linkedin' i], input[data-automation-id*='linkedin']", "LinkedIn Profile URL", candidate.get("linkedin", "https://linkedin.com/in/vanrajsinh")),
            ("input[name*='github' i], input[placeholder*='GitHub' i], input[id*='github' i], input[data-automation-id*='github']", "GitHub URL", candidate.get("github", "https://github.com/vanrajsinh650")),
            ("input[name*='website' i], input[name*='portfolio' i], input[placeholder*='portfolio' i], input[placeholder*='website' i]", "Portfolio URL", candidate.get("portfolio", "https://github.com/vanrajsinh650")),
            ("input[name*='city' i], input[placeholder*='city' i], input[data-automation-id*='addressSection_city'], input[data-ph-id*='city']", "City", candidate.get("city", "Ahmedabad")),
            ("input[name*='location' i], input[placeholder*='location' i]", "Location", candidate.get("location", "India")),
            ("input[name*='postal' i], input[name*='zip' i], input[placeholder*='postal' i], input[placeholder*='zip' i], input[data-automation-id*='postalCode']", "Postal Code", candidate.get("postal_code", "380015")),
            ("input[name*='address' i], input[placeholder*='address' i], input[data-automation-id*='addressSection_addressLine1']", "Address", candidate.get("street_address", "132 Feet Ring Road")),
            ("input[name*='company' i], input[placeholder*='current company' i], input[name='org']", "Current Company", candidate.get("current_company", "Route Mobile Limited")),
            ("input[name*='title' i], input[placeholder*='current title' i]", "Current Title", candidate.get("current_title", "Software & Automation Engineer")),
            ("input[name*='notice' i], input[placeholder*='notice period' i]", "Notice Period", candidate.get("notice_period", "Immediate")),
        ]

        for ctx in contexts:
            for selector_group, question, default_val in fields_map:
                if full_name_filled and question in ("First Name", "Last Name"):
                    continue

                for sel in selector_group.split(", "):
                    try:
                        el = ctx.query_selector(sel.strip()) if hasattr(ctx, "query_selector") else None
                        if inspect.isawaitable(el):
                            el = await el
                        if el:
                            is_vis = await _eval_maybe_async(getattr(el, "is_visible", None))
                            if is_vis:
                                val = await _eval_maybe_async(getattr(el, "input_value", None))
                                if not str(val or "").strip():
                                    val_to_fill = ""
                                    if self.form_rag:
                                        try:
                                            ans = self.form_rag.answer_question(question, field_type=FieldType.TEXT)
                                            val_to_fill = ans.answer
                                        except Exception:
                                            pass
                                    if not val_to_fill:
                                        val_to_fill = default_val
                                    if val_to_fill:
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
                                break
                    except Exception:
                        continue

        # 3. If standard selectors found fewer than 2 fields, invoke Groq AI field mapper
        if filled_count < 2:
            try:
                from src.browser.groq_form_assistant import map_unrecognized_form_fields_with_groq
                ai_mappings = await map_unrecognized_form_fields_with_groq(page, candidate)
                for m in ai_mappings:
                    target_id = m.get("id")
                    val = m.get("fill_value")
                    if target_id and val:
                        inp = await page.query_selector(f"#{target_id}, [name='{target_id}']") if hasattr(page, "query_selector") else None
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
                            matched = next((o for o in opts if o["text"].lower() == best_answer.lower() or best_answer.lower() in o["text"].lower()), None)
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
                        const fieldset = r.closest('fieldset, [role="radiogroup"], .form-group, .radio-group');
                        if (fieldset) {
                            const leg = fieldset.querySelector('legend, label, .question-label, h3, h4');
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

                        radio_selector = f"#{target_id}" if target_id else f"input[type='radio'][name='{group_name}'][value='{target_val}']"
                        radio_el = ctx.query_selector(radio_selector) if hasattr(ctx, "query_selector") else None
                        if inspect.isawaitable(radio_el):
                            radio_el = await radio_el

                        if radio_el:
                            res = radio_el.check() if hasattr(radio_el, "check") else radio_el.click()
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
                                const l = document.querySelector(`label[for="${el.id}"]`);
                                if (l) text = l.innerText || '';
                            }
                            if (!text && el.closest('label')) text = el.closest('label').innerText || '';
                            if (!text) text = el.getAttribute('aria-label') || el.name || el.id || '';
                            const isReq = el.required || el.getAttribute('aria-required') === 'true' || el.classList.contains('required');
                            return { text: text.toLowerCase(), isRequired: isReq };
                        }""", chk) if hasattr(ctx, "evaluate") else None
                        if inspect.isawaitable(info):
                            info = await info

                        info_dict = info if isinstance(info, dict) else {}
                        lbl_text = info_dict.get("text", "")
                        is_req = info_dict.get("isRequired", False)

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
                    const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"]):not([type="file"]), textarea'));
                    const results = [];
                    for (const el of inputs) {
                        if (el.offsetWidth === 0 && el.offsetHeight === 0 && !el.offsetParent) continue;
                        if (el.value && el.value.trim().length > 0) continue;
                        
                        let label = '';
                        if (el.id) {
                            const l = document.querySelector(`label[for="${el.id}"]`);
                            if (l) label = l.innerText || '';
                        }
                        if (!label && el.closest('label')) label = el.closest('label').innerText || '';
                        if (!label) label = el.getAttribute('aria-label') || el.placeholder || el.name || el.id || '';
                        
                        const isRequired = el.required || el.getAttribute('aria-required') === 'true' || el.classList.contains('required');
                        
                        results.push({
                            id: el.id || '',
                            name: el.name || '',
                            type: el.type || 'text',
                            label: label.trim(),
                            placeholder: el.placeholder || '',
                            required: isRequired
                        });
                    }
                    return results.slice(0, 15);
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

                        from src.browser.groq_form_assistant import answer_question_with_groq
                        ans = answer_question_with_groq(
                            question=q_text,
                            field_type=field.get("type", "text"),
                            candidate_info=candidate,
                        )

                        if ans:
                            fid = field.get("id")
                            fname = field.get("name")
                            selector = f"#{fid}" if fid else f"[name='{fname}']"
                            inp_el = ctx.query_selector(selector) if hasattr(ctx, "query_selector") else None
                            if inspect.isawaitable(inp_el):
                                inp_el = await inp_el

                            if inp_el:
                                res = inp_el.fill(ans)
                                if inspect.isawaitable(res):
                                    await res
                                if hasattr(ctx, "evaluate"):
                                    ev = ctx.evaluate("(el) => { el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", inp_el)
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
            "button:has-text('Submit Application')",
            "button:has-text('Submit application')",
            "button:has-text('Submit Application Now')",
            "button:has-text('Send Application')",
            "input[type='submit'][value*='Submit' i]",
            "button#submit_app",
            "button#btn-submit",
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
            "button:has-text('Submit Application')",
            "button:has-text('Submit application')",
            "button:has-text('Submit Application Now')",
            "button:has-text('Submit Form')",
            "button:has-text('Submit')",
            "button:has-text('Send Application')",
            "button#submit_app",
            "button#btn-submit",
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
