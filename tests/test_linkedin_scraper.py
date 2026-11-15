"""
Policy Enforcement Tests for LinkedIn Automation Prohibition (AutoBot v2.1).
Verifies that all automated scraping, DOM extraction, and session handling
for LinkedIn strictly fail closed with LinkedInPolicyViolationError.
"""

import pytest

from src.application.workflows import LinkedInPolicyViolationError
from src.ingestion.linkedin_scraper import LinkedInScraper, scrape_linkedin_profile
from src.utils.config import EnvSettings


@pytest.mark.asyncio
async def test_scrape_linkedin_profile_strictly_prohibited():
    """Verify that calling scrape_linkedin_profile immediately raises LinkedInPolicyViolationError."""
    with pytest.raises(LinkedInPolicyViolationError) as exc_info:
        await scrape_linkedin_profile("https://www.linkedin.com/in/testuser")

    assert "Compliance Policy Violation" in str(exc_info.value)
    assert "prohibited" in str(exc_info.value).lower()


def test_linkedin_scraper_instantiation_strictly_prohibited():
    """Verify that attempting to instantiate LinkedInScraper immediately raises LinkedInPolicyViolationError."""
    with pytest.raises(LinkedInPolicyViolationError) as exc_info:
        LinkedInScraper()

    assert "Compliance Policy Violation" in str(exc_info.value)
    assert "prohibited" in str(exc_info.value).lower()


def test_env_settings_does_not_accept_linkedin_credentials():
    """Verify that EnvSettings no longer includes linkedin_email or linkedin_password."""
    env = EnvSettings()
    assert not hasattr(env, "linkedin_email")
    assert not hasattr(env, "linkedin_password")
