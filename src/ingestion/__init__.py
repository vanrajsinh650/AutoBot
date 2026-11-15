"""
Ingestion layer for AutoBot v2.

Exports public models, parsers, scrapers, embedders, and pipeline orchestrators.
"""

from src.ingestion.embedder import (
    ProfileEmbedder,
    detect_embedding_dimension,
    embed_and_index_chunks,
    generate_chunk_uuid,
    get_or_create_collection,
    init_qdrant_client,
)
from src.ingestion.linkedin_scraper import (
    LinkedInScraper,
    scrape_linkedin_profile,
)
from src.ingestion.models import (
    DocumentChunk,
    IngestionSource,
    IngestionSummary,
    SectionType,
)
from src.ingestion.pipeline import ingest_profile
from src.ingestion.portfolio_scraper import scrape_portfolio
from src.ingestion.resume_parser import parse_resume

__all__ = [
    "IngestionSource",
    "SectionType",
    "DocumentChunk",
    "IngestionSummary",
    "parse_resume",
    "LinkedInScraper",
    "scrape_linkedin_profile",
    "scrape_portfolio",
    "ProfileEmbedder",
    "detect_embedding_dimension",
    "embed_and_index_chunks",
    "generate_chunk_uuid",
    "get_or_create_collection",
    "init_qdrant_client",
    "ingest_profile",
]
