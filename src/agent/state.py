"""
LangGraph State and Domain Models for AutoBot v2.

Educational Concept:
LangGraph models agentic behavior as a directed state graph.
1. Immutable State Transitions:
   Each node in LangGraph receives the full `AgentState`, performs computation,
   and returns a dictionary of mutations. The LangGraph runtime merges these mutations
   into the next state snapshot.
2. Separation of Concerns:
   - `JobPosting`: Pure external data contract representing a found job vacancy.
   - `ApplicationResult`: Audit record capturing decision, match score, and outcome.
   - `AgentState`: The complete execution context passing through the state machine.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict
from pydantic import BaseModel, Field

from src.memory.models import JobMatchEvaluation


class ApplicationOutcome(str, Enum):
    """Execution status for a processed job posting."""
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"
    DRY_RUN = "dry_run"


class JobPosting(BaseModel):
    """
    Representation of a single job opportunity scraped or retrieved from search.
    """
    job_id: str
    title: str
    company: str
    location: str = ""
    url: str = ""
    description: str = ""
    is_easy_apply: bool = True
    external_apply_url: Optional[str] = None


class ApplicationResult(BaseModel):
    """
    Diagnostic telemetry recording the processing outcome of a JobPosting.
    """
    job: JobPosting
    status: ApplicationOutcome
    match_score: float = 0.0
    reason: str = ""
    applied_at: str = ""


class AgentState(TypedDict, total=False):
    """
    Execution state for the AutoBot LangGraph state machine.
    
    Fields:
        keywords: Search query list (e.g. ['Python Developer', 'Backend Engineer']).
        keyword_index: Index of the current active search keyword.
        current_keyword: Current active keyword string.
        location: Target geographic location or 'Remote'.
        current_page: 1-indexed pagination counter.
        max_pages: Maximum pagination limit per keyword.
        unprocessed_jobs: Queue of discovered JobPosting instances waiting for evaluation.
        current_job: The active JobPosting currently undergoing evaluation or application.
        current_evaluation: The JobMatchEvaluation produced by JobMatcher for current_job.
        skip_reason: If current_job was skipped (blacklist, duplicate, low score), the reason.
        applied_count: Running total of successful applications.
        skipped_count: Running total of skipped vacancies.
        failed_count: Running total of application failures.
        max_applications: Session cap terminating the agent once reached.
        min_match_score: Semantic match threshold (0.0 to 1.0).
        dry_run: If True, simulates applications without submitting forms or moving browsers.
        history: Audit trail of all processed vacancies.
        status_message: Human-readable telemetry for console/logs.
        is_complete: Boolean flag signaling graceful loop termination.
    """
    keywords: List[str]
    keyword_index: int
    current_keyword: str
    location: str
    current_page: int
    max_pages: int
    unprocessed_jobs: List[JobPosting]
    current_job: Optional[JobPosting]
    current_evaluation: Optional[JobMatchEvaluation]
    skip_reason: Optional[str]
    last_outcome: Optional[ApplicationOutcome]
    applied_count: int
    skipped_count: int
    failed_count: int
    max_applications: int
    min_match_score: float
    dry_run: bool
    history: List[ApplicationResult]
    status_message: str
    is_complete: bool
