"""
Direct Live Search in Real Google Chrome for AutoBot v2.
Opens genuine Google Chrome, navigates to LinkedIn Jobs, types search keywords
naturally with human typing delays, applies filters (past 24 hours, Easy Apply, location),
and extracts discovered job postings into the local database and dashboard.
"""

import asyncio
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote_plus

from src.agent.state import JobPosting
from src.browser.linkedin_apply_extractor import (
    decode_linkedin_apply_url,
    resolve_direct_apply_url_from_page,
)
from src.browser.manager import BrowserManager
from src.browser.navigator import LinkedInNavigator
from src.browser.popup_handler import dismiss_sign_in_popup, install_popup_observer, recover_from_authwall
from src.storage.db import get_db_connection, init_db, is_job_processed, save_application, save_scraped_job
from src.utils.config import AppConfig, EnvSettings, get_config, get_env
from src.utils.logger import logger


async def run_direct_chrome_search(
    keywords: Optional[List[str]] = None,
    location: Optional[str] = None,
    job_types: Optional[List[str]] = None,
    num_browsers: int = 1,
    min_score: Optional[float] = None,
    max_pages: int = 1,
    headless: bool = False,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    user_id: int = 1,
    keep_open: bool = False,
) -> List[JobPosting]:
    """
    Launch real Google Chrome and execute keyword search directly on LinkedIn.
    Enforces strict search sequence:
      1. Primary keyword 'Python Developer' is searched FIRST.
      2. After 'Python Developer' completes, secondary resume keywords are searched.
      3. If num_browsers > 1, secondary keywords run in parallel across concurrent Chrome browsers.
    """
    cfg = get_config()
    env = get_env()

    def _notify(level: str, msg: str):
        logger.info(f"[live-search]{msg}[/live-search]")
        if progress_callback:
            try:
                progress_callback(level, msg)
            except Exception:
                pass

    # 1. Resolve keywords and establish strict 'Python Developer' priority
    from src.matching.keyword_expansion import resolve_search_keywords
    search_keywords, origin = resolve_search_keywords(
        user_provided=keywords,
        user_id=user_id,
        db_path=getattr(getattr(cfg, "storage", None), "db_path", None),
    )
    search_location = location or getattr(cfg.search, "location", "India")
    effective_job_types = job_types or getattr(cfg.search, "job_type", ["full-time", "internship"])

    primary_kw = "Python Developer"
    secondary_kws = [k.strip() for k in search_keywords if k.strip().lower() != primary_kw.lower() and k.strip()]
    ordered_keywords = [primary_kw] + secondary_kws

    min_score_threshold = float(min_score) if min_score is not None else float(getattr(getattr(cfg, "apply", None), "min_match_score", 0.60))

    _notify(
        "info",
        f"Configured LinkedIn search: Primary='{primary_kw}' (Priority #1), Secondary=[{', '.join(secondary_kws)}], "
        f"Types={effective_job_types}, Threshold={int(min_score_threshold*100)}%, Browsers={num_browsers}"
    )

    # Prepare blacklist & seniority filters
    init_db()
    exp_levels = getattr(cfg.search, "experience_level", ["entry", "associate"])
    blacklist_keywords = [
        k.lower() for k in getattr(cfg.blacklist, "title_keywords", []) if k
    ]
    is_senior_target = any(e.lower() in ("mid-senior", "director", "executive") for e in exp_levels)
    if not is_senior_target:
        senior_defaults = ["senior", "sr.", "sr", "lead", "principal", "staff", "director", "vp", "architect", "head of", "manager"]
        for sp in senior_defaults:
            if sp not in blacklist_keywords:
                blacklist_keywords.append(sp)

    async def _scrape_single_keyword(
        nav: LinkedInNavigator,
        kw: str,
        loc: str,
        j_types: List[str],
        worker_tag: str,
    ) -> List[JobPosting]:
        found_jobs: List[JobPosting] = []
        for page_num in range(1, max_pages + 1):
            _notify("info", f"[{worker_tag}] 🔍 Searching '{kw}' (page {page_num}) in {loc} [Types: {', '.join(j_types)}]...")
            try:
                jobs = await nav.search_jobs(keyword=kw, location=loc, page=page_num, job_types=j_types)
            except Exception as ex:
                logger.error(f"[{worker_tag}] Error querying '{kw}': {ex}")
                jobs = []

            _notify("info", f"[{worker_tag}] Found {len(jobs)} jobs for '{kw}' (page {page_num}).")

            for job in jobs:
                # Check seniority
                from src.matching.evaluator import is_senior_or_blacklisted_title
                is_senior, blk_term = is_senior_or_blacklisted_title(job.title, blacklist_keywords)
                if is_senior:
                    logger.info(f"[{worker_tag}] ⏭ Skipping senior role: '{job.title}' @ '{job.company}' ({blk_term})")
                    continue

                # Check duplicate
                if is_job_processed(job_id=job.job_id, url=job.url, title=job.title, company=job.company, user_id=user_id):
                    logger.info(f"[{worker_tag}] ⏭ Skipping duplicate job: '{job.title}' @ '{job.company}'")
                    continue

                # Evaluate resume match fit
                from src.matching.evaluator import evaluate_scraped_job_fit
                eval_res = evaluate_scraped_job_fit(
                    title=job.title,
                    company=job.company,
                    description=job.description or f"Role: {job.title} at {job.company}.",
                    user_id=user_id,
                )
                match_score = eval_res["match_score"]
                match_pct = eval_res["match_percentage"]

                if match_score >= min_score_threshold:
                    found_jobs.append(job)
                    status_label = "discovered"
                    _notify("info", f"[{worker_tag}] 🎯 Matched: '{job.title}' @ '{job.company}' ({match_pct}% fit >= {int(min_score_threshold*100)}% threshold)")
                else:
                    status_label = "skipped_low_fit"
                    logger.info(f"[{worker_tag}] ⏭ Filtered low-fit role: '{job.title}' ({match_pct}% < {int(min_score_threshold*100)}%)")

                # Resolve direct apply URL
                final_apply_url = getattr(job, "external_apply_url", None) or getattr(job, "apply_url", None) or job.url

                # If matching role is an external apply job and apply_url still points to LinkedIn,
                # invoke fetch_job_details to extract the outbound direct ATS link (Workday, iCIMS, Greenhouse, etc.)
                if not job.is_easy_apply and any(li in str(final_apply_url).lower() for li in ("linkedin.com", "lnkd.in")):
                    try:
                        detailed_job = await nav.fetch_job_details(job)
                        ext_url = getattr(detailed_job, "external_apply_url", None)
                        if ext_url and not any(li in str(ext_url).lower() for li in ("linkedin.com", "lnkd.in")):
                            final_apply_url = ext_url
                            logger.info(f"[{worker_tag}] 🎯 Extracted outbound direct ATS apply link for '{job.title}' @ '{job.company}': {final_apply_url}")
                    except Exception as ex:
                        logger.debug(f"[{worker_tag}] fetch_job_details fallback failed: {ex}")

                try:
                    save_scraped_job(
                        title=job.title,
                        company=job.company,
                        location=job.location,
                        description=job.description or f"Role: {job.title} at {job.company}.",
                        apply_url=final_apply_url,
                        source_name="LinkedIn",
                        is_easy_apply=job.is_easy_apply,
                        job_id=job.job_id,
                        user_id=user_id,
                        raw_data={"search_keyword": kw, "source_url": job.url, "match_percentage": match_pct},
                        match_score=match_score,
                        status=status_label,
                    )
                except Exception as ex:
                    logger.debug(f"Could not save job: {ex}")

            await asyncio.sleep(1.0)
        return found_jobs

    all_discovered_jobs: List[JobPosting] = []

    # ── Phase 1: Search Primary Keyword 'Python Developer' in Browser 1 ──
    _notify("info", f"🚀 Phase 1: Launching Primary Chrome Browser for '{primary_kw}'...")
    manager1 = BrowserManager(cfg=cfg, env=env, headless=headless, user_id=user_id)

    try:
        await manager1.start()
        nav1 = LinkedInNavigator(manager=manager1, cfg=cfg, env=env)
        _notify("info", "Checking LinkedIn authentication session...")
        is_auth = await nav1.ensure_logged_in()
        if not is_auth:
            _notify("warning", "LinkedIn authentication required. Proceeding in public stealth search mode.")

        p1_jobs = await _scrape_single_keyword(
            nav=nav1,
            kw=primary_kw,
            loc=search_location,
            j_types=effective_job_types,
            worker_tag="Browser 1 (Primary)",
        )
        all_discovered_jobs.extend(p1_jobs)
        _notify("success", f"✓ Phase 1 complete: Finished search for '{primary_kw}'. Discovered {len(p1_jobs)} matching roles.")

        # ── Phase 2: Search Secondary Keywords ───────────────────────
        if secondary_kws:
            if num_browsers <= 1:
                # Sequential scraping in Browser 1
                _notify("info", f"Phase 2: Continuing with {len(secondary_kws)} secondary keywords in Browser 1...")
                for s_kw in secondary_kws:
                    s_jobs = await _scrape_single_keyword(
                        nav=nav1,
                        kw=s_kw,
                        loc=search_location,
                        j_types=effective_job_types,
                        worker_tag="Browser 1",
                    )
                    all_discovered_jobs.extend(s_jobs)
            else:
                # Parallel scraping across multiple concurrent Chrome browsers
                active_workers = min(num_browsers, len(secondary_kws))
                _notify("info", f"⚡ Phase 2: Launching {active_workers} parallel Chrome browsers for {len(secondary_kws)} keywords: {', '.join(secondary_kws)}...")

                session_dir = manager1.session_dir
                sem = asyncio.Semaphore(active_workers)

                async def _worker_task(kw_item: str, worker_id: int):
                    async with sem:
                        worker_data_dir = session_dir / f"user_data_worker_{worker_id}"
                        worker_mgr = BrowserManager(
                            cfg=cfg,
                            env=env,
                            user_data_dir=worker_data_dir,
                            headless=headless,
                            user_id=user_id,
                        )
                        try:
                            _notify("info", f"🌐 [Browser {worker_id}] Launching parallel Chrome instance for '{kw_item}'...")
                            await worker_mgr.start()
                            w_nav = LinkedInNavigator(manager=worker_mgr, cfg=cfg, env=env)
                            await w_nav.ensure_logged_in(require_login=False)
                            w_jobs = await _scrape_single_keyword(
                                nav=w_nav,
                                kw=kw_item,
                                loc=search_location,
                                j_types=effective_job_types,
                                worker_tag=f"Browser {worker_id}",
                            )
                            return w_jobs
                        except Exception as w_err:
                            logger.error(f"[Browser {worker_id}] Parallel search error: {w_err}")
                            return []
                        finally:
                            try:
                                await worker_mgr.close()
                            except Exception:
                                pass

                tasks = [
                    _worker_task(kw, (idx % active_workers) + 2)
                    for idx, kw in enumerate(secondary_kws)
                ]
                parallel_results = await asyncio.gather(*tasks, return_exceptions=True)
                for pr in parallel_results:
                    if isinstance(pr, list):
                        all_discovered_jobs.extend(pr)

        _notify("success", f"🎉 Autonomous search complete! Total {len(all_discovered_jobs)} matching opportunities discovered.")

        if keep_open:
            _notify("info", "Chrome browser is ready. Keeping primary window open for you to view results...")
            return all_discovered_jobs

    except Exception as e:
        _notify("error", f"Search encountered an error: {e}")
        logger.error(f"Error in direct Chrome search: {e}", exc_info=True)
    finally:
        if not keep_open:
            try:
                await manager1.close()
            except Exception:
                pass

    return all_discovered_jobs


