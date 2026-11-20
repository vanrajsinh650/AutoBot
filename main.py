"""
AutoBot v2 — Entry Point
Run: python main.py [--ingest-only] [--dry-run]
"""
import asyncio
import argparse
import os
import sys
from pathlib import Path

from src.utils.config import get_config, get_env
from src.utils.logger import logger, console
from rich.panel import Panel


def parse_args():
    parser = argparse.ArgumentParser(description="AutoBot — LinkedIn Job Agent")
    parser.add_argument(
        "--ingest-only",
        action="store_true",
        help="Only ingest profile into vector DB, don't apply to jobs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Search and rank jobs but don't actually apply",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-ingestion of profile even if already indexed in Qdrant",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Launch the interactive web Mission Control dashboard",
    )
    parser.add_argument(
        "--frontend-only",
        "--frontend",
        dest="frontend_only",
        action="store_true",
        help="Run lightweight dynamic frontend UI without background schedulers or heavy scrapers",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for the Mission Control dashboard (default: 8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for the Mission Control dashboard (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--search",
        type=str,
        default="",
        help="Search a single keyword directly inside Google Chrome on Google (e.g. 'Python Developer')",
    )
    parser.add_argument(
        "--search-live",
        action="store_true",
        help="Open real Google Chrome directly and search for jobs with keywords and filters",
    )
    parser.add_argument(
        "--keyword",
        type=str,
        default="",
        help="Specific keyword to search in Chrome (e.g. 'Python Developer')",
    )
    parser.add_argument(
        "--location",
        type=str,
        default="",
        help="Target location for the search (e.g. 'India', 'Remote')",
    )
    parser.add_argument(
        "--target",
        type=str,
        default="google",
        choices=["google", "linkedin"],
        help="Where to search: 'google' (default, direct inside Chrome) or 'linkedin'",
    )
    return parser.parse_args()


async def main(args=None):
    if args is None:
        args = parse_args()

    cfg = get_config()
    env = get_env()

    console.print(Panel.fit(
        "[bold cyan]🤖 AutoBot v2[/bold cyan]\n"
        "[dim]LangGraph · LangChain · Qdrant · Playwright[/dim]",
        border_style="cyan",
    ))

    # ── Live Search Shortcut: Direct Google Chrome Keyword Search ──
    search_keyword = getattr(args, "search", "").strip() or getattr(args, "keyword", "").strip()
    if getattr(args, "search_live", False) or search_keyword:
        target = getattr(args, "target", "roles").lower()
        loc = getattr(args, "location", "").strip() or None
        from src.matching.keyword_expansion import resolve_search_keywords
        resolved_kws, kw_origin = resolve_search_keywords(user_provided=search_keyword or None, user_id=1)
        kw = resolved_kws[0] if resolved_kws else "Python Developer"
        logger.info(f"[agent]🔍 Search keyword resolved ({kw_origin}): '{kw}'[/agent]")

        if target == "linkedin":
            logger.info("[agent]🌐 Starting direct LinkedIn search in Google Chrome...[/agent]")
            from src.browser.live_search import run_direct_chrome_search
            jobs = await run_direct_chrome_search(keywords=[kw], location=loc, headless=False, keep_open=True)
            console.print(f"[bold green]✅ Discovered {len(jobs)} jobs on LinkedIn via Google Chrome![/bold green]")
        elif target == "google_only":
            logger.info(f"[agent]🌐 Starting direct Google-only search in Google Chrome...[/agent]")
            from src.browser.live_search import run_direct_google_keyword_search
            results = await run_direct_google_keyword_search(keyword=kw, location=loc, headless=False, keep_open=True)
            console.print(f"[bold green]✅ Found {len(results)} results directly inside Google Chrome![/bold green]")
        else:
            # Default: Search on Google -> Navigate to LinkedIn job roles -> Open top role in Chrome!
            logger.info(f"[agent]🌐 Running keyword search -> LinkedIn job roles -> opening job role in Chrome...[/agent]")
            from src.browser.live_search import run_google_to_linkedin_job_search
            roles = await run_google_to_linkedin_job_search(
                keyword=kw,
                location=loc,
                open_first_role=True,
                headless=False,
                keep_open=True,
            )
            console.print(f"[bold green]✅ Discovered {len(roles)} job roles and opened top role in Google Chrome![/bold green]")
        return

    # ── Step 1: Validate inputs ───────────────────────────────────
    resume = Path(cfg.profile.resume_path)
    if not resume.exists():
        console.print(
            f"\n[bold red]❌ Resume not found: [yellow]{resume}[/yellow][/bold red]\n"
            f"[bold]Place your PDF at:[/bold] [cyan]{resume}[/cyan]\n"
        )
        sys.exit(1)

    # ── Step 2: Ingest profile into Qdrant ───────────────────────
    logger.info("[agent]📥 Step 1 — Ingesting profile...[/agent]")
    from src.ingestion.pipeline import ingest_profile
    await ingest_profile(cfg, env, force=args.force)

    if args.ingest_only:
        logger.info("[success]✅ Ingestion complete. Exiting (--ingest-only).[/success]")
        return

    # ── Step 3: Run the LangGraph agent ──────────────────────────
    logger.info("[agent]🤖 Step 2 — Starting job agent...[/agent]")
    from src.agent.graph import run_agent
    await run_agent(cfg, env, dry_run=args.dry_run)


if __name__ == "__main__":
    args = parse_args()
    if args.ui or getattr(args, "frontend_only", False):
        if getattr(args, "frontend_only", False):
            os.environ["AUTOBOT_DISABLE_SCHEDULER"] = "1"
            os.environ["AUTOBOT_FRONTEND_ONLY"] = "1"
        from src.web.server import start_server
        try:
            start_server(host=args.host, port=args.port)
        except KeyboardInterrupt:
            console.print("\n[yellow]⚡ Server stopped by user.[/yellow]")
    else:
        try:
            asyncio.run(main(args))
        except KeyboardInterrupt:
            console.print("\n[yellow]⚡ Stopped by user.[/yellow]")
