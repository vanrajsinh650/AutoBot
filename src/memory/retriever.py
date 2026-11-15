"""
Semantic vector retrieval engine querying Qdrant long-term memory.

Educational Concept:
Vector retrieval (dense retrieval) performs approximate nearest neighbor (ANN) search
in embedding space. By pairing vector search with metadata filtering, we achieve
hybrid-style precision:
1. Dense Semantic Similarity:
   Computes cosine similarity between query embedding and candidate profile embeddings.
   Finds concepts even when exact keywords differ (e.g., query "distributed systems"
   matches chunk "microservice architecture and gRPC").
2. Metadata Filtering:
   When answering "What degrees do you hold?", filtering to `section == 'education'`
   avoids false positives from the work experience section mentioning colleges.
3. Dual API Resilience:
   Supports both modern Qdrant client (`client.query_points`) and legacy (`client.search`),
   guaranteeing robust cross-environment operation.
"""

from typing import List, Optional, Union

from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models

from src.ingestion.embedder import init_qdrant_client
from src.ingestion.models import IngestionSource, SectionType
from src.memory.models import RetrievedChunk
from src.utils.config import EnvSettings, get_env
from src.utils.llm_factory import get_embeddings
from src.utils.logger import logger


class ProfileRetriever:
    """
    Retrieves semantically relevant candidate profile chunks from Qdrant vector store.
    """

    def __init__(
        self,
        env: Optional[EnvSettings] = None,
        client: Optional[QdrantClient] = None,
        embeddings: Optional[Embeddings] = None,
        collection_name: Optional[str] = None,
    ):
        self.env = env or get_env()
        self.client = client or init_qdrant_client(self.env)
        self.embeddings = embeddings or get_embeddings()
        self.collection_name = collection_name or self.env.qdrant_collection

    def _build_filter(
        self,
        section_filter: Optional[Union[SectionType, List[SectionType]]] = None,
        source_filter: Optional[Union[IngestionSource, List[IngestionSource]]] = None,
    ) -> Optional[models.Filter]:
        """
        Construct a Qdrant Filter object combining section and source conditions.
        """
        must_conditions = []

        if section_filter:
            sections = (
                [section_filter]
                if isinstance(section_filter, SectionType)
                else list(section_filter)
            )
            section_values = [s.value if isinstance(s, SectionType) else str(s) for s in sections]
            if len(section_values) == 1:
                must_conditions.append(
                    models.FieldCondition(
                        key="section",
                        match=models.MatchValue(value=section_values[0]),
                    )
                )
            else:
                must_conditions.append(
                    models.FieldCondition(
                        key="section",
                        match=models.MatchAny(any=section_values),
                    )
                )

        if source_filter:
            sources = (
                [source_filter]
                if isinstance(source_filter, IngestionSource)
                else list(source_filter)
            )
            source_values = [s.value if isinstance(s, IngestionSource) else str(s) for s in sources]
            if len(source_values) == 1:
                must_conditions.append(
                    models.FieldCondition(
                        key="source",
                        match=models.MatchValue(value=source_values[0]),
                    )
                )
            else:
                must_conditions.append(
                    models.FieldCondition(
                        key="source",
                        match=models.MatchAny(any=source_values),
                    )
                )

        if not must_conditions:
            return None

        return models.Filter(must=must_conditions)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: Optional[float] = None,
        section_filter: Optional[Union[SectionType, List[SectionType]]] = None,
        source_filter: Optional[Union[IngestionSource, List[IngestionSource]]] = None,
    ) -> List[RetrievedChunk]:
        """
        Perform semantic similarity search against candidate profile embeddings in Qdrant.

        Args:
            query: Natural language query (e.g. question or job description excerpt).
            top_k: Maximum number of chunks to return.
            score_threshold: Minimum cosine similarity score (0.0 to 1.0).
            section_filter: Filter results to specific section(s) (skills, experience, etc.).
            source_filter: Filter results to specific source(s) (resume, linkedin, portfolio).

        Returns:
            List of RetrievedChunk instances ordered by similarity score descending.
        """
        if not query.strip():
            return []

        try:
            if not self.client.collection_exists(self.collection_name):
                logger.warning(
                    f"Qdrant collection '{self.collection_name}' does not exist. "
                    "Run ingestion first (python main.py --ingest-only)."
                )
                return []
        except Exception as e:
            logger.error(f"Error checking Qdrant collection status: {e}")
            return []

        # 1. Embed query into vector representation
        try:
            query_vector = self.embeddings.embed_query(query)
        except Exception as e:
            logger.error(f"Failed to generate embedding vector for query: {e}")
            return []

        # 2. Build metadata filter
        qdrant_filter = self._build_filter(
            section_filter=section_filter,
            source_filter=source_filter,
        )

        # 3. Query Qdrant with dual-API compatibility
        scored_points = []
        try:
            if hasattr(self.client, "query_points"):
                response = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    query_filter=qdrant_filter,
                    limit=top_k,
                    score_threshold=score_threshold,
                )
                scored_points = response.points
            elif hasattr(self.client, "search"):
                scored_points = self.client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    query_filter=qdrant_filter,
                    limit=top_k,
                    score_threshold=score_threshold,
                )
            else:
                logger.error("QdrantClient has neither 'query_points' nor 'search' method.")
                return []
        except Exception as e:
            logger.error(f"Qdrant query execution failed: {e}")
            return []

        # 4. Map ScoredPoints to domain RetrievedChunk models
        results: List[RetrievedChunk] = []
        for point in scored_points:
            payload = point.payload or {}
            content = payload.get("content", "")
            source_str = payload.get("source", "resume")
            section_str = payload.get("section", "other")

            try:
                source_enum = IngestionSource(source_str)
            except ValueError:
                source_enum = IngestionSource.RESUME

            try:
                section_enum = SectionType(section_str)
            except ValueError:
                section_enum = SectionType.OTHER

            # Extract remaining metadata fields
            metadata = {
                k: v
                for k, v in payload.items()
                if k not in ("content", "source", "section")
            }

            results.append(
                RetrievedChunk(
                    content=content,
                    source=source_enum,
                    section=section_enum,
                    metadata=metadata,
                    score=float(point.score if point.score is not None else 0.0),
                    chunk_id=str(point.id) if point.id is not None else None,
                )
            )

        logger.debug(
            f"Retrieved {len(results)} chunks for query: '{query[:40]}...' "
            f"(filters: section={section_filter}, source={source_filter})"
        )
        return results

    # ── Convenience section-filtered retrievers ─────────────────────

    def retrieve_skills(self, query: str, top_k: int = 5) -> List[RetrievedChunk]:
        """Retrieve specifically from candidate skills sections."""
        return self.retrieve(
            query=query,
            top_k=top_k,
            section_filter=SectionType.SKILLS,
        )

    def retrieve_experience(self, query: str, top_k: int = 5) -> List[RetrievedChunk]:
        """Retrieve specifically from candidate work experience sections."""
        return self.retrieve(
            query=query,
            top_k=top_k,
            section_filter=SectionType.EXPERIENCE,
        )

    def retrieve_projects(self, query: str, top_k: int = 5) -> List[RetrievedChunk]:
        """Retrieve specifically from candidate project sections."""
        return self.retrieve(
            query=query,
            top_k=top_k,
            section_filter=SectionType.PROJECTS,
        )

    def retrieve_education(self, query: str, top_k: int = 3) -> List[RetrievedChunk]:
        """Retrieve specifically from candidate education sections."""
        return self.retrieve(
            query=query,
            top_k=top_k,
            section_filter=SectionType.EDUCATION,
        )

    def get_candidate_context(
        self,
        query: str,
        top_k: int = 6,
    ) -> str:
        """
        Convenience method to retrieve chunks and format them into a cohesive Markdown
        context block for LLM prompts.
        """
        chunks = self.retrieve(query=query, top_k=top_k)
        if not chunks:
            return "No relevant candidate profile information found in vector memory."

        formatted_parts = []
        for i, chunk in enumerate(chunks, 1):
            source_tag = f"[{chunk.source.value.upper()} | {chunk.section.value.upper()}]"
            formatted_parts.append(f"{i}. {source_tag} (Relevance: {chunk.score:.2f})\n{chunk.content}")

        return "\n\n".join(formatted_parts)
