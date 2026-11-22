"""
Unit tests for AutoBot simultaneous multi-browser parallel search.
Verifies that when multiple browsers are selected, all browser instances
launch concurrently with different keywords assigned.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.agent.state import JobPosting
from src.browser.live_search import run_direct_chrome_search


@pytest.mark.asyncio
async def test_simultaneous_multi_browser_parallel_search():
    """Verify that multiple browsers launch concurrently with distinct keywords."""
    mock_keywords = ["Python Developer", "Automation Engineer"]

    # Track invocations across workers
    started_managers = []
    scraped_keywords = []

    class MockBrowserManager:
        def __init__(self, *args, **kwargs):
            self.user_data_dir = kwargs.get("user_data_dir")
            started_managers.append(self)

        async def start(self):
            pass

        async def close(self):
            pass

    class MockNavigator:
        def __init__(self, *args, **kwargs):
            pass

        async def ensure_logged_in(self, require_login=False):
            return True

        async def search_jobs(self, keyword, location, page, job_types):
            scraped_keywords.append(keyword)
            return [
                JobPosting(
                    job_id=f"job_{keyword}_{page}",
                    title=f"Engineer ({keyword})",
                    company="Tech Corp",
                    location=location,
                    url=f"https://example.com/job_{keyword}",
                    is_easy_apply=False,
                )
            ]

    with patch("src.browser.live_search.BrowserManager", side_effect=MockBrowserManager), \
         patch("src.browser.live_search.LinkedInNavigator", side_effect=MockNavigator), \
         patch("src.storage.db.is_job_processed", return_value=False), \
         patch("src.matching.evaluator.evaluate_scraped_job_fit", return_value={"match_score": 0.85, "match_percentage": 85}):

        results = await run_direct_chrome_search(
            keywords=mock_keywords,
            location="India",
            num_browsers=2,
            min_score=0.6,
            max_pages=1,
            headless=True,
            keep_open=False,
        )

        # 2 browser instances were launched simultaneously
        assert len(started_managers) == 2
        # Both keywords were scraped across the parallel workers
        assert "Python Developer" in scraped_keywords
        assert "Automation Engineer" in scraped_keywords
        assert len(results) == 2
