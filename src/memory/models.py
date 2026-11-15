"""
Data models and schemas for AutoBot v2 Memory & RAG Retrieval Layer.

Educational Concept:
In an agentic workflow, Memory is divided into:
1. Long-Term Semantic Memory (Vector Store):
   Stores immutable or persistent knowledge (the candidate's resume, experience, skills,
   and portfolio) as multi-dimensional embeddings in Qdrant.
2. Retrieval Context (RAG):
   At runtime, the agent queries the vector store for semantic matches to ground LLM
   responses. RetrievedChunk encapsulates the result and its cosine similarity score.
3. Form & Decision Contracts:
   FormQuestion, FormAnswer, JobMatchEvaluation, and CoverLetter provide strict, typed
   contracts between the retrieval engine, the LLM reasoning agent, and the browser actuators.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.ingestion.models import IngestionSource, SectionType


class FieldType(str, Enum):
    """
    HTML / Web form field types encountered during job applications.
    
    Pedagogical Note:
    Different form fields require different output post-processing.
    For example:
    - NUMBER requires integer/float extraction (e.g., '5', not 'I have 5 years').
    - SELECT and RADIO require an exact match against allowed options.
    - CHECKBOX requires boolean coercion.
    """
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"


class RetrievedChunk(BaseModel):
    """
    A single chunk of candidate profile information returned from semantic vector retrieval.
    
    Attributes:
        content: The text excerpt from the candidate's profile.
        source: Provenance source (resume, linkedin, portfolio).
        section: Semantic section (skills, experience, projects, etc.).
        metadata: Associated key-value metadata.
        score: Cosine similarity score (typically 0.0 to 1.0, where 1.0 is identical).
        chunk_id: Unique identifier in Qdrant.
    """
    content: str
    source: IngestionSource
    section: SectionType
    metadata: Dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    chunk_id: Optional[str] = None


class FormQuestion(BaseModel):
    """
    Specification of a screening question extracted from a job application form.
    """
    question: str
    field_type: FieldType = FieldType.TEXT
    options: Optional[List[str]] = None
    required: bool = True


class FormAnswer(BaseModel):
    """
    Structured answer produced by the FormRAG engine.
    
    Attributes:
        question: The original question text.
        answer: The final formatted string to type/select in the form.
        confidence: Estimated confidence score (0.0 to 1.0).
        source: Attribution of answer ("config_override", "rag_llm", or "fallback").
        evidence_chunks: Profile chunks retrieved from Qdrant that substantiate this answer.
    """
    question: str
    answer: str
    confidence: float = 1.0
    source: str = "rag_llm"
    evidence_chunks: List[RetrievedChunk] = Field(default_factory=list)


class JobMatchEvaluation(BaseModel):
    """
    Semantic evaluation comparing a job posting against the candidate's profile.
    
    Used by the LangGraph agent state machine to decide whether to proceed with
    application (should_apply edge).
    """
    job_title: str
    company: str
    match_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Cosine/LLM composite match score between 0.0 and 1.0.",
    )
    is_match: bool = Field(
        ...,
        description="True if match_score exceeds configured min_match_score threshold.",
    )
    matching_skills: List[str] = Field(default_factory=list)
    missing_skills: List[str] = Field(default_factory=list)
    summary_reason: str = ""
    relevant_experiences: List[str] = Field(default_factory=list)


class CoverLetter(BaseModel):
    """
    Tailored cover letter generated for a specific job application.
    """
    recipient: str = "Hiring Team"
    company: str
    role: str
    content: str
    highlighted_skills: List[str] = Field(default_factory=list)
