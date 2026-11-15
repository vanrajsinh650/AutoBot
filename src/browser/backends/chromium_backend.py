"""
Playwright Chromium Browser Backend for AutoBot v2.2.
Preserves existing Chromium lifecycle, persistent profile, session caching,
and Gemini visual cursor overlay as the default, production-hardened backend.
"""

import json
import os
from pathlib import Path
from typing import Optional, Union

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from src.browser.base_backend import BrowserBackend
from src.utils.config import AppConfig, EnvSettings, PROJECT_ROOT, get_config, get_env
from src.utils.human_behavior import CURSOR_OVERLAY_SCRIPT
from src.utils.logger import logger

DEFAULT_SESSION_DIR = PROJECT_ROOT / "data" / "session"
DEFAULT_SESSION_FILE = DEFAULT_SESSION_DIR / "browser_state.json"
DEFAULT_USER_DATA_DIR = DEFAULT_SESSION_DIR / "user_data"


class ChromiumBackend(BrowserBackend):
    """
    Standard Chromium backend powered by Playwright.
    Acts as the primary/default browser backend and automatic fallback.
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

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    @property
    def backend_name(self) -> str:
        return "chromium"

    @property
    def context(self) -> Optional[BrowserContext]:
        return self._context

    @property
    def page(self) -> Optional[Page]:
        return self._page

    @property
    def browser(self) -> Optional[Browser]:
        return self._browser

    @property
    def playwright(self) -> Optional[Playwright]:
        return self._playwright

    async def start(self) -> None:
        """Launch Playwright Chromium with persistent session and domain guard."""
        logger.info(
            f"[browser]🌐 Launching Playwright Chromium backend (headless={self.headless})...[/browser]"
        )
        self._playwright = await async_playwright().start()

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

        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock_file = self.user_data_dir / lock_name
            if lock_file.exists() or lock_file.is_symlink():
                try:
                    lock_file.unlink(missing_ok=True)
                except Exception:
                    pass

        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                headless=self.headless,
                slow_mo=slow_mo,
                args=launch_args,
                viewport={"width": viewport_w, "height": viewport_h},
                user_agent=user_agent,
                locale="en-US",
            )
            self._browser = self._context.browser
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            logger.info(f"[browser]Persistent browser profile active: {self.user_data_dir}[/browser]")
        except Exception as e:
            logger.warning(f"Could not launch persistent context ({e}). Falling back to standard browser launch.")
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                slow_mo=slow_mo,
                args=launch_args,
            )
            if self.session_file.exists():
                try:
                    logger.info(f"[browser]Loading authenticated session from: {self.session_file}[/browser]")
                    self._context = await self._browser.new_context(
                        storage_state=str(self.session_file),
                        viewport={"width": viewport_w, "height": viewport_h},
                        user_agent=user_agent,
                        locale="en-US",
                    )
                except Exception as ex:
                    logger.warning(f"Could not load session state ({ex}); creating clean context.")
                    self._context = await self._browser.new_context(
                        viewport={"width": viewport_w, "height": viewport_h},
                        user_agent=user_agent,
                        locale="en-US",
                    )
            else:
                self._context = await self._browser.new_context(
                    viewport={"width": viewport_w, "height": viewport_h},
                    user_agent=user_agent,
                    locale="en-US",
                )
            self._page = await self._context.new_page()

        # Sync session cookies & localStorage if present
        if self.session_file.exists() and self._context:
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
                        await self._context.add_cookies(clean_cookies)
                        logger.info(f"[browser]Synced {len(clean_cookies)} cookies from {self.session_file.name}[/browser]")
                    except Exception:
                        pass

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
                            await self._context.add_init_script(storage_script)
                        except Exception:
                            pass
            except Exception as ex:
                logger.debug(f"Could not sync session data from session file: {ex}")

        # Inject webdriver evasion & cursor overlay
        await self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        await self._context.add_init_script(CURSOR_OVERLAY_SCRIPT)

        # Policy Gate: Block all network requests targeting LinkedIn domains and subdomains
        async def _block_prohibited_domains(route):
            req_url = route.request.url.lower()
            if "linkedin.com" in req_url or "lnkd.in" in req_url:
                logger.error(f"[browser]HARD POLICY GATE: Blocked request to prohibited domain '{req_url}'.")
                await route.abort("blockedbyclient")
            else:
                await route.continue_()

        try:
            await self._context.route("**/*", _block_prohibited_domains)
        except Exception:
            pass

        logger.info("[browser]✓ Chromium backend initialized successfully with policy guard.[/browser]")

    async def is_healthy(self) -> bool:
        """Check if browser process and page context are alive and responsive."""
        if not self._context or not self._page:
            return False
        try:
            val = await self._page.evaluate("1 + 1")
            return val == 2
        except Exception:
            return False

    async def upload_file(self, page: Page, selector: str, file_path: Union[str, Path]) -> bool:
        """Upload file via Playwright set_input_files, with CDP fallback."""
        path_str = str(Path(file_path).resolve())
        try:
            await page.set_input_files(selector, path_str)
            return True
        except Exception as e:
            logger.debug(f"Standard set_input_files failed ({e}); attempting CDP fallback...")
            try:
                cdp = await page.context.new_cdp_session(page)
                root = await cdp.send("DOM.getDocument")
                node = await cdp.send("DOM.querySelector", {"nodeId": root["root"]["nodeId"], "selector": selector})
                node_id = node.get("nodeId")
                if not node_id:
                    return False
                await cdp.send("DOM.setFileInputFiles", {
                    "files": [path_str],
                    "nodeId": node_id
                })
                await page.evaluate(f"""() => {{
                    const el = document.querySelector('{selector}');
                    if (el) {{
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    }}
                }}""")
                return True
            except Exception as cdp_err:
                logger.warning(f"CDP upload fallback failed: {cdp_err}")
                return False

    async def save_session_state(self, only_if_authenticated: bool = False) -> None:
        """Persist current cookies and storage state to disk, stripping prohibited tokens."""
        if not self._context:
            return

        try:
            try:
                cookies = await self._context.cookies()
                prohibited = [c for c in cookies if c.get("name") == "li_at" or "linkedin.com" in c.get("domain", "").lower()]
                if prohibited:
                    logger.warning("[browser]Stripping prohibited LinkedIn tokens from browser storage state.[/browser]")
                    for c in prohibited:
                        try:
                            await self._context.clear_cookies(name=c.get("name"), domain=c.get("domain"))
                        except Exception:
                            pass
            except Exception:
                pass

            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(self.session_file))
            logger.info(f"[browser]💾 Saved session state to {self.session_file}[/browser]")
        except Exception as e:
            logger.debug(f"Could not save session state: {e}")

    async def close(self) -> None:
        """Gracefully release all browser resources and save session."""
        if self._context:
            try:
                await self.save_session_state(only_if_authenticated=True)
            except Exception:
                pass

        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None

        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        logger.info("[browser]🌐 Chromium backend closed cleanly.[/browser]")
