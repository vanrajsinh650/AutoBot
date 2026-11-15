"""
Playwright Browser Lifecycle & Stealth Session Manager for AutoBot v2.

Educational Concept:
Autonomous browser interaction requires strict session management and anti-detection engineering:
1. Anti-Bot Stealth Hardening:
   - Sets `--disable-blink-features=AutomationControlled` to hide Chromium automation flags.
   - Injects runtime script removing `navigator.webdriver`.
   - Customizes viewport dimensions (1280x800) and desktop user agent.
2. Session State Persistence:
   Playwright's `storage_state` serializes cookies, local storage, and authentication tokens
   to `data/session/linkedin_state.json`. Reusing this file bypasses recurring two-factor
   authentication and login checkpoints on subsequent executions.
3. Clean Resource Deallocation:
   Implements an asynchronous context manager (`async with BrowserManager(...) as bm:`)
   guaranteeing browser termination even in the event of unhandled exceptions or Ctrl+C signals.
"""

import json
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from src.utils.config import AppConfig, EnvSettings, PROJECT_ROOT, get_config, get_env
from src.utils.human_behavior import CURSOR_OVERLAY_SCRIPT
from src.utils.logger import logger


DEFAULT_SESSION_DIR = PROJECT_ROOT / "data" / "session"
DEFAULT_SESSION_FILE = DEFAULT_SESSION_DIR / "linkedin_state.json"
DEFAULT_USER_DATA_DIR = DEFAULT_SESSION_DIR / "user_data"


