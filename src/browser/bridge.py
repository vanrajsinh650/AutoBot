"""
Browser Bridge Adapter connecting LangGraph Agent to Playwright Actuators.

Educational Concept:
The Bridge Pattern decouples high-level agentic orchestration from low-level browser drivers:
1. Standardized Node Contracts:
   Exposes:
   - `search_provider`: Signature matches `Callable[[str, str, int], List[JobPosting]]`
     consumed directly by `SearchNode`.
   - `application_executor`: Signature matches `Callable[[JobPosting, Optional[str]], bool]`
     consumed directly by `ApplyNode`.
2. Lifecycle Orchestration:
   Serves as an async context manager (`async with BrowserBridge(...) as bridge:`)
   initializing `BrowserManager`, `LinkedInNavigator`, `EasyApplyActuator`, and
   `ExternalApplyActuator` together and guaranteeing safe browser shutdown.
"""

from pathlib import Path
from typing import List, Optional

from src.agent.state import JobPosting
from src.browser.easy_apply_actuator import EasyApplyActuator
from src.browser.external_apply_actuator import ExternalApplyActuator
from src.browser.manager import BrowserManager
from src.browser.navigator import LinkedInNavigator
from src.memory.form_rag import FormRAG
from src.utils.config import AppConfig, EnvSettings, get_config, get_env
from src.utils.logger import logger


class BrowserBridge:
    """
    Unified adapter integrating Playwright browser automation with AutoBot LangGraph nodes.
    """

    def __init__(
        self,
        form_rag: FormRAG,
        cfg: Optional[AppConfig] = None,
        env: Optional[EnvSettings] = None,
        resume_path: Optional[Path] = None,
    ):
        self.form_rag = form_rag
        self.cfg = cfg or get_config()
        self.env = env or get_env()
        self.resume_path = resume_path

        self.manager: Optional[BrowserManager] = None
        self.navigator: Optional[LinkedInNavigator] = None
        self.easy_apply_actuator: Optional[EasyApplyActuator] = None
        self.external_apply_actuator: Optional[ExternalApplyActuator] = None

    async def __aenter__(self) -> "BrowserBridge":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def start(self) -> None:
        """Launch browser and initialize actuators."""
        self.manager = BrowserManager(cfg=self.cfg, env=self.env)
        await self.manager.start()

        self.navigator = LinkedInNavigator(
            manager=self.manager,
            cfg=self.cfg,
            env=self.env,
        )

        # Authenticate with LinkedIn
        is_logged_in = await self.navigator.ensure_logged_in()
        if not is_logged_in:
            logger.warning("[bridge]⚠ LinkedIn authentication not verified. Search may be constrained.[/bridge]")

        self.easy_apply_actuator = EasyApplyActuator(
            page=self.manager.page,
            form_rag=self.form_rag,
            cfg=self.cfg,
            resume_path=self.resume_path,
        )

        self.external_apply_actuator = ExternalApplyActuator(
            context=self.manager.context,
            form_rag=self.form_rag,
            cfg=self.cfg,
            resume_path=self.resume_path,
        )

    async def search_provider(
        self,
        keyword: str,
        location: str,
        page: int,
    ) -> List[JobPosting]:
        """
        Search provider callback plugged into SearchNode.
        """
        if not self.navigator:
            raise RuntimeError("BrowserBridge has not been started.")

        jobs = await self.navigator.search_jobs(keyword, location, page)

        # For the first few jobs, scrape full description if short
        enriched_jobs = []
        for job in jobs:
            if len(job.description) < 100:
                enriched_job = await self.navigator.fetch_job_details(job)
                enriched_jobs.append(enriched_job)
            else:
                enriched_jobs.append(job)

        return enriched_jobs

    async def application_executor(
        self,
        job: JobPosting,
        cover_letter: Optional[str] = None,
    ) -> bool:
        """
        Application executor callback plugged into ApplyNode.
        """
        if not self.manager or not self.manager.page:
            raise RuntimeError("BrowserBridge has not been started.")

        # Route between Easy Apply vs External Apply based on vacancy badge & config
        if job.is_easy_apply and getattr(self.cfg.apply, "easy_apply", True):
            if not self.easy_apply_actuator:
                return False
            return await self.easy_apply_actuator.apply(job, cover_letter=cover_letter)

        elif not job.is_easy_apply and getattr(self.cfg.apply, "external_apply", True):
            if not self.external_apply_actuator:
                return False
            return await self.external_apply_actuator.apply(
                job,
                apply_url=job.external_apply_url or job.url,
                cover_letter=cover_letter,
            )

        else:
            logger.info(f"[bridge]Skipping application: apply type disabled in config for {job.job_id}[/bridge]")
            return False

    async def close(self) -> None:
        """Tear down browser session."""
        if self.manager:
            await self.manager.close()
            self.manager = None
