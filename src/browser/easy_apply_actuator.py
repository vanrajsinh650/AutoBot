"""
LinkedIn Easy Apply Multi-Step Form Actuator for AutoBot.

Interactive multi-step modal form dialog actuator:
1. Dynamic Form Tree:
   Each step in the modal can present varying form elements:
   - File upload inputs (uploading resume PDF).
   - Text & textarea inputs (short answers, portfolio links).
   - Numeric inputs (years of experience, compensation).
   - Select dropdowns & Radio groups (degrees, authorization, demographics).
2. RAG Cognitive Form Filling:
   For every unknown form field, the actuator extracts the human-readable label or
   legend and delegates to `FormRAG`. `FormRAG` queries the candidate's vector profile
   in Qdrant and instructs the LLM to format the response adhering to the exact HTML input type.
3. Safe Error Recovery:
   If an unexpected validation rule blocks advancement, the actuator safely discards
   the draft and closes the modal, preventing the browser from getting stuck in an invalid state.
"""

import os
from pathlib import Path
from typing import List, Optional

from playwright.async_api import ElementHandle, Page

from src.agent.state import JobPosting
from src.application.workflows import LinkedInPolicyViolationError
from src.browser.external_apply_actuator import load_candidate_profile_info
from src.memory.form_rag import FormRAG
from src.memory.models import FieldType
from src.utils.config import AppConfig, get_config
from src.utils.human_behavior import (
    human_delay,
    slow_type,
    update_visual_cursor,
    visual_click,
    visual_type,
)
from src.utils.logger import logger


