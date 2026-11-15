"""
Conditional routing edges for AutoBot v2 LangGraph Agent.

Educational Concept:
LangGraph conditional edges define runtime branch points based on state inspection:
1. `should_apply_edge`:
   Evaluates whether the candidate meets the match threshold or was filtered out.
   Directs flow to either `apply` (to submit) or `record` (to log the skip).
2. `after_record_edge`:
   After an application or skip is committed, checks termination conditions:
   - Cap Reached: `applied_count >= max_applications` -> END
   - Jobs in Queue: `unprocessed_jobs` non-empty -> `filter` (next job)
   - Queue Empty: -> `advance` (step page or keyword)
3. `after_advance_edge`:
   After advancing, checks if the search space is exhausted (`is_complete=True` -> END)
   or if new searches should execute -> `search`.
"""

from src.agent.state import AgentState
from src.utils.logger import logger


def should_apply_edge(state: AgentState) -> str:
    """
    Branch logic following job evaluation.
    
    Returns:
        'apply': If job passed filters and match_score >= min_match_score.
        'record': If job was skipped or below threshold.
    """
    if state.get("skip_reason"):
        return "record"

    evaluation = state.get("current_evaluation")
    if evaluation and evaluation.is_match:
        return "apply"

    return "record"


def after_record_edge(state: AgentState) -> str:
    """
    Branch logic following result recording.
    
    Returns:
        'end': If application session cap is reached.
        'filter': If there are remaining jobs waiting in the queue.
        'advance': If the current queue is empty and pagination/keyword step is needed.
    """
    applied = state.get("applied_count", 0)
    max_apps = state.get("max_applications", 30)

    if applied >= max_apps:
        logger.info(
            f"[agent]🏁 Reached session maximum applications ({applied}/{max_apps}). Terminating.[/agent]"
        )
        return "end"

    unprocessed = state.get("unprocessed_jobs", [])
    if unprocessed:
        return "filter"

    return "advance"


def after_advance_edge(state: AgentState) -> str:
    """
    Branch logic following queue advancement.
    
    Returns:
        'end': If all keywords and pages have been exhausted.
        'search': To execute job discovery for the new page or keyword.
    """
    if state.get("is_complete", False):
        return "end"

    return "search"