async def run_direct_google_keyword_search(
    keyword: str,
    location: Optional[str] = None,
    headless: bool = False,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    user_id: int = 1,
    keep_open: bool = True,
) -> List[Dict[str, str]]:
    """
    Launch real Google Chrome directly to Google Search (not LinkedIn),
    types the single keyword naturally with human cadence, presses Enter,
    and displays the live results in Chrome.

    Args:
        keyword: Single search keyword (e.g. 'Python Developer' or 'Software Engineer').
        location: Optional target location.
        headless: Whether to run headlessly. Defaults to False.
        progress_callback: Callback for telemetry events.
        user_id: User ID.
        keep_open: Whether to keep Google Chrome open after searching.

    Returns:
        List of result items with title, link, snippet.
    """
    cfg = get_config()
    env = get_env()

    def _notify(level: str, msg: str):
        logger.info(f"[google-search]{msg}[/google-search]")
        if progress_callback:
            try:
                progress_callback(level, msg)
            except Exception:
                pass

    from src.matching.keyword_expansion import resolve_search_keywords
    resolved_kws, origin = resolve_search_keywords(
        user_provided=keyword,
        user_id=user_id,
        db_path=getattr(getattr(cfg, "storage", None), "db_path", None),
    )
    base_kw = resolved_kws[0] if resolved_kws else "Python Developer"
    query = base_kw
    if location and location.strip():
        query += f" jobs in {location.strip()}"
    elif "job" not in query.lower():
        query += " jobs"

    _notify("info", f"Opening Google Chrome for keyword search: '{query}' ({origin})")

    manager = BrowserManager(
        cfg=cfg,
        env=env,
        headless=headless,
        user_id=user_id,
    )

    results: List[Dict[str, str]] = []

    try:
        _notify("info", "Launching Google Chrome with persistent profile...")
        await manager.start()

        page = manager.page
        if not page:
            raise RuntimeError("Browser page could not be initialized.")

        _notify("info", "Navigating to Google...")
        await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1)

        # Locate Google search box
        search_box = None
        for sel in ("textarea[name='q']", "input[name='q']", "[aria-label='Search']"):
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    search_box = el
                    break
            except Exception:
                pass

        if search_box:
            _notify("info", f"Typing search query: '{query}' with natural human typing...")
            await search_box.click()
            for ch in query:
                await page.keyboard.type(ch, delay=45)
            await page.keyboard.press("Enter")
        else:
            from urllib.parse import quote_plus
            _notify("info", "Navigating directly to Google Search results...")
            await page.goto(f"https://www.google.com/search?q={quote_plus(query)}", wait_until="domcontentloaded")

        await asyncio.sleep(2.5)

        # Parse search results
        h3_elements = await page.query_selector_all("h3")
        _notify("success", f"Search completed! Found {len(h3_elements)} result headings on Google.")

        for h3 in h3_elements[:15]:
            title = await h3.inner_text()
            title = title.strip()
            if not title:
                continue
            parent_link = await h3.evaluate("el => el.closest('a') ? el.closest('a').href : ''")
            results.append({"title": title, "url": parent_link})

        _notify("info", f"Extracted {len(results)} search results in Google Chrome.")

        if keep_open:
            _notify("success", "Google Chrome window is open and active with your search results.")
            return results

    except Exception as e:
        _notify("error", f"Search encountered an error: {e}")
        logger.error(f"Google Chrome search error: {e}", exc_info=True)
    finally:
        if not keep_open:
            try:
                await manager.close()
            except Exception:
                pass

    return results


