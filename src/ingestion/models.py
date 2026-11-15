"""
Data models and schemas for AutoBot v2 Ingestion Layer.

Educational Concept:
Retrieval-Augmented Generation (RAG) relies on chunking continuous documents
into discrete, semantically meaningful units. IngestionSource tracks provenance
(where a piece of information came from), while SectionType classifies content
semantically (e.g., job experience vs. skills list). This enables metadata
filtering at vector query time, ensuring questions like "Does candidate know Docker?"
can search specifically within 'skills' or 'experience' sections rather than scanning
unstructured noise.
"""

from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class IngestionSource(str, Enum):
    """
    Source identifier for candidate profile data.
    
    Pedagogical Note:
    Tracking provenance allows the RAG retrieval pipeline to weight or filter
    results (e.g. prioritizing an authoritative PDF resume over web scraping).
    """
    RESUME = "resume"
    LINKEDIN = "linkedin"
    PORTFOLIO = "portfolio"


class SectionType(str, Enum):
    """
    Semantic section classification for candidate documents.
    
    Pedagogical Note:
    Vector search works best when embeddings represent cohesive topics. Partitioning
    by section allows precise metadata-filtered queries (e.g., section == 'skills').
    """
    CONTACT = "contact"
    SUMMARY = "summary"
    SKILLS = "skills"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    PROJECTS = "projects"
    CERTIFICATIONS = "certifications"
    OTHER = "other"


class DocumentChunk(BaseModel):
    """
    A single cohesive chunk of candidate information destined for vector indexing.
    
    Attributes:
        content: The text representation of the chunk.
        source: Origin of data (resume, linkedin, portfolio).
        section: Semantic section type.
        metadata: Key-value metadata (e.g., company, role, dates, page_number).
        chunk_id: Unique deterministic or generated identifier.
    """
    content: str
    source: IngestionSource
    section: SectionType
    metadata: Dict[str, Any] = Field(default_factory=dict)
    chunk_id: Optional[str] = None


class IngestionSummary(BaseModel):
    """
    Telemetry and summary of the completed ingestion process.
    
    Used to render Rich CLI dashboards and track database state.
    """
    total_chunks: int = 0
    chunks_by_source: Dict[str, int] = Field(default_factory=dict)
    chunks_by_section: Dict[str, int] = Field(default_factory=dict)
    collection_name: str = ""
    vector_dim: int = 0
    duration_seconds: float = 0.0
    skipped: bool = False
