"""
Playwright Browser Lifecycle & Session Manager for AutoBot v2.2.
Provides clean backend delegation between Chromium (default) and Obscura (experimental),
with automatic health-check fallback to Chromium.
"""

import os
from pathlib import Path
from typing import Optional, Union

from playwright.async_api import Browser, BrowserContext, Page, Playwright

from src.application.workflows import LinkedInPolicyViolationError
from src.browser.base_backend import BrowserBackend
from src.browser.backends.chromium_backend import ChromiumBackend, DEFAULT_SESSION_FILE, DEFAULT_USER_DATA_DIR
from src.browser.backends.obscura_backend import ObscuraBackend
from src.utils.config import AppConfig, EnvSettings, get_config, get_env
from src.utils.logger import logger


class BrowserManager:
    """
    Manages browser lifecycle, delegating to ChromiumBackend (default) or ObscuraBackend.
    Enforces automatic fallback to Chromium if Obscura fails startup or health checks.
    """

    def __init__(
        self,
        cfg: Optional[AppConfig] = None,
        env: Optional[EnvSettings] = None,
        session_file: Optional[Path] = None,
        user_data_dir: Optional[Path] = None,
        headless: Optional[bool] = None,
        backend: Optional[str] = None,
        user_id: Optional[int] = None,
        executable_path: Optional[Union[str, Path]] = None,
    ):
        self.cfg = cfg or get_config()
        self.env = env or get_env()
        self.session_file = Path(session_file) if session_file else DEFAULT_SESSION_FILE
        self.session_dir = self.session_file.parent
        self.user_data_dir = Path(user_data_dir) if user_data_dir else DEFAULT_USER_DATA_DIR
        self.user_id = user_id or 1
        self.executable_path = executable_path

        if headless is not None:
            self.headless = headless
        else:
            self.headless = bool(self.env.headless)

        if not self.headless and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            if Path("/tmp/.X11-unix/X0").exists():
                os.environ["DISPLAY"] = ":0"
            if Path("/run/user/1000/wayland-1").exists():
                os.environ["WAYLAND_DISPLAY"] = "wayland-1"
            if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                logger.info("[browser]No display server detected; running Chromium in headless mode.[/browser]")
                self.headless = True

        # Determine requested backend
        resolved_backend = (
            backend
            or getattr(self.env, "browser_backend", None)
            or getattr(getattr(self.cfg, "browser", None), "backend", None)
            or "chromium"
        )
        self.requested_backend = str(resolved_backend).lower().strip()
        self._active_application: bool = False

        # Instantiate backend
        self.backend: BrowserBackend = self._create_backend(self.requested_backend)

    @property
    def is_active_application(self) -> bool:
        return self._active_application

    def set_active_application(self, active: bool) -> None:
        """Mark whether an application workflow is actively in progress."""
        self._active_application = active

    def switch_backend(self, backend_name: str) -> None:
        """
        Switch browser backend. Engine switching during an active application is strictly prohibited.
        """
        if self._active_application:
            raise RuntimeError(
                "Security & Policy Violation: Switching browser engines during an active application is strictly prohibited."
            )
        self.requested_backend = str(backend_name).lower().strip()
        self.backend = self._create_backend(self.requested_backend)

    def _create_backend(self, name: str) -> BrowserBackend:
        """Instantiate backend instance according to name identifier."""
        if name == "obscura":
            return ObscuraBackend(
                cfg=self.cfg,
                env=self.env,
                user_id=self.user_id,
            )
        return ChromiumBackend(
            cfg=self.cfg,
            env=self.env,
            session_file=self.session_file,
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            executable_path=self.executable_path,
        )

    @property
    def backend_name(self) -> str:
        return self.backend.backend_name

    @property
    def context(self) -> Optional[BrowserContext]:
        return self.backend.context

    @context.setter
    def context(self, val: Optional[BrowserContext]) -> None:
        if hasattr(self.backend, "_context"):
            self.backend._context = val

    @property
    def page(self) -> Optional[Page]:
        return self.backend.page

    @page.setter
    def page(self, val: Optional[Page]) -> None:
        if hasattr(self.backend, "_page"):
            self.backend._page = val

    @property
    def browser(self) -> Optional[Browser]:
        return self.backend.browser

    @browser.setter
    def browser(self, val: Optional[Browser]) -> None:
        if hasattr(self.backend, "_browser"):
            self.backend._browser = val

    @property
    def playwright(self) -> Optional[Playwright]:
        return self.backend.playwright

    @playwright.setter
    def playwright(self, val: Optional[Playwright]) -> None:
        if hasattr(self.backend, "_playwright"):
            self.backend._playwright = val

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def start(self) -> None:
        """
        Start browser backend with automatic fallback:
        If Obscura is selected but fails or is unhealthy, falls back seamlessly to Chromium.
        """
        if self.requested_backend == "obscura":
            try:
                await self.backend.start()
                if not await self.backend.is_healthy():
                    raise RuntimeError("Obscura backend health check failed immediately after start.")
                return
            except Exception as e:
                logger.warning(
                    f"[browser]⚠ Obscura backend failed ({e}). Falling back automatically to ChromiumBackend.[/browser]"
                )
                try:
                    await self.backend.close()
                except Exception:
                    pass
                self.backend = self._create_backend("chromium")
                await self.backend.start()
        else:
            await self.backend.start()

    @staticmethod
    def verify_safe_url(url: str) -> None:
        """Assert that a URL does not point to prohibited domains if strict policy is enabled."""
        if os.environ.get("AUTOBOT_STRICT_POLICY") == "1":
            clean = (url or "").lower().strip()
            if "linkedin.com" in clean or "lnkd.in" in clean:
                raise LinkedInPolicyViolationError(
                    f"Compliance Policy Violation: Automated browser navigation to LinkedIn ({clean}) is strictly prohibited."
                )

    async def upload_file(self, page: Page, selector: str, file_path: Union[str, Path]) -> bool:
        """Upload file via backend-appropriate mechanism."""
        return await self.backend.upload_file(page, selector, file_path)

    async def save_session_state(self, only_if_authenticated: bool = False) -> None:
        """Persist current cookies and storage state to disk if supported by backend."""
        if hasattr(self.backend, "save_session_state"):
            await self.backend.save_session_state(only_if_authenticated=only_if_authenticated)

    async def close(self) -> None:
        """Gracefully release all browser resources."""
        await self.backend.close()
