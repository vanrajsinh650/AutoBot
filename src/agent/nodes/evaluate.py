"""
Evaluate Node for AutoBot v2 LangGraph Agent.

Educational Concept:
Semantic evaluation node grounds agent decision-making in Qdrant vector memory:
1. Grounded Match Assessment:
   Calls JobMatcher to compare candidate skills, experiences, and education in Qdrant
   against the job vacancy description.
2. Threshold Gating:
   Checks whether `evaluation.is_match` is True (score >= min_match_score).
   If False, sets `skip_reason` so the conditional router diverts to `record_node`
   instead of `apply_node`.
3. Early Exit Optimization:
   If `filter_node` has already set `skip_reason` (e.g. duplicate or blacklist),
   `evaluate_node` immediately passes through without expending embedding or LLM compute.
"""

from typing import Any, Dict

from src.agent.state import AgentState
from src.memory.job_matcher import JobMatcher
from src.utils.logger import logger


class EvaluateNode:
    """
    Evaluates candidate fit for the active JobPosting using JobMatcher.
    """

    def __init__(self, matcher: JobMatcher):
        self.matcher = matcher

    def __call__(self, state: AgentState) -> Dict[str, Any]:
        current_job = state.get("current_job")
        if not current_job:
            return {"status_message": "No active job to evaluate."}

        # If already filtered out, bypass LLM evaluation
        if state.get("skip_reason"):
            return {"status_message": f"Job already skipped: {state['skip_reason']}"}

        logger.info(
            f"[agent]⚖ Evaluating fit for '{current_job.title}' @ '{current_job.company}'...[/agent]"
        )

        evaluation = self.matcher.evaluate_job(
            job_title=current_job.title,
            company=current_job.company,
            job_description=current_job.description,
        )

        min_score = state.get("min_match_score", self.matcher.min_match_score)

        if not evaluation.is_match:
            skip_msg = (
                f"Match score {evaluation.match_score:.2f} below threshold {min_score:.2f}. "
                f"Reason: {evaluation.summary_reason}"
            )
            logger.info(f"[agent]⏭ Skip: {current_job.title} ({skip_msg})[/agent]")
            return {
                "current_evaluation": evaluation,
                "skip_reason": skip_msg,
                "status_message": skip_msg,
            }

        logger.info(
            f"[agent]✅ Fit confirmed! Score: {evaluation.match_score:.2f} (>= {min_score:.2f}). Proceeding to apply.[/agent]"
        )
        return {
            "current_evaluation": evaluation,
            "skip_reason": None,
            "status_message": f"Match verified: score {evaluation.match_score:.2f}",
        }
