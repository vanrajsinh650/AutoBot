"""
Orchestration pipeline for candidate profile ingestion into Qdrant.

Educational Concept:
A production RAG ingestion pipeline requires:
1. Pre-flight Skip Check:
   Embedding generation consumes LLM API tokens and incurs network latency.
   Before re-running document processing, the pipeline queries Qdrant. If the
   candidate profile collection already contains indexed vectors and the `--force`
   flag is not set, ingestion short-circuits instantly.
2. Multi-Source Synthesis with Graceful Fault Isolation:
   The candidate's professional identity is assembled from three distinct channels:
   - Primary: Structured PDF resume (mandatory, fails fast if missing/unreadable).
   - Secondary: LinkedIn profile (optional, authenticated Playwright automation).
   - Tertiary: Portfolio website (optional, sanitized BeautifulSoup scraping).
   Failures in secondary or tertiary sources are isolated so they never prevent
   the primary application workflow from succeeding.
3. Observability & Rich Telemetry:
   Structured breakdown by source and section provides instant feedback on
   the distribution of indexed knowledge chunks.
"""

from collections import Counter
from pathlib import Path
import time
from typing import List, Optional

from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient
from rich.table import Table

from src.ingestion.embedder import ProfileEmbedder, init_qdrant_client
from src.ingestion.models import DocumentChunk, IngestionSummary
from src.ingestion.portfolio_scraper import scrape_portfolio
from src.ingestion.resume_parser import parse_resume
from src.utils.config import AppConfig, EnvSettings
from src.utils.logger import console, logger


def _render_summary_table(summary: IngestionSummary) -> None:
    """Render a formatted Rich table visualizing ingestion metrics."""
    table = Table(
        title="[bold green]AutoBot Profile Ingestion Summary[/bold green]",
        show_header=True,
        header_style="bold magenta",
        border_style="cyan",
    )
    table.add_column("Category", style="dim", width=22)
    table.add_column("Details", style="bold white")

    table.add_row("Vector Collection", summary.collection_name)
    table.add_row("Vector Dimension", str(summary.vector_dim))
    table.add_row("Total Chunks", str(summary.total_chunks))
    table.add_row("Duration", f"{summary.duration_seconds:.2f} seconds")

    # Sources breakdown
    source_breakdown = ", ".join(f"{k}: {v}" for k, v in summary.chunks_by_source.items()) or "None"
    table.add_row("Chunks by Source", source_breakdown)

    # Sections breakdown
    section_breakdown = ", ".join(f"{k}: {v}" for k, v in summary.chunks_by_section.items()) or "None"
    table.add_row("Chunks by Section", section_breakdown)

    console.print()
    console.print(table)
    console.print()


async def ingest_profile(
    cfg: AppConfig,
    env: EnvSettings,
    force: bool = False,
    client: Optional[QdrantClient] = None,
    embeddings: Optional[Embeddings] = None,
) -> IngestionSummary:
    """
    Ingest candidate's resume, LinkedIn profile, and portfolio into Qdrant.
    
    Args:
        cfg: Application configuration (paths, search parameters).
        env: Environment settings (credentials, models, vector db config).
        force: If True, re-indexes chunks even if collection already has points.
        client: Optional injected QdrantClient (used for testing/in-memory).
        embeddings: Optional injected Embeddings model (used for testing).
        
    Returns:
        IngestionSummary containing statistics and telemetry.
    """
    start_time = time.time()
    collection_name = env.qdrant_collection
    q_client = client or init_qdrant_client(env)

    # ── Pre-flight Check: Skip if already ingested ────────────────
    if not force:
        try:
            if q_client.collection_exists(collection_name):
                col_info = q_client.get_collection(collection_name)
                if col_info.points_count and col_info.points_count > 0:
                    logger.info(
                        f"[yellow]⚡ Profile already ingested ({col_info.points_count} chunks "
                        f"in '{collection_name}'). Skipping. Use --force to re-ingest.[/yellow]"
                    )
                    return IngestionSummary(
                        total_chunks=col_info.points_count,
                        collection_name=collection_name,
                        vector_dim=(col_info.config.params.vectors.size if hasattr(col_info.config.params, "vectors") and col_info.config.params.vectors else 0),
                        duration_seconds=time.time() - start_time,
                        skipped=True,
                    )
        except Exception as e:
            logger.debug(f"Pre-flight collection check exception ({e}); continuing with ingestion.")
    else:
        if force and q_client.collection_exists(collection_name):
            logger.info(f"Force re-ingestion: dropping existing collection '{collection_name}'...")
            q_client.delete_collection(collection_name)

    all_chunks: List[DocumentChunk] = []

    # ── Source 1: Resume PDF (Mandatory) ───────────────────────────
    resume_path = Path(cfg.profile.resume_path)
    logger.info(f"[cyan]📄 Step 1.1: Parsing resume PDF from {resume_path}...[/cyan]")
    resume_chunks = parse_resume(resume_path)
    all_chunks.extend(resume_chunks)
    logger.info(f"Loaded {len(resume_chunks)} chunks from resume.")

    # ── Source 2: Portfolio Website (Optional) ────────────────────
    portfolio_url = cfg.profile.portfolio_url.strip()
    if portfolio_url:
        logger.info(f"[cyan]🌐 Step 1.3: Scraping portfolio website ({portfolio_url})...[/cyan]")
        try:
            portfolio_chunks = scrape_portfolio(portfolio_url)
            all_chunks.extend(portfolio_chunks)
            logger.info(f"Loaded {len(portfolio_chunks)} chunks from portfolio.")
        except Exception as e:
            logger.warning(f"Failed to scrape portfolio website ({e}); continuing pipeline.")
    else:
        logger.info("Portfolio URL not configured; skipping portfolio ingestion.")

    if not all_chunks:
        raise ValueError("No chunks were extracted from any profile source.")

    # ── Embed & Index into Qdrant ─────────────────────────────────
    logger.info(f"[cyan]🧠 Step 1.4: Embedding and indexing {len(all_chunks)} chunks into Qdrant...[/cyan]")
    embedder = ProfileEmbedder(
        env=env,
        client=q_client,
        embeddings=embeddings,
        recreate_collection=force,
    )
    indexed_count = embedder.index_chunks(all_chunks)

    # ── Calculate Telemetry & Summaries ───────────────────────────
    source_counts = dict(Counter(c.source.value for c in all_chunks))
    section_counts = dict(Counter(c.section.value for c in all_chunks))
    duration = time.time() - start_time

    summary = IngestionSummary(
        total_chunks=indexed_count,
        chunks_by_source=source_counts,
        chunks_by_section=section_counts,
        collection_name=collection_name,
        vector_dim=embedder.vector_dim,
        duration_seconds=duration,
        skipped=False,
    )

    _render_summary_table(summary)
    return summary
