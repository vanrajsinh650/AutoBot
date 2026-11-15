"""
Apply Node for AutoBot v2 LangGraph Agent.

Educational Concept:
The apply node represents the actuator layer of the agent:
1. Dry-Run Safety Simulation:
   When `dry_run=True` (e.g. running `python main.py --dry-run`), the agent performs
   full discovery, filtering, RAG retrieval, and scoring, but halts immediately
   before form submission. This allows users to inspect agent judgment risk-free.
2. Pluggable Application Executor:
   Decoupled interface (`ApplicationExecutor`) allowing mock execution during tests
   and Playwright browser form filling during live deployment.
3. Cover Letter Synthesis:
   Optionally synthesizes a customized cover letter using `CoverLetterGenerator`
   to upload or paste into the application form.
"""

import asyncio
import concurrent.futures
import inspect
from typing import Any, Callable, Dict, Optional

from src.agent.state import AgentState, ApplicationOutcome, JobPosting
from src.memory.cover_letter import CoverLetterGenerator
from src.utils.logger import logger


ApplicationExecutor = Callable[[JobPosting, Optional[str]], bool]


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


class ApplyNode:
    """
    Submits an application for the active JobPosting via browser automation or simulation.
    Supports both sync and async application executors.
    """

    def __init__(
        self,
        executor: Optional[ApplicationExecutor] = None,
        cover_letter_gen: Optional[CoverLetterGenerator] = None,
    ):
        self.executor = executor
        self.cover_letter_gen = cover_letter_gen

    def __call__(self, state: AgentState) -> Dict[str, Any]:
        current_job = state.get("current_job")
        if not current_job:
            return {"status_message": "No active job to apply for."}

        is_dry_run = state.get("dry_run", False)
        applied_count = state.get("applied_count", 0)
        failed_count = state.get("failed_count", 0)

        # ── 1. Synthesize Tailored Cover Letter (if generator available)
        cover_letter_text = None
        if self.cover_letter_gen:
            try:
                cover_letter = self.cover_letter_gen.generate(
                    job_title=current_job.title,
                    company=current_job.company,
                    job_description=current_job.description,
                )
                cover_letter_text = cover_letter.content
            except Exception as e:
                logger.warning(f"Could not generate cover letter: {e}")

        # ── 2. Handle Dry-Run Simulation ──────────────────────────────
        if is_dry_run:
            logger.info(
                f"[agent]🧪 [DRY RUN] Simulated application to '{current_job.title}' @ '{current_job.company}'[/agent]"
            )
            return {
                "last_outcome": ApplicationOutcome.DRY_RUN,
                "applied_count": applied_count + 1,
                "status_message": f"[DRY RUN] Simulated application for {current_job.title}",
            }

        # ── 3. Live Form Submission via Executor ──────────────────────
        logger.info(
            f"[agent]🚀 Submitting application to '{current_job.title}' @ '{current_job.company}'...[/agent]"
        )

        success = True
        if self.executor:
            try:
                res = self.executor(current_job, cover_letter_text)
                if inspect.isawaitable(res):
                    success = bool(_run_coro_sync(res))
                else:
                    success = bool(res)
            except Exception as e:
                logger.error(f"Application execution error for {current_job.job_id}: {e}")
                success = False

        if success:
            logger.info(
                f"[agent]🎉 Successfully applied to '{current_job.title}' @ '{current_job.company}'![/agent]"
            )
            return {
                "last_outcome": ApplicationOutcome.APPLIED,
                "applied_count": applied_count + 1,
                "status_message": f"Successfully applied: {current_job.title}",
            }
        else:
            logger.warning(
                f"[agent]❌ Failed to apply to '{current_job.title}' @ '{current_job.company}'.[/agent]"
            )
            return {
                "last_outcome": ApplicationOutcome.FAILED,
                "failed_count": failed_count + 1,
                "status_message": f"Application failed: {current_job.title}",
            }

    async def acall(self, state: AgentState) -> Dict[str, Any]:
        current_job = state.get("current_job")
        if not current_job:
            return {"status_message": "No active job to apply for."}

        is_dry_run = state.get("dry_run", False)
        applied_count = state.get("applied_count", 0)
        failed_count = state.get("failed_count", 0)

        # ── 1. Synthesize Tailored Cover Letter (if generator available)
        cover_letter_text = None
        if self.cover_letter_gen:
            try:
                cover_letter = self.cover_letter_gen.generate(
                    job_title=current_job.title,
                    company=current_job.company,
                    job_description=current_job.description,
                )
                cover_letter_text = cover_letter.content
            except Exception as e:
                logger.warning(f"Could not generate cover letter: {e}")

        # ── 2. Handle Dry-Run Simulation ──────────────────────────────
        if is_dry_run:
            logger.info(
                f"[agent]🧪 [DRY RUN] Simulated application to '{current_job.title}' @ '{current_job.company}'[/agent]"
            )
            return {
                "last_outcome": ApplicationOutcome.DRY_RUN,
                "applied_count": applied_count + 1,
                "status_message": f"[DRY RUN] Simulated application for {current_job.title}",
            }

        # ── 3. Live Form Submission via Executor ──────────────────────
        logger.info(
            f"[agent]🚀 Submitting application to '{current_job.title}' @ '{current_job.company}'...[/agent]"
        )

        success = True
        if self.executor:
            try:
                res = self.executor(current_job, cover_letter_text)
                if inspect.isawaitable(res):
                    success = bool(await res)
                else:
                    success = bool(res)
            except Exception as e:
                logger.error(f"Application execution error for {current_job.job_id}: {e}")
                success = False

        if success:
            logger.info(
                f"[agent]🎉 Successfully applied to '{current_job.title}' @ '{current_job.company}'![/agent]"
            )
            return {
                "last_outcome": ApplicationOutcome.APPLIED,
                "applied_count": applied_count + 1,
                "status_message": f"Successfully applied: {current_job.title}",
            }
        else:
            logger.warning(
                f"[agent]❌ Failed to apply to '{current_job.title}' @ '{current_job.company}'.[/agent]"
            )
            return {
                "last_outcome": ApplicationOutcome.FAILED,
                "failed_count": failed_count + 1,
                "status_message": f"Application failed: {current_job.title}",
            }
