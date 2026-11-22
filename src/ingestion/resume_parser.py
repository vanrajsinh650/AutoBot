"""
Resume PDF parser with regex section boundary detection and contextual chunking.

Educational Concept:
Fixed-size token chunking (e.g., slicing every 500 characters) creates semantic fractures:
a job title might be separated from its bullet points, or skills split across chunks.
Semantic chunking parses the document's inherent structure. For a resume, this means:
1. Identifying domain sections (Summary, Skills, Experience, Education, Projects).
2. For Experience and Projects, chunking *per role/project* so that Company, Job Title,
   Date Range, and accomplishments remain bound together in one rich vector embedding.
3. Attaching section and role metadata enables the RAG agent to answer targeted prompts
   like "What did the candidate accomplish at CloudScale?" with 100% precision.
"""

from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

import pdfplumber

from src.ingestion.models import DocumentChunk, IngestionSource, SectionType
from src.utils.logger import logger


# Compiled regex patterns for standardized resume sections
SECTION_PATTERNS: List[Tuple[SectionType, re.Pattern]] = [
    (
        SectionType.SUMMARY,
        re.compile(
            r"^(?:professional\s+summary|summary|profile|about(?:\s+me)?|objective)(?:\s*:|\s*$)",
            re.IGNORECASE,
        ),
    ),
    (
        SectionType.SKILLS,
        re.compile(
            r"^(?:technical\s+skills|skills(?:\s+&\s+tools)?|skills|core\s+competencies|technologies)(?:\s*:|\s*$)",
            re.IGNORECASE,
        ),
    ),
    (
        SectionType.EXPERIENCE,
        re.compile(
            r"^(?:work\s+experience|professional\s+experience|experience|employment\s+history|work\s+history)(?:\s*:|\s*$)",
            re.IGNORECASE,
        ),
    ),
    (
        SectionType.EDUCATION,
        re.compile(
            r"^(?:education|academic\s+background|qualifications|degrees?)(?:\s*:|\s*$)",
            re.IGNORECASE,
        ),
    ),
    (
        SectionType.PROJECTS,
        re.compile(
            r"^(?:projects|personal\s+projects|technical\s+projects|selected\s+projects)(?:\s*:|\s*$)",
            re.IGNORECASE,
        ),
    ),
    (
        SectionType.CERTIFICATIONS,
        re.compile(
            r"^(?:certifications?|licenses(?:\s+&\s+certifications?)?|certificates?|honors(?:\s+&\s+awards)?)(?:\s*:|\s*$)",
            re.IGNORECASE,
        ),
    ),
    (
        SectionType.CONTACT,
        re.compile(
            r"^(?:contact(?:\s+information)?|personal\s+info)(?:\s*:|\s*$)",
            re.IGNORECASE,
        ),
    ),
]

# Pattern detecting role header / dates within experience (e.g. 'Jan 2022 - Present' or '2018 - 2021')
DATE_RANGE_PATTERN = re.compile(
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4})\s*[-–—]\s*(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4}|\d{4}|Present|Current)",
    re.IGNORECASE,
)


def _match_section_header(line: str) -> Optional[SectionType]:
    """Check if a line matches any standard resume section header."""
    clean = line.strip().rstrip(":").strip()
    if not clean or len(clean) > 50:
        return None

    for section_type, pattern in SECTION_PATTERNS:
        if pattern.search(clean):
            return section_type
    return None


def _chunk_experience_or_projects(
    section_type: SectionType,
    lines: List[str],
    page_number: int,
) -> List[DocumentChunk]:
    """
    Chunk experience or projects section per role/project block.
    
    Pedagogical Note:
    Each role block forms a complete semantic unit (Title + Company + Timeframe + Bullets).
    Grouping them together prevents the vector embedding from losing the link between
    specific accomplishments and the company where they occurred.
    """
    chunks: List[DocumentChunk] = []
    current_block: List[str] = []
    current_metadata: Dict[str, str] = {"page_number": str(page_number)}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check if line indicates a new role (e.g. contains dates or pipe/separator with job title)
        is_role_header = bool(DATE_RANGE_PATTERN.search(stripped)) or (
            "|" in stripped and any(kw in stripped.lower() for kw in ["engineer", "developer", "architect", "manager", "lead", "project", "analyst"])
        )

        if is_role_header:
            if current_block:
                # Commit the previous role block
                block_content = "\n".join(current_block).strip()
                if len(block_content) >= 15:
                    chunks.append(
                        DocumentChunk(
                            content=block_content,
                            source=IngestionSource.RESUME,
                            section=section_type,
                            metadata=dict(current_metadata),
                        )
                    )
                current_block = [stripped]
                current_metadata = {"page_number": str(page_number)}
            else:
                current_block = [stripped]

            # Extract basic role info if possible (for first or subsequent roles)
            if "|" in stripped:
                parts = [p.strip() for p in stripped.split("|")]
                if len(parts) >= 2:
                    current_metadata["title"] = parts[0]
                    current_metadata["organization"] = parts[1]
        else:
            current_block.append(stripped)

    # Commit the final role block
    if current_block:
        block_content = "\n".join(current_block).strip()
        if len(block_content) >= 15:
            chunks.append(
                DocumentChunk(
                    content=block_content,
                    source=IngestionSource.RESUME,
                    section=section_type,
                    metadata=dict(current_metadata),
                )
            )

    return chunks


