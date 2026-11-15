"""Tests for ingestion models and resume parsing."""

import os
from pathlib import Path
import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from src.ingestion.models import (
    IngestionSource,
    SectionType,
    DocumentChunk,
    IngestionSummary,
)
from src.ingestion.resume_parser import parse_resume


def create_sample_resume_pdf(
    file_path: Path,
    include_headers: bool = True,
    sparse_text: bool = False,
) -> None:
    """Helper to generate structured test PDFs using ReportLab."""
    c = canvas.Canvas(str(file_path), pagesize=letter)
    if sparse_text:
        # Less than 50 characters to simulate an empty or scanned PDF
        c.drawString(100, 750, "Short scan")
        c.save()
        return

    if not include_headers:
        # Fallback text without recognizable section headers
        c.drawString(100, 750, "This is a plain document without any standardized headers.")
        c.drawString(100, 730, "It contains multiple paragraphs describing background and knowledge.")
        c.drawString(100, 710, "Python and Docker are utilized for various engineering solutions.")
        c.save()
        return

    # Standard structured resume
    y = 750
    c.drawString(100, y, "Jane Doe")
    y -= 15
    c.drawString(100, y, "Email: jane.doe@example.com | Phone: +1 555-0199 | Location: San Francisco, CA | GitHub: github.com/janedoe")
    y -= 25

    c.drawString(100, y, "PROFESSIONAL SUMMARY")
    y -= 15
    c.drawString(100, y, "Senior Full-Stack Engineer with 7+ years of experience designing scalable microservices,")
    y -= 15
    c.drawString(100, y, "distributed architectures, and autonomous AI agent workflows using LangGraph and Python.")
    y -= 25

    c.drawString(100, y, "TECHNICAL SKILLS")
    y -= 15
    c.drawString(100, y, "Languages: Python, TypeScript, Go, SQL")
    y -= 15
    c.drawString(100, y, "Frameworks & Tools: FastAPI, LangChain, LangGraph, Qdrant, Docker, Kubernetes, AWS, PostgreSQL")
    y -= 25

    c.drawString(100, y, "WORK EXPERIENCE")
    y -= 15
    c.drawString(100, y, "Lead Platform Architect | CloudScale Inc | Jan 2022 - Present")
    y -= 15
    c.drawString(100, y, "- Spearheaded migration of monolithic batch jobs to event-driven microservices on Kubernetes.")
    y -= 15
    c.drawString(100, y, "- Built RAG document retrieval pipeline with Qdrant vector database reducing search latency by 45%.")
    y -= 25

    c.drawString(100, y, "Senior Software Engineer | DataCore Systems | Mar 2018 - Dec 2021")
    y -= 15
    c.drawString(100, y, "- Developed high-throughput REST APIs handling 15,000 requests/sec with FastAPI and Redis caching.")
    y -= 15
    c.drawString(100, y, "- Mentored a team of 6 engineers and standardized CI/CD pipelines with GitHub Actions.")
    y -= 25

    c.drawString(100, y, "EDUCATION")
    y -= 15
    c.drawString(100, y, "Bachelor of Science in Computer Science | University of California, Berkeley | 2014 - 2018")
    y -= 25

    c.drawString(100, y, "PROJECTS")
    y -= 15
    c.drawString(100, y, "AutoBot Agent | Open Source Project | 2024")
    y -= 15
    c.drawString(100, y, "- Autonomous multi-agent job application system built on LangGraph and Playwright.")
    y -= 25

    c.drawString(100, y, "CERTIFICATIONS")
    y -= 15
    c.drawString(100, y, "AWS Certified Solutions Architect - Professional (2023)")

    c.save()


