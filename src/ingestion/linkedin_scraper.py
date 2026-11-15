"""
Policy Enforcement Module for LinkedIn Profile Scraping in AutoBot v2.1.
Enforces complete prohibition of automated browser scraping, DOM extraction,
login automation, and session persistence for LinkedIn.
"""

from pathlib import Path
from typing import List, Optional

from src.application.workflows import LinkedInPolicyViolationError
from src.ingestion.models import DocumentChunk
from src.utils.config import EnvSettings
from src.utils.logger import logger


class LinkedInScraper:
    """
    Deprecated / Prohibited.
    Automated browser scraping of LinkedIn profiles is strictly forbidden.
    Raises LinkedInPolicyViolationError on any instantiation or method call.
    """

    def __init__(
        self,
        env: Optional[EnvSettings] = None,
        session_file: Optional[Path] = None,
        headless: Optional[bool] = None,
    ):
        raise LinkedInPolicyViolationError(
            "Compliance Policy Violation: Automated browser scraping, DOM extraction, "
            "and session persistence on LinkedIn is strictly prohibited. "
            "Candidate profiles and job information must be imported manually."
        )

    async def scrape(self, profile_url: str) -> List[DocumentChunk]:
        raise LinkedInPolicyViolationError(
            "Compliance Policy Violation: Automated browser scraping of LinkedIn is strictly prohibited."
        )


async def scrape_linkedin_profile(
    profile_url: Optional[str] = None,
    env: Optional[EnvSettings] = None,
    session_file: Optional[Path] = None,
    headless: Optional[bool] = None,
) -> List[DocumentChunk]:
    """
    Policy Gate: Strictly prevents automated scraping of LinkedIn profiles.
    Always raises LinkedInPolicyViolationError.
    """
    raise LinkedInPolicyViolationError(
        "Compliance Policy Violation: Automated browser scraping, DOM extraction, "
        "and session persistence on LinkedIn is strictly prohibited. "
        "Candidate profiles and job information must be imported manually."
    )
