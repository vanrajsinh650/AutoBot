"""Tests for the ingestion pipeline orchestrator."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models

from src.ingestion.models import (
    DocumentChunk,
    IngestionSource,
    IngestionSummary,
    SectionType,
)
from src.ingestion.pipeline import ingest_profile
from src.utils.config import AppConfig, EnvSettings, ProfileConfig


class FakeEmbeddings:
    """Mock Embeddings for pipeline testing."""

    def __init__(self, dim: int = 1536):
        self.dim = dim

    def embed_query(self, text: str):
        return [0.1] * self.dim

    def embed_documents(self, texts):
        return [[0.1] * self.dim for _ in texts]


@pytest.fixture
def test_cfg():
    return AppConfig(
        profile=ProfileConfig(
            resume_path="data/resume/resume.pdf",
            linkedin_url="https://linkedin.com/in/testuser",
            portfolio_url="https://testuser.dev",
        )
    )


@pytest.fixture
def test_env():
    return EnvSettings(
        qdrant_collection="test_profile_pipeline",
        qdrant_url=":memory:",
        linkedin_email="test@example.com",
        linkedin_password="pass",
    )


@pytest.mark.asyncio
async def test_pipeline_skip_when_already_ingested(test_cfg, test_env):
    """Pipeline should skip ingestion if collection already contains points and force=False."""
    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name=test_env.qdrant_collection,
        vectors_config=models.VectorParams(size=1536, distance=models.Distance.COSINE),
    )
    # Insert a dummy point
    client.upsert(
        collection_name=test_env.qdrant_collection,
        points=[
            models.PointStruct(
                id="00000000-0000-0000-0000-000000000001",
                vector=[0.1] * 1536,
                payload={"content": "existing chunk"},
            )
        ],
    )

    with patch("src.ingestion.pipeline.parse_resume") as mock_parse_resume:
        summary = await ingest_profile(
            cfg=test_cfg,
            env=test_env,
            force=False,
            client=client,
            embeddings=FakeEmbeddings(),
        )

        assert summary.skipped is True
        assert summary.total_chunks == 1
        # Crucial: parse_resume should not even have been called
        mock_parse_resume.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_force_reingest(test_cfg, test_env):
    """Pipeline should re-index when force=True even if points already exist."""
    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name=test_env.qdrant_collection,
        vectors_config=models.VectorParams(size=1536, distance=models.Distance.COSINE),
    )
    client.upsert(
        collection_name=test_env.qdrant_collection,
        points=[
            models.PointStruct(
                id="00000000-0000-0000-0000-000000000001",
                vector=[0.1] * 1536,
                payload={"content": "old chunk"},
            )
        ],
    )

    resume_chunks = [
        DocumentChunk(
            content="Resume experience at Google",
            source=IngestionSource.RESUME,
            section=SectionType.EXPERIENCE,
        )
    ]

    with patch("src.ingestion.pipeline.parse_resume", return_value=resume_chunks), \
         patch("src.ingestion.pipeline.scrape_linkedin_profile", new_callable=AsyncMock, return_value=[]), \
         patch("src.ingestion.pipeline.scrape_portfolio", return_value=[]):

        summary = await ingest_profile(
            cfg=test_cfg,
            env=test_env,
            force=True,
            client=client,
            embeddings=FakeEmbeddings(),
        )

        assert summary.skipped is False
        assert summary.total_chunks == 1
        assert summary.chunks_by_source["resume"] == 1
        assert client.get_collection(test_env.qdrant_collection).points_count == 1


@pytest.mark.asyncio
async def test_pipeline_force_reingest_dimension_switch(test_cfg, test_env):
    """When switching embedding models (e.g. 1536 dim to 768 dim), force=True drops collection and avoids vector dim mismatch."""
    client = QdrantClient(":memory:")
    # Collection initially created with 1536 dimensions (e.g. OpenAI)
    client.create_collection(
        collection_name=test_env.qdrant_collection,
        vectors_config=models.VectorParams(size=1536, distance=models.Distance.COSINE),
    )
    client.upsert(
        collection_name=test_env.qdrant_collection,
        points=[
            models.PointStruct(
                id="00000000-0000-0000-0000-000000000099",
                vector=[0.1] * 1536,
                payload={"content": "old openai chunk"},
            )
        ],
    )

    new_chunks = [
        DocumentChunk(
            content="New Gemini chunk with 768 dimensions",
            source=IngestionSource.RESUME,
            section=SectionType.SKILLS,
        )
    ]

    with patch("src.ingestion.pipeline.parse_resume", return_value=new_chunks), \
         patch("src.ingestion.pipeline.scrape_linkedin_profile", new_callable=AsyncMock, return_value=[]), \
         patch("src.ingestion.pipeline.scrape_portfolio", return_value=[]):

        summary = await ingest_profile(
            cfg=test_cfg,
            env=test_env,
            force=True,
            client=client,
            embeddings=FakeEmbeddings(dim=768),
        )

        assert summary.skipped is False
        assert summary.total_chunks == 1
        assert summary.vector_dim == 768
        col_info = client.get_collection(test_env.qdrant_collection)
        assert col_info.points_count == 1
        assert col_info.config.params.vectors.size == 768


@pytest.mark.asyncio
async def test_pipeline_multi_source_aggregation_and_fault_tolerance(test_cfg, test_env):
    """Pipeline aggregates resume, LinkedIn, and portfolio, tolerating portfolio failure."""
    client = QdrantClient(":memory:")

    resume_chunks = [
        DocumentChunk(
            content="Resume Skills: Python, Docker",
            source=IngestionSource.RESUME,
            section=SectionType.SKILLS,
        )
    ]
    linkedin_chunks = [
        DocumentChunk(
            content="LinkedIn Experience: Principal Architect",
            source=IngestionSource.LINKEDIN,
            section=SectionType.EXPERIENCE,
        )
    ]

    with patch("src.ingestion.pipeline.parse_resume", return_value=resume_chunks), \
         patch("src.ingestion.pipeline.scrape_linkedin_profile", new_callable=AsyncMock, return_value=linkedin_chunks), \
         patch("src.ingestion.pipeline.scrape_portfolio", side_effect=Exception("Portfolio network timeout")):

        summary = await ingest_profile(
            cfg=test_cfg,
            env=test_env,
            force=False,
            client=client,
            embeddings=FakeEmbeddings(),
        )

        # Ingestion should succeed despite portfolio exception
        assert summary.skipped is False
        assert summary.total_chunks == 2
        assert summary.chunks_by_source["resume"] == 1
        assert summary.chunks_by_source["linkedin"] == 1
        assert summary.chunks_by_section["skills"] == 1
        assert summary.chunks_by_section["experience"] == 1
