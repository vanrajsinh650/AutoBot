"""
LinkedIn Navigation & Search Scraper for AutoBot v2.

Educational Concept:
Automated web navigation requires mimicking human browser interaction patterns:
1. Session Checking & Verification:
   Before attempting search, checks if the session is alive (e.g. on `feed` or `jobs`).
   If unauthenticated, enters credentials with variable typing delays and saves cookies.
2. Structured Query Construction:
   Maps high-level configuration flags into LinkedIn's query parameters:
   - `f_TPR`: Time filter (day = r86400, week = r604800, month = r2592000).
   - `f_LF=f_AL`: LinkedIn Easy Apply filter flag.
   - `f_WT=2`: Remote work flag.
   - `start`: 0-indexed pagination offset (`(page - 1) * 25`).
3. DOM Traversal & Lazy Loading:
   LinkedIn search uses virtualized lists. Scrolling the left-hand job list container
   triggers dynamic DOM rendering of job cards.
"""

import asyncio
import re
from typing import List, Optional

from playwright.async_api import ElementHandle, Page

from src.agent.state import JobPosting
from src.browser.manager import BrowserManager
from src.utils.config import AppConfig, EnvSettings, get_config, get_env
from src.utils.human_behavior import (
    human_delay,
    random_scroll,
    slow_type,
    update_visual_cursor,
    visual_click,
    visual_scroll,
    visual_type,
)
from src.utils.logger import logger


