"""
AutoBot v2 Memory & RAG Retrieval Module.

Exports:
- ProfileRetriever: Queries Qdrant vector database for candidate profile chunks.
- FormRAG: Answers form screening questions grounded in profile memory.
- JobMatcher: Evaluates candidate fit and calculates match score vs job descriptions.
- CoverLetterGenerator: Generates personalized cover letters based on profile accomplishments.
- Data Models: RetrievedChunk, FormQuestion, FormAnswer, JobMatchEvaluation, CoverLetter, FieldType.
"""

from src.memory.models import (
    CoverLetter,
    FieldType,
    FormAnswer,
    FormQuestion,
    JobMatchEvaluation,
    RetrievedChunk,
)
from src.memory.retriever import ProfileRetriever
from src.memory.form_rag import FormRAG
from src.memory.job_matcher import JobMatcher
from src.memory.cover_letter import CoverLetterGenerator

__all__ = [
    "CoverLetter",
    "CoverLetterGenerator",
    "FieldType",
    "FormAnswer",
    "FormQuestion",
    "FormRAG",
    "JobMatchEvaluation",
    "JobMatcher",
    "ProfileRetriever",
    "RetrievedChunk",
]