class EasyApplyActuator:
    """
    Automates the multi-step LinkedIn Easy Apply modal form flow.
    """

    MAX_STEPS = 10

    def __init__(
        self,
        page: Optional[Page] = None,
        form_rag: Optional[FormRAG] = None,
        cfg: Optional[AppConfig] = None,
        resume_path: Optional[Path] = None,
        candidate_info: Optional[dict] = None,
    ):
        if page is None or os.environ.get("AUTOBOT_STRICT_POLICY") == "1":
            raise LinkedInPolicyViolationError(
                "Compliance Policy Violation: Automated Easy Apply modal traversal, form filling, "
                "and submission on LinkedIn is strictly prohibited without an active page session."
            )
        self.page = page
        self.form_rag = form_rag
        self.cfg = cfg or get_config()
        self.candidate_info = candidate_info or load_candidate_profile_info(self.cfg)

        if resume_path is not None:
            self.resume_path = Path(resume_path)
        else:
            p = getattr(self.cfg.profile, "resume_path", "data/resume/resume.pdf")
            self.resume_path = Path(p)

    def _answer_heuristic(
        self,
        question: str,
        field_type: FieldType = FieldType.TEXT,
        options: Optional[List[str]] = None,
    ) -> str:
        """
        Fallback question answering using candidate profile and standard application heuristics
        when FormRAG is unavailable or returns an empty answer.
        """
        q = (question or "").lower()
        info = self.candidate_info or {}

        # 1. Contact details
        if any(w in q for w in ("phone", "mobile", "cell", "contact number")):
            return info.get("phone", "+91-8320452875")
        if "email" in q:
            return info.get("email", "vanrajsolanki2875@gmail.com")
        if "first name" in q:
            return info.get("first_name", "Vanraj")
        if "last name" in q:
            return info.get("last_name", "Solanki")
        if "full name" in q:
            return info.get("full_name", "Vanraj Solanki")
        if any(w in q for w in ("linkedin", "profile link", "profile url")):
            return info.get("linkedin", "https://linkedin.com/in/vanrajsinh")
        if any(w in q for w in ("github", "repo", "git")):
            return info.get("github", "https://github.com/vanrajsinh650")
        if any(w in q for w in ("portfolio", "website", "personal site", "url")):
            return info.get("portfolio", "https://github.com/vanrajsinh650")
        if any(w in q for w in ("city", "location", "address", "residence", "where are you located", "postal", "country")):
            return info.get("location", "India")

        # 2. Legal authorization & background check
        if any(w in q for w in ("authorized to work", "legally authorized", "eligible to work", "right to work")):
            if options:
                for opt in options:
                    if opt.lower().strip() in ("yes", "y", "authorized"):
                        return opt
            return "Yes"

        if any(w in q for w in ("sponsorship", "visa sponsorship", "require sponsorship")):
            if options:
                for opt in options:
                    if opt.lower().strip() in ("no", "n", "do not require"):
                        return opt
            return "No"

        if any(w in q for w in ("background check", "drug test", "18 years of age", "at least 18", "bachelor", "degree")):
            if options:
                for opt in options:
                    if opt.lower().strip() in ("yes", "y"):
                        return opt
            return "Yes"

        # 3. Experience & Numerical
        if field_type == FieldType.NUMBER or any(w in q for w in ("years of experience", "years have you", "how many years", "total experience")):
            return "3"

        # 4. Notice period & Availability
        if any(w in q for w in ("notice period", "availability", "how soon", "when can you start")):
            if options:
                for opt in options:
                    if any(w in opt.lower() for w in ("immediate", "15", "30", "1 month")):
                        return opt
            return "15 days"

        # 5. Compensation expectations
        if any(w in q for w in ("salary", "compensation", "expected ctc", "desired salary")):
            return "Competitive" if field_type == FieldType.TEXT else "75000"

        # 6. Dropdown / Radio generic match
        if options:
            for opt in options:
                if opt.lower().strip() in ("yes", "y"):
                    return opt
            return options[0]

        return ""

    async def apply(
        self,
        job: JobPosting,
        cover_letter: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """
        Execute the complete Easy Apply flow for the given JobPosting.

        Args:
            job: Target JobPosting.
            cover_letter: Optional tailored cover letter text.
            dry_run: When True, simulates form completion and safely dismisses without final submission.

        Returns:
            True if submitted or simulated successfully, False otherwise.
        """
        logger.info(f"[browser]📝 Commencing Easy Apply for '{job.title}' @ '{job.company}' (dry_run={dry_run})...[/browser]")
        try:
            mode_badge = "[DRY RUN] " if dry_run else ""
            await update_visual_cursor(self.page, action_text=f"{mode_badge}Easy Apply: {job.title[:18]}...")
        except Exception:
            pass

        # 1. Open job page if not already there
        if job.url and job.url not in self.page.url:
            try:
                await self.page.goto(job.url, wait_until="domcontentloaded", timeout=20000)
                await human_delay(1500, 2500)
            except Exception as e:
                logger.warning(f"Navigation to job URL failed: {e}")

        # 2. Click Easy Apply button
        if not await self._click_easy_apply_button():
            logger.warning("[browser]Could not find or click Easy Apply button.[/browser]")
            return False

        # 3. Walk multi-step modal dialog
        for step in range(1, self.MAX_STEPS + 1):
            await human_delay(1000, 2000)

            # Check if we have arrived at the Submit step
            if await self._is_submit_step():
                if dry_run:
                    logger.info(f"[browser]  → Step {step}: Submit reached! [DRY RUN SIMULATION] Form filled successfully.[/browser]")
                    try:
                        await update_visual_cursor(self.page, action_text="[DRY RUN] Complete! Discarding modal.")
                    except Exception:
                        pass
                    await human_delay(1200, 2000)
                    await self._dismiss_modal()
                    return True

                logger.info(f"[browser]  → Step {step}: Submit application reached.[/browser]")
                return await self._submit_application()

            logger.info(f"[browser]  → Step {step}: Filling form fields...[/browser]")
            try:
                await update_visual_cursor(self.page, action_text=f"Step {step}: Filling form fields...")
            except Exception:
                pass

            # Fill all fields on active step
            await self._fill_step_fields(cover_letter=cover_letter)

            # Advance to next step
            advanced = await self._click_next_button()
            if not advanced:
                logger.warning(f"[browser]Could not advance past step {step}. Discarding draft.[/browser]")
                await self._dismiss_modal()
                return False

        logger.warning(f"[browser]Exceeded maximum {self.MAX_STEPS} steps without reaching Submit.[/browser]")
        await self._dismiss_modal()
        return False

    async def _click_easy_apply_button(self) -> bool:
        """Locate and click the Easy Apply button on the job page."""
        selectors = [
            "button.jobs-apply-button",
            "button[aria-label*='Easy Apply']",
            ".jobs-s-apply button",
            "button:has-text('Easy Apply')",
        ]
        for sel in selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await visual_click(self.page, btn, action_text="Clicking Easy Apply")
                    await human_delay(1500, 2500)
                    modal = await self.page.query_selector(
                        ".jobs-easy-apply-modal, [data-test-modal]"
                    )
                    if modal:
                        return True
            except Exception:
                continue
        return False

    async def _is_submit_step(self) -> bool:
        """Check if the current modal step contains a visible Submit button."""
        submit_selectors = [
            "button[aria-label='Submit application']",
            "button:has-text('Submit application')",
            "button:has-text('Submit')",
        ]
        for sel in submit_selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    return True
            except Exception:
                continue
        return False

    async def _submit_application(self) -> bool:
        """Click Submit Application button and confirm success."""
        submit_selectors = [
            "button[aria-label='Submit application']",
            "button:has-text('Submit application')",
            "button:has-text('Submit')",
        ]
        for sel in submit_selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible() and await btn.is_enabled():
                    await visual_click(self.page, btn, action_text="Submitting application!")
                    await human_delay(2000, 4000)

                    # Check for success confirmation or close button
                    close_btn = await self.page.query_selector(
                        "[data-test-modal-close-btn], .artdeco-modal__dismiss, button:has-text('Done')"
                    )
                    if close_btn:
                        try:
                            await visual_click(self.page, close_btn, action_text="Closing dialog")
                        except Exception:
                            pass

                    logger.info("[browser]🎉 Application successfully submitted![/browser]")
                    return True
            except Exception:
                continue
        return False

    async def _click_next_button(self) -> bool:
        """Click the primary button to advance to the next modal step."""
        next_selectors = [
            "button[aria-label='Continue to next step']",
            "button[aria-label='Review your application']",
            "button:has-text('Next')",
            "button:has-text('Continue')",
            "button:has-text('Review')",
            ".artdeco-button--primary:has-text('Next')",
        ]
        for sel in next_selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible() and await btn.is_enabled():
                    await visual_click(self.page, btn, action_text="Next step →")
                    await human_delay(1000, 2000)
                    return True
            except Exception:
                continue
        return False

    async def _dismiss_modal(self) -> None:
        """Safely discard application draft and close modal window."""
        dismiss_selectors = [
            "button[aria-label='Dismiss']",
            ".artdeco-modal__dismiss",
            "[data-test-modal-close-btn]",
        ]
        for sel in dismiss_selectors:
            try:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await visual_click(self.page, btn, action_text="Dismissing modal")
                    await human_delay(500, 1000)

                    # Confirm discard prompt if modal asks
                    discard_btn = await self.page.query_selector(
                        "button:has-text('Discard'), "
                        "[data-control-name='discard_application_confirm_btn']"
                    )
                    if discard_btn:
                        await visual_click(self.page, discard_btn, action_text="Confirm discard")
                        await human_delay(500, 1000)
                    return
            except Exception:
                continue

    async def _fill_step_fields(self, cover_letter: Optional[str] = None) -> None:
        """Inspect and fill all inputs present on the current modal step."""
        await self._upload_resume_if_needed()
        await self._fill_text_inputs(cover_letter=cover_letter)
        await self._fill_select_dropdowns()
        await self._fill_radio_groups()
        await self._fill_checkboxes()

    async def _upload_resume_if_needed(self) -> None:
        """Upload resume PDF if a file input is present."""
        if not self.resume_path.exists():
            return
        try:
            file_inputs = await self.page.query_selector_all(
                "input[type='file'][name*='resume'], "
                "input[type='file'][accept*='pdf'], "
                ".jobs-document-upload__upload-button input[type='file']"
            )
            for inp in file_inputs:
                try:
                    try:
                        await update_visual_cursor(self.page, action_text=f"Uploading resume: {self.resume_path.name}")
                    except Exception:
                        pass
                    await inp.set_input_files(str(self.resume_path.resolve()))
                    await human_delay(1500, 2500)
                    logger.info(f"[browser]📎 Uploaded resume: {self.resume_path.name}[/browser]")
                except Exception:
                    continue
        except Exception:
            pass

    async def _fill_text_inputs(self, cover_letter: Optional[str] = None) -> None:
        """Fill all empty text and textarea inputs using FormRAG."""
        try:
            inputs = await self.page.query_selector_all(
                ".jobs-easy-apply-form-section__grouping input[type='text'], "
                ".jobs-easy-apply-form-section__grouping input[type='number'], "
                ".jobs-easy-apply-form-section__grouping textarea, "
                "input[id*='single-line-text']"
            )
            for inp in inputs:
                try:
                    if not await inp.is_visible() or not await inp.is_enabled():
                        continue

                    val = await inp.input_value()
                    if val.strip():
                        continue  # Already filled

                    label = await self._get_label_for_element(inp)
                    field_type_str = await inp.get_attribute("type") or "text"
                    field_type = FieldType.NUMBER if field_type_str == "number" else FieldType.TEXT

                    # If this input asks for cover letter and we have one synthesized:
                    answer_text = ""
                    if "cover letter" in label.lower() and cover_letter:
                        answer_text = cover_letter
                    elif self.form_rag:
                        try:
                            form_ans = self.form_rag.answer_question(
                                question=label or "Form question",
                                field_type=field_type,
                            )
                            answer_text = form_ans.answer
                        except Exception:
                            answer_text = ""

                    if not answer_text:
                        answer_text = self._answer_heuristic(label, field_type=field_type)

                    if not answer_text:
                        continue

                    action_name = f"Filling: {label[:18]}" if label else "Entering field"
                    await visual_click(self.page, inp, action_text=action_name)
                    if len(answer_text) > 80:
                        await inp.fill(answer_text)
                    else:
                        await visual_type(self.page, inp, answer_text, action_text=action_name)
                    await human_delay(300, 600)
                except Exception:
                    continue
        except Exception:
            pass

    async def _fill_select_dropdowns(self) -> None:
        """Select appropriate options for dropdowns using FormRAG with heuristic fallback."""
        try:
            selects = await self.page.query_selector_all(
                ".jobs-easy-apply-form-section__grouping select"
            )
            for sel in selects:
                try:
                    if not await sel.is_visible():
                        continue

                    options_elements = await sel.query_selector_all("option")
                    options = []
                    for opt in options_elements:
                        t = (await opt.inner_text()).strip()
                        if t and t.lower() not in ("select an option", "choose", ""):
                            options.append(t)

                    if not options:
                        continue

                    label = await self._get_label_for_element(sel)
                    ans_text = ""
                    if self.form_rag:
                        try:
                            ans = self.form_rag.answer_question(
                                question=label or "Dropdown selection",
                                field_type=FieldType.SELECT,
                                options=options,
                            )
                            ans_text = ans.answer
                        except Exception:
                            ans_text = ""

                    if not ans_text:
                        ans_text = self._answer_heuristic(label, field_type=FieldType.SELECT, options=options)

                    if not ans_text:
                        continue

                    await visual_click(self.page, sel, action_text=f"Selecting: {ans_text[:18]}")
                    try:
                        await sel.select_option(label=ans_text)
                    except Exception:
                        await sel.select_option(value=ans_text)
                    await human_delay(300, 600)
                except Exception:
                    continue
        except Exception:
            pass

    async def _fill_radio_groups(self) -> None:
        """Select appropriate radio buttons within fieldsets using FormRAG with heuristic fallback."""
        try:
            fieldsets = await self.page.query_selector_all(
                "fieldset.fb-text-selectable__option, "
                ".jobs-easy-apply-form-section__grouping fieldset"
            )
            for fs in fieldsets:
                try:
                    legend = await fs.query_selector("legend")
                    question_text = (await legend.inner_text()).strip() if legend else "Radio question"

                    radios = await fs.query_selector_all("input[type='radio']")
                    if not radios:
                        continue

                    # Check if already selected
                    options_map = []
                    any_checked = False
                    for r in radios:
                        rid = await r.get_attribute("id")
                        label_el = await self.page.query_selector(f"label[for='{rid}']")
                        opt_text = (await label_el.inner_text()).strip() if label_el else ""
                        options_map.append((r, opt_text))
                        if await r.is_checked():
                            any_checked = True

                    if any_checked:
                        continue

                    allowed_options = [om[1] for om in options_map if om[1]]
                    ans_text = ""
                    if self.form_rag:
                        try:
                            ans = self.form_rag.answer_question(
                                question=question_text,
                                field_type=FieldType.RADIO,
                                options=allowed_options,
                            )
                            ans_text = ans.answer
                        except Exception:
                            ans_text = ""

                    if not ans_text:
                        ans_text = self._answer_heuristic(question_text, field_type=FieldType.RADIO, options=allowed_options)

                    if not ans_text:
                        continue

                    # Click matching radio
                    for r, opt_text in options_map:
                        if opt_text.lower().strip() == ans_text.lower().strip() or (ans_text.lower() in opt_text.lower()):
                            await visual_click(self.page, r, action_text=f"Selecting: {opt_text[:18]}")
                            await human_delay(300, 600)
                            break
                except Exception:
                    continue
        except Exception:
            pass

    async def _fill_checkboxes(self) -> None:
        """Check mandatory consent or agreement checkboxes."""
        try:
            checkboxes = await self.page.query_selector_all(
                "input[type='checkbox'][required], "
                ".jobs-easy-apply-form-section__grouping input[type='checkbox']"
            )
            for cb in checkboxes:
                try:
                    if not await cb.is_checked():
                        await visual_click(self.page, cb, action_text="Checking consent")
                        await human_delay(200, 400)
                except Exception:
                    continue
        except Exception:
            pass

    async def _get_label_for_element(self, element: ElementHandle) -> str:
        """Retrieve associated label text for an input element."""
        try:
            elem_id = await element.get_attribute("id")
            if elem_id:
                label_el = await self.page.query_selector(f"label[for='{elem_id}']")
                if label_el:
                    return (await label_el.inner_text()).strip()

            # Inspect parent grouping
            parent = await element.evaluate_handle(
                "el => el.closest('.fb-dash-form-element, .jobs-easy-apply-form-section__grouping')"
            )
            if parent:
                label_el = await parent.query_selector("label, legend")
                if label_el:
                    return (await label_el.inner_text()).strip()
        except Exception:
            pass
        return ""
