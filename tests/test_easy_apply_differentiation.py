import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from aiohttp import web
from src.storage.db import detect_apply_platform, get_apply_portals
from src.browser.linkedin_apply_extractor import detect_easy_apply_from_html

def test_detect_apply_platform_easy_vs_external():
    # Easy Apply
    plat_easy, cat_easy = detect_apply_platform(
        url="https://www.linkedin.com/jobs/view/4492817177/",
        source_name="LinkedIn",
        is_easy_apply=True,
    )
    assert plat_easy == "LinkedIn (Easy Apply)"
    assert cat_easy == "linkedin"

    # External Form (Only Apply)
    plat_ext, cat_ext = detect_apply_platform(
        url="https://careers.micron.com/careers/job/44495516",
        source_name="LinkedIn",
        is_easy_apply=False,
    )
    assert plat_ext == "LinkedIn (External Form)"
    assert cat_ext == "external"

def test_detect_easy_apply_from_html_signals():
    # Onsite tracking signal -> Easy Apply
    html_easy = '<button data-tracking-control-name="public_jobs_apply-link-onsite" class="apply-button apply-button--default">Easy Apply</button>'
    assert detect_easy_apply_from_html(html_easy) is True

    # Offsite tracking signal -> Only Apply / External
    html_ext = '<button data-tracking-control-name="public_jobs_apply-link-offsite" class="sign-up-modal__outlet">Apply on company site</button>'
    assert detect_easy_apply_from_html(html_ext) is False

    # Benefits badge with Easy Apply -> Easy Apply
    html_card_easy = '<li class="job-search-card__benefits-item"><span>Easy Apply</span></li>'
    assert detect_easy_apply_from_html(html_card_easy) is True

def test_get_apply_portals_categorization():
    # Verify that get_apply_portals separates Easy Apply and External Forms
    res_easy = get_apply_portals(user_id=1, platform_category="linkedin_easy")
    for job in res_easy.get("jobs", []):
        assert job["platform"] == "LinkedIn (Easy Apply)"
        assert job["platform_category"] == "linkedin"
        assert job["apply_type"] == "Easy Apply"
        assert "linkedin.com" in job["apply_url"]

    res_ext = get_apply_portals(user_id=1, platform_category="linkedin_external")
    for job in res_ext.get("jobs", []):
        assert job["platform"] != "LinkedIn (Easy Apply)"
        assert job["platform_category"] == "external"
        assert job["apply_type"] == "External Apply"