async def run_google_to_linkedin_job_search(
    keyword: str,
    location: Optional[str] = None,
    job_types: Optional[List[str]] = None,
    min_score: Optional[float] = None,
    open_first_role: bool = True,
    headless: bool = False,
    progress_callback: Optional[Callable[[str, str], None]] = None,
    user_id: int = 1,
    keep_open: bool = True,
) -> List[Dict[str, str]]:
    """
    1. Opens genuine Google Chrome with persistent profile.
    2. Searches the single keyword on Google with natural typing cadence.
    3. Seamlessly navigates to the LinkedIn page showing all job roles for that keyword.
    4. Extracts all listed job roles (title, company, URL) into database.
    5. Clicks and opens the top job role directly on screen in Google Chrome!

    Args:
        keyword: Search keyword (e.g. 'Python Developer', 'Software Engineer').
        location: Target location (e.g. 'India', 'Remote').
        open_first_role: Whether to automatically click/open the first job role.
        headless: Whether to run headlessly. Defaults to False (visible Chrome).
        progress_callback: Telemetry callback for live dashboard updates.
        user_id: User ID for local database application tracking.
        keep_open: Whether to leave Google Chrome open with the job view active.

    Returns:
        List of discovered job role dicts.
    """
    cfg = get_config()
    env = get_env()

    def _notify(level: str, msg: str):
        logger.info(f"[search-nav]{msg}[/search-nav]")
        if progress_callback:
            try:
                progress_callback(level, msg)
            except Exception:
                pass

    from src.matching.keyword_expansion import resolve_search_keywords
    resolved_kws, origin = resolve_search_keywords(
        user_provided=keyword,
        user_id=user_id,
        db_path=getattr(getattr(cfg, "storage", None), "db_path", None),
    )
    search_kw = resolved_kws[0] if resolved_kws else "Python Developer"
    search_loc = (location.strip() if location and location.strip() else getattr(cfg.search, "location", "India")) or "India"

    _notify("info", f"Initiating Google Chrome job search: '{search_kw}' ({origin}) in {search_loc}...")

    manager = BrowserManager(
        cfg=cfg,
        env=env,
        headless=headless,
        user_id=user_id,
    )

    discovered_roles: List[Dict[str, str]] = []

    try:
        _notify("info", "Launching genuine Google Chrome with persistent profile and hardware GPU...")
        await manager.start()

        page = manager.page
        if not page:
            raise RuntimeError("Browser page could not be initialized.")

        # ── Step 1: Search keyword on Google with natural human typing ──
        google_query = f"{search_kw} jobs {search_loc}"
        _notify("info", f"Step 1: Performing keyword search on Google: '{google_query}'...")
        await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(1.0)

        search_box = None
        for sel in ("textarea[name='q']", "input[name='q']", "[aria-label='Search']"):
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    search_box = el
                    break
            except Exception:
                pass

        if search_box:
            await search_box.click()
            for ch in google_query:
                await page.keyboard.type(ch, delay=35)
            await page.keyboard.press("Enter")
        else:
            await page.goto(f"https://www.google.com/search?q={quote_plus(google_query)}", wait_until="domcontentloaded")

        await asyncio.sleep(2.0)
        _notify("success", "Google keyword search completed.")

        # ── Step 2: Navigate directly to LinkedIn job roles page ─────────
        # Translate experience levels to LinkedIn f_E parameter
        exp_levels = getattr(cfg.search, "experience_level", ["entry", "associate"])
        exp_map = {
            "internship": "1",
            "entry": "2",
            "associate": "3",
            "mid-senior": "4",
            "director": "5",
            "executive": "6",
        }
        exp_codes = [exp_map[e.lower()] for e in exp_levels if e.lower() in exp_map]
        exp_filter = f"&f_E={'%2C'.join(exp_codes)}" if exp_codes else "&f_E=1%2C2%2C3"

        # Translate job types (Full-time: F, Internship: I, Contract: C, Part-time: P)
        target_jts = job_types or getattr(cfg.search, "job_type", ["full-time", "internship"])
        jt_map = {"full-time": "F", "full_time": "F", "internship": "I", "intern": "I", "contract": "C", "part-time": "P", "part_time": "P"}
        jt_codes = [jt_map[j.lower()] for j in target_jts if j.lower() in jt_map]
        jt_filter = f"&f_JT={'%2C'.join(jt_codes)}" if jt_codes else ""

        linkedin_url = (
            f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(search_kw)}"
            f"&location={quote_plus(search_loc)}&f_TPR=r86400{exp_filter}{jt_filter}"
        )
        _notify("info", f"Step 2: Navigating to LinkedIn page showing non-senior job roles for '{search_kw}'...")
        await page.goto(linkedin_url, wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(2.5)

        # Intelligently detect and click close icon ('X') on contextual sign-in or guest popups
        await dismiss_sign_in_popup(page)

        # ── Step 3: Extract discovered job roles ─────────────────────────
        init_db()
        roles_data = await page.evaluate("""() => {
            const list = [];
            const cards = document.querySelectorAll('.job-card-container, .base-card, .jobs-search-results__list-item');
            for (const card of cards) {
                const titleEl = card.querySelector('.job-card-list__title, .base-card__full-link, h3, a[href*="/jobs/view/"]');
                const compEl = card.querySelector('.job-card-container__primary-description, .base-card__subtitle, h4');
                const locEl = card.querySelector('.job-card-container__metadata-item, .job-search-card__location');
                const linkEl = card.querySelector('a[href*="/jobs/view/"], .base-card__full-link, a.job-card-list__title');
                const snippetEl = card.querySelector('.job-search-card__snippet, .base-search-card__metadata, .job-card-list__insight-item');
                const cardText = card.innerText || '';
                const isEasyApply = Boolean(
                    card.querySelector('.job-search-card__easy-apply, .job-card-container__apply-method') ||
                    cardText.includes('Easy Apply') ||
                    cardText.includes('Easy apply')
                );
                const applyBtn = card.querySelector('a.apply-button, a[data-tracking-control-name*="apply"]');
                const directApplyUrl = applyBtn && applyBtn.href ? applyBtn.href : (linkEl ? linkEl.href : '');

                if (titleEl && linkEl && linkEl.href) {
                    list.push({
                        title: titleEl.innerText.trim(),
                        company: compEl ? compEl.innerText.trim() : 'Company',
                        location: locEl ? locEl.innerText.trim() : '',
                        url: linkEl.href,
                        apply_url: directApplyUrl,
                        is_easy_apply: isEasyApply,
                        description: snippetEl ? snippetEl.innerText.trim() : `Role: ${titleEl.innerText.trim()} at ${compEl ? compEl.innerText.trim() : 'Company'}.`
                    });
                }
            }
            return list;
        }""")

        _notify("success", f"Discovered {len(roles_data)} job roles for '{search_kw}' on LinkedIn!")

        # Title blacklist and seniority exclusion
        blacklist_keywords = [
            k.lower() for k in getattr(cfg.blacklist, "title_keywords", []) if k
        ]
        is_senior_target = any(e.lower() in ("mid-senior", "director", "executive") for e in exp_levels)
        if not is_senior_target:
            senior_defaults = ["senior", "sr.", "sr", "lead", "principal", "staff", "director", "vp", "architect", "head of", "manager"]
            for sp in senior_defaults:
                if sp not in blacklist_keywords:
                    blacklist_keywords.append(sp)

        eligible_roles = []
        for r in roles_data:
            title = r.get("title", "")
            title_lower = title.lower()
            company = r.get("company", "")
            url = r.get("url", "")
            
            # Check if there is an encoded direct external apply form URL
            decoded_direct = decode_linkedin_apply_url(r.get("apply_url") or "")
            if decoded_direct:
                apply_url = decoded_direct
                is_easy = False
            else:
                apply_url = r.get("apply_url") or url
                is_easy = r.get("is_easy_apply", False)

            # Check seniority / title blacklist
            from src.matching.evaluator import is_senior_or_blacklisted_title
            is_blacklisted, blk_term = is_senior_or_blacklisted_title(title, blacklist_keywords)
            if is_blacklisted:
                logger.info(f"[live-search]⏭ Filtered out senior role: '{title}' @ '{company}' ({blk_term})")
                continue

            # Check if this job has already been fetched, evaluated, skipped, or applied to
            already_processed = is_job_processed(
                url=url,
                title=title,
                company=company,
                user_id=user_id,
            )

            if already_processed:
                logger.info(f"[live-search]⏭ Filtered out duplicate job already in database: '{title}' @ '{company}'")
                continue

            discovered_roles.append(r)

            # Evaluate resume match fit
            from src.matching.evaluator import evaluate_scraped_job_fit

            eval_res = evaluate_scraped_job_fit(
                title=title,
                company=company,
                description=r.get("description") or f"Position: {title} at {company}. Location: {r.get('location') or search_loc}.",
                user_id=user_id,
            )
            match_score = eval_res["match_score"]
            match_pct = eval_res["match_percentage"]
            min_score_threshold = float(getattr(getattr(cfg, "apply", None), "min_match_score", 0.60))

            if match_score >= min_score_threshold:
                eligible_roles.append(r)
                status_label = "discovered"
                _notify("info", f"🎯 Matched '{title}' @ '{company}': {match_pct}% fit (>= {int(min_score_threshold*100)}% threshold)")
            else:
                status_label = "skipped_low_fit"
                _notify("info", f"⏭ Below threshold: '{title}' @ '{company}': {match_pct}% fit (< {int(min_score_threshold*100)}%). Skipped.")

            # Persist to local database with clean separation of direct external apply vs easy apply
            try:
                save_scraped_job(
                    title=title,
                    company=company,
                    location=r.get("location") or search_loc,
                    description=r.get("description") or f"Position: {title} at {company}. Location: {r.get('location') or search_loc}.",
                    apply_url=apply_url,
                    source_name="LinkedIn",
                    is_easy_apply=is_easy,
                    user_id=user_id,
                    raw_data={
                        "source_url": url,
                        "search_keyword": search_kw,
                        "is_easy_apply": is_easy,
                        "match_percentage": match_pct,
                        "direct_apply_url": apply_url if apply_url != url else None,
                    },
                    match_score=match_score,
                    status=status_label,
                )
            except Exception:
                pass

        _notify("info", f"{len(eligible_roles)} fresh, eligible non-senior roles available to process.")

        # ── Step 4: Open top eligible job role directly in Google Chrome ───
        if open_first_role:
            if not eligible_roles:
                _notify("info", "All discovered jobs on this page are either senior roles or already in your database. No duplicate reopened.")
            else:
                top_role = eligible_roles[0]
                _notify("info", f"Step 3: Opening fresh eligible role: '{top_role['title']}' at '{top_role['company']}' in Chrome...")
                
                opened = False
                # 1. Natural in-page click if visible
                try:
                    cards = await page.query_selector_all(".base-card, .job-search-card, .job-card-container")
                    for card in cards:
                        text = await card.inner_text()
                        if top_role["company"].lower() in text.lower() or top_role["title"].lower() in text.lower():
                            link = await card.query_selector("a.base-card__full-link, a[href*='/jobs/view/'], a")
                            if link and await link.is_visible():
                                await link.click()
                                await asyncio.sleep(2.0)
                                if "authwall" not in page.url.lower():
                                    opened = True
                                    break
                except Exception as e:
                    logger.debug(f"In-page card click warning: {e}")

                # 2. Direct navigation with Google Referer header if in-page click didn't trigger
                if not opened or "authwall" in page.url.lower():
                    try:
                        await page.goto(
                            top_role["url"],
                            referer="https://www.google.com/",
                            wait_until="domcontentloaded",
                            timeout=20000,
                        )
                        await asyncio.sleep(1.5)
                    except Exception as ex:
                        _notify("warning", f"Could not navigate with referer ({ex})")

                # 3. If redirected to authwall, automatically recover via public search view
                if "authwall" in page.url.lower():
                    await recover_from_authwall(
                        page,
                        fallback_url=top_role.get("url") or linkedin_url,
                        keyword=search_kw,
                        location=search_loc,
                    )

                # Automatically detect and click close icon on contextual sign-in modal
                await dismiss_sign_in_popup(page)
                final_title = await page.title()

                # Scrape full job description and direct application form link from open page
                try:
                    full_details = await page.evaluate("""() => {
                        const descEl = document.querySelector('.show-more-less-html__markup, .jobs-description__content, .jobs-box__html-content, #job-details, .jobs-description-content__text');
                        const applyEl = document.querySelector('.apply-button, [data-tracking-control-name*="apply"], a.top-card-layout__cta--primary');
                        return {
                            description: descEl ? descEl.innerText.trim() : '',
                            apply_url: applyEl && applyEl.href ? applyEl.href : ''
                        };
                    }""")

                    # Extract direct external application form link behind the Apply button
                    direct_apply_link = await resolve_direct_apply_url_from_page(page)

                    if full_details and full_details.get("description"):
                        top_role["description"] = full_details["description"]

                    if direct_apply_link:
                        top_role["apply_url"] = direct_apply_link
                        top_role["is_easy_apply"] = False
                    elif full_details and full_details.get("apply_url"):
                        decoded = decode_linkedin_apply_url(full_details["apply_url"])
                        if decoded:
                            top_role["apply_url"] = decoded
                            top_role["is_easy_apply"] = False
                        else:
                            top_role["apply_url"] = full_details["apply_url"]

                    from src.matching.evaluator import evaluate_scraped_job_fit
                    eval_res = evaluate_scraped_job_fit(
                        title=top_role["title"],
                        company=top_role["company"],
                        description=top_role.get("description") or "",
                        user_id=user_id,
                    )
                    match_score = eval_res["match_score"]
                    save_scraped_job(
                        title=top_role["title"],
                        company=top_role["company"],
                        location=top_role.get("location") or search_loc,
                        description=top_role.get("description") or "",
                        apply_url=top_role.get("apply_url") or top_role["url"],
                        source_name="LinkedIn",
                        is_easy_apply=top_role.get("is_easy_apply", False),
                        user_id=user_id,
                        raw_data={
                            "source_url": top_role["url"],
                            "search_keyword": search_kw,
                            "match_percentage": eval_res["match_percentage"],
                            "direct_apply_url": top_role.get("apply_url") if top_role.get("apply_url") != top_role["url"] else None,
                        },
                        match_score=match_score,
                        status="discovered",
                    )
                except Exception as dx:
                    logger.debug(f"Full details extraction: {dx}")

                _notify("success", f"Job role page active in Google Chrome: '{final_title}'")

        if keep_open:
            _notify("success", "Google Chrome window is active with the selected job role. You can explore and apply!")
            return discovered_roles

    except Exception as e:
        _notify("error", f"Search and navigate error: {e}")
        logger.error(f"Error in run_google_to_linkedin_job_search: {e}", exc_info=True)
    finally:
        if not keep_open:
            try:
                await manager.close()
            except Exception:
                pass

    return discovered_roles
