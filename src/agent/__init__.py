"""
AutoBot v2 Agent Module.

Exports:
- build_job_agent_graph: Constructs and compiles the LangGraph state machine.
- run_agent: High-level async agent runner called from main.py.
- AgentState, JobPosting, ApplicationOutcome, ApplicationResult: Domain models.
"""

from src.agent.graph import build_job_agent_graph, create_initial_state, run_agent
from src.agent.state import (
    AgentState,
    ApplicationOutcome,
    ApplicationResult,
    JobPosting,
)

__all__ = [
    "AgentState",
    "ApplicationOutcome",
    "ApplicationResult",
    "JobPosting",
    "build_job_agent_graph",
    "create_initial_state",
    "run_agent",
]
