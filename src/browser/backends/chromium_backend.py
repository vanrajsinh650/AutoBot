"""
Playwright Chromium Browser Backend for AutoBot v2.2.
Preserves existing Chromium lifecycle, persistent profile, session caching,
and Gemini visual cursor overlay as the default, production-hardened backend.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Optional, Union

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from src.browser.base_backend import BrowserBackend
from src.browser.popup_handler import POPUP_AUTO_DISMISS_SCRIPT
from src.utils.config import AppConfig, EnvSettings, PROJECT_ROOT, get_config, get_env
from src.utils.human_behavior import CURSOR_OVERLAY_SCRIPT
from src.utils.logger import logger

DEFAULT_SESSION_DIR = PROJECT_ROOT / "data" / "session"
DEFAULT_SESSION_FILE = DEFAULT_SESSION_DIR / "browser_state.json"
DEFAULT_USER_DATA_DIR = DEFAULT_SESSION_DIR / "user_data"

STEALTH_EVASION_SCRIPT = """
(() => {
  // 1. Remove navigator.webdriver cleanly from prototype without own-property tell
  try {
    const proto = Object.getPrototypeOf(navigator);
    delete proto.webdriver;
    Object.defineProperty(proto, 'webdriver', {
      get: () => undefined,
      enumerable: true,
      configurable: true
    });
  } catch (e) {}

  // 2. Realistic window.chrome object
  if (!window.chrome) {
    window.chrome = {};
  }
  if (!window.chrome.runtime) {
    window.chrome.runtime = { connect: () => {}, sendMessage: () => {}, id: undefined };
  }
  if (!window.chrome.loadTimes) {
    window.chrome.loadTimes = () => ({
      commitLoadTime: Date.now() / 1000,
      connectionInfo: 'h2',
      finishDocumentLoadTime: Date.now() / 1000,
      finishLoadTime: Date.now() / 1000,
      firstPaintAfterLoadTime: 0,
      firstPaintTime: Date.now() / 1000,
      navigationType: 'Other',
      npnNegotiatedProtocol: 'h2',
      requestTime: (Date.now() - 300) / 1000,
      startLoadTime: (Date.now() - 300) / 1000,
      wasAlternateProtocolAvailable: false,
      wasFetchedViaSpdy: true,
      wasNpnNegotiated: true
    });
  }
  if (!window.chrome.csi) {
    window.chrome.csi = () => ({ onloadT: Date.now(), pageT: 200, startE: Date.now() - 200, tran: 15 });
  }
  if (!window.chrome.app) {
    window.chrome.app = {
      isInstalled: false,
      InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
      RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
    };
  }

  // 3. Permissions query spoofing
  try {
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
      parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
    );
  } catch (e) {}

  // 4. Default standard Chrome plugins
  try {
    if (!navigator.plugins || navigator.plugins.length === 0) {
      const makePlugin = (name, description, filename) => {
        const p = Object.create(Plugin.prototype);
        Object.defineProperties(p, {
          name: { value: name, enumerable: true },
          description: { value: description, enumerable: true },
          filename: { value: filename, enumerable: true },
          length: { value: 0, enumerable: true }
        });
        return p;
      };
      const plugins = [
        makePlugin('PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'),
        makePlugin('Chrome PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'),
        makePlugin('Chromium PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'),
        makePlugin('Microsoft Edge PDF Viewer', 'Portable Document Format', 'internal-pdf-viewer'),
        makePlugin('WebKit built-in PDF', 'Portable Document Format', 'internal-pdf-viewer')
      ];
      Object.defineProperty(navigator, 'plugins', {
        get: () => plugins,
        enumerable: true,
        configurable: true
      });
    }
  } catch (e) {}

  // 5. Default natural languages
  try {
    Object.defineProperty(navigator, 'languages', {
      get: () => ['en-US', 'en'],
      enumerable: true,
      configurable: true
    });
  } catch (e) {}
})();
"""


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
        executable_path: Optional[Union[str, Path]] = None,
    ):
        self.cfg = cfg or get_config()
        self.env = env or get_env()
        self.session_file = Path(session_file) if session_file else DEFAULT_SESSION_FILE
        self.session_dir = self.session_file.parent
        self.user_data_dir = Path(user_data_dir) if user_data_dir else (self.session_dir / "user_data")
        self.custom_executable_path = str(executable_path).strip() if executable_path else None

        if headless is not None:
            self.headless = headless
        else:
            self.headless = bool(self.env.headless)

        if not self.headless and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            uid = os.getuid() if hasattr(os, "getuid") else 1000
            if not os.environ.get("XDG_RUNTIME_DIR"):
                user_run = Path(f"/run/user/{uid}")
                if user_run.exists():
                    os.environ["XDG_RUNTIME_DIR"] = str(user_run)
            if Path("/tmp/.X11-unix/X0").exists():
                os.environ["DISPLAY"] = ":0"
            for wsock in Path(f"/run/user/{uid}").glob("wayland-*"):
                if not wsock.name.endswith(".lock"):
                    os.environ["WAYLAND_DISPLAY"] = wsock.name
                    break
            if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                logger.info("[browser]No display server detected; running Chromium in headless mode.[/browser]")
                self.headless = True

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self.active_executable_path: Optional[str] = None

    def _resolve_executable_path(self) -> Optional[str]:
        """
        Locate system Google Chrome, Brave, or custom browser binary if available.
        Prefers real system Google Chrome over testing Chromium for anti-bot evasion and human authenticity.
        """
        # 1. Direct explicit instance argument
        if self.custom_executable_path:
            p = self.custom_executable_path
            if Path(p).exists() or shutil.which(p):
                return p

        # 2. Check explicit env var override or config override
        env_path = (
            getattr(self.env, "browser_executable_path", None)
            or os.environ.get("BROWSER_EXECUTABLE_PATH", "").strip()
            or getattr(getattr(self.cfg, "browser", None), "executable_path", "").strip()
        )
        if env_path and (Path(env_path).exists() or shutil.which(env_path)):
            return env_path

        # 3. Check if user explicitly opted out of system chrome
        use_system_chrome = getattr(self.env, "use_system_chrome", True)
        if os.environ.get("USE_SYSTEM_CHROME", "").lower() in ("false", "0", "no"):
            use_system_chrome = False
        if not use_system_chrome:
            return None

        # 4. Check for system Google Chrome / Brave binaries (Native, Flatpak Host Extra, Debian, Arch, Fedora)
        candidates = [
            # Direct host Google Chrome binary (runs natively with host user-namespace sandbox; eliminates --no-sandbox warning banner)
            "/var/lib/flatpak/app/com.google.Chrome/current/active/files/extra/chrome",
            str(Path.home() / ".local/share/flatpak/app/com.google.Chrome/current/active/files/extra/chrome"),
            shutil.which("google-chrome-stable"),
            shutil.which("google-chrome"),
            "/var/lib/flatpak/exports/bin/com.google.Chrome",
            str(Path.home() / ".local/share/flatpak/exports/bin/com.google.Chrome"),
            "/var/lib/flatpak/app/com.brave.Browser/current/active/files/extra/brave",
            str(Path.home() / ".local/share/flatpak/app/com.brave.Browser/current/active/files/extra/brave"),
            "/var/lib/flatpak/exports/bin/com.brave.Browser",
            str(Path.home() / ".local/share/flatpak/exports/bin/com.brave.Browser"),
            shutil.which("brave-browser"),
            shutil.which("brave"),
            shutil.which("chromium-browser"),
            shutil.which("chromium"),
        ]

        for cand in candidates:
            if cand and (Path(cand).exists() or shutil.which(cand)):
                return cand

        return None

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
        """Launch Playwright Chromium or real Google Chrome with persistent session and domain guard."""
        exec_path = self._resolve_executable_path()
        self.active_executable_path = exec_path
        if exec_path:
            logger.info(
                f"[browser]🌐 Launching real Google Chrome / system browser: {exec_path} (headless={self.headless})...[/browser]"
            )
        else:
            logger.info(
                f"[browser]🌐 Launching Playwright Chromium backend (headless={self.headless})...[/browser]"
            )
        self._playwright = await async_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--test-type",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-breakpad",
            "--disable-component-update",
            "--disable-domain-reliability",
            "--disable-sync",
            "--ozone-platform-hint=auto",
            "--js-flags=--max-old-space-size=512",
            "--renderer-process-limit=2",
        ]

        slow_mo = getattr(self.cfg.browser, "slow_mo", 50) if hasattr(self.cfg, "browser") else 50
        if not self.headless:
            slow_mo = max(slow_mo, 75)
        viewport_w = getattr(self.cfg.browser, "viewport_width", 1280) if hasattr(self.cfg, "browser") else 1280
        viewport_h = getattr(self.cfg.browser, "viewport_height", 800) if hasattr(self.cfg, "browser") else 800

        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock_file = self.user_data_dir / lock_name
            if lock_file.exists() or lock_file.is_symlink():
                try:
                    lock_file.unlink(missing_ok=True)
                except Exception:
                    pass

        persistent_kwargs = {
            "user_data_dir": str(self.user_data_dir),
            "headless": self.headless,
            "slow_mo": slow_mo,
            "args": launch_args,
            "ignore_default_args": ["--enable-automation", "--no-sandbox"],
            "viewport": {"width": viewport_w, "height": viewport_h},
            "locale": "en-US",
        }
        if exec_path:
            persistent_kwargs["executable_path"] = exec_path

        try:
            self._context = await self._playwright.chromium.launch_persistent_context(**persistent_kwargs)
            self._browser = self._context.browser
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            logger.info(f"[browser]Persistent browser profile active: {self.user_data_dir}[/browser]")
        except Exception as e:
            logger.warning(f"Could not launch persistent context ({e}). Falling back to standard browser launch.")
            launch_kwargs = {
                "headless": self.headless,
                "slow_mo": slow_mo,
                "args": launch_args,
                "ignore_default_args": ["--enable-automation", "--no-sandbox"],
            }
            if exec_path:
                launch_kwargs["executable_path"] = exec_path
            try:
                self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            except Exception as e2:
                if exec_path:
                    logger.warning(f"System browser launch failed ({e2}). Falling back to bundled Chromium.")
                    launch_kwargs.pop("executable_path", None)
                    self._browser = await self._playwright.chromium.launch(**launch_kwargs)
                else:
                    raise e2
            if self.session_file.exists():
                try:
                    logger.info(f"[browser]Loading authenticated session from: {self.session_file}[/browser]")
                    self._context = await self._browser.new_context(
                        storage_state=str(self.session_file),
                        viewport={"width": viewport_w, "height": viewport_h},
                        locale="en-US",
                    )
                except Exception as ex:
                    logger.warning(f"Could not load session state ({ex}); creating clean context.")
                    self._context = await self._browser.new_context(
                        viewport={"width": viewport_w, "height": viewport_h},
                        locale="en-US",
                    )
            else:
                self._context = await self._browser.new_context(
                    viewport={"width": viewport_w, "height": viewport_h},
                    locale="en-US",
                )
            self._page = await self._context.new_page()

        # Sync session cookies & localStorage ONLY if session file contains authenticated token (li_at)
        if self.session_file.exists() and self._context:
            try:
                state_data = json.loads(self.session_file.read_text(encoding="utf-8"))
                cookies = state_data.get("cookies", [])
                has_li_at = any(c.get("name") == "li_at" and c.get("value") for c in cookies)
                if not has_li_at:
                    logger.debug("[browser]Session file does not contain authenticated li_at; skipping sync of unverified session.")
                else:
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

        # Inject natural stealth evasions (no custom bot globals or DOM overlays)
        await self._context.add_init_script(STEALTH_EVASION_SCRIPT)

        # Inject automatic contextual sign-in & guest modal dismiss observer
        await self._context.add_init_script(POPUP_AUTO_DISMISS_SCRIPT)

        # Policy Gate: Block network requests to LinkedIn ONLY if strict policy mode is requested
        if os.environ.get("AUTOBOT_STRICT_POLICY") == "1":
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

        logger.info("[browser]✓ Chromium backend initialized successfully.[/browser]")

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
        """Persist current cookies and storage state to disk."""
        if not self._context:
            return

        # If requested only when authenticated, assert li_at exists before overwriting disk state
        if only_if_authenticated and os.environ.get("AUTOBOT_STRICT_POLICY") != "1":
            try:
                cookies = await self._context.cookies()
                has_auth = any(c.get("name") == "li_at" and c.get("value") for c in cookies)
                if not has_auth:
                    logger.debug("[browser]Skipping session save: no active li_at authentication cookie present.[/browser]")
                    return
            except Exception:
                pass

        try:
            if os.environ.get("AUTOBOT_STRICT_POLICY") == "1":
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
