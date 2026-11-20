"""
Search Node for AutoBot v2 LangGraph Agent.

Educational Concept:
In an agent state machine, environment perception begins at the search node:
1. Parameter Calibration:
   The search node reads the current target keyword, pagination index, and location
   from `AgentState` to parameterize job discovery.
2. Pluggable Perception Interface:
   By allowing an optional `job_search_provider` injection, the search node remains
   fully decoupled from Playwright browser instances. This allows fast, deterministic
   mocking in unit tests while executing real web browsing in production.
3. Queue Ingestion:
   Newly discovered job postings are enqueued into `unprocessed_jobs` for pipeline
   processing.
"""

import asyncio
import concurrent.futures
import inspect
from typing import Any, Callable, Dict, List, Optional

from src.agent.state import AgentState, JobPosting
from src.utils.logger import logger


JobSearchProvider = Callable[[str, str, int], List[JobPosting]]


def _run_coro_sync(coro):
    """Run an async coroutine synchronously from sync context safely."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


class SearchNode:
    """
    Discovers candidate job postings matching current keyword and pagination state.
    Supports both synchronous and asynchronous search providers seamlessly.
    """

    def __init__(self, search_provider: Optional[JobSearchProvider] = None):
        self.search_provider = search_provider

    def __call__(self, state: AgentState) -> Dict[str, Any]:
        keyword = state.get("current_keyword", "Software Engineer")
        location = state.get("location", "India")
        page = state.get("current_page", 1)

        logger.info(
            f"[agent]🔍 Searching jobs: '{keyword}' in '{location}' (page {page})...[/agent]"
        )

        discovered_jobs: List[JobPosting] = []

        if self.search_provider:
            try:
                res = self.search_provider(keyword, location, page)
                if inspect.isawaitable(res):
                    discovered_jobs = _run_coro_sync(res)
                else:
                    discovered_jobs = res or []
            except Exception as e:
                logger.error(f"Search provider error: {e}")
                discovered_jobs = []

        if not discovered_jobs:
            try:
                from src.storage.db import get_db_connection, init_db
                init_db()
                with get_db_connection() as conn:
                    pattern = f"%{keyword}%"
                    sql = """
                        SELECT j.* FROM jobs j
                        WHERE j.status NOT IN ('expired', 'rejected_seniority', 'purged_senior', 'skipped_seniority')
                        AND (j.title LIKE ? OR j.description LIKE ?)
                        AND NOT EXISTS (
                            SELECT 1 FROM applications a
                            WHERE a.job_id = j.stable_id
                               OR a.job_id = CAST(j.id AS TEXT)
                               OR (LOWER(TRIM(a.job_title)) = LOWER(TRIM(j.title)) AND LOWER(TRIM(a.company)) = LOWER(TRIM(j.company)))
                        )
                        ORDER BY j.id DESC LIMIT 20
                    """
                    rows = conn.execute(sql, (pattern, pattern)).fetchall()
                    if not rows:
                        rows = conn.execute("""
                            SELECT j.* FROM jobs j
                            WHERE j.status NOT IN ('expired', 'rejected_seniority', 'purged_senior', 'skipped_seniority')
                            AND NOT EXISTS (
                                SELECT 1 FROM applications a
                                WHERE a.job_id = j.stable_id
                                   OR a.job_id = CAST(j.id AS TEXT)
                                   OR (LOWER(TRIM(a.job_title)) = LOWER(TRIM(j.title)) AND LOWER(TRIM(a.company)) = LOWER(TRIM(j.company)))
                            )
                            ORDER BY j.id DESC LIMIT 20
                        """).fetchall()
                    for r in rows:
                        discovered_jobs.append(JobPosting(
                            job_id=str(r["id"]),
                            title=r["title"],
                            company=r["company"],
                            location=r["location"] or "Remote",
                            url=r["application_url"] or "",
                            description=r["description"] or "",
                            posted_date=r["publication_date"] or "",
                            source=r["source_name"] or "ats",
                        ))
            except Exception as e:
                logger.debug(f"Database job search fallback error: {e}")

        from src.matching.evaluator import is_senior_or_blacklisted_title
        clean_discovered_jobs: List[JobPosting] = []
        for dj in discovered_jobs:
            is_sr, sr_kw = is_senior_or_blacklisted_title(dj.title)
            if is_sr:
                logger.info(f"[agent]⏭ Filtered out senior role in search: '{dj.title}' @ '{dj.company}' ({sr_kw})")
                continue
            clean_discovered_jobs.append(dj)

        logger.info(
            f"[agent]📋 Found {len(clean_discovered_jobs)} eligible non-senior job postings on page {page}.[/agent]"
        )

        # Merge newly discovered jobs with any existing unprocessed jobs, deduplicating
        existing_jobs = list(state.get("unprocessed_jobs", []))
        seen_keys = {
            (j.job_id, (j.title or "").strip().lower(), (j.company or "").strip().lower())
            for j in existing_jobs
        }
        for dj in clean_discovered_jobs:
            key = (dj.job_id, (dj.title or "").strip().lower(), (dj.company or "").strip().lower())
            if key not in seen_keys:
                seen_keys.add(key)
                existing_jobs.append(dj)
        updated_queue = existing_jobs

        return {
            "unprocessed_jobs": updated_queue,
            "status_message": f"Discovered {len(discovered_jobs)} jobs for '{keyword}' page {page}.",
        }

    async def acall(self, state: AgentState) -> Dict[str, Any]:
        keyword = state.get("current_keyword", "Software Engineer")
        location = state.get("location", "India")
        page = state.get("current_page", 1)

        logger.info(
            f"[agent]🔍 Searching jobs: '{keyword}' in '{location}' (page {page})...[/agent]"
        )

        discovered_jobs: List[JobPosting] = []

        if self.search_provider:
            try:
                res = self.search_provider(keyword, location, page)
                if inspect.isawaitable(res):
                    discovered_jobs = await res
                else:
                    discovered_jobs = res or []
            except Exception as e:
                logger.error(f"Search provider error: {e}")
                discovered_jobs = []

        if not discovered_jobs:
            try:
                from src.storage.db import get_db_connection, init_db
                init_db()
                with get_db_connection() as conn:
                    pattern = f"%{keyword}%"
                    sql = """
                        SELECT j.* FROM jobs j
                        WHERE j.status NOT IN ('expired', 'rejected_seniority', 'purged_senior', 'skipped_seniority')
                        AND (j.title LIKE ? OR j.description LIKE ?)
                        AND NOT EXISTS (
                            SELECT 1 FROM applications a
                            WHERE a.job_id = j.stable_id
                               OR a.job_id = CAST(j.id AS TEXT)
                               OR (LOWER(TRIM(a.job_title)) = LOWER(TRIM(j.title)) AND LOWER(TRIM(a.company)) = LOWER(TRIM(j.company)))
                        )
                        ORDER BY j.id DESC LIMIT 20
                    """
                    rows = conn.execute(sql, (pattern, pattern)).fetchall()
                    if not rows:
                        rows = conn.execute("""
                            SELECT j.* FROM jobs j
                            WHERE j.status NOT IN ('expired', 'rejected_seniority', 'purged_senior', 'skipped_seniority')
                            AND NOT EXISTS (
                                SELECT 1 FROM applications a
                                WHERE a.job_id = j.stable_id
                                   OR a.job_id = CAST(j.id AS TEXT)
                                   OR (LOWER(TRIM(a.job_title)) = LOWER(TRIM(j.title)) AND LOWER(TRIM(a.company)) = LOWER(TRIM(j.company)))
                            )
                            ORDER BY j.id DESC LIMIT 20
                        """).fetchall()
                    for r in rows:
                        discovered_jobs.append(JobPosting(
                            job_id=str(r["id"]),
                            title=r["title"],
                            company=r["company"],
                            location=r["location"] or "Remote",
                            url=r["application_url"] or "",
                            description=r["description"] or "",
                            posted_date=r["publication_date"] or "",
                            source=r["source_name"] or "ats",
                        ))
            except Exception as e:
                logger.debug(f"Database job search fallback error: {e}")

        from src.matching.evaluator import is_senior_or_blacklisted_title
        clean_discovered_jobs: List[JobPosting] = []
        for dj in discovered_jobs:
            is_sr, sr_kw = is_senior_or_blacklisted_title(dj.title)
            if is_sr:
                logger.info(f"[agent]⏭ Filtered out senior role in search: '{dj.title}' @ '{dj.company}' ({sr_kw})")
                continue
            clean_discovered_jobs.append(dj)

        logger.info(
            f"[agent]📋 Found {len(clean_discovered_jobs)} eligible non-senior job postings on page {page}.[/agent]"
        )

        # Merge newly discovered jobs with any existing unprocessed jobs, deduplicating
        existing_jobs = list(state.get("unprocessed_jobs", []))
        seen_keys = {
            (j.job_id, (j.title or "").strip().lower(), (j.company or "").strip().lower())
            for j in existing_jobs
        }
        for dj in clean_discovered_jobs:
            key = (dj.job_id, (dj.title or "").strip().lower(), (dj.company or "").strip().lower())
            if key not in seen_keys:
                seen_keys.add(key)
                existing_jobs.append(dj)
        updated_queue = existing_jobs

        return {
            "unprocessed_jobs": updated_queue,
            "status_message": f"Discovered {len(discovered_jobs)} jobs for '{keyword}' page {page}.",
        }
