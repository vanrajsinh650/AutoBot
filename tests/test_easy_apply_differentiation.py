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

    # Greenhouse ATS
    plat_gh, cat_gh = detect_apply_platform(
        url="https://boards.greenhouse.io/cloudflare/jobs/7695702",
        source_name="Greenhouse",
        is_easy_apply=False,
    )
    assert plat_gh == "Greenhouse"
    assert cat_gh == "greenhouse"

    # Lever ATS
    plat_lev, cat_lev = detect_apply_platform(
        url="https://jobs.lever.co/leverdemo/ad208490-4052-4f91-a57e-433f2d1e484b",
        source_name="Lever",
        is_easy_apply=False,
    )
    assert plat_lev == "Lever"
    assert cat_lev == "lever"

    # Ashby ATS
    plat_ash, cat_ash = detect_apply_platform(
        url="https://jobs.ashbyhq.com/ramp/34413f8d-26bf-4bbc-8ade-eb309a0e2245",
        source_name="Ashby",
        is_easy_apply=False,
    )
    assert plat_ash == "Ashby"
    assert cat_ash == "ashby"

    # Workday ATS
    plat_wd, cat_wd = detect_apply_platform(
        url="https://ghc.wd1.myworkdayjobs.com/Kaplan_Careers/job/Bangalore-KA-India/AI-Software-Engineer",
        source_name="Workday",
        is_easy_apply=False,
    )
    assert plat_wd == "Workday"
    assert cat_wd == "workday"

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
