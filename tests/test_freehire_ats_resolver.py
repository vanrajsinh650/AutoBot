"""
Tests for FreeHire and PushCV direct ATS discovery engines in AutoBot.
"""

from unittest.mock import MagicMock, patch
import pytest

from src.browser.freehire_ats_resolver import (
    _generate_company_slugs,
    extract_requisition_ids_from_text,
    lookup_greenhouse_api,
    lookup_lever_api,
    lookup_ashby_api,
    resolve_freehire_ats_url,
)
from src.browser.company_careers_resolver import resolve_company_direct_apply_url


def test_extract_requisition_ids_pushcv():
    """Verify PushCV regexes extract diverse formal requisition IDs."""
    text1 = "Join GE Vernova as Engineer - Platform NPI. Job ID: R5058359 in Hyderabad."
    reqs1 = extract_requisition_ids_from_text(text1)
    assert "R5058359" in reqs1

    text2 = "Associate Specialist at MSD. Requisition # R339798."
    reqs2 = extract_requisition_ids_from_text(text2)
    assert "R339798" in reqs2

    text3 = "Senior Software Engineer (JR1044669), Bangalore"
    reqs3 = extract_requisition_ids_from_text(text3)
    assert "JR1044669" in reqs3

    text4 = "Ref: REQ-4482 - Python Developer"
    reqs4 = extract_requisition_ids_from_text(text4)
    assert "REQ-4482" in reqs4


def test_generate_company_slugs():
    """Verify company slug derivation handles suffixes and multi-word names."""
    slugs1 = _generate_company_slugs("Route Mobile Limited")
    assert "routemobile" in slugs1 or "route-mobile" in slugs1

    slugs2 = _generate_company_slugs("Stripe, Inc.")
    assert "stripe" in slugs2

    slugs3 = _generate_company_slugs("DoorDash Technologies Pvt Ltd")
    assert "doordash" in slugs3


@patch("urllib.request.urlopen")
def test_lookup_greenhouse_api_match(mock_urlopen):
    """Verify FreeHire Greenhouse API lookup returns matching job URL."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"jobs": [{"title": "Software Engineer", "absolute_url": "https://boards.greenhouse.io/stripe/jobs/12345"}]}'
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    url = lookup_greenhouse_api("stripe", "Software Engineer")
    assert url == "https://boards.greenhouse.io/stripe/jobs/12345"


@patch("urllib.request.urlopen")
def test_lookup_lever_api_match(mock_urlopen):
    """Verify FreeHire Lever API lookup returns matching job URL."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = b'[{"text": "Backend Engineer", "hostedUrl": "https://jobs.lever.co/figma/abcde"}]'
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    url = lookup_lever_api("figma", "Backend Engineer")
    assert url == "https://jobs.lever.co/figma/abcde"


@patch("src.browser.company_careers_resolver.resolve_freehire_ats_url")
def test_company_careers_resolver_uses_freehire(mock_freehire):
    """Verify resolve_company_direct_apply_url calls FreeHire before search engine."""
    mock_freehire.return_value = "https://boards.greenhouse.io/sample/jobs/999"

    res = resolve_company_direct_apply_url(
        title="Software Engineer",
        company="SampleCorp",
        current_url="https://www.linkedin.com/jobs/view/9999999/",
    )
    assert res == "https://boards.greenhouse.io/sample/jobs/999"
