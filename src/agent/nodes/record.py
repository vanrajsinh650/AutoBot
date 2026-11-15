"""
Record Node for AutoBot v2 LangGraph Agent.

Educational Concept:
The record node commits transactional history to SQLite and updates the audit log:
1. State Audit Trail:
   Constructs an ApplicationResult snapshot encapsulating the job, outcome,
   semantic match score, and notes.
2. Database Persistence:
   Calls `save_application` to write the result into SQLite, guaranteeing that
   future sessions or crash restarts will not duplicate work.
3. Pipeline Housekeeping:
   Clears temporary per-vacancy registers (`current_job`, `current_evaluation`,
   `skip_reason`, `last_outcome`) to prepare the state machine for the next iteration.
"""

from datetime import datetime
from typing import Any, Dict

from src.agent.state import AgentState, ApplicationOutcome, ApplicationResult
from src.storage.db import get_db_path, save_application
from src.utils.logger import logger


class RecordNode:
    """
    Persists application outcomes to SQLite and maintains the in-memory execution history.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_db_path()

    def __call__(self, state: AgentState) -> Dict[str, Any]:
        current_job = state.get("current_job")
        if not current_job:
            return {"status_message": "No job to record."}

        skip_reason = state.get("skip_reason")
        last_outcome = state.get("last_outcome")
        skipped_count = state.get("skipped_count", 0)
        history = list(state.get("history", []))

        evaluation = state.get("current_evaluation")
        match_score = evaluation.match_score if evaluation else 0.0

        apply_type = "easy_apply" if current_job.is_easy_apply else "external"

        # ── 1. Determine Status & Reason ──────────────────────────────
        if skip_reason:
            status = ApplicationOutcome.SKIPPED
            reason = skip_reason
            new_skipped_count = skipped_count + 1
        elif last_outcome == ApplicationOutcome.DRY_RUN:
            status = ApplicationOutcome.DRY_RUN
            reason = "Dry-run simulation"
            new_skipped_count = skipped_count
        elif last_outcome == ApplicationOutcome.APPLIED:
            status = ApplicationOutcome.APPLIED
            reason = "Successfully applied"
            new_skipped_count = skipped_count
        elif last_outcome == ApplicationOutcome.FAILED:
            status = ApplicationOutcome.FAILED
            reason = "Application submission failed"
            new_skipped_count = skipped_count
        else:
            status = ApplicationOutcome.SKIPPED
            reason = "Unknown outcome"
            new_skipped_count = skipped_count + 1

        # ── 2. Persist to SQLite Database ─────────────────────────────
        save_application(
            job_id=current_job.job_id,
            job_title=current_job.title,
            company=current_job.company,
            location=current_job.location,
            apply_type=apply_type,
            match_score=match_score,
            status=status.value,
            url=current_job.url,
            notes=reason,
            db_path=self.db_path,
        )

        # ── 3. Append to Audit History ────────────────────────────────
        result = ApplicationResult(
            job=current_job,
            status=status,
            match_score=match_score,
            reason=reason,
            applied_at=datetime.now().isoformat(),
        )
        history.append(result)

        logger.debug(
            f"[agent]💾 Recorded {status.value} for {current_job.title} @ {current_job.company}[/agent]"
        )

        # ── 4. Clean Registers for Next Iteration ─────────────────────
        return {
            "skipped_count": new_skipped_count,
            "history": history,
            "current_job": None,
            "current_evaluation": None,
            "skip_reason": None,
            "last_outcome": None,
            "status_message": f"Recorded {status.value} for {current_job.job_id}",
        }
