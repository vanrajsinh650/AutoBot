"""
Tests for AutoBot Career Page Requisition Equalizer.
Verifies Tier 1 fuzzy matching, candidate extraction, and Tier 2 Groq LLM requisition selection.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.browser.career_page_equalizer import (
    is_generic_career_hub_url,
    normalize_tokens,
    extract_candidate_links_from_html,
    fuzzy_match_candidate,
    llm_match_candidate_groq,
    equalize_career_hub_url,
    resolve_career_hub_requisition_offline,
)


def test_is_generic_career_hub_url():
    # Generic hubs without specific job slug
    assert is_generic_career_hub_url("https://example.com/careers") is True
    assert is_generic_career_hub_url("https://example.com/careers/") is True
    assert is_generic_career_hub_url("https://example.com/jobs") is True
    assert is_generic_career_hub_url("https://example.com/en/careers/") is True
    assert is_generic_career_hub_url("https://example.com/openings/") is True
    assert is_generic_career_hub_url("https://ishantechnologies.com/careers/") is True

    # Specific requisition URLs
    assert is_generic_career_hub_url("https://example.com/careers/python-developer-1234") is False
    assert is_generic_career_hub_url("https://example.com/job/senior-data-engineer") is False
    assert is_generic_career_hub_url("https://example.com/careers?req=REQ-987") is False
    assert is_generic_career_hub_url("https://example.com/careers?jobId=4521") is False


def test_normalize_tokens():
    tokens = normalize_tokens("Sr. Python Dev & SWE")
    assert "senior" in tokens
    assert "python" in tokens
    assert "developer" in tokens
    assert "software engineer" in tokens or "swe" in tokens


def test_extract_candidate_links_from_html():
    html = """
    <html>
    <body>
        <nav>
            <a href="/about">About Us</a>
            <a href="/privacy">Privacy Policy</a>
            <a href="mailto:careers@example.com">Contact</a>
        </nav>
        <section class="openings">
            <div class="job-card">
                <a href="/careers/senior-python-dev/">Senior Python Developer</a>
                <span>Location: Remote</span>
            </div>
            <div class="job-card">
                <a href="/careers/react-frontend-lead/">React Frontend Lead</a>
                <span>Location: New York</span>
            </div>
            <div class="job-card">
                <a href="/careers/hr-business-partner/">HR Business Partner</a>
            </div>
        </section>
    </body>
    </html>
    """
    candidates = extract_candidate_links_from_html(html, base_url="https://company.com")
    assert len(candidates) == 3
    urls = [c["url"] for c in candidates]
    assert "https://company.com/careers/senior-python-dev/" in urls
    assert "https://company.com/careers/react-frontend-lead/" in urls
    assert not any("privacy" in u for u in urls)
    assert not any("about" in u for u in urls)


def test_fuzzy_match_candidate_tier1():
    candidates = [
        {"url": "https://company.com/careers/sr-python-dev/", "title": "Senior Python Developer", "snippet": "Remote"},
        {"url": "https://company.com/careers/devops-architect/", "title": "DevOps Architect", "snippet": "Bangalore"},
        {"url": "https://company.com/careers/hr-lead/", "title": "HR Lead", "snippet": "Ahmedabad"},
    ]

    # Matching with abbreviation expansion (Sr. -> Senior)
    match = fuzzy_match_candidate(
        target_title="Sr. Python Developer",
        candidates=candidates,
    )
    assert match is not None
    assert match["url"] == "https://company.com/careers/sr-python-dev/"

    # Matching with Requisition ID override
    match_req = fuzzy_match_candidate(
        target_title="Platform Engineer",
        candidates=[
            {"url": "https://company.com/careers/job-123", "title": "Software Engineer (REQ-4482)", "snippet": "Backend"},
            {"url": "https://company.com/careers/job-456", "title": "QA Engineer (REQ-1102)", "snippet": "Testing"},
        ],
        req_id="REQ-4482",
    )
    assert match_req is not None
    assert match_req["url"] == "https://company.com/careers/job-123"


def test_llm_match_candidate_groq_mocked():
    candidates = [
        {"url": "https://company.com/careers/fullstack-ruby", "title": "Fullstack Ruby Engineer", "snippet": ""},
        {"url": "https://company.com/careers/cloud-infra", "title": "Senior Cloud Infrastructure Engineer", "snippet": "AWS, Kubernetes"},
        {"url": "https://company.com/careers/marketing-ops", "title": "Marketing Operations Specialist", "snippet": ""},
    ]

    mock_resp_data = {
        "choices": [
            {
                "message": {
                    "content": '{"matched_url": "https://company.com/careers/cloud-infra", "confidence": 0.95, "reason": "Direct match for Cloud & DevOps requirements."}'
                }
            }
        ]
    }

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        import json
        mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        target_job = {
            "title": "Senior AWS & Cloud Infrastructure Engineer",
            "company": "Company Inc",
            "location": "Remote",
        }
        result = llm_match_candidate_groq(target_job, candidates, groq_api_key="mock_key")
        assert result is not None
        assert result["url"] == "https://company.com/careers/cloud-infra"


@pytest.mark.asyncio
async def test_equalize_career_hub_url_navigation():
    # Mock Playwright Page
    mock_page = AsyncMock()
    mock_page.url = "https://ishantechnologies.com/careers/"

    # DOM evaluation returns candidates
    mock_page.evaluate.return_value = [
        {
            "url": "https://ishantechnologies.com/careers/senior-python-engineer/",
            "title": "Senior Python Engineer",
            "snippet": "Ahmedabad, Gujarat",
        },
        {
            "url": "https://ishantechnologies.com/careers/network-specialist/",
            "title": "Network Specialist",
            "snippet": "Mumbai",
        },
    ]

    with patch("src.browser.cookie_handler.dismiss_cookie_banners", new=AsyncMock()):
        result_url = await equalize_career_hub_url(
            page=mock_page,
            target_title="Senior Python Developer",
            company="Ishan Technologies",
            location="Ahmedabad",
        )

        assert result_url == "https://ishantechnologies.com/careers/senior-python-engineer/"
        # Verify page.goto was called with the exact requisition URL
        mock_page.goto.assert_called_once()
        call_url = mock_page.goto.call_args[0][0]
        assert call_url == "https://ishantechnologies.com/careers/senior-python-engineer/"


def test_resolve_career_hub_requisition_offline():
    html_content = """
    <html>
    <body>
        <div class="job-list">
            <a href="/careers/sr-automation-qa/">Sr Automation QA Engineer</a>
            <a href="/careers/data-scientist/">Data Scientist</a>
        </div>
    </body>
    </html>
    """

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = html_content.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = resolve_career_hub_requisition_offline(
            hub_url="https://techcompany.com/careers/",
            target_title="Senior Automation QA",
            company="Tech Company",
        )
        assert res == "https://techcompany.com/careers/sr-automation-qa/"