class LinkedInNavigator:
    """
    Automates LinkedIn authentication, search navigation, and job posting extraction.
    """

    BASE_URL = "https://www.linkedin.com"
    LOGIN_URL = "https://www.linkedin.com/login"
    JOBS_URL = "https://www.linkedin.com/jobs/search/"

    def __init__(
        self,
        manager: BrowserManager,
        cfg: Optional[AppConfig] = None,
        env: Optional[EnvSettings] = None,
    ):
        self.manager = manager
        self.cfg = cfg or get_config()
        self.env = env or get_env()

    @property
    def page(self) -> Page:
        if not self.manager.page:
            raise RuntimeError("Browser page not initialized. Call manager.start() first.")
        return self.manager.page

    async def is_authenticated(self) -> bool:
        """Check if currently authenticated by inspecting cookies, URL path, and DOM elements."""
        from urllib.parse import urlparse
        try:
            parsed = urlparse(self.page.url)
            path = parsed.path.lower()
        except Exception:
            path = ""

        # Immediate unauthenticated indicators
        unauth_indicators = ("authwall", "login", "checkpoint", "challenge", "signup", "uas")
        if any(term in path for term in unauth_indicators):
            return False

        # 1. Check for LinkedIn session cookie (li_at)
        try:
            if hasattr(self.page, "context") and hasattr(self.page.context, "cookies"):
                cookies = await self.page.context.cookies()
                if any(c.get("name") == "li_at" and c.get("value") for c in cookies):
                    return True
        except Exception:
            pass

        # 2. Check DOM presence of authenticated navigation bar or profile identity
        try:
            auth_selectors = (
                "nav.global-nav, #global-nav, .global-nav__me-photo, "
                ".feed-identity-module, .profile-rail-card, "
                "button.global-nav__primary-link-me-menu-trigger, "
                "a[data-control-name='nav.settings_signout']"
            )
            count = await self.page.locator(auth_selectors).count()
            if count > 0:
                return True
        except Exception:
            pass

        # 3. Known authenticated page paths without guest authwall / login prompts
        auth_paths = ("/feed", "/mynetwork", "/jobs", "/messaging", "/notifications")
        if any(path.startswith(p) for p in auth_paths):
            try:
                guest_count = await self.page.locator(".authwall-modal, a[href*='/login'], .nav__button-secondary").count()
                if guest_count == 0:
                    return True
            except Exception:
                return True

        return False

    async def ensure_logged_in(self) -> bool:
        """Verify existing session authentication or perform credential login."""
        logger.info("[browser]🔐 Verifying LinkedIn authentication status...[/browser]")
        try:
            await update_visual_cursor(self.page, action_text="Verifying LinkedIn authentication...")
        except Exception:
            pass

        try:
            await self.page.goto(f"{self.BASE_URL}/feed/", wait_until="domcontentloaded", timeout=20000)
            await human_delay(1500, 2500)
        except Exception:
            pass

        # Check if already authenticated
        if await self.is_authenticated():
            logger.info("[browser]✅ Existing authenticated LinkedIn session confirmed.[/browser]")
            try:
                await update_visual_cursor(self.page, action_text="Session authenticated ✓")
            except Exception:
                pass
            await self.manager.save_session_state(only_if_authenticated=True)
            return True

        return await self._login()

    async def _login(self) -> bool:
        """Authenticate using credentials from .env or manual login, and persist session."""
        email = self.env.linkedin_email
        password = self.env.linkedin_password

        # If credentials are not set in .env, open login page and guide user
        if not email or not password:
            logger.info(
                "[browser]🔐 LinkedIn credentials not configured in .env. "
                "Navigating to login page for manual login in the browser window...[/browser]"
            )
            try:
                await update_visual_cursor(self.page, action_text="Navigating to LinkedIn login...")
                await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                pass

            # Point visual cursor to username field to assist user
            try:
                username_el = await self.page.query_selector(
                    "#username, input[name='session_key'], #session_key"
                )
                if username_el:
                    await visual_click(self.page, username_el, action_text="👉 Enter credentials in browser", delay_after=0.5)
            except Exception:
                pass

            logger.info(
                "[browser]👉 Please log into your LinkedIn account in the open Chromium window. "
                "AutoBot will automatically detect your login and save the session (waiting up to 300s)...[/browser]"
            )
            try:
                await update_visual_cursor(self.page, action_text="Waiting for user login...")
            except Exception:
                pass

            for i in range(150):
                await asyncio.sleep(2)
                if await self.is_authenticated():
                    logger.info("[browser]✅ Logged in successfully! Saving session state...[/browser]")
                    try:
                        await update_visual_cursor(self.page, action_text="✅ Logged in! Saving session...")
                    except Exception:
                        pass
                    await asyncio.sleep(1.5)
                    await self.manager.save_session_state(only_if_authenticated=True)
                    return True
                if (i + 1) % 15 == 0:
                    logger.info(f"[browser]⏳ Waiting for LinkedIn login ({300 - (i + 1) * 2}s remaining)...[/browser]")

            logger.error("[browser]❌ Login timeout (300s exceeded). Could not verify LinkedIn authentication.[/browser]")
            return False

        logger.info("[browser]🔐 Navigating to LinkedIn login page...[/browser]")
        try:
            await update_visual_cursor(self.page, action_text="Navigating to login page...")
        except Exception:
            pass
        await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded")
        await human_delay(1000, 2000)

        # Fill username with visual cursor
        user_selectors = ["#username", "input[name='session_key']", "#session_key", "input[type='email']"]
        user_found = False
        for u_sel in user_selectors:
            try:
                u_el = await self.page.query_selector(u_sel)
                if u_el and await u_el.is_visible():
                    await visual_type(self.page, u_el, email, action_text="Entering username...", clear_first=True)
                    user_found = True
                    break
            except Exception:
                pass
        if not user_found:
            await visual_type(self.page, "#username", email, action_text="Entering username...")
        await human_delay(400, 800)

        # Fill password with visual cursor (masked in floating badge)
        pass_selectors = ["#password", "input[name='session_password']", "#session_password", "input[type='password']"]
        pass_found = False
        for p_sel in pass_selectors:
            try:
                p_el = await self.page.query_selector(p_sel)
                if p_el and await p_el.is_visible():
                    await visual_type(self.page, p_el, password, action_text="Entering password...", clear_first=True, is_password=True)
                    pass_found = True
                    break
            except Exception:
                pass
        if not pass_found:
            await visual_type(self.page, "#password", password, action_text="Entering password...", is_password=True)
        await human_delay(400, 800)

        # Submit button with visual cursor
        submit_btn_selectors = [
            'button[type="submit"]',
            'button.sign-in-form__submit-btn',
            'button[data-litms-control-urn*="login-submit"]',
            'button:has-text("Sign in")',
        ]
        btn_clicked = False
        for s_sel in submit_btn_selectors:
            try:
                btn = await self.page.query_selector(s_sel)
                if btn and await btn.is_visible():
                    await visual_click(self.page, btn, action_text="Clicking Sign in...")
                    btn_clicked = True
                    break
            except Exception:
                pass
        if not btn_clicked:
            await self.page.click('button[type="submit"]')

        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        await human_delay(2000, 4000)

        # Handle Challenge / CAPTCHA if prompted
        if any(term in self.page.url for term in ("checkpoint", "challenge", "uas")):
            logger.warning(
                "[browser]⚠ LinkedIn security verification encountered. "
                "Please solve it manually in the browser window (waiting up to 180s)...[/browser]"
            )
            try:
                await update_visual_cursor(self.page, action_text="Security check: please solve verification...")
            except Exception:
                pass
            for _ in range(36):
                await asyncio.sleep(5)
                if await self.is_authenticated():
                    break

        if await self.is_authenticated():
            logger.info("[browser]✅ Logged in successfully! Saving session state...[/browser]")
            try:
                await update_visual_cursor(self.page, action_text="✅ Authentication confirmed!")
            except Exception:
                pass
            await asyncio.sleep(1.5)
            await self.manager.save_session_state(only_if_authenticated=True)
            return True

        logger.error(f"[browser]❌ Login failed. Current URL: {self.page.url}[/browser]")
        return False

    async def open_jobs_section(self) -> None:
        """
        Navigate to the LinkedIn Jobs section using Gemini visual cursor interactions.
        Clicks the top navigation 'Jobs' icon when available; falls back to direct URL.
        """
        from urllib.parse import urlparse
        try:
            parsed = urlparse(self.page.url)
            path = parsed.path.lower()
        except Exception:
            path = ""

        if path.startswith("/jobs"):
            try:
                await update_visual_cursor(self.page, action_text="In LinkedIn Jobs section")
            except Exception:
                pass
            return

        logger.info("[browser]💼 Navigating to Jobs section via top navigation...[/browser]")
        try:
            await update_visual_cursor(self.page, action_text="Navigating to Jobs section...")
        except Exception:
            pass

        jobs_nav_selectors = [
            "a.global-nav__primary-link[href*='/jobs']",
            "nav a[href*='/jobs']",
            "#global-nav a[href*='/jobs']",
            "a[data-test-global-nav-link='jobs']",
            "a[href='https://www.linkedin.com/jobs/']",
        ]

        clicked = False
        for sel in jobs_nav_selectors:
            try:
                link = await self.page.query_selector(sel)
                if link and await link.is_visible():
                    clicked = await visual_click(self.page, link, action_text="Opening Jobs section", delay_after=0.8)
                    if clicked:
                        try:
                            await self.page.wait_for_url("**/jobs**", timeout=12000)
                        except Exception:
                            pass
                        await human_delay(1000, 2000)
                        break
            except Exception:
                continue

        if not clicked or "/jobs" not in self.page.url:
            try:
                await self.page.goto(self.JOBS_URL, wait_until="domcontentloaded", timeout=20000)
                await human_delay(1000, 2000)
            except Exception as e:
                logger.debug(f"Direct jobs navigation fallback: {e}")

        try:
            await update_visual_cursor(self.page, action_text="Jobs section loaded ✓")
        except Exception:
            pass

    def build_search_url(
        self,
        keyword: str,
        location: str = "India",
        page: int = 1,
    ) -> str:
        """Construct the search URL with query filters and pagination offset."""
        params = {
            "keywords": keyword,
            "location": location,
            "start": str((page - 1) * 25),
        }

        # Date posted filter
        date_opt = getattr(self.cfg.search, "date_posted", "week")
        date_map = {"day": "r86400", "week": "r604800", "month": "r2592000"}
        params["f_TPR"] = date_map.get(date_opt, "r604800")

        # Easy Apply filter
        if getattr(self.cfg.search, "easy_apply_only", False):
            params["f_LF"] = "f_AL"

        # Remote work filter
        if getattr(self.cfg.search, "remote", True):
            params["f_WT"] = "2"

        # Experience level filter
        exp_levels = getattr(self.cfg.search, "experience_level", [])
        if exp_levels:
            exp_map = {
                "internship": "1",
                "entry": "2",
                "associate": "3",
                "mid-senior": "4",
                "director": "5",
                "executive": "6",
            }
            codes = [exp_map[e] for e in exp_levels if e in exp_map]
            if codes:
                params["f_E"] = "%2C".join(codes)

        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.JOBS_URL}?{query_string}"

    async def search_jobs(
        self,
        keyword: str,
        location: str = "India",
        page: int = 1,
    ) -> List[JobPosting]:
        """Navigate to search results and extract JobPosting models with Gemini cursor presence."""
        # 1. First ensure we are in the Jobs section through visual navigation
        await self.open_jobs_section()

        # 2. Check for on-screen search inputs for visual typing
        keyword_selectors = [
            "input.jobs-search-box__text-input[aria-label*='Search by title']",
            "input[id*='jobs-search-box-keyword']",
            "input.jobs-search-box__text-input",
            "input[aria-label*='Search by title']",
            "input[placeholder*='title, skill']",
        ]
        location_selectors = [
            "input.jobs-search-box__text-input[aria-label*='City']",
            "input[id*='jobs-search-box-location']",
            "input[aria-label*='City, state']",
            "input[placeholder*='City, state']",
        ]
        search_btn_selectors = [
            "button.jobs-search-box__submit-button",
            "button[type='submit'].jobs-search-box__submit-button",
            "button[type='submit'][aria-label*='Search']",
            "button.jobs-search-box__submit-button:has-text('Search')",
        ]

        kw_elem = None
        loc_elem = None
        btn_elem = None

        for sel in keyword_selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    kw_elem = el
                    break
            except Exception:
                pass

        for sel in location_selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    loc_elem = el
                    break
            except Exception:
                pass

        for sel in search_btn_selectors:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    btn_elem = el
                    break
            except Exception:
                pass

        used_visual_search = False
        if kw_elem and page == 1:
            try:
                logger.info(f"[browser]🔍 Entering search keyword '{keyword}' with visual cursor...[/browser]")
                await visual_type(self.page, kw_elem, keyword, action_text=f"Searching: {keyword}", clear_first=True)
                await human_delay(400, 800)

                if loc_elem and location:
                    logger.info(f"[browser]📍 Entering location '{location}' with visual cursor...[/browser]")
                    await visual_type(self.page, loc_elem, location, action_text=f"Location: {location}", clear_first=True)
                    await human_delay(400, 800)

                if btn_elem:
                    logger.info("[browser]🖱 Clicking Search button with visual cursor...[/browser]")
                    await visual_click(self.page, btn_elem, action_text="Clicking Search", delay_after=1.0)
                elif hasattr(self.page, "keyboard"):
                    await self.page.keyboard.press("Enter")

                try:
                    await self.page.wait_for_load_state("domcontentloaded", timeout=12000)
                except Exception:
                    pass
                await human_delay(1500, 2500)
                used_visual_search = True
            except Exception as ex:
                logger.debug(f"Visual search input error: {ex}")

        # If specific filters or pagination require explicit URL query parameters:
        url = self.build_search_url(keyword, location, page)
        needs_url_nav = not used_visual_search or page > 1 or getattr(self.cfg.search, "easy_apply_only", False)
        if needs_url_nav:
            logger.info(f"[browser]🔍 Searching: '{keyword}' in '{location}' (page {page})...[/browser]")
            try:
                await update_visual_cursor(self.page, action_text=f"Searching: {keyword} ({location})...")
            except Exception:
                pass

            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await human_delay(1500, 2500)
            except Exception as e:
                logger.warning(f"Search navigation warning: {e}")

        # Scroll the job list panel to load cards
        await self._scroll_job_list()

        # Query all job card elements
        card_selectors = [
            "li.jobs-search-results__list-item",
            ".job-card-container",
            "[data-occludable-job-id]",
        ]
        cards: List[ElementHandle] = []
        for sel in card_selectors:
            cards = await self.page.query_selector_all(sel)
            if cards:
                break

        logger.info(f"[browser]Found {len(cards)} job card elements on page {page}.[/browser]")
        try:
            await update_visual_cursor(self.page, action_text=f"Found {len(cards)} jobs on page {page}")
        except Exception:
            pass

        job_postings: List[JobPosting] = []
        for idx, card in enumerate(cards):
            # Visually highlight and interact with top job cards as Gemini agent scans them
            if idx < 6:
                try:
                    await visual_click(self.page, card, action_text=f"Inspecting job #{idx+1}...", delay_after=0.2)
                    await human_delay(200, 400)
                except Exception:
                    pass

            job = await self._parse_job_card(card)
            if job:
                job_postings.append(job)

        return job_postings

    async def _scroll_job_list(self) -> None:
        """Scroll the left-hand job list container with visual cursor to trigger lazy loading."""
        try:
            await update_visual_cursor(self.page, action_text="Scanning job listings...")
        except Exception:
            pass

        panel_selectors = [
            ".jobs-search-results-list",
            ".scaffold-layout__list",
            ".jobs-search__results-list",
        ]
        panel = None
        for sel in panel_selectors:
            try:
                p = await self.page.query_selector(sel)
                if p and await p.is_visible():
                    panel = p
                    break
            except Exception:
                pass

        if panel:
            for _ in range(3):
                await visual_scroll(
                    self.page,
                    distance=450,
                    direction="down",
                    target_element_or_selector=panel,
                    action_text="Scanning job listings...",
                )
                await human_delay(200, 400)
        else:
            await visual_scroll(
                self.page,
                distance=450,
                direction="down",
                action_text="Scanning job listings...",
            )

    async def _parse_job_card(self, card: ElementHandle) -> Optional[JobPosting]:
        """Extract metadata from a single job card element."""
        try:
            # 1. Job ID
            job_id = await card.get_attribute("data-job-id") or ""
            if not job_id:
                job_id = await card.get_attribute("data-occludable-job-id") or ""

            # 2. Title & Link
            title_el = await card.query_selector(
                "a.job-card-list__title, .job-card-container__link, a[href*='/jobs/view/']"
            )
            title = (await title_el.inner_text()).strip() if title_el else "Unknown Title"
            href = (await title_el.get_attribute("href")) if title_el else ""

            if href.startswith("/"):
                url = f"{self.BASE_URL}{href}"
            else:
                url = href

            if not job_id and url:
                match = re.search(r"/jobs/view/(\d+)", url)
                if match:
                    job_id = match.group(1)

            if not job_id:
                return None

            # 3. Company
            company_el = await card.query_selector(
                ".job-card-container__primary-description, "
                ".artdeco-entity-lockup__subtitle, "
                ".job-card-container__company-name"
            )
            company = (await company_el.inner_text()).strip() if company_el else "Unknown Company"

            # 4. Location
            location_el = await card.query_selector(
                ".job-card-container__metadata-item, "
                ".artdeco-entity-lockup__caption, "
                ".job-card-container__metadata-wrapper"
            )
            location = (await location_el.inner_text()).strip() if location_el else ""

            # 5. Easy Apply Check
            easy_badge = await card.query_selector(
                ".job-card-container__apply-method, [aria-label*='Easy Apply'], :text('Easy Apply')"
            )
            is_easy_apply = easy_badge is not None

            # 6. Description Preview
            desc = f"Position: {title} at {company}. Location: {location}."

            return JobPosting(
                job_id=job_id,
                title=title,
                company=company,
                location=location,
                url=url,
                description=desc,
                is_easy_apply=is_easy_apply,
            )
        except Exception:
            return None

    async def fetch_job_details(self, job: JobPosting) -> JobPosting:
        """Navigate to the job details page and scrape the full description text with visual cursor."""
        # 1. First check if details are already rendered in the right-hand panel
        try:
            desc_el = await self.page.query_selector(
                ".jobs-description-content__text, .jobs-box__html-content, #job-details, .jobs-description__content"
            )
            if desc_el and await desc_el.is_visible():
                full_text = (await desc_el.inner_text()).strip()
                if len(full_text) > 80:
                    job.description = full_text
                    await visual_scroll(
                        self.page,
                        distance=300,
                        direction="down",
                        target_element_or_selector=desc_el,
                        action_text=f"Reading: {job.title[:20]}...",
                    )
                    return job
        except Exception:
            pass

        if not job.url:
            return job

        try:
            await update_visual_cursor(self.page, action_text=f"Reading job: {job.title[:20]}...")
        except Exception:
            pass

        try:
            await self.page.goto(job.url, wait_until="domcontentloaded", timeout=15000)
            await human_delay(1000, 2000)

            desc_el = await self.page.query_selector(
                ".jobs-description-content__text, "
                ".jobs-box__html-content, "
                "#job-details, "
                ".jobs-description__content"
            )
            if desc_el:
                await visual_scroll(
                    self.page,
                    distance=350,
                    direction="down",
                    target_element_or_selector=desc_el,
                    action_text=f"Reading details: {job.title[:18]}...",
                )
                full_text = (await desc_el.inner_text()).strip()
                if full_text:
                    job.description = full_text
        except Exception as e:
            logger.debug(f"Could not fetch full job details for {job.job_id}: {e}")

        return job
