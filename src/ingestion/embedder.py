"""
Vector embedding generation and Qdrant indexing engine.

Educational Concept:
Vector search is the algorithmic foundation of RAG (Retrieval-Augmented Generation):
1. Why Cosine Distance?
   Cosine distance evaluates the cosine of the angle between two multi-dimensional
   vectors: distance = 1 - (A · B) / (||A|| * ||B||). Unlike Euclidean distance, which
   is distorted by document length, Cosine distance is scale-invariant. A 30-word bullet
   and a 200-word paragraph discussing "Kubernetes orchestration" will have nearly
   identical vector directions.
2. Why Deterministic UUID5 Point IDs?
   Standard UUID4 generates pseudo-random identifiers. If ingestion is run multiple times,
   UUID4 creates duplicate points for the exact same resume text, polluting the vector store.
   UUID5 hashes a namespace with the content key:
       uuid.uuid5(uuid.NAMESPACE_DNS, f"{source}_{section}_{content}")
   This guarantees idempotence: re-running ingestion safely updates points in-place.
3. Why Payload Keyword Indexes?
   Filtering by metadata (e.g. searching only within `section == 'skills'`) requires an index.
   Without keyword indexing on `section` and `source`, Qdrant must perform full-table scans.
   Payload indexes enable sub-millisecond pre-filtering prior to HNSW graph traversal.
"""

from pathlib import Path
from typing import List, Optional
import uuid

from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models

from src.ingestion.models import DocumentChunk, IngestionSource, SectionType
from src.utils.config import EnvSettings
from src.utils.llm_factory import get_embeddings
from src.utils.logger import logger


def generate_chunk_uuid(chunk: DocumentChunk) -> str:
    """
    Generate a deterministic UUID5 identifier for a DocumentChunk.
    
    Pedagogical Note:
    Hashing `{source}_{section}_{content}` ensures identical content from the same
    source and section always produces the same UUID, preventing duplicate indexing.
    """
    unique_string = f"{chunk.source.value}_{chunk.section.value}_{chunk.content.strip()}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, unique_string))


def detect_embedding_dimension(embeddings: Embeddings) -> int:
    """
    Dynamically detect vector dimensionality by probing the embedding model.
    
    Pedagogical Note:
    Different embedding models output different vector dimensions:
    - OpenAI text-embedding-3-small: 1536
    - Google text-embedding-004: 768
    Hardcoding dimensions causes vector database schema mismatch errors when users
    switch providers. Dynamic probing guarantees schema alignment.
    """
    try:
        sample_vector = embeddings.embed_query("dimension_probe")
        dim = len(sample_vector)
        logger.debug(f"Detected embedding vector dimension: {dim}")
        return dim
    except Exception as e:
        logger.warning(
            f"Could not probe embedding dimension ({e}); falling back to default 1536."
        )
        return 1536


def init_qdrant_client(
    env: EnvSettings,
    fallback_to_local: bool = True,
    local_path: str = "data/qdrant",
) -> QdrantClient:
    """
    Connect to Qdrant vector database, falling back gracefully to local storage if remote server is unreachable.
    
    Args:
        env: Application environment settings.
        fallback_to_local: Whether to fallback to local embedded Qdrant on connection error.
        local_path: Filesystem path for embedded storage.
    """
    # 1. Check if configured as in-memory or explicit local path
    if env.qdrant_url == ":memory:":
        logger.info("Initializing in-memory QdrantClient.")
        return QdrantClient(":memory:")

    if env.qdrant_url.startswith("file://") or env.qdrant_url.startswith("/"):
        path = env.qdrant_url.replace("file://", "")
        Path(path).mkdir(parents=True, exist_ok=True)
        logger.info(f"Initializing local disk-backed QdrantClient at: {path}")
        return QdrantClient(path=path)

    # 2. Attempt remote server connection
    try:
        client = QdrantClient(url=env.qdrant_url, timeout=3.0)
        # Probe server connectivity
        client.get_collections()
        logger.info(f"Connected to remote Qdrant server at: {env.qdrant_url}")
        return client
    except Exception as e:
        if fallback_to_local:
            logger.warning(
                f"Could not connect to Qdrant at {env.qdrant_url} ({e}). "
                f"Falling back to embedded local storage at '{local_path}'."
            )
            Path(local_path).mkdir(parents=True, exist_ok=True)
            return QdrantClient(path=local_path)
        else:
            raise ConnectionError(
                f"Failed to connect to Qdrant at {env.qdrant_url}: {e}"
            )


