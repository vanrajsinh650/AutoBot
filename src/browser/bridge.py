"""
Browser Bridge Adapter connecting LangGraph Agent to External ATS Actuators in AutoBot v2.1.
Enforces complete compliance: strictly prohibits LinkedIn browser automation.
"""

from pathlib import Path
from typing import List, Optional

from src.agent.state import JobPosting
from src.application.workflows import LinkedInPolicyViolationError
from src.browser.external_apply_actuator import ExternalApplyActuator
from src.browser.manager import BrowserManager
from src.memory.form_rag import FormRAG
from src.utils.config import AppConfig, EnvSettings, get_config, get_env
from src.utils.logger import logger


class BrowserBridge:
    """
    Adapter strictly limited to authorized external career portals (ATS).
    Automated LinkedIn navigation, scraping, and Easy Apply are prohibited.
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
        self.external_apply_actuator: Optional[ExternalApplyActuator] = None

    async def __aenter__(self) -> "BrowserBridge":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def start(self) -> None:
        """Launch browser and initialize authorized external actuators."""
        self.manager = BrowserManager(cfg=self.cfg, env=self.env)
        await self.manager.start()

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
        Policy Gate: Automated LinkedIn search scraping is strictly prohibited.
        """
        raise LinkedInPolicyViolationError(
            "Compliance Policy Violation: Automated job search scraping on LinkedIn is strictly prohibited. "
            "Use authorized public ATS adapters via JobDiscoveryEngine or user-submitted imports."
        )

    async def application_executor(
        self,
        job: JobPosting,
        cover_letter: Optional[str] = None,
    ) -> bool:
        """
        Application executor callback for ApplyNode.
        Fails closed on any LinkedIn job.
        """
        if not self.manager or not self.manager.page:
            raise RuntimeError("BrowserBridge has not been started.")

        target_url = (job.external_apply_url or job.url or "").lower()

        # Hard compliance gate: LinkedIn is strictly prohibited
        if job.is_easy_apply or "linkedin.com" in target_url or "lnkd.in" in target_url:
            raise LinkedInPolicyViolationError(
                f"Compliance Policy Violation: Automated application to LinkedIn jobs ({job.job_id}) "
                "is strictly prohibited. Applications to LinkedIn vacancies must be submitted directly "
                "on LinkedIn by the candidate using the manual workflow."
            )

        if getattr(self.cfg.apply, "external_apply", True):
            if not self.external_apply_actuator:
                return False
            return await self.external_apply_actuator.apply(
                job,
                apply_url=job.external_apply_url or job.url,
                cover_letter=cover_letter,
            )

        logger.info(f"[bridge]Skipping application: external apply disabled in config for {job.job_id}[/bridge]")
        return False

    async def close(self) -> None:
        """Tear down browser session."""
        if self.manager:
            await self.manager.close()
            self.manager = None
