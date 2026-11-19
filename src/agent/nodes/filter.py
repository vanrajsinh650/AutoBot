"""
Filter Node for AutoBot v2 LangGraph Agent.

Educational Concept:
Deterministic filtering is the first line of defense in agentic execution:
1. Fast-Path Rejection:
   Expensive LLM reasoning and slow browser interactions should only occur for jobs
   that pass basic eligibility criteria.
2. Invariants Checked:
   - Already Applied Check: Queries the SQLite database to avoid embarrassing duplicate
     applications.
   - Company Blacklist: Enforces exclusion of companies configured in `config.yaml`
     (e.g., current employer or unwanted firms).
   - Title Keyword Blacklist: Filters out unwanted seniorities (e.g., "10+ years",
     "Director", "Principal") before spending LLM tokens on evaluation.
3. Queue Consumption:
   Pops the next candidate vacancy from `unprocessed_jobs` into `current_job`.
"""

import re
from typing import Any, Dict, List, Optional

from src.agent.state import AgentState, JobPosting
from src.storage.db import get_db_path, is_already_applied, is_job_processed
from src.utils.config import get_config
from src.utils.logger import logger


class FilterNode:
    """
    Dequeues the next job vacancy and executes deterministic deduplication and blacklist checks.
    """

    def __init__(
        self,
        blacklist_companies: Optional[List[str]] = None,
        blacklist_keywords: Optional[List[str]] = None,
        db_path: Optional[str] = None,
    ):
        self.db_path = db_path or get_db_path()
        if blacklist_companies is not None:
            self.blacklist_companies = [c.lower() for c in blacklist_companies if c]
        else:
            try:
                self.blacklist_companies = [
                    c.lower() for c in get_config().blacklist.companies if c
                ]
            except Exception:
                self.blacklist_companies = []

        if blacklist_keywords is not None:
            self.blacklist_keywords = [
                k.lower() for k in blacklist_keywords if k
            ]
        else:
            try:
                self.blacklist_keywords = [
                    k.lower() for k in get_config().blacklist.title_keywords if k
                ]
            except Exception:
                self.blacklist_keywords = []

    def __call__(self, state: AgentState) -> Dict[str, Any]:
        unprocessed = list(state.get("unprocessed_jobs", []))
        if not unprocessed:
            return {
                "current_job": None,
                "skip_reason": None,
                "status_message": "No jobs remaining in current queue.",
            }

        # Pop next job from FIFO queue
        current_job: JobPosting = unprocessed.pop(0)
        job_id = current_job.job_id
        title_lower = current_job.title.lower()
        company_lower = current_job.company.lower()

        # ── Check 1: Already Applied or Processed ─────────────────────
        if is_already_applied(job_id, db_path=self.db_path) or is_job_processed(
            job_id=job_id,
            url=getattr(current_job, "url", ""),
            title=current_job.title,
            company=current_job.company,
            db_path=self.db_path,
        ):
            skip_msg = f"Already applied or processed job_id '{job_id}' ({current_job.title} @ {current_job.company})"
            logger.info(f"[agent]⏭ Skip: {current_job.title} @ {current_job.company} ({skip_msg})[/agent]")
            return {
                "unprocessed_jobs": unprocessed,
                "current_job": current_job,
                "skip_reason": skip_msg,
                "status_message": skip_msg,
            }

        # ── Check 2: Blacklisted Company ──────────────────────────────
        for blk in self.blacklist_companies:
            if blk in company_lower:
                skip_msg = f"Company '{current_job.company}' matches blacklist '{blk}'"
                logger.info(f"[agent]⏭ Skip: {current_job.title} @ {current_job.company} ({skip_msg})[/agent]")
                return {
                    "unprocessed_jobs": unprocessed,
                    "current_job": current_job,
                    "skip_reason": skip_msg,
                    "status_message": skip_msg,
                }

        # ── Check 3: Blacklisted Title Keywords ───────────────────────
        for blk in self.blacklist_keywords:
            clean_blk = blk.strip().lower()
            if not clean_blk:
                continue
            if clean_blk.isalnum():
                matched = bool(re.search(rf"\b{re.escape(clean_blk)}\b", title_lower))
            else:
                matched = clean_blk in title_lower
            if matched:
                skip_msg = f"Title '{current_job.title}' contains blacklisted keyword '{blk}'"
                logger.info(f"[agent]⏭ Skip: {current_job.title} @ {current_job.company} ({skip_msg})[/agent]")
                return {
                    "unprocessed_jobs": unprocessed,
                    "current_job": current_job,
                    "skip_reason": skip_msg,
                    "status_message": skip_msg,
                }

        # Candidate job passed all deterministic filters!
        logger.info(
            f"[agent]Selected '{current_job.title}' @ '{current_job.company}' for evaluation.[/agent]"
        )
        return {
            "unprocessed_jobs": unprocessed,
            "current_job": current_job,
            "skip_reason": None,
            "status_message": f"Candidate job passed deterministic filters: {current_job.title}",
        }