def get_or_create_collection(
    client: QdrantClient,
    collection_name: str,
    vector_dim: int,
    recreate: bool = False,
) -> None:
    """
    Ensure the Qdrant collection exists with Cosine distance and keyword payload indexes.
    
    Args:
        client: Active QdrantClient instance.
        collection_name: Name of target collection.
        vector_dim: Dimensionality of vector embeddings.
        recreate: If True, drops the collection before creation if it exists.
    """
    exists = client.collection_exists(collection_name)
    if exists and recreate:
        logger.info(f"Recreating Qdrant collection '{collection_name}' (dropping existing)...")
        client.delete_collection(collection_name)
        exists = False

    if not exists:
        logger.info(
            f"Creating Qdrant collection '{collection_name}' "
            f"(dim={vector_dim}, distance=COSINE)..."
        )
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=vector_dim,
                distance=models.Distance.COSINE,
            ),
        )

        # Create payload indexes for fast filtered vector retrieval
        client.create_payload_index(
            collection_name=collection_name,
            field_name="section",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        client.create_payload_index(
            collection_name=collection_name,
            field_name="source",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        logger.info(f"Created keyword payload indexes on 'section' and 'source'.")
    else:
        logger.debug(f"Qdrant collection '{collection_name}' already exists.")


class ProfileEmbedder:
    """
    Embedder orchestrator managing chunk batching, vector generation, and Qdrant upserts.
    """

    def __init__(
        self,
        env: EnvSettings,
        client: Optional[QdrantClient] = None,
        embeddings: Optional[Embeddings] = None,
        batch_size: int = 32,
        recreate_collection: bool = False,
    ):
        self.env = env
        self.batch_size = batch_size
        self.client = client or init_qdrant_client(env)
        self.embeddings = embeddings or get_embeddings()
        self.collection_name = env.qdrant_collection
        self.vector_dim = detect_embedding_dimension(self.embeddings)

        get_or_create_collection(
            self.client,
            self.collection_name,
            self.vector_dim,
            recreate=recreate_collection,
        )

    def index_chunks(self, chunks: List[DocumentChunk]) -> int:
        """
        Embed a list of DocumentChunks and upsert them into Qdrant in batches.
        
        Returns:
            Number of chunks successfully indexed.
        """
        if not chunks:
            logger.info("No chunks provided for vector indexing.")
            return 0

        logger.info(
            f"Indexing {len(chunks)} chunks into Qdrant collection '{self.collection_name}'..."
        )

        total_indexed = 0

        for i in range(0, len(chunks), self.batch_size):
            batch = chunks[i : i + self.batch_size]
            texts = [c.content for c in batch]

            # Generate dense embedding vectors
            vectors = self.embeddings.embed_documents(texts)

            # Build PointStruct instances
            points: List[models.PointStruct] = []
            for chunk, vector in zip(batch, vectors):
                point_id = chunk.chunk_id or generate_chunk_uuid(chunk)
                payload = {
                    "content": chunk.content,
                    "source": chunk.source.value,
                    "section": chunk.section.value,
                    **chunk.metadata,
                }
                points.append(
                    models.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload,
                    )
                )

            # Upsert batch
            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
            )
            total_indexed += len(points)
            logger.debug(f"Upserted batch {i // self.batch_size + 1}: {len(points)} points.")

        logger.info(f"Successfully indexed {total_indexed} points into Qdrant.")
        return total_indexed


def embed_and_index_chunks(
    chunks: List[DocumentChunk],
    env: EnvSettings,
    client: Optional[QdrantClient] = None,
    embeddings: Optional[Embeddings] = None,
    batch_size: int = 32,
) -> int:
    """
    Public helper function to initialize embedder and index document chunks.
    """
    embedder = ProfileEmbedder(
        env=env,
        client=client,
        embeddings=embeddings,
        batch_size=batch_size,
    )
    return embedder.index_chunks(chunks)
