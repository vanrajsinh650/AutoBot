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


def load_candidate_profile_info(cfg: Optional[AppConfig] = None) -> Dict[str, str]:
    """Extract candidate contact details from resume PDF or application configuration."""
    config = cfg or get_config()
    info = {
        "full_name": "Vanraj Solanki",
        "first_name": "Vanraj",
        "last_name": "Solanki",
        "email": "vanrajsolanki2875@gmail.com",
        "phone": "+91-8320452875",
        "linkedin": "https://linkedin.com/in/vanrajsinh",
        "github": "https://github.com/vanrajsinh650",
        "portfolio": "https://github.com/vanrajsinh650",
        "location": getattr(config.search, "location", "India"),
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
            if profile_dict.get("linkedin_url"):
                info["linkedin"] = profile_dict["linkedin_url"]
            if profile_dict.get("github_url"):
                info["github"] = profile_dict["github_url"]
            if profile_dict.get("portfolio_url"):
                info["portfolio"] = profile_dict["portfolio_url"]
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
            await self._ensure_application_form_visible(tab)

            # Re-dismiss cookie banners in case opening the form spawned a consent dialog
            await dismiss_cookie_banners(tab, policy=cookie_pol)

            # 1. Upload Resume
            await self._upload_resume(tab)

            # 2. Fill Standard Contact Fields
            await self._fill_contact_fields(tab)

            # 3. Fill Standard Questions (work authorization, sponsorship)
            await self._fill_standard_questions(tab)

            # 4. Fill Cover Letter if textarea present
            if cover_letter:
                await self._fill_cover_letter(tab, cover_letter)

            # Re-check challenges before submission
            await self.check_security_challenges(tab)

            from src.browser.proof_audit import capture_proof_screenshot, verify_submission_status

            # 5. Attempt Submit or Dry-Run Simulation
            if dry_run:
                logger.info(
                    f"[browser]🔍 [Dry-Run] Application form for '{job.title}' @ '{job.company}' "
                    f"completed successfully (simulation mode - not submitted).[/browser]"
                )
                proof_path = await capture_proof_screenshot(tab, job.job_id, job.company, job.title, is_success=True)
                self.last_outcome = {
                    "success": True,
                    "status": "dry_run",
                    "reason_code": "DRY_RUN",
                    "description": "Form auto-filled and validated in simulation mode.",
                    "proof_screenshot": proof_path or "",
                }
                await human_delay(3000, 5000)
                return True

            submitted = await self._submit_form(tab)
            if submitted:
                # Strictly verify post-submit confirmation on the page!
                verification = await verify_submission_status(tab)
                if verification["is_submitted"]:
                    logger.info(f"[browser]✅ Verified external application submission for {job.company}!")
                    proof_path = await capture_proof_screenshot(tab, job.job_id, job.company, job.title, is_success=True)
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
                    blocker_path = await capture_proof_screenshot(tab, job.job_id, job.company, job.title, is_success=False, reason=verification["description"])
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
                blocker_path = await capture_proof_screenshot(tab, job.job_id, job.company, job.title, is_success=False, reason=reason_desc)
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
            has_form = await page.query_selector("input[type='file'], input[type='email']")
            if has_form and await has_form.is_visible():
                return

            apply_triggers = [
                "a[data-automation-id*='adventureButton']",
                "a[data-automation-id*='applyManually']",
                "button[data-automation-id*='apply']",
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
                        break
                except Exception:
                    continue
        except Exception:
            pass

    ALLOWED_RESUME_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}

    async def _upload_resume(self, page: Page) -> None:
        """Upload resume document to any file input element present on page with CDP fallback."""
        if not self.resume_path.exists():
            logger.warning(f"[browser]Resume file not found on disk: {self.resume_path}")
            return

        if self.resume_path.suffix.lower() not in self.ALLOWED_RESUME_EXTENSIONS:
            logger.warning(
                f"[browser]SECURITY POLICY VIOLATION: Blocked attempt to upload unauthorized file type: '{self.resume_path.name}'"
            )
            return
        try:
            file_inputs = await page.query_selector_all(
                "input[type='file'][accept*='pdf'], "
                "input[type='file'][name*='resume'], "
                "input[type='file'][name*='cv'], "
                "input[type='file']"
            )
            resume_full_path = str(self.resume_path.resolve())
            for inp in file_inputs:
                uploaded = False
                try:
                    await inp.set_input_files(resume_full_path)
                    uploaded = True
                except Exception as ex:
                    # CDP fallback for headless engines lacking DOM DataTransfer bindings
                    try:
                        cdp = await page.context.new_cdp_session(page)
                        root = await cdp.send("DOM.getDocument")
                        # Find nodeId of this input element
                        box = await inp.bounding_box()
                        # Fallback query via selector or matching
                        node = await cdp.send("DOM.querySelector", {
                            "nodeId": root["root"]["nodeId"],
                            "selector": "input[type='file']"
                        })
                        node_id = node.get("nodeId")
                        if node_id:
                            await cdp.send("DOM.setFileInputFiles", {
                                "files": [resume_full_path],
                                "nodeId": node_id
                            })
                            await page.evaluate("""() => {
                                const el = document.querySelector("input[type='file']");
                                if (el) {
                                    el.dispatchEvent(new Event('change', { bubbles: true }));
                                    el.dispatchEvent(new Event('input', { bubbles: true }));
                                }
                            }""")
                            uploaded = True
                    except Exception:
                        pass

                if uploaded:
                    await human_delay(1500, 2500)
                    logger.info("[browser]📎 Resume uploaded to external portal[/browser]")
                    break
        except Exception:
            pass

    async def _fill_contact_fields(self, page: Page) -> None:
        """Fill common personal and contact fields."""
        candidate = getattr(self, "candidate_info", {}) or {}

        # 1. Full name input (common on Ashby, Lever, Greenhouse, Workday)
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
        for sel in full_name_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible() and await el.is_enabled():
                    val = await el.input_value()
                    if not val.strip():
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
                            await human_delay(200, 400)
                    full_name_filled = True
                    break
            except Exception:
                continue

        # 2. Field mappings for first/last name and other contact items
        fields_map = [
            ("input[name*='first'], input[placeholder*='First' i], input[data-automation-id*='legalNameSection_firstName'], #first_name, #firstname", "First Name", candidate.get("first_name", "Vanraj")),
            ("input[name*='last'], input[placeholder*='Last' i], input[data-automation-id*='legalNameSection_lastName'], #last_name, #lastname", "Last Name", candidate.get("last_name", "Solanki")),
            ("input[type='email'], input[name*='email'], input[placeholder*='email' i], input[data-automation-id*='email'], #email", "Email Address", candidate.get("email", "vanrajsolanki2875@gmail.com")),
            ("input[type='tel'], input[name*='phone'], input[placeholder*='phone' i], input[data-automation-id*='phone'], #phone", "Phone Number", candidate.get("phone", "+91-8320452875")),
            ("input[name*='linkedin'], input[placeholder*='LinkedIn' i], input[id*='linkedin'], input[data-automation-id*='linkedin']", "LinkedIn Profile URL", candidate.get("linkedin", "https://linkedin.com/in/vanrajsinh")),
            ("input[name*='github'], input[placeholder*='GitHub' i], input[id*='github'], input[data-automation-id*='github']", "GitHub URL", candidate.get("github", "https://github.com/vanrajsinh650")),
            ("input[name*='website'], input[name*='portfolio'], input[placeholder*='portfolio' i], input[placeholder*='website' i]", "Portfolio URL", candidate.get("portfolio", "https://github.com/vanrajsinh650")),
            ("input[name*='location'], input[placeholder*='location' i], input[placeholder*='city' i], input[data-automation-id*='addressSection_city']", "Location", candidate.get("location", "India")),
        ]

        for selector_group, question, default_val in fields_map:
            # Skip first/last name if full name already filled
            if full_name_filled and question in ("First Name", "Last Name"):
                continue

            for sel in selector_group.split(", "):
                try:
                    el = await page.query_selector(sel.strip())
                    if el and await el.is_visible() and await el.is_enabled():
                        val = await el.input_value()
                        if not val.strip():
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
                                await human_delay(200, 400)
                        break
                except Exception:
                    continue

    async def _fill_standard_questions(self, page: Page) -> None:
        """Fill common standard ATS screening and compliance questions."""
        # 1. Work Authorization & Sponsorship Radio Buttons
        try:
            auth_radios = await page.query_selector_all("input[type='radio'][value*='yes' i], input[type='radio'][value='1']")
            for r in auth_radios:
                try:
                    name = (await r.get_attribute("name") or "").lower()
                    if any(k in name for k in ("authoriz", "legal", "eligible", "work_auth")):
                        if not await r.is_checked():
                            await r.check()
                except Exception:
                    pass

            spons_radios = await page.query_selector_all("input[type='radio'][value*='no' i], input[type='radio'][value='0']")
            for r in spons_radios:
                try:
                    name = (await r.get_attribute("name") or "").lower()
                    if any(k in name for k in ("sponsor", "visa")):
                        if not await r.is_checked():
                            await r.check()
                except Exception:
                    pass
        except Exception:
            pass

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
        """Look for and click application submit button."""
        submit_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "button[data-automation-id='bottom-navigation-next-button']",
            "button[data-automation-id='submit-button']",
            "button:has-text('Submit Application')",
            "button:has-text('Submit application')",
            "button:has-text('Submit')",
            "button:has-text('Apply')",
            "button:has-text('Send Application')",
        ]
        for sel in submit_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible() and await btn.is_enabled():
                    await visual_click(page, btn, action_text="Submitting external application")
                    await human_delay(2500, 5000)
                    return True
            except Exception:
                continue
        return False
