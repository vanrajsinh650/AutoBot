"""
LangGraph Workflow Assembly & Orchestrator for AutoBot v2.

Educational Concept:
LangGraph choreographs multiple specialized nodes into a cohesive, deterministic agent loop:
1. Declarative Topology:
   The graph is declared using `StateGraph(AgentState)` and connected via:
   - Standard Directed Edges: `START -> search -> filter -> evaluate`
   - Conditional Decision Edges: `evaluate -> (should_apply_edge) -> apply | record`
   - Cyclic Feedback Loops: `record -> (after_record_edge) -> filter | advance | END`
   - Discovery Loop: `advance -> (after_advance_edge) -> search | END`
2. Telemetry and Audit:
   Captures rich runtime statistics and renders a clean summary table upon completion.
3. Resilience & Testability:
   The graph builder supports full dependency injection, enabling fast, isolated
   in-memory test execution as well as live production runs.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from rich.table import Table

from src.agent.edges import after_advance_edge, after_record_edge, should_apply_edge
from src.agent.nodes.advance import AdvanceNode
from src.agent.nodes.apply import ApplicationExecutor, ApplyNode
from src.agent.nodes.evaluate import EvaluateNode
from src.agent.nodes.filter import FilterNode
from src.agent.nodes.record import RecordNode
from src.agent.nodes.search import JobSearchProvider, SearchNode
from src.agent.state import AgentState
from src.memory.cover_letter import CoverLetterGenerator
from src.memory.job_matcher import JobMatcher
from src.memory.retriever import ProfileRetriever
from src.storage.db import (
    end_session,
    get_db_path,
    get_stats,
    init_db,
    start_session,
)
from src.utils.config import AppConfig, EnvSettings, get_config, get_env
from src.utils.llm_factory import get_llm
from src.utils.logger import console, logger


def create_initial_state(
    cfg: AppConfig,
    dry_run: bool = False,
) -> AgentState:
    """
    Construct the baseline AgentState from application configuration.
    """
    keywords = list(cfg.search.keywords) if cfg.search.keywords else ["Software Engineer"]
    first_keyword = keywords[0] if keywords else "Software Engineer"

    return {
        "keywords": keywords,
        "keyword_index": 0,
        "current_keyword": first_keyword,
        "location": cfg.search.location,
        "current_page": 1,
        "max_pages": cfg.agent.max_pages,
        "unprocessed_jobs": [],
        "current_job": None,
        "current_evaluation": None,
        "skip_reason": None,
        "applied_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "max_applications": cfg.apply.max_applications,
        "min_match_score": cfg.apply.min_match_score,
        "dry_run": dry_run,
        "history": [],
        "status_message": "Initializing AutoBot v2 agent state machine.",
        "is_complete": False,
    }


def build_job_agent_graph(
    matcher: JobMatcher,
    search_provider: Optional[JobSearchProvider] = None,
    application_executor: Optional[ApplicationExecutor] = None,
    cover_letter_gen: Optional[CoverLetterGenerator] = None,
    blacklist_companies: Optional[list] = None,
    blacklist_keywords: Optional[list] = None,
    db_path: Optional[str] = None,
    delay_between_jobs: float = 2.0,
) -> CompiledStateGraph:
    """
    Assemble and compile the AutoBot LangGraph state machine.

    Args:
        matcher: Injected JobMatcher instance for semantic qualification.
        search_provider: Callable providing job vacancies (mock or Playwright).
        application_executor: Callable performing form submissions.
        cover_letter_gen: CoverLetterGenerator for tailored applications.
        blacklist_companies: Explicit company exclusion list.
        blacklist_keywords: Explicit title keyword exclusion list.
        db_path: Path to SQLite persistence database.

    Returns:
        CompiledStateGraph executable with .invoke() or .ainvoke().
    """
    builder = StateGraph(AgentState)

    # 1. Instantiate Nodes
    search_node = SearchNode(search_provider=search_provider)
    filter_node = FilterNode(
        blacklist_companies=blacklist_companies,
        blacklist_keywords=blacklist_keywords,
        db_path=db_path,
    )
    evaluate_node = EvaluateNode(matcher=matcher)
    apply_node = ApplyNode(
        executor=application_executor,
        cover_letter_gen=cover_letter_gen,
        delay_between_jobs=delay_between_jobs,
    )
    record_node = RecordNode(db_path=db_path)
    advance_node = AdvanceNode()

    # 2. Register Nodes
    from langgraph.utils.runnable import RunnableCallable

    builder.add_node("search", RunnableCallable(search_node, search_node.acall))
    builder.add_node("filter", filter_node)
    builder.add_node("evaluate", evaluate_node)
    builder.add_node("apply", RunnableCallable(apply_node, apply_node.acall))
    builder.add_node("record", record_node)
    builder.add_node("advance", advance_node)

    # 3. Connect Edges
    builder.add_edge(START, "search")
    builder.add_edge("search", "filter")
    builder.add_edge("filter", "evaluate")

    # Conditional Branch: Should Apply vs Skip
    builder.add_conditional_edges(
        "evaluate",
        should_apply_edge,
        {
            "apply": "apply",
            "record": "record",
        },
    )

    builder.add_edge("apply", "record")

    # Conditional Branch: Queue / Advance / End
    builder.add_conditional_edges(
        "record",
        after_record_edge,
        {
            "end": END,
            "filter": "filter",
            "advance": "advance",
        },
    )

    # Conditional Branch: New Search vs End
    builder.add_conditional_edges(
        "advance",
        after_advance_edge,
        {
            "end": END,
            "search": "search",
        },
    )

    return builder.compile()


async def run_agent(
    cfg: Optional[AppConfig] = None,
    env: Optional[EnvSettings] = None,
    dry_run: bool = False,
    search_provider: Optional[JobSearchProvider] = None,
    application_executor: Optional[ApplicationExecutor] = None,
    matcher: Optional[JobMatcher] = None,
    retriever: Optional[ProfileRetriever] = None,
    cover_letter_gen: Optional[CoverLetterGenerator] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    High-level entry point called from main.py to execute the autonomous job application loop.
    """
    app_cfg = cfg or get_config()
    app_env = env or get_env()

    # 1. Initialize SQLite Database & Session
    init_db(db_path)
    session_id = start_session(db_path)
    logger.info(f"[agent]Started session #{session_id} (dry_run={dry_run})[/agent]")

    # 2. Initialize Memory Components (if not injected)
    llm = None
    try:
        llm = get_llm(temperature=0.0)
    except Exception as e:
        logger.debug(f"LLM not configured; using heuristic fallback: {e}")

    if matcher is None:
        if retriever is None:
            try:
                retriever = ProfileRetriever(env=app_env)
            except Exception as e:
                logger.warning(
                    f"Could not initialize vector retriever ({e}); using offline fallback."
                )
                from qdrant_client import QdrantClient
                from tests.test_memory import DeterministicEmbeddings
                retriever = ProfileRetriever(
                    env=app_env,
                    client=QdrantClient(":memory:"),
                    embeddings=DeterministicEmbeddings(),
                    collection_name="offline_fallback",
                )

        matcher = JobMatcher(
            retriever=retriever,
            llm=llm,
            min_match_score=app_cfg.apply.min_match_score,
        )

    if cover_letter_gen is None and retriever is not None:
        cover_letter_gen = CoverLetterGenerator(
            retriever=retriever,
            llm=llm,
        )

    # 2.5 Auto-launch BrowserBridge if no custom provider supplied and browser automation enabled
    use_browser = (
        search_provider is None
        and os.environ.get("AUTOBOT_STRICT_POLICY") != "1"
        and os.environ.get("AUTOBOT_OFFLINE") != "1"
        and getattr(getattr(app_cfg, "browser", None), "enabled", True)
    )
    if use_browser:
        try:
            from src.browser.bridge import BrowserBridge
            from src.memory.form_rag import FormRAG

            resume_file = Path(app_cfg.profile.resume_path)
            form_rag = FormRAG(retriever=retriever, llm=llm)
            logger.info("[agent]🌐 Auto-launching BrowserBridge for live LinkedIn search & applications...[/agent]")
            async with BrowserBridge(
                form_rag=form_rag,
                cfg=app_cfg,
                env=app_env,
                resume_path=resume_file if resume_file.exists() else None,
            ) as bridge:
                return await run_agent(
                    cfg=app_cfg,
                    env=app_env,
                    dry_run=dry_run,
                    search_provider=bridge.search_provider,
                    application_executor=bridge.application_executor,
                    matcher=matcher,
                    retriever=retriever,
                    cover_letter_gen=cover_letter_gen,
                    db_path=db_path,
                )
        except Exception as e:
            logger.warning(
                f"[agent]Could not auto-start BrowserBridge ({e}). Falling back to local database ATS jobs.[/agent]"
            )

    # 3. Build & Compile StateGraph
    delay_between_jobs = getattr(getattr(app_cfg, "agent", None), "delay_between_jobs", 2.0)
    graph = build_job_agent_graph(
        matcher=matcher,
        search_provider=search_provider,
        application_executor=application_executor,
        cover_letter_gen=cover_letter_gen,
        blacklist_companies=app_cfg.blacklist.companies,
        blacklist_keywords=app_cfg.blacklist.title_keywords,
        db_path=db_path,
        delay_between_jobs=delay_between_jobs,
    )

    # 4. Initialize State & Execute Graph
    initial_state = create_initial_state(app_cfg, dry_run=dry_run)
    logger.info("[agent]⚡ Commencing LangGraph execution loop...[/agent]")

    final_state: Dict[str, Any] = {}
    try:
        from src.web.routes import execution_manager
        async for chunk in graph.astream(initial_state):
            for node_name in chunk.keys():
                execution_manager.current_node = node_name
                execution_manager.broadcast("status", {"state": "running", "node": node_name})
                msg = chunk[node_name].get("status_message") or f"Node {node_name} completed."
                execution_manager.broadcast("log", {"level": "info", "message": msg})
                final_state.update(chunk[node_name])
    except Exception as e:
        logger.debug(f"Streaming execution fallback to invoke: {e}")
        try:
            final_state = await graph.ainvoke(initial_state)
        except Exception as e2:
            logger.error(f"Error during agent graph execution: {e2}")
            try:
                final_state = graph.invoke(initial_state)
            except Exception as e3:
                logger.error(f"Synchronous graph execution failed as well: {e3}")

    # 5. Session Wrap-up & Telemetry
    applied = final_state.get("applied_count", 0)
    skipped = final_state.get("skipped_count", 0)
    failed = final_state.get("failed_count", 0)

    end_session(session_id, applied, skipped, failed, db_path=db_path)

    # Render Summary Table
    _render_summary_table(applied, skipped, failed, dry_run, db_path)

    return final_state


def _render_summary_table(
    applied: int,
    skipped: int,
    failed: int,
    dry_run: bool,
    db_path: str,
) -> None:
    """Render Rich CLI summary table showing session metrics and all-time totals."""
    table = Table(title="📊 AutoBot v2 Session Summary", border_style="cyan")
    table.add_column("Metric", style="bold white")
    table.add_column("Count", style="bold cyan", justify="right")

    mode_label = "🧪 Simulated (Dry Run)" if dry_run else "✅ Applied"
    table.add_row(mode_label, str(applied))
    table.add_row("⏭ Skipped (Filter / Low Match)", str(skipped))
    table.add_row("❌ Failed", str(failed))
    table.add_row("📋 Total Evaluated", str(applied + skipped + failed))

    console.print()
    console.print(table)

    all_stats = get_stats(db_path)
    console.print(
        f"\n[dim]All-time database totals: "
        f"{all_stats.get('applied', 0)} applied, "
        f"{all_stats.get('dry_run', 0)} dry-run, "
        f"{all_stats.get('skipped', 0)} skipped, "
        f"{all_stats.get('failed', 0)} failed[/dim]\n"
    )
