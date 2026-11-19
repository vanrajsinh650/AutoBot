"""
Playwright-based LinkedIn profile scraper with session persistence and anti-detection.
"""

import asyncio
import os
from pathlib import Path
from typing import List, Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from src.application.workflows import LinkedInPolicyViolationError
from src.ingestion.models import DocumentChunk, IngestionSource, SectionType
from src.utils.config import EnvSettings, PROJECT_ROOT
from src.utils.human_behavior import human_delay, random_scroll, slow_type
from src.utils.logger import console, logger


DEFAULT_SESSION_DIR = PROJECT_ROOT / "data" / "session"
DEFAULT_SESSION_FILE = DEFAULT_SESSION_DIR / "linkedin_state.json"


class LinkedInScraper:
    """
    Automated browser scraper for extracting candidate profile data from LinkedIn.
    """

    def __init__(
        self,
        env: Optional[EnvSettings] = None,
        session_file: Optional[Path] = None,
        headless: Optional[bool] = None,
    ):
        if env is None or os.environ.get("AUTOBOT_STRICT_POLICY") == "1":
            raise LinkedInPolicyViolationError(
                "Compliance Policy Violation: Automated browser scraping, DOM extraction, "
                "and session persistence on LinkedIn is strictly prohibited without configured environment credentials."
            )
        self.env = env
        self.session_file = session_file or DEFAULT_SESSION_FILE
        self.headless = getattr(env, "headless", True) if headless is None else headless

    async def _ensure_authenticated_context(
        self, browser
    ) -> BrowserContext:
        """Create a browser context with existing session storage or perform login."""
        if self.session_file.exists():
            try:
                logger.info(f"Loading LinkedIn session from: {self.session_file}")
                context = await browser.new_context(
                    storage_state=str(self.session_file),
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                return context
            except Exception as e:
                logger.warning(f"Could not restore session ({e}); initializing clean context.")

        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        return context

    async def _login(self, page: Page) -> bool:
        """Log into LinkedIn using email and password, then save session state."""
        email = getattr(self.env, "linkedin_email", None) or os.environ.get("LINKEDIN_EMAIL", "").strip()
        password = getattr(self.env, "linkedin_password", None) or os.environ.get("LINKEDIN_PASSWORD", "").strip()

        if not email or not password:
            logger.warning(
                "LinkedIn credentials not configured (LINKEDIN_EMAIL / LINKEDIN_PASSWORD). "
                "Skipping LinkedIn profile ingestion."
            )
            return False

        logger.info("Navigating to LinkedIn login page...")
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await human_delay(1000, 2500)

        # Check if already authenticated or on feed
        if "feed" in page.url:
            logger.info("Already authenticated on LinkedIn.")
            return True

        logger.info("Entering credentials using humanized typing intervals...")
        await slow_type(page, "input#username", email)
        await human_delay(400, 900)
        await slow_type(page, "input#password", password)
        await human_delay(600, 1200)

        # Click submit button
        submit_btn = await page.query_selector("button[type='submit']")
        if submit_btn:
            await submit_btn.click()
        else:
            await page.keyboard.press("Enter")

        # Wait for navigation / challenge
        await human_delay(2000, 4000)

        # Check for challenge or 2FA checkpoint
        if "checkpoint" in page.url or "challenge" in page.url:
            if self.headless:
                logger.error(
                    "❌ LinkedIn presented a security checkpoint/CAPTCHA in headless mode. "
                    "Run with HEADLESS=false to solve the prompt once and save session."
                )
                return False
            else:
                console.print(
                    "\n[bold yellow]⚠️ LinkedIn Security Checkpoint detected![/bold yellow]\n"
                    "Please solve the verification in the open Chromium browser window...\n"
                    "Waiting up to 90 seconds for resolution..."
                )
                for _ in range(90):
                    await asyncio.sleep(1)
                    if "feed" in page.url or "in/" in page.url or "jobs" in page.url:
                        logger.info("Checkpoint resolved successfully by user!")
                        break

        # Confirm successful login
        if "feed" in page.url or "in/" in page.url or "mynetwork" in page.url or "jobs" in page.url:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            await page.context.storage_state(path=str(self.session_file))
            logger.info(f"Saved authenticated session state to: {self.session_file}")
            return True

        logger.warning(f"LinkedIn login did not navigate to feed (current URL: {page.url}).")
        return False

    async def _extract_profile_data(
        self, page: Page, profile_url: str
    ) -> List[DocumentChunk]:
        """Extract professional sections from a LinkedIn profile page."""
        chunks: List[DocumentChunk] = []

        # 1. Headline / Summary Header
        headline_elem = await page.query_selector(
            "div.text-body-medium, h2.top-card-layout__headline, .pv-text-details__leftpanel .text-body-medium"
        )
        if headline_elem:
            headline_text = (await headline_elem.inner_text()).strip()
            if len(headline_text) > 10:
                chunks.append(
                    DocumentChunk(
                        content=headline_text,
                        source=IngestionSource.LINKEDIN,
                        section=SectionType.SUMMARY,
                        metadata={"type": "headline", "profile_url": profile_url},
                    )
                )

        # 2. About / Bio Section
        about_elem = await page.query_selector(
            "section#about ~ div, section[data-section='about'], div.display-flex.ph5.pv3 span[aria-hidden='true']"
        )
        if about_elem:
            about_text = (await about_elem.inner_text()).strip()
            if len(about_text) > 20:
                chunks.append(
                    DocumentChunk(
                        content=about_text,
                        source=IngestionSource.LINKEDIN,
                        section=SectionType.SUMMARY,
                        metadata={"type": "about", "profile_url": profile_url},
                    )
                )

        # 3. Experience Items
        exp_items = await page.query_selector_all(
            "section#experience ~ div ul li, section[data-section='experience'] ul li, .pvs-list__paged-list-item"
        )
        for item in exp_items:
            text = (await item.inner_text()).strip()
            if len(text) > 30:
                chunks.append(
                    DocumentChunk(
                        content=text,
                        source=IngestionSource.LINKEDIN,
                        section=SectionType.EXPERIENCE,
                        metadata={"source_url": profile_url},
                    )
                )

        # 4. Education Items
        edu_items = await page.query_selector_all(
            "section#education ~ div ul li, section[data-section='education'] ul li"
        )
        for item in edu_items:
            text = (await item.inner_text()).strip()
            if len(text) > 20:
                chunks.append(
                    DocumentChunk(
                        content=text,
                        source=IngestionSource.LINKEDIN,
                        section=SectionType.EDUCATION,
                        metadata={"source_url": profile_url},
                    )
                )

        # 5. Skills Items
        skill_items = await page.query_selector_all(
            "section#skills ~ div ul li, section[data-section='skills'] ul li"
        )
        for item in skill_items:
            text = (await item.inner_text()).strip()
            if len(text) > 5:
                chunks.append(
                    DocumentChunk(
                        content=text,
                        source=IngestionSource.LINKEDIN,
                        section=SectionType.SKILLS,
                        metadata={"source_url": profile_url},
                    )
                )

        return chunks

    async def scrape(self, profile_url: str) -> List[DocumentChunk]:
        """Execute the end-to-end LinkedIn profile scraping workflow."""
        if not profile_url or not profile_url.strip():
            return []

        clean_url = profile_url.strip()
        logger.info(f"Starting LinkedIn profile scrape for: {clean_url}")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--js-flags=--max-old-space-size=512",
                    ],
                )
                context = await self._ensure_authenticated_context(browser)
                page = await context.new_page()

                # Verify if we need to log in
                if not self.session_file.exists():
                    login_success = await self._login(page)
                    if not login_success:
                        logger.warning("Could not establish LinkedIn login; proceeding without LinkedIn data.")
                        await browser.close()
                        return []

                # Navigate to the candidate's profile
                logger.info(f"Navigating to LinkedIn profile: {clean_url}")
                await page.goto(clean_url, wait_until="domcontentloaded")
                await human_delay(1500, 3000)

                if "login" in page.url:
                    logger.info("Session expired; performing fresh login...")
                    login_success = await self._login(page)
                    if login_success:
                        await page.goto(clean_url, wait_until="domcontentloaded")
                        await human_delay(1500, 3000)
                    else:
                        await browser.close()
                        return []

                # Scroll to trigger lazy loading of dynamic sections
                await random_scroll(page, times=3)
                await human_delay(1000, 2000)

                # Extract profile data
                chunks = await self._extract_profile_data(page, clean_url)
                logger.info(f"Extracted {len(chunks)} chunks from LinkedIn profile.")

                await browser.close()
                return chunks

        except Exception as e:
            logger.error(f"Error during LinkedIn profile scraping: {e}")
            return []


async def scrape_linkedin_profile(
    profile_url: Optional[str] = None,
    env: Optional[EnvSettings] = None,
    session_file: Optional[Path] = None,
    headless: Optional[bool] = None,
) -> List[DocumentChunk]:
    """Public API helper to scrape a LinkedIn profile."""
    if env is None or os.environ.get("AUTOBOT_STRICT_POLICY") == "1":
        raise LinkedInPolicyViolationError(
            "Compliance Policy Violation: Automated browser scraping, DOM extraction, "
            "and session persistence on LinkedIn is strictly prohibited without configured environment credentials."
        )

    if not profile_url or not profile_url.strip():
        return []

    scraper = LinkedInScraper(env=env, session_file=session_file, headless=headless)
    return await scraper.scrape(profile_url)
