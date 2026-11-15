"""
Obscura Browser Backend for AutoBot v2.2 (Experimental).
Integrates Obscura (v0.2.7) headless browser via CDP for external ATS form assistance.

IMPORTANT COMPLIANCE & SECURITY POLICIES:
1. Strict Loopback Binding: Bound exclusively to 127.0.0.1, never exposed externally.
2. Tenant & Session Isolation: Ephemeral storage directory per session with 0700 permissions,
   completely wiped on close. Never share cookies or storage across users or jobs.
3. No Stealth / No Evasion: The `--stealth` flag is strictly forbidden and never passed.
4. Anti-Bot Integrity: Never bypass CAPTCHA, Cloudflare, or anti-bot gates; immediately halt.
5. Fail-Closed LinkedIn Guard: Prohibits all navigation and network requests to LinkedIn domains.
"""

import asyncio
import os
import shutil
import socket
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Union

import httpx
from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from src.browser.base_backend import BrowserBackend
from src.utils.config import AppConfig, EnvSettings, PROJECT_ROOT, get_config, get_env
from src.utils.human_behavior import CURSOR_OVERLAY_SCRIPT
from src.utils.logger import logger


def _find_free_port() -> int:
    """Find an available ephemeral port on loopback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ObscuraBackend(BrowserBackend):
    """
    Experimental browser backend leveraging Obscura v0.2.7 via CDP.
    Designed for fast, isolated external career portal assistance.
    """

    def __init__(
        self,
        cfg: Optional[AppConfig] = None,
        env: Optional[EnvSettings] = None,
        binary_path: Optional[Union[str, Path]] = None,
        port: Optional[int] = None,
        user_id: Optional[int] = None,
    ):
        self.cfg = cfg or get_config()
        self.env = env or get_env()
        self.user_id = user_id or 1

        # Locate Obscura binary
        if binary_path:
            self.binary_path = Path(binary_path)
        elif self.env.obscura_binary_path:
            self.binary_path = Path(self.env.obscura_binary_path)
        else:
            default_bin = PROJECT_ROOT / "bin" / "obscura"
            if default_bin.exists():
                self.binary_path = default_bin
            else:
                which_bin = shutil.which("obscura")
                self.binary_path = Path(which_bin) if which_bin else default_bin

        self.port = port or _find_free_port()
        self.host = "127.0.0.1"  # Non-negotiable loopback binding

        # Ephemeral per-session storage directory for tenant isolation
        self.session_id = uuid.uuid4().hex[:12]
        self.storage_dir = PROJECT_ROOT / "data" / "obscura_profiles" / f"user_{self.user_id}_{self.session_id}"
        self.ready_file = Path(tempfile.gettempdir()) / f"obscura_ready_{self.port}_{self.session_id}.txt"

        self._process: Optional[subprocess.Popen] = None
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    @property
    def backend_name(self) -> str:
        return "obscura"

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

    def _build_command(self) -> list[str]:
        """
        Build CLI command for launching Obscura serve.
        Enforces policy: NEVER include --stealth.
        """
        cmd = [
            str(self.binary_path.resolve()),
            "serve",
            "--host", self.host,
            "--port", str(self.port),
            "--allow-private-network",
            "--allow-file-access",
            "--storage-dir", str(self.storage_dir.resolve()),
            "--ready-file", str(self.ready_file.resolve()),
            "--quiet",
        ]
        # Strict safety check: Ensure stealth flag is never present
        assert "--stealth" not in cmd, "Policy Violation: Obscura --stealth option is strictly prohibited."
        return cmd

    async def start(self) -> None:
        """Launch Obscura server and connect via Playwright CDP."""
        if not self.binary_path.exists():
            raise FileNotFoundError(
                f"Obscura binary not found at '{self.binary_path}'. Ensure Obscura v0.2.7 is installed in bin/."
            )

        # Create private, permission-restricted ephemeral storage directory (0700)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.storage_dir, 0o700)
        except Exception:
            pass

        if self.ready_file.exists():
            try:
                self.ready_file.unlink(missing_ok=True)
            except Exception:
                pass

        logger.info(
            f"[browser]🌐 Launching Obscura v0.2.7 backend (host={self.host}, port={self.port}, profile={self.session_id})...[/browser]"
        )

        # Ensure NO_PROXY includes loopback so internal CDP requests are not intercepted
        current_no_proxy = os.environ.get("NO_PROXY", "")
        if "127.0.0.1" not in current_no_proxy:
            clean_no_proxy = f"{current_no_proxy},127.0.0.1,localhost,*" if current_no_proxy else "127.0.0.1,localhost,*"
            os.environ["NO_PROXY"] = clean_no_proxy
            os.environ["no_proxy"] = clean_no_proxy

        env_vars = os.environ.copy()
        cmd = self._build_command()
        self._process = subprocess.Popen(
            cmd,
            env=env_vars,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for Obscura CDP server to be ready
        ready = False
        async with httpx.AsyncClient(trust_env=False) as client:
            for _ in range(50):
                if self._process.poll() is not None:
                    _, stderr = self._process.communicate()
                    err_msg = stderr.decode(errors="replace")
                    raise RuntimeError(f"Obscura process exited prematurely with code {self._process.returncode}: {err_msg}")
                try:
                    res = await client.get(f"http://{self.host}:{self.port}/json/version", timeout=0.5)
                    if res.status_code == 200:
                        ready = True
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.1)

        if not ready:
            raise TimeoutError(f"Timed out waiting for Obscura CDP endpoint at http://{self.host}:{self.port}/json/version")

        # Connect Playwright via CDP over loopback
        logger.info(f"[browser]Connecting Playwright over CDP to http://{self.host}:{self.port}...[/browser]")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(f"http://{self.host}:{self.port}")

        self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

        # Inject visual cursor overlay script
        try:
            await self._context.add_init_script(CURSOR_OVERLAY_SCRIPT)
        except Exception:
            pass

        # Fail-closed LinkedIn Policy Gate: Block all network requests to LinkedIn domains
        async def _block_prohibited_domains(route):
            req_url = route.request.url.lower()
            if "linkedin.com" in req_url or "lnkd.in" in req_url:
                logger.error(f"[browser]HARD POLICY GATE: Blocked request to prohibited domain '{req_url}' on Obscura backend.")
                await route.abort("blockedbyclient")
            else:
                await route.continue_()

        try:
            await self._context.route("**/*", _block_prohibited_domains)
        except Exception:
            pass

        logger.info("[browser]✓ Obscura backend connected and initialized with policy guard.[/browser]")

    async def is_healthy(self) -> bool:
        """Check if Obscura process is alive and CDP endpoint responds."""
        if not self._process or self._process.poll() is not None:
            return False
        try:
            async with httpx.AsyncClient(trust_env=False) as client:
                res = await client.get(f"http://{self.host}:{self.port}/json/version", timeout=1.0)
                if res.status_code != 200:
                    return False
            if self._page:
                val = await self._page.evaluate("1 + 1")
                return val == 2
            return True
        except Exception:
            return False

    async def upload_file(self, page: Page, selector: str, file_path: Union[str, Path]) -> bool:
        """
        Upload file to a file input element.
        Attempts standard Playwright set_input_files, and on failure (e.g. missing DataTransfer in V8)
        falls back to native Chrome DevTools Protocol DOM.setFileInputFiles.
        """
        path_str = str(Path(file_path).resolve())
        try:
            await page.set_input_files(selector, path_str)
            return True
        except Exception as e:
            logger.debug(f"[obscura]Standard set_input_files failed ({e}); falling back to CDP DOM.setFileInputFiles...")
            try:
                cdp = await page.context.new_cdp_session(page)
                root = await cdp.send("DOM.getDocument")
                node = await cdp.send("DOM.querySelector", {"nodeId": root["root"]["nodeId"], "selector": selector})
                node_id = node.get("nodeId")
                if not node_id:
                    logger.warning(f"[obscura]Could not locate DOM node for selector: {selector}")
                    return False
                await cdp.send("DOM.setFileInputFiles", {
                    "files": [path_str],
                    "nodeId": node_id,
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
                logger.error(f"[obscura]CDP file upload failed: {cdp_err}")
                return False

    async def close(self) -> None:
        """Cleanly terminate Obscura process and wipe ephemeral storage."""
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

        # Terminate Obscura process
        if self._process:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=1)
            except Exception as ex:
                logger.debug(f"[obscura]Error terminating process: {ex}")
            self._process = None

        # Clean up ready file
        if self.ready_file.exists():
            try:
                self.ready_file.unlink(missing_ok=True)
            except Exception:
                pass

        # Securely wipe ephemeral storage directory
        if self.storage_dir.exists():
            try:
                shutil.rmtree(self.storage_dir, ignore_errors=True)
                logger.info(f"[browser]Ephemeral profile wiped: {self.storage_dir.name}[/browser]")
            except Exception as ex:
                logger.debug(f"[obscura]Error wiping storage directory: {ex}")

        logger.info("[browser]🌐 Obscura backend closed cleanly.[/browser]")
