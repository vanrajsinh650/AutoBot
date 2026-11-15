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
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Page

from src.agent.state import JobPosting
from src.application.workflows import AntiBotChallengeDetected, LinkedInPolicyViolationError
from src.memory.form_rag import FormRAG
from src.memory.models import FieldType
from src.utils.config import AppConfig, get_config
from src.utils.human_behavior import human_delay, update_visual_cursor, visual_click
from src.utils.logger import logger


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
        "smartrecruiters.com",
        "workable.com",
        "bamboohr.com",
        "rippling-ats.com",
        "icims.com",
    ]

    CHALLENGE_PATTERNS = [
        "challenge", "cf-challenge", "challenge-platform", "turnstile", "hcaptcha", "recaptcha",
        "captcha", "perimeterx", "datadome", "checkpoint", "authwall", "cloudflare"
    ]

    CHALLENGE_TEXTS = [
        "verify you are human", "security check", "robot or human", "access denied",
        "attention required", "cloudflare", "two-factor authentication", "2fa", "mfa"
    ]

    def __init__(
        self,
        context: BrowserContext,
        form_rag: FormRAG,
        cfg: Optional[AppConfig] = None,
        resume_path: Optional[Path] = None,
        authorized_domains: Optional[list] = None,
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
            raise ValueError(
                f"Domain '{hostname}' is not authorized for automated ATS application. "
                f"Authorized ATS platforms: {', '.join(self.authorized_domains)}"
            )

        return hostname

    async def check_security_challenges(self, page: Page) -> None:
        """
        Check page URL and content for anti-bot challenges, CAPTCHAs, or MFA walls.
        Halts immediately without attempting bypass.
        """
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
            for text in self.CHALLENGE_TEXTS:
                if text in title:
                    raise AntiBotChallengeDetected(
                        f"Anti-bot challenge gate detected in title '{title}'. Halting execution immediately."
                    )

            if hasattr(page, "evaluate") and callable(page.evaluate):
                body_eval = page.evaluate("() => (document.body ? document.body.innerText.slice(0, 2000).toLowerCase() : '')")
                if inspect.isawaitable(body_eval):
                    body_eval = await body_eval
                body_str = str(body_eval or "").lower()
                for text in self.CHALLENGE_TEXTS:
                    if text in body_str:
                        raise AntiBotChallengeDetected(
                            "Anti-bot verification challenge detected on page. Halting execution immediately."
                        )
        except AntiBotChallengeDetected:
            raise
        except Exception:
            pass

    async def apply(
        self,
        job: JobPosting,
        apply_url: Optional[str] = None,
        cover_letter: Optional[str] = None,
    ) -> bool:
        """
        Open the external application URL and attempt automated submission.

        Args:
            job: The target JobPosting.
            apply_url: External career page URL (defaults to job.external_apply_url or job.url).
            cover_letter: Optional cover letter text.

        Returns:
            True if submitted successfully, False otherwise.
        """
        target_url = apply_url or job.external_apply_url or job.url
        if not target_url:
            logger.warning("[browser]No external apply URL available.[/browser]")
            return False

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
            await human_delay(2000, 3500)

            # Check for security challenges / CAPTCHA gates
            await self.check_security_challenges(tab)

            # 1. Upload Resume
            await self._upload_resume(tab)

            # 2. Fill Standard Contact Fields
            await self._fill_contact_fields(tab)

            # 3. Fill Cover Letter if textarea present
            if cover_letter:
                await self._fill_cover_letter(tab, cover_letter)

            # Re-check challenges before submission
            await self.check_security_challenges(tab)

            # 4. Attempt Submit
            submitted = await self._submit_form(tab)
            if submitted:
                logger.info("[browser]✅ External application submitted successfully![/browser]")
            else:
                logger.info("[browser]⚠ External portal submission requires manual verification.[/browser]")
            return submitted

        except AntiBotChallengeDetected as abc:
            logger.error(f"[browser]🛑 Anti-bot challenge: {abc}. Halting submission cleanly.[/browser]")
            raise
        except LinkedInPolicyViolationError:
            raise
        except Exception as e:
            logger.warning(f"External apply error: {e}")
            return False
        finally:
            try:
                await tab.close()
            except Exception:
                pass

    async def _upload_resume(self, page: Page) -> None:
        """Upload resume PDF to any file input element present on page with CDP fallback."""
        if not self.resume_path.exists():
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
        fields_map = [
            ("input[name*='first'], input[placeholder*='First']", "First Name"),
            ("input[name*='last'], input[placeholder*='Last']", "Last Name"),
            ("input[name*='email'], input[type='email']", "Email Address"),
            ("input[name*='phone'], input[type='tel']", "Phone Number"),
            ("input[name*='linkedin'], input[placeholder*='LinkedIn']", "LinkedIn Profile URL"),
            ("input[name*='github'], input[placeholder*='GitHub']", "GitHub URL"),
            ("input[name*='website'], input[placeholder*='Portfolio']", "Portfolio URL"),
        ]

        for selector_group, question in fields_map:
            for sel in selector_group.split(", "):
                try:
                    el = await page.query_selector(sel.strip())
                    if el and await el.is_visible() and await el.is_enabled():
                        val = await el.input_value()
                        if not val.strip():
                            ans = self.form_rag.answer_question(question, field_type=FieldType.TEXT)
                            if ans.answer:
                                await el.fill(ans.answer)
                                await human_delay(200, 400)
                        break
                except Exception:
                    continue

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
            "button:has-text('Submit Application')",
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
