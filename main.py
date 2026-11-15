"""
AutoBot v2 — Entry Point
Run: python main.py [--ingest-only] [--dry-run]
"""
import asyncio
import argparse
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
    if args.ui:
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