def test_ingestion_models_validation():
    """Verify DocumentChunk and IngestionSummary instantiate and validate correctly."""
    chunk = DocumentChunk(
        content="Senior Software Engineer with 5 years experience in Python",
        source=IngestionSource.RESUME,
        section=SectionType.EXPERIENCE,
        metadata={"role": "Senior Software Engineer", "years": 5},
    )
    assert chunk.content.startswith("Senior Software Engineer")
    assert chunk.source == IngestionSource.RESUME
    assert chunk.section == SectionType.EXPERIENCE
    assert chunk.metadata["role"] == "Senior Software Engineer"
    assert chunk.chunk_id is None

    summary = IngestionSummary(
        total_chunks=10,
        chunks_by_source={"resume": 10},
        chunks_by_section={"experience": 10},
        collection_name="test_collection",
        vector_dim=1536,
        duration_seconds=1.5,
        skipped=False,
    )
    assert summary.total_chunks == 10
    assert summary.skipped is False


def test_parse_resume_file_not_found():
    """Missing resume PDF must raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        parse_resume("non_existent_file.pdf")


def test_parse_resume_empty_or_scanned_pdf(tmp_path):
    """PDF with insufficient text (< 50 chars) must raise ValueError."""
    sparse_pdf = tmp_path / "sparse.pdf"
    create_sample_resume_pdf(sparse_pdf, sparse_text=True)

    with pytest.raises(ValueError, match="insufficient text"):
        parse_resume(sparse_pdf)


def test_parse_resume_structured_sections(tmp_path):
    """Structured resume must parse into semantic section chunks."""
    pdf_path = tmp_path / "jane_doe_resume.pdf"
    create_sample_resume_pdf(pdf_path, include_headers=True)

    chunks = parse_resume(pdf_path)
    assert len(chunks) >= 5

    sections = {c.section for c in chunks}
    assert SectionType.SUMMARY in sections
    assert SectionType.SKILLS in sections
    assert SectionType.EXPERIENCE in sections
    assert SectionType.EDUCATION in sections

    for chunk in chunks:
        assert chunk.source == IngestionSource.RESUME
        assert len(chunk.content.strip()) > 0
        assert "page_number" in chunk.metadata

    # Verify experience section chunking per role and first-role metadata extraction
    exp_chunks = [c for c in chunks if c.section == SectionType.EXPERIENCE]
    assert len(exp_chunks) >= 2  # CloudScale and DataCore
    assert exp_chunks[0].metadata.get("title") == "Lead Platform Architect"
    assert exp_chunks[0].metadata.get("organization") == "CloudScale Inc"
    assert exp_chunks[1].metadata.get("title") == "Senior Software Engineer"
    assert exp_chunks[1].metadata.get("organization") == "DataCore Systems"


def test_parse_resume_paragraph_fallback(tmp_path):
    """PDF without standard headers should fall back to paragraph chunking."""
    pdf_path = tmp_path / "plain_doc.pdf"
    create_sample_resume_pdf(pdf_path, include_headers=False)

    chunks = parse_resume(pdf_path)
    assert len(chunks) >= 1
    for chunk in chunks:
        assert chunk.source == IngestionSource.RESUME
        assert chunk.section == SectionType.OTHER


def test_parse_resume_preserves_sentences_starting_with_keywords(tmp_path):
    """Body sentences starting with section keywords (e.g. 'Experience with Python...') must not be treated as headers."""
    pdf_path = tmp_path / "keyword_sentences.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    c.drawString(100, 750, "Jane Doe")
    c.drawString(100, 735, "Email: jane@example.com")
    c.drawString(100, 715, "PROFESSIONAL SUMMARY")
    c.drawString(100, 700, "Experience with Python is extensive and spans over eight years.")
    c.drawString(100, 685, "Projects completed include large-scale distributed streaming systems.")
    c.drawString(100, 665, "TECHNICAL SKILLS")
    c.drawString(100, 650, "Python, Go, Docker, Kubernetes, AWS")
    c.save()

    chunks = parse_resume(pdf_path)
    summary_chunks = [c for c in chunks if c.section == SectionType.SUMMARY]
    assert len(summary_chunks) == 1
    assert "Experience with Python is extensive" in summary_chunks[0].content
    assert "Projects completed include" in summary_chunks[0].content
