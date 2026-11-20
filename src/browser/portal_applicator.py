"""
Automated Portal Application Runner for AutoBot v2.
Orchestrates automated application submissions to external ATS career portals
(Ashby, Greenhouse, Lever, Workday, SmartRecruiters, etc.) for individually
selected jobs or batch-selected jobs.
"""

import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from src.agent.state import JobPosting
from src.application.workflows import AntiBotChallengeDetected, LinkedInPolicyViolationError
from src.browser.easy_apply_actuator import EasyApplyActuator
from src.browser.external_apply_actuator import ExternalApplyActuator, load_candidate_profile_info
from src.browser.linkedin_apply_extractor import (
    decode_linkedin_apply_url,
    resolve_direct_apply_url_from_page,
)
from src.browser.manager import BrowserManager
from src.browser.popup_handler import dismiss_sign_in_popup
from src.storage.db import get_db_connection, get_db_path, init_db, save_application
from src.utils.config import AppConfig, get_config, get_env
from src.utils.logger import logger


async def apply_to_portals(
    job_ids: List[Union[int, str]],
    user_id: int = 1,
    dry_run: bool = False,
    headless: bool = True,
    progress_callback: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Automate applying to a list of external jobs.

    Args:
        job_ids: List of job database IDs or stable IDs to apply to.
        user_id: User ID for database multi-tenant tracking.
        dry_run: If True, fills out forms without pressing final submit.
        headless: Whether to run headlessly in background mode.
        progress_callback: Optional callback(level, message, meta_dict) for live telemetry.
        db_path: Optional custom database path.

    Returns:
        Summary dictionary of outcomes.
    """
    cfg = get_config()
    env = get_env()
    active_db = db_path or get_db_path()
    init_db(active_db)

    def _notify(level: str, message: str, meta: Optional[Dict[str, Any]] = None):
        logger.info(f"[portal-bot]{message}[/portal-bot]")
        if progress_callback:
            try:
                progress_callback(level, message, meta or {})
            except Exception:
                pass

    if not job_ids:
        _notify("warning", "No jobs selected for automated application.")
        return {"success": False, "total": 0, "succeeded": 0, "failed": 0, "results": []}

    _notify(
        "info",
        f"Starting Auto-Apply Bot for {len(job_ids)} selected job(s) "
        f"(dry_run={dry_run}, background={headless})...",
        {"total": len(job_ids)},
    )

    # 1. Fetch job records from database
    jobs_to_apply: List[Dict[str, Any]] = []
    with get_db_connection(active_db) as conn:
        for jid in job_ids:
            try:
                if str(jid).isdigit():
                    row = conn.execute(
                        """
                        SELECT j.*, a.status AS app_status, a.apply_type AS app_apply_type,
                               a.url AS app_url, a.notes AS app_notes
                        FROM jobs j
                        LEFT JOIN applications a ON (a.job_id = j.stable_id OR a.job_id = CAST(j.id AS TEXT))
                        WHERE j.id = ?
                        LIMIT 1
                        """,
                        (int(jid),),
                    ).fetchone()
                else:
                    row = conn.execute(
                        """
                        SELECT j.*, a.status AS app_status, a.apply_type AS app_apply_type,
                               a.url AS app_url, a.notes AS app_notes
                        FROM jobs j
                        LEFT JOIN applications a ON (a.job_id = j.stable_id OR a.job_id = CAST(j.id AS TEXT))
                        WHERE j.stable_id = ? OR j.id = ?
                        LIMIT 1
                        """,
                        (str(jid), str(jid)),
                    ).fetchone()

                if row:
                    jobs_to_apply.append(dict(row))
                else:
                    # Check if row is directly in applications table
                    app_row = conn.execute(
                        "SELECT * FROM applications WHERE id = ? OR job_id = ? LIMIT 1",
                        (str(jid), str(jid)),
                    ).fetchone()
                    if app_row:
                        app_dict = dict(app_row)
                        jobs_to_apply.append({
                            "id": app_dict.get("id"),
                            "stable_id": app_dict.get("job_id"),
                            "title": app_dict.get("job_title"),
                            "company": app_dict.get("company"),
                            "location": app_dict.get("location"),
                            "application_url": app_dict.get("url"),
                            "source_name": app_dict.get("source_name") or "External ATS",
                            "description": app_dict.get("notes") or "",
                        })
            except Exception as e:
                logger.debug(f"Error fetching job {jid}: {e}")

    if not jobs_to_apply:
        _notify("error", "None of the selected jobs could be found in the database.")
        return {"success": False, "total": 0, "succeeded": 0, "failed": 0, "results": []}

    _notify("info", f"Loaded {len(jobs_to_apply)} job records. Initializing browser session...")

    # 2. Initialize BrowserManager and Actuator
    manager = BrowserManager(
        cfg=cfg,
        env=env,
        headless=headless,
        user_id=user_id,
    )

    results: List[Dict[str, Any]] = []
    succeeded = 0
    failed = 0

    try:
        await manager.start()
        context = manager.context
        if not context:
            raise RuntimeError("Browser context could not be created.")

        candidate_info = load_candidate_profile_info(cfg)
        actuator = ExternalApplyActuator(
            context=context,
            cfg=cfg,
            candidate_info=candidate_info,
        )

        for idx, job in enumerate(jobs_to_apply, start=1):
            title = job.get("title") or "Unknown Role"
            company = job.get("company") or "Company"
            target_url = job.get("application_url") or job.get("app_url") or ""
            job_stable_id = job.get("stable_id") or str(job.get("id"))

            if not target_url:
                _notify("warning", f"({idx}/{len(jobs_to_apply)}) No apply URL for '{title}' @ '{company}'. Skipping.", {"job_id": job.get("id"), "stable_id": job_stable_id, "status": "skipped"})
                failed += 1
                results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "skipped", "reason": "No apply URL"})
                continue

            # ── Check if Job is LinkedIn Easy Apply ──────────────────
            raw_is_easy = False
            if job.get("raw_data"):
                try:
                    rd = json.loads(job["raw_data"]) if isinstance(job["raw_data"], str) else job["raw_data"]
                    if isinstance(rd, dict):
                        raw_is_easy = bool(rd.get("is_easy_apply"))
                except Exception:
                    pass

            is_easy = bool(
                job.get("app_apply_type") == "easy_apply"
                or "easy apply" in (job.get("source_name") or "").lower()
                or job.get("is_easy_apply") is True
                or raw_is_easy
            )

            if is_easy:
                _notify(
                    "info",
                    f"({idx}/{len(jobs_to_apply)}) 🚀 Autonomously applying via LinkedIn Easy Apply for '{title}' @ '{company}'...",
                    {"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "applying"},
                )

                job_posting = JobPosting(
                    job_id=job_stable_id,
                    title=title,
                    company=company,
                    location=job.get("location") or "Remote",
                    url=target_url,
                    description=job.get("description") or "",
                    is_easy_apply=True,
                )

                easy_page = None
                try:
                    easy_page = await context.new_page()
                    easy_actuator = EasyApplyActuator(
                        page=easy_page,
                        cfg=cfg,
                        candidate_info=candidate_info,
                    )
                    success = await easy_actuator.apply(
                        job=job_posting,
                        dry_run=dry_run,
                    )

                    if success:
                        succeeded += 1
                        status = "dry_run" if dry_run else "applied"
                        note = "Applied via AutoBot LinkedIn Easy Apply (dry-run simulation)" if dry_run else "Submitted via AutoBot LinkedIn Easy Apply"
                        save_application(
                            job_id=job_stable_id,
                            job_title=title,
                            company=company,
                            location=job.get("location") or "Remote",
                            apply_type="easy_apply",
                            match_score=0.9,
                            status=status,
                            url=target_url,
                            notes=note,
                            db_path=active_db,
                            user_id=user_id,
                        )
                        _notify(
                            "success",
                            f"({idx}/{len(jobs_to_apply)}) ✅ LinkedIn Easy Apply for '{title}' @ '{company}' completed ({status})!",
                            {"job_id": job.get("id"), "stable_id": job_stable_id, "status": status, "success": True},
                        )
                        results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": status, "success": True})
                    else:
                        failed += 1
                        _notify(
                            "warning",
                            f"({idx}/{len(jobs_to_apply)}) ⚠ LinkedIn Easy Apply for '{title}' @ '{company}' could not complete automatically.",
                            {"job_id": job.get("id"), "stable_id": job_stable_id, "status": "requires_manual", "success": False},
                        )
                        results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "requires_manual", "success": False})

                except AntiBotChallengeDetected as abc:
                    failed += 1
                    _notify(
                        "warning",
                        f"({idx}/{len(jobs_to_apply)}) 🛑 Security challenge gate on LinkedIn for {company}: {abc}.",
                        {"job_id": job.get("id"), "stable_id": job_stable_id, "status": "challenge_detected", "success": False},
                    )
                    results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "challenge_detected", "success": False})

                except Exception as ex:
                    failed += 1
                    logger.warning(f"Easy Apply error on {title} @ {company}: {ex}")
                    _notify(
                        "error",
                        f"({idx}/{len(jobs_to_apply)}) ❌ Error in LinkedIn Easy Apply for '{title}' @ '{company}': {ex}",
                        {"job_id": job.get("id"), "stable_id": job_stable_id, "status": "failed", "success": False},
                    )
                    results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "failed", "success": False})
                finally:
                    if easy_page:
                        try:
                            await easy_page.close()
                        except Exception:
                            pass

                if idx < len(jobs_to_apply):
                    await asyncio.sleep(2.0)
                continue

            # ── External Apply (or LinkedIn External Form Link) ───────
            # Automatically resolve direct external form link if URL is currently pointing to LinkedIn
            if any(li in target_url.lower() for li in ("linkedin.com", "lnkd.in")):
                decoded_target = decode_linkedin_apply_url(target_url)
                if not decoded_target:
                    _notify("info", f"({idx}/{len(jobs_to_apply)}) 🎯 Extracting direct external application form link from LinkedIn for '{title}' @ '{company}'...")
                    temp_page = None
                    try:
                        temp_page = await context.new_page()
                        await temp_page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
                        await dismiss_sign_in_popup(temp_page)
                        decoded_target = await resolve_direct_apply_url_from_page(temp_page, timeout_ms=8000)

                        # If direct outbound ATS link was not found, check if it actually has an Easy Apply button
                        if not decoded_target:
                            easy_btn = await temp_page.query_selector(
                                ".jobs-apply-button:has-text('Easy Apply'), button[aria-label*='Easy Apply'], .jobs-s-apply button"
                            )
                            if easy_btn:
                                _notify("info", f"({idx}/{len(jobs_to_apply)}) Discovered Easy Apply button on LinkedIn page for '{title}' @ '{company}'. Running Easy Apply...")
                                easy_actuator = EasyApplyActuator(
                                    page=temp_page,
                                    cfg=cfg,
                                    candidate_info=candidate_info,
                                )
                                job_posting = JobPosting(
                                    job_id=job_stable_id,
                                    title=title,
                                    company=company,
                                    location=job.get("location") or "Remote",
                                    url=target_url,
                                    description=job.get("description") or "",
                                    is_easy_apply=True,
                                )
                                success = await easy_actuator.apply(job=job_posting, dry_run=dry_run)
                                if success:
                                    succeeded += 1
                                    status = "dry_run" if dry_run else "applied"
                                    note = "Applied via AutoBot LinkedIn Easy Apply (dry-run simulation)" if dry_run else "Submitted via AutoBot LinkedIn Easy Apply"
                                    save_application(
                                        job_id=job_stable_id,
                                        job_title=title,
                                        company=company,
                                        location=job.get("location") or "Remote",
                                        apply_type="easy_apply",
                                        match_score=0.9,
                                        status=status,
                                        url=target_url,
                                        notes=note,
                                        db_path=active_db,
                                        user_id=user_id,
                                    )
                                    _notify(
                                        "success",
                                        f"({idx}/{len(jobs_to_apply)}) ✅ LinkedIn Easy Apply for '{title}' @ '{company}' completed ({status})!",
                                        {"job_id": job.get("id"), "stable_id": job_stable_id, "status": status, "success": True},
                                    )
                                    results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": status, "success": True})
                                else:
                                    failed += 1
                                    _notify(
                                        "warning",
                                        f"({idx}/{len(jobs_to_apply)}) ⚠ LinkedIn Easy Apply for '{title}' @ '{company}' requires manual completion.",
                                        {"job_id": job.get("id"), "stable_id": job_stable_id, "status": "requires_manual", "success": False},
                                    )
                                    results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "requires_manual", "success": False})

                                await temp_page.close()
                                temp_page = None
                                if idx < len(jobs_to_apply):
                                    await asyncio.sleep(2.0)
                                continue
                    except Exception as resolve_err:
                        logger.debug(f"Direct link resolution from LinkedIn page failed: {resolve_err}")
                    finally:
                        if temp_page:
                            try:
                                await temp_page.close()
                            except Exception:
                                pass

                if decoded_target:
                    _notify("success", f"🎯 Extracted direct form link for {company}: {decoded_target}")
                    target_url = decoded_target
                    job["application_url"] = target_url
                    try:
                        with get_db_connection(active_db) as uconn:
                            uconn.execute(
                                "UPDATE jobs SET application_url = ? WHERE stable_id = ? OR id = ?",
                                (target_url, job_stable_id, job.get("id")),
                            )
                            uconn.execute(
                                "UPDATE applications SET url = ?, apply_type = 'external' WHERE job_id = ? OR id = ?",
                                (target_url, job_stable_id, job.get("id")),
                            )
                    except Exception:
                        pass
                else:
                    _notify(
                        "warning",
                        f"({idx}/{len(jobs_to_apply)}) Could not extract direct external ATS link for '{title}' @ '{company}'. Target is still on LinkedIn.",
                        {"job_id": job.get("id"), "stable_id": job_stable_id, "status": "requires_manual"},
                    )
                    failed += 1
                    results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "requires_manual", "reason": "Could not resolve direct ATS link from LinkedIn"})
                    if idx < len(jobs_to_apply):
                        await asyncio.sleep(2.0)
                    continue

            _notify(
                "info",
                f"({idx}/{len(jobs_to_apply)}) Applying to external portal for '{title}' @ '{company}'...",
                {"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "applying"},
            )

            job_posting = JobPosting(
                job_id=job_stable_id,
                title=title,
                company=company,
                location=job.get("location") or "Remote",
                url=target_url,
                description=job.get("description") or "",
                external_apply_url=target_url,
                is_easy_apply=False,
            )

            try:
                success = await actuator.apply(
                    job=job_posting,
                    apply_url=target_url,
                    dry_run=dry_run,
                )

                if success:
                    succeeded += 1
                    status = "dry_run" if dry_run else "applied"
                    note = "Applied via AutoBot external form applicator (dry-run simulation)" if dry_run else "Submitted via AutoBot external form applicator"
                    save_application(
                        job_id=job_stable_id,
                        job_title=title,
                        company=company,
                        location=job.get("location") or "Remote",
                        apply_type="external_apply",
                        match_score=0.9,
                        status=status,
                        url=target_url,
                        notes=note,
                        db_path=active_db,
                        user_id=user_id,
                    )
                    _notify(
                        "success",
                        f"({idx}/{len(jobs_to_apply)}) ✅ Application to '{title}' @ '{company}' completed ({status})!",
                        {"job_id": job.get("id"), "stable_id": job_stable_id, "status": status, "success": True},
                    )
                    results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": status, "success": True})
                else:
                    failed += 1
                    _notify(
                        "warning",
                        f"({idx}/{len(jobs_to_apply)}) ⚠ Application to '{title}' @ '{company}' requires manual completion.",
                        {"job_id": job.get("id"), "stable_id": job_stable_id, "status": "requires_manual", "success": False},
                    )
                    results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "requires_manual", "success": False})

            except AntiBotChallengeDetected as abc:
                failed += 1
                _notify(
                    "warning",
                    f"({idx}/{len(jobs_to_apply)}) 🛑 Security challenge gate on {company}: {abc}. Saved for manual review.",
                    {"job_id": job.get("id"), "stable_id": job_stable_id, "status": "challenge_detected", "success": False},
                )
                results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "challenge_detected", "success": False})

            except LinkedInPolicyViolationError as lpe:
                failed += 1
                _notify(
                    "warning",
                    f"({idx}/{len(jobs_to_apply)}) ⏭ LinkedIn URL detected: {lpe}. Skipping automated external submit.",
                    {"job_id": job.get("id"), "stable_id": job_stable_id, "status": "skipped_policy", "success": False},
                )
                results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "skipped_policy", "success": False})

            except Exception as ex:
                failed += 1
                _notify(
                    "error",
                    f"({idx}/{len(jobs_to_apply)}) ❌ Error applying to '{title}' @ '{company}': {ex}",
                    {"job_id": job.get("id"), "stable_id": job_stable_id, "status": "failed", "success": False},
                )
                results.append({"job_id": job.get("id"), "stable_id": job_stable_id, "title": title, "company": company, "status": "failed", "success": False})

            # Polite human pacing between applications
            if idx < len(jobs_to_apply):
                await asyncio.sleep(2.0)

    except Exception as e:
        logger.error(f"Error in apply_to_portals: {e}", exc_info=True)
        _notify("error", f"Fatal error during portal application run: {e}")
    finally:
        try:
            await manager.close()
        except Exception:
            pass

    _notify(
        "success" if succeeded > 0 else "info",
        f"Auto-Apply Bot run complete! Succeeded: {succeeded}, Failed/Manual: {failed}, Total: {len(jobs_to_apply)}.",
        {"succeeded": succeeded, "failed": failed, "total": len(jobs_to_apply)},
    )

    return {
        "success": succeeded > 0,
        "total": len(jobs_to_apply),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }
