"""
Unit and integration tests for AutoBot v2 Memory & RAG Retrieval Layer.
"""

from typing import List
import pytest
from langchain_core.language_models import FakeListChatModel
from qdrant_client import QdrantClient
from qdrant_client.http import models

from src.ingestion.models import DocumentChunk, IngestionSource, SectionType
from src.memory.cover_letter import CoverLetterGenerator
from src.memory.form_rag import FormRAG
from src.memory.job_matcher import JobMatcher
from src.memory.models import (
    CoverLetter,
    FieldType,
    FormAnswer,
    FormQuestion,
    JobMatchEvaluation,
    RetrievedChunk,
)
from src.memory.retriever import ProfileRetriever
from src.utils.config import EnvSettings


class DeterministicEmbeddings:
    """Mock embeddings generating orthogonal vectors for predictable retrieval."""

    def __init__(self, dim: int = 4):
        self.dim = dim

    def embed_query(self, text: str) -> List[float]:
        t = text.lower()
        if "python" in t or "backend" in t or "skill" in t:
            return [1.0, 0.0, 0.0, 0.0]
        if "lead" in t or "experience" in t or "architect" in t:
            return [0.0, 1.0, 0.0, 0.0]
        if "degree" in t or "education" in t or "college" in t:
            return [0.0, 0.0, 1.0, 0.0]
        return [0.5, 0.5, 0.5, 0.5]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self.embed_query(t) for t in texts]


@pytest.fixture
def mock_qdrant_client():
    """Create an isolated in-memory Qdrant client populated with test profile points."""
    client = QdrantClient(":memory:")
    collection_name = "test_memory_collection"

    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE),
    )

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

    test_points = [
        models.PointStruct(
            id=1,
            vector=[1.0, 0.0, 0.0, 0.0],
            payload={
                "content": "Expert in Python, FastAPI, Docker, and PostgreSQL with 5 years experience.",
                "source": "resume",
                "section": "skills",
            },
        ),
        models.PointStruct(
            id=2,
            vector=[0.0, 1.0, 0.0, 0.0],
            payload={
                "content": "Senior Backend Engineer at Acme Corp leading distributed microservices.",
                "source": "resume",
                "section": "experience",
            },
        ),
        models.PointStruct(
            id=3,
            vector=[0.0, 0.0, 1.0, 0.0],
            payload={
                "content": "Bachelor of Technology in Computer Science from National University.",
                "source": "linkedin",
                "section": "education",
            },
        ),
        models.PointStruct(
            id=4,
            vector=[0.8, 0.6, 0.0, 0.0],
            payload={
                "content": "Built high-throughput payment processing engine handling 50k req/sec.",
                "source": "portfolio",
                "section": "projects",
            },
        ),
    ]

    client.upsert(collection_name=collection_name, points=test_points)
    return client, collection_name


@pytest.fixture
def retriever(mock_qdrant_client):
    """Instantiate ProfileRetriever pointing to the mock Qdrant collection."""
    client, coll_name = mock_qdrant_client
    env = EnvSettings(
        qdrant_url=":memory:",
        qdrant_collection=coll_name,
    )
    embeddings = DeterministicEmbeddings(dim=4)
    return ProfileRetriever(
        env=env,
        client=client,
        embeddings=embeddings,
        collection_name=coll_name,
    )


# ── ProfileRetriever Tests ─────────────────────────────────────────

def test_retriever_basic_search(retriever):
    """Verify semantic similarity retrieval returns expected chunks."""
    results = retriever.retrieve("Python backend developer", top_k=2)
    assert len(results) > 0
    top = results[0]
    assert isinstance(top, RetrievedChunk)
    assert "Python" in top.content
    assert top.section == SectionType.SKILLS
    assert top.source == IngestionSource.RESUME
    assert top.score > 0.90


def test_retriever_section_filtering(retriever):
    """Verify metadata filtering restricts retrieval to the requested section."""
    # Searching for education should only return education chunks
    edu_results = retriever.retrieve(
        "university degree",
        top_k=5,
        section_filter=SectionType.EDUCATION,
    )
    assert len(edu_results) == 1
    assert edu_results[0].section == SectionType.EDUCATION
    assert "Computer Science" in edu_results[0].content


def test_retriever_source_filtering(retriever):
    """Verify source filtering isolates resume vs linkedin vs portfolio."""
    portfolio_results = retriever.retrieve(
        "payment engine",
        top_k=5,
        source_filter=IngestionSource.PORTFOLIO,
    )
    assert len(portfolio_results) == 1
    assert portfolio_results[0].source == IngestionSource.PORTFOLIO


def test_retriever_empty_or_whitespace_query(retriever):
    """Empty queries must return an empty list without error."""
    assert retriever.retrieve("") == []
    assert retriever.retrieve("   ") == []


def test_retriever_convenience_methods(retriever):
    """Verify retrieve_skills, retrieve_experience, and get_candidate_context."""
    skills = retriever.retrieve_skills("Python", top_k=2)
    assert all(c.section == SectionType.SKILLS for c in skills)

    exp = retriever.retrieve_experience("Acme Corp", top_k=2)
    assert all(c.section == SectionType.EXPERIENCE for c in exp)

    context_str = retriever.get_candidate_context("Python", top_k=2)
    assert "RESUME" in context_str
    assert "Python" in context_str


# ── FormRAG Tests ──────────────────────────────────────────────────

def test_form_rag_config_override(retriever):
    """Verify deterministic config overrides intercept common screening questions."""
    config_answers = {
        "years_of_experience": "4",
        "expected_salary": "20 LPA",
        "willing_to_relocate": "Yes",
        "work_authorization": "Yes, legally authorized",
        "sponsorship_required": "No",
    }
    rag = FormRAG(retriever=retriever, config_answers=config_answers)

    # 1. Experience years question
    ans1 = rag.answer_question(
        "How many years of experience do you have?",
        field_type=FieldType.NUMBER,
    )
    assert ans1.source == "config_override"
    assert ans1.answer == "4"

    # 2. Sponsorship question
    ans2 = rag.answer_question(
        "Will you now or in the future require visa sponsorship?",
        field_type=FieldType.SELECT,
        options=["Yes", "No"],
    )
    assert ans2.source == "config_override"
    assert ans2.answer == "No"


def test_form_rag_llm_answering(retriever):
    """Verify grounded RAG generation when no config override matches."""
    fake_llm = FakeListChatModel(responses=["I have 5 years of professional Python experience."])
    rag = FormRAG(retriever=retriever, llm=fake_llm, config_answers={})

    ans = rag.answer_question(
        "Describe your background in Python backend engineering.",
        field_type=FieldType.TEXTAREA,
    )
    assert ans.source == "rag_llm"
    assert "Python" in ans.answer
    assert len(ans.evidence_chunks) > 0


def test_form_rag_number_field_sanitization(retriever):
    """Verify numeric fields extract only numeric digits even if LLM is verbose."""
    fake_llm = FakeListChatModel(responses=["I have approximately 5.5 years of experience."])
    rag = FormRAG(retriever=retriever, llm=fake_llm, config_answers={})

    ans = rag.answer_question(
        "How many years have you used Docker?",
        field_type=FieldType.NUMBER,
    )
    assert ans.answer == "5.5"


def test_form_rag_select_option_matching(retriever):
    """Verify select/radio fields constrain answers to the allowed option list."""
    fake_llm = FakeListChatModel(responses=["Bachelor's Degree"])
    rag = FormRAG(retriever=retriever, llm=fake_llm, config_answers={})

    ans = rag.answer_question(
        "What is your highest completed level of education?",
        field_type=FieldType.SELECT,
        options=["High School", "Bachelor's", "Master's", "PhD"],
    )
    assert ans.answer == "Bachelor's"


def test_form_rag_fallback_when_llm_unavailable(retriever):
    """Verify graceful heuristic fallback when LLM is unavailable."""
    rag = FormRAG(retriever=retriever, llm=None, config_answers={"years_of_experience": "3"})

    ans_num = rag.answer_question("Years of experience with Kubernetes?", field_type=FieldType.NUMBER)
    assert ans_num.source == "fallback"
    assert ans_num.answer == "3"

    ans_bool = rag.answer_question("Are you willing to relocate?", field_type=FieldType.RADIO, options=["Yes", "No"])
    assert ans_bool.answer == "Yes"


# ── JobMatcher Tests ───────────────────────────────────────────────

def test_job_matcher_llm_evaluation(retriever):
    """Verify JobMatcher parses structured JSON from LLM and calculates thresholds."""
    json_response = (
        '{\n'
        '  "match_score": 0.85,\n'
        '  "matching_skills": ["Python", "FastAPI", "Docker"],\n'
        '  "missing_skills": ["Kubernetes"],\n'
        '  "summary_reason": "Strong backend alignment with core Python stack.",\n'
        '  "relevant_experiences": ["Acme Corp"]\n'
        '}'
    )
    fake_llm = FakeListChatModel(responses=[json_response])
    matcher = JobMatcher(retriever=retriever, llm=fake_llm, min_match_score=0.60)

    eval_result = matcher.evaluate_job(
        job_title="Senior Python Developer",
        company="TechCorp",
        job_description="Seeking a Python engineer experienced with FastAPI and Docker.",
    )

    assert isinstance(eval_result, JobMatchEvaluation)
    assert eval_result.match_score == 0.85
    assert eval_result.is_match is True
    assert "Python" in eval_result.matching_skills
    assert "Kubernetes" in eval_result.missing_skills


def test_job_matcher_below_threshold(retriever):
    """Verify match is flagged False when score falls below min_match_score."""
    json_response = (
        '{\n'
        '  "match_score": 0.40,\n'
        '  "matching_skills": [],\n'
        '  "missing_skills": ["Rust", "Solidity"],\n'
        '  "summary_reason": "Candidate lacks blockchain experience.",\n'
        '  "relevant_experiences": []\n'
        '}'
    )
    fake_llm = FakeListChatModel(responses=[json_response])
    matcher = JobMatcher(retriever=retriever, llm=fake_llm, min_match_score=0.70)

    eval_result = matcher.evaluate_job(
        job_title="Rust Blockchain Developer",
        company="CryptoInc",
        job_description="Requires deep Rust and Solidity smart contract experience.",
    )

    assert eval_result.match_score == 0.40
    assert eval_result.is_match is False


def test_job_matcher_heuristic_fallback(retriever):
    """Verify mathematical fallback scoring when LLM is unavailable."""
    matcher = JobMatcher(retriever=retriever, llm=None, min_match_score=0.50)

    eval_result = matcher.evaluate_job(
        job_title="Python Backend Engineer",
        company="StartupX",
        job_description="We need Python and backend engineers.",
    )

    assert isinstance(eval_result, JobMatchEvaluation)
    assert eval_result.match_score > 0.0
    assert "python" in [s.lower() for s in eval_result.matching_skills]


# ── CoverLetterGenerator Tests ─────────────────────────────────────

def test_cover_letter_llm_generation(retriever):
    """Verify LLM-driven cover letter generation grounded in profile evidence."""
    mock_letter = (
        "Dear Hiring Team,\n\n"
        "I am writing to express my enthusiasm for the Senior Backend Engineer role at Acme Corp. "
        "With 5 years of experience architecting high-throughput systems with Python and FastAPI, "
        "I have built distributed microservices and payment engines handling 50k req/sec.\n\n"
        "I look forward to discussing how my experience can benefit your team.\n\n"
        "Sincerely,\nCandidate"
    )
    fake_llm = FakeListChatModel(responses=[mock_letter])
    generator = CoverLetterGenerator(retriever=retriever, llm=fake_llm)

    letter = generator.generate(
        job_title="Senior Backend Engineer",
        company="Acme Corp",
        job_description="Looking for experienced backend engineers in Python.",
    )

    assert isinstance(letter, CoverLetter)
    assert letter.company == "Acme Corp"
    assert letter.role == "Senior Backend Engineer"
    assert "FastAPI" in letter.content


def test_cover_letter_template_fallback(retriever):
    """Verify template variable substitution when LLM is not used."""
    custom_template = "Applying for {role} at {company}. Dear {recipient}."
    generator = CoverLetterGenerator(
        retriever=retriever,
        llm=None,
        default_template=custom_template,
    )

    letter = generator.generate(
        job_title="DevOps Specialist",
        company="CloudScale",
        job_description="Kubernetes and Terraform role.",
        recipient="Engineering Manager",
    )

    assert "Applying for DevOps Specialist at CloudScale." in letter.content
    assert "Dear Engineering Manager." in letter.content
