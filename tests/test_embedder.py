"""Tests for vector embedding and Qdrant indexing module."""

import uuid
from unittest.mock import MagicMock, patch
import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models

from src.ingestion.models import DocumentChunk, IngestionSource, SectionType
from src.ingestion.embedder import (
    ProfileEmbedder,
    detect_embedding_dimension,
    generate_chunk_uuid,
    get_or_create_collection,
    init_qdrant_client,
)
from src.utils.config import EnvSettings


class FakeEmbeddings:
    """Mock LangChain Embeddings provider returning deterministic test vectors."""

    def __init__(self, dim: int = 1536):
        self.dim = dim

    def embed_query(self, text: str):
        # Deterministic pseudo-vector with unit length
        vec = [0.0] * self.dim
        vec[0] = 1.0
        return vec

    def embed_documents(self, texts):
        return [self.embed_query(t) for t in texts]


def test_generate_chunk_uuid():
    """Verify deterministic UUID5 generation for deduplication."""
    chunk1 = DocumentChunk(
        content="Proficient in Python and Go",
        source=IngestionSource.RESUME,
        section=SectionType.SKILLS,
    )
    chunk2 = DocumentChunk(
        content="Proficient in Python and Go",
        source=IngestionSource.RESUME,
        section=SectionType.SKILLS,
    )
    chunk3 = DocumentChunk(
        content="Different content",
        source=IngestionSource.RESUME,
        section=SectionType.SKILLS,
    )

    id1 = generate_chunk_uuid(chunk1)
    id2 = generate_chunk_uuid(chunk2)
    id3 = generate_chunk_uuid(chunk3)

    # Identical chunks must produce the exact same valid UUID string
    assert id1 == id2
    assert uuid.UUID(id1).version == 5
    assert id1 != id3


def test_detect_embedding_dimension():
    """Verify dynamic dimension detection probes embedding model."""
    fake_1536 = FakeEmbeddings(dim=1536)
    fake_768 = FakeEmbeddings(dim=768)

    assert detect_embedding_dimension(fake_1536) == 1536
    assert detect_embedding_dimension(fake_768) == 768


def test_get_or_create_collection_in_memory():
    """Verify Qdrant collection initialization with Cosine distance and payload indexes."""
    client = QdrantClient(":memory:")
    collection_name = "test_profile"
    dim = 1536

    get_or_create_collection(client, collection_name, dim)

    # Verify collection exists
    assert client.collection_exists(collection_name)
    info = client.get_collection(collection_name)
    assert info.config.params.vectors.size == dim
    assert info.config.params.vectors.distance == models.Distance.COSINE


def test_embed_and_index_chunks_real_qdrant_in_memory():
    """Verify end-to-end embedding, batching, and indexing into real in-memory Qdrant."""
    client = QdrantClient(":memory:")
    env = EnvSettings(
        qdrant_collection="test_profile",
        embeddings_provider="openai",
    )
    fake_embeddings = FakeEmbeddings(dim=1536)

    embedder = ProfileEmbedder(
        env=env,
        client=client,
        embeddings=fake_embeddings,
    )

    chunks = [
        DocumentChunk(
            content="Built high-performance RAG agent with LangChain and Qdrant.",
            source=IngestionSource.RESUME,
            section=SectionType.EXPERIENCE,
            metadata={"role": "AI Architect", "company": "AutoCorp"},
        ),
        DocumentChunk(
            content="Languages: Python, Rust, Go, SQL. Frameworks: FastAPI, PyTorch.",
            source=IngestionSource.RESUME,
            section=SectionType.SKILLS,
        ),
        DocumentChunk(
            content="Open source contributor to AutoBot project.",
            source=IngestionSource.PORTFOLIO,
            section=SectionType.PROJECTS,
            metadata={"url": "https://example.com/projects"},
        ),
    ]

    indexed_count = embedder.index_chunks(chunks)
    assert indexed_count == 3

    # Check points count in collection
    col_info = client.get_collection("test_profile")
    assert col_info.points_count == 3

    # Verify searching with payload filter on section
    filter_skills = models.Filter(
        must=[models.FieldCondition(key="section", match=models.MatchValue(value="skills"))]
    )
    res = client.query_points(
        collection_name="test_profile",
        query=fake_embeddings.embed_query("Python"),
        query_filter=filter_skills,
        limit=5,
    )
    assert len(res.points) == 1
    assert res.points[0].payload["section"] == "skills"
    assert "FastAPI" in res.points[0].payload["content"]


def test_init_qdrant_client_fallback():
    """Verify that when remote Qdrant fails, it falls back to local or in-memory client."""
    env = EnvSettings(qdrant_url="http://nonexistent-host:6333")

    with patch("src.ingestion.embedder.QdrantClient") as mock_qdrant:
        # First call (remote URL) raises exception
        mock_remote = MagicMock()
        mock_remote.get_collections.side_effect = Exception("Connection refused")

        mock_local = MagicMock()
        mock_local.get_collections.return_value = []

        mock_qdrant.side_effect = [mock_remote, mock_local]

        client = init_qdrant_client(env, fallback_to_local=True)
        assert client == mock_local
        assert mock_qdrant.call_count == 2