class BrowserManager:
    """
    Manages the lifecycle of Playwright Chromium browser, persistent session context,
    and Gemini visual cursor overlay.
    """

    def __init__(
        self,
        cfg: Optional[AppConfig] = None,
        env: Optional[EnvSettings] = None,
        session_file: Optional[Path] = None,
        user_data_dir: Optional[Path] = None,
        headless: Optional[bool] = None,
    ):
        self.cfg = cfg or get_config()
        self.env = env or get_env()
        self.session_file = Path(session_file) if session_file else DEFAULT_SESSION_FILE
        self.session_dir = self.session_file.parent
        self.user_data_dir = Path(user_data_dir) if user_data_dir else (self.session_dir / "user_data")

        if headless is not None:
            self.headless = headless
        else:
            self.headless = bool(self.env.headless)

        if not self.headless and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            logger.info("[browser]No display server detected; running Chromium in headless mode.[/browser]")
            self.headless = True

        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def start(self) -> None:
        """Launch Playwright Chromium with anti-detection args, persistent session, and visual cursor."""
        logger.info(
            f"[browser]🌐 Launching Playwright Chromium (headless={self.headless})...[/browser]"
        )
        self.playwright = await async_playwright().start()

        # Stealth launch arguments
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
        ]

        slow_mo = getattr(self.cfg.browser, "slow_mo", 50) if hasattr(self.cfg, "browser") else 50
        viewport_w = getattr(self.cfg.browser, "viewport_width", 1280) if hasattr(self.cfg, "browser") else 1280
        viewport_h = getattr(self.cfg.browser, "viewport_height", 800) if hasattr(self.cfg, "browser") else 800

        user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        # Clean up stale locks if process crashed previously
        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock_file = self.user_data_dir / lock_name
            if lock_file.exists() or lock_file.is_symlink():
                try:
                    lock_file.unlink(missing_ok=True)
                except Exception:
                    pass

        # Primary approach: Launch persistent browser context (stores all cookies, localStorage, IndexedDB)
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=self.headless,
                slow_mo=slow_mo,
                args=launch_args,
                viewport={"width": viewport_w, "height": viewport_h},
                user_agent=user_agent,
                locale="en-US",
            )
            self.browser = self.context.browser
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            logger.info(f"[browser]Persistent browser profile active: {self.user_data_dir}[/browser]")
        except Exception as e:
            logger.warning(f"Could not launch persistent context ({e}). Falling back to standard browser launch.")
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                slow_mo=slow_mo,
                args=launch_args,
            )
            if self.session_file.exists():
                try:
                    logger.info(f"[browser]Loading authenticated session from: {self.session_file}[/browser]")
                    self.context = await self.browser.new_context(
                        storage_state=str(self.session_file),
                        viewport={"width": viewport_w, "height": viewport_h},
                        user_agent=user_agent,
                        locale="en-US",
                    )
                except Exception as ex:
                    logger.warning(f"Could not load session state ({ex}); creating clean context.")
                    self.context = await self.browser.new_context(
                        viewport={"width": viewport_w, "height": viewport_h},
                        user_agent=user_agent,
                        locale="en-US",
                    )
            else:
                self.context = await self.browser.new_context(
                    viewport={"width": viewport_w, "height": viewport_h},
                    user_agent=user_agent,
                    locale="en-US",
                )
            self.page = await self.context.new_page()

        # If session_file exists, sync cookies and localStorage origins into context
        if self.session_file.exists() and self.context:
            try:
                state_data = json.loads(self.session_file.read_text(encoding="utf-8"))
                cookies = state_data.get("cookies", [])
                clean_cookies = []
                for c in cookies:
                    try:
                        clean_c = {
                            "name": c["name"],
                            "value": c["value"],
                            "domain": c.get("domain") or ".linkedin.com",
                            "path": c.get("path") or "/",
                        }
                        if "expires" in c and c["expires"] is not None:
                            clean_c["expires"] = c["expires"]
                        if "httpOnly" in c:
                            clean_c["httpOnly"] = bool(c["httpOnly"])
                        if "secure" in c:
                            clean_c["secure"] = bool(c["secure"])
                        same_site = c.get("sameSite", "")
                        if same_site in ("Strict", "Lax", "None"):
                            clean_c["sameSite"] = same_site
                            if same_site == "None":
                                clean_c["secure"] = True
                        clean_cookies.append(clean_c)
                    except Exception:
                        continue

                if clean_cookies:
                    try:
                        await self.context.add_cookies(clean_cookies)
                        logger.info(f"[browser]Synced {len(clean_cookies)} cookies from {self.session_file.name}[/browser]")
                    except Exception:
                        synced = 0
                        for ck in clean_cookies:
                            try:
                                await self.context.add_cookies([ck])
                                synced += 1
                            except Exception:
                                pass
                        logger.info(f"[browser]Synced {synced}/{len(clean_cookies)} cookies from {self.session_file.name}[/browser]")

                # Restore localStorage origins
                origins = state_data.get("origins", [])
                for orig in origins:
                    items = orig.get("localStorage", [])
                    if items:
                        storage_script = (
                            "(() => {\n"
                            "  try {\n"
                            f"    const items = {json.dumps(items)};\n"
                            "    for (const item of items) {\n"
                            "      if (!window.localStorage.getItem(item.name)) {\n"
                            "        window.localStorage.setItem(item.name, item.value);\n"
                            "      }\n"
                            "    }\n"
                            "  } catch (e) {}\n"
                            "})();"
                        )
                        try:
                            await self.context.add_init_script(storage_script)
                        except Exception:
                            pass
            except Exception as ex:
                logger.debug(f"Could not sync session data from session file: {ex}")

        # Inject webdriver evasion script
        await self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        # Inject Gemini visual cursor & human interaction overlay script
        await self.context.add_init_script(CURSOR_OVERLAY_SCRIPT)

        logger.info("[browser]✓ Browser window initialized with Gemini visual cursor overlay.[/browser]")

    async def save_session_state(self, only_if_authenticated: bool = False) -> None:
        """Persist current cookies and storage state to disk."""
        if not self.context:
            return

        try:
            if only_if_authenticated and self.session_file.exists():
                try:
                    cookies = await self.context.cookies()
                    has_li_at = any(c.get("name") == "li_at" and c.get("value") for c in cookies)
                    if not has_li_at:
                        logger.debug("Skipping session state save: context missing li_at cookie; preserving existing session.")
                        return
                except Exception:
                    pass

            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            await self.context.storage_state(path=str(self.session_file))
            logger.info(f"[browser]💾 Saved session state to {self.session_file}[/browser]")
        except Exception as e:
            logger.debug(f"Could not save session state: {e}")

    async def close(self) -> None:
        """Gracefully release all browser resources and save session."""
        if self.context:
            try:
                await self.save_session_state(only_if_authenticated=True)
            except Exception:
                pass

        if self.page:
            try:
                await self.page.close()
            except Exception:
                pass
            self.page = None

        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context = None

        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None

        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception:
                pass
            self.playwright = None

        logger.info("[browser]🌐 Browser closed cleanly.[/browser]")
