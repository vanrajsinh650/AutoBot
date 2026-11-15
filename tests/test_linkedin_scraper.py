"""Tests for LinkedIn scraper module."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.ingestion.models import DocumentChunk, IngestionSource, SectionType
from src.ingestion.linkedin_scraper import LinkedInScraper, scrape_linkedin_profile
from src.utils.config import EnvSettings


@pytest.fixture
def mock_env():
    return EnvSettings(
        linkedin_email="test_user@example.com",
        linkedin_password="secure_password",
        linkedin_profile_url="https://www.linkedin.com/in/testuser",
        headless=True,
    )


@pytest.mark.asyncio
async def test_scrape_linkedin_empty_url(mock_env):
    """Empty or whitespace URL should immediately return empty list without launching browser."""
    chunks = await scrape_linkedin_profile("", mock_env)
    assert chunks == []

    chunks_none = await scrape_linkedin_profile(None, mock_env)
    assert chunks_none == []


@pytest.mark.asyncio
async def test_scrape_linkedin_missing_credentials():
    """Missing credentials should log warning and return [] safely."""
    empty_env = EnvSettings(linkedin_email="", linkedin_password="")
    chunks = await scrape_linkedin_profile("https://www.linkedin.com/in/testuser", empty_env)
    assert chunks == []


@pytest.mark.asyncio
async def test_scrape_linkedin_with_existing_session(tmp_path, mock_env):
    """If valid session storage file exists, context is initialized with storage_state and skips login."""
    session_file = tmp_path / "linkedin_state.json"
    session_file.write_text(json.dumps({"cookies": [{"name": "li_at", "value": "dummy"}]}))

    scraper = LinkedInScraper(env=mock_env, session_file=session_file)

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html></html>")
    mock_page.url = "https://www.linkedin.com/in/testuser"

    # Mock extraction methods on scraper
    scraper._extract_profile_data = AsyncMock(
        return_value=[
            DocumentChunk(
                content="Senior Staff Engineer at TechCorp",
                source=IngestionSource.LINKEDIN,
                section=SectionType.SUMMARY,
            )
        ]
    )

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_browser = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    with patch("src.ingestion.linkedin_scraper.async_playwright") as mock_playwright:
        mock_p = AsyncMock()
        mock_p.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_playwright.return_value.__aenter__.return_value = mock_p

        chunks = await scraper.scrape("https://www.linkedin.com/in/testuser")

        assert len(chunks) == 1
        assert chunks[0].source == IngestionSource.LINKEDIN
        # Verify storage_state was passed to new_context
        mock_browser.new_context.assert_called_once()
        _, kwargs = mock_browser.new_context.call_args
        assert kwargs.get("storage_state") == str(session_file)


@pytest.mark.asyncio
async def test_extract_profile_sections():
    """Verify DOM section extraction builds appropriate DocumentChunk models."""
    scraper = LinkedInScraper(env=EnvSettings(), session_file=None)

    mock_page = AsyncMock()

    # Simulate query_selector and inner_text results
    async def mock_query_selector_all(selector: str):
        if "experience" in selector:
            item1 = AsyncMock()
            item1.inner_text = AsyncMock(return_value="Staff Engineer\nAcme Corp\n2020 - Present\nBuilt distributed agents.")
            return [item1]
        elif "education" in selector:
            item2 = AsyncMock()
            item2.inner_text = AsyncMock(return_value="Stanford University\nB.S. in Computer Science\n2015 - 2019")
            return [item2]
        elif "skills" in selector:
            item3 = AsyncMock()
            item3.inner_text = AsyncMock(return_value="Python, LangChain, Kubernetes")
            return [item3]
        return []

    mock_page.query_selector_all = mock_query_selector_all

    async def mock_query_selector(selector: str):
        elem = AsyncMock()
        if "about" in selector:
            elem.inner_text = AsyncMock(return_value="Passionate software architect building autonomous LLM agents.")
            return elem
        elif "headline" in selector:
            elem.inner_text = AsyncMock(return_value="Lead AI Engineer | Distributed Systems")
            return elem
        return None

    mock_page.query_selector = mock_query_selector

    chunks = await scraper._extract_profile_data(mock_page, "https://www.linkedin.com/in/testuser")

    sections = {c.section for c in chunks}
    assert SectionType.SUMMARY in sections
    assert SectionType.EXPERIENCE in sections
    assert SectionType.EDUCATION in sections
    assert SectionType.SKILLS in sections

    for c in chunks:
        assert c.source == IngestionSource.LINKEDIN