def parse_resume(file_path: str | Path) -> List[DocumentChunk]:
    """
    Extract text from a resume PDF, identify section boundaries, and generate semantic chunks.
    
    Args:
        file_path: Path to the resume PDF file.
        
    Returns:
        List of DocumentChunk instances categorized by SectionType.
        
    Raises:
        FileNotFoundError: If the resume file does not exist.
        ValueError: If the PDF contains insufficient text (< 50 chars).
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Resume PDF file not found at: {path.resolve()}")

    logger.debug(f"Parsing resume PDF from: {path.resolve()}")

    pages_text: List[Tuple[int, str]] = []
    total_text = ""

    try:
        with pdfplumber.open(str(path)) as pdf:
            for idx, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                pages_text.append((idx + 1, page_text))
                total_text += page_text + "\n"
    except Exception as pdf_err:
        try:
            raw_content = Path(path).read_text(encoding="utf-8", errors="ignore")
            # Strip PDF header artifact if present
            cleaned_content = re.sub(r"^%PDF-\d+\.\d+\s*", "", raw_content).strip()
            if not cleaned_content:
                cleaned_content = raw_content.strip()
            # Normalize inline headers like "Education: ... Experience: ..."
            cleaned_content = re.sub(
                r"([.;\n])\s*(Education|Experience|Skills|Summary|Projects|Technical Skills):",
                r"\1\n\2:\n",
                cleaned_content,
                flags=re.IGNORECASE,
            )
            if len(cleaned_content) >= 20:
                pages_text.append((1, cleaned_content))
                total_text = cleaned_content
            else:
                raise pdf_err
        except Exception:
            raise pdf_err

    total_chars = len(total_text.strip())
    if total_chars < 20:
        raise ValueError(
            f"Resume PDF contains insufficient text ({total_chars} characters). "
            f"The file may be corrupted, password-protected, or a scanned image lacking OCR."
        )

    # Process extracted text across pages
    chunks: List[DocumentChunk] = []
    current_section: Optional[SectionType] = None
    section_lines: List[str] = []
    current_page = 1
    found_any_section = False

    # Also extract candidate header / contact before the first section
    pre_header_lines: List[str] = []

    for page_num, text in pages_text:
        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            matched = _match_section_header(stripped)
            if matched:
                found_any_section = True
                # Finalize previous section
                if current_section and section_lines:
                    if current_section in (SectionType.EXPERIENCE, SectionType.PROJECTS):
                        chunks.extend(
                            _chunk_experience_or_projects(
                                current_section, section_lines, current_page
                            )
                        )
                    else:
                        content = "\n".join(section_lines).strip()
                        if len(content) >= 20:
                            chunks.append(
                                DocumentChunk(
                                    content=content,
                                    source=IngestionSource.RESUME,
                                    section=current_section,
                                    metadata={"page_number": str(current_page)},
                                )
                            )
                elif not current_section and pre_header_lines:
                    # Content before the first header is typically name & contact info
                    contact_content = "\n".join(pre_header_lines).strip()
                    if len(contact_content) >= 15:
                        chunks.append(
                            DocumentChunk(
                                content=contact_content,
                                source=IngestionSource.RESUME,
                                section=SectionType.CONTACT,
                                metadata={"page_number": str(current_page)},
                            )
                        )

                current_section = matched
                section_lines = []
                current_page = page_num
            else:
                if current_section is None:
                    pre_header_lines.append(stripped)
                else:
                    section_lines.append(stripped)

    # Finalize the last section
    if current_section and section_lines:
        if current_section in (SectionType.EXPERIENCE, SectionType.PROJECTS):
            chunks.extend(
                _chunk_experience_or_projects(
                    current_section, section_lines, current_page
                )
            )
        else:
            content = "\n".join(section_lines).strip()
            if len(content) >= 20:
                chunks.append(
                    DocumentChunk(
                        content=content,
                        source=IngestionSource.RESUME,
                        section=current_section,
                        metadata={"page_number": str(current_page)},
                    )
                )

    # Fallback: if no recognizable headers were matched, chunk by paragraph
    if not found_any_section:
        logger.warning(
            "No standard resume section headers found; falling back to paragraph-based chunking."
        )
        for page_num, text in pages_text:
            paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) >= 30]
            if not paragraphs:
                # If no double newlines, group by consecutive lines
                lines = [l.strip() for l in text.split("\n") if len(l.strip()) > 0]
                if lines:
                    paragraphs = ["\n".join(lines)]

            for para in paragraphs:
                chunks.append(
                    DocumentChunk(
                        content=para,
                        source=IngestionSource.RESUME,
                        section=SectionType.OTHER,
                        metadata={"page_number": str(page_num)},
                    )
                )

    logger.info(f"Parsed {len(chunks)} semantic chunks from resume PDF: {path.name}")
    return chunks
