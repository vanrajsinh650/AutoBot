"""
Portfolio / personal website scraper with HTML sanitization and semantic heading categorization.

Educational Concept:
Web scraping for RAG requires high-signal text extraction:
1. HTML Sanitization:
   Raw web pages are filled with boilerplate (navigation menus, cookie consent banners,
   tracking scripts, footer copyrights). If embedded, these noise tokens corrupt the vector
   space, causing false positive semantic matches. Decomposing `<script>`, `<style>`, `<nav>`,
   `<footer>`, and `<header>` tags isolates pure content.
2. Semantic Heading Grouping:
   Heading tags (`<h2>`, `<h3>`) often define the structural taxonomy of a personal portfolio
   ("About Me", "Projects", "Technical Skills"). Grouping text under each heading and classifying
   it into `SectionType` ensures rich context is preserved.
3. Fault Isolation:
   Personal websites may suffer from DNS failures, SSL expiration, or bot blocking.
   Portfolio scraping is strictly non-fatal: exceptions are caught and logged as warnings,
   allowing the core resume ingestion to proceed unhindered.
"""

from typing import List, Optional
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import requests

from src.ingestion.models import DocumentChunk, IngestionSource, SectionType
from src.utils.logger import logger


# Mapping keywords in headings to SectionType
HEADING_SECTION_MAP = [
    (re.compile(r"\b(?:about(?:\s+me)?|bio|background|who\s+i\s+am|intro(?:duction)?)\b", re.IGNORECASE), SectionType.SUMMARY),
    (re.compile(r"\b(?:projects?|featured\s+work|creations|portfolio|open\s+source)\b", re.IGNORECASE), SectionType.PROJECTS),
    (re.compile(r"\b(?:skills?|technologies|tech\s+stack|competencies|tools)\b", re.IGNORECASE), SectionType.SKILLS),
    (re.compile(r"\b(?:experience|employment|work\s+history|career)\b", re.IGNORECASE), SectionType.EXPERIENCE),
    (re.compile(r"\b(?:education|academic|degrees?)\b", re.IGNORECASE), SectionType.EDUCATION),
    (re.compile(r"\b(?:certifications?|awards?|honors?)\b", re.IGNORECASE), SectionType.CERTIFICATIONS),
    (re.compile(r"\b(?:contact(?:\s+me)?|get\s+in\s+touch)\b", re.IGNORECASE), SectionType.CONTACT),
]

TAGS_TO_REMOVE = [
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "noscript",
    "svg",
    "form",
    "iframe",
]


def _categorize_heading(heading_text: str) -> SectionType:
    """Classify a section heading into a standardized SectionType."""
    for pattern, section_type in HEADING_SECTION_MAP:
        if pattern.search(heading_text):
            return section_type
    return SectionType.OTHER


def scrape_portfolio(url: Optional[str], timeout: int = 15) -> List[DocumentChunk]:
    """
    Fetch and sanitize content from a candidate's portfolio website.
    
    Args:
        url: The web URL to scrape.
        timeout: Network request timeout in seconds.
        
    Returns:
        List of DocumentChunk instances extracted from sanitized HTML.
    """
    if not url or not url.strip():
        return []

    clean_url = url.strip()
    try:
        parsed = urlparse(clean_url)
        if not parsed.scheme or not parsed.netloc:
            logger.warning(f"Invalid portfolio URL format: {clean_url}")
            return []
    except (ValueError, Exception) as e:
        logger.warning(f"Malformed portfolio URL ({clean_url}): {e}")
        return []

    logger.info(f"Fetching portfolio content from: {clean_url}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 AutoBot/2.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        response = requests.get(clean_url, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning(
            f"Failed to fetch portfolio website ({clean_url}): {e}. "
            "Proceeding without portfolio data."
        )
        return []

    soup = BeautifulSoup(response.text, "html.parser")

    # Sanitize: decompose non-content tags
    for tag_name in TAGS_TO_REMOVE:
        for element in soup.find_all(tag_name):
            element.decompose()

    chunks: List[DocumentChunk] = []

    # Search for structured sections or headings
    headings = soup.find_all(["h1", "h2", "h3"])

    if headings:
        for heading in headings:
            heading_text = heading.get_text(strip=True)
            if not heading_text or len(heading_text) < 3:
                continue

            section_type = _categorize_heading(heading_text)

            # Collect subsequent text siblings until next heading
            section_content: List[str] = []
            curr = heading.find_next_sibling()
            while curr and curr.name not in ["h1", "h2", "h3"]:
                text = curr.get_text(separator=" ", strip=True)
                if len(text) >= 15:
                    section_content.append(text)
                curr = curr.find_next_sibling()

            # If no siblings were found, inspect parent container
            if not section_content and heading.parent:
                parent_text = heading.parent.get_text(separator=" ", strip=True)
                # Remove heading text from parent content
                body_text = parent_text.replace(heading_text, "").strip()
                if len(body_text) >= 20:
                    section_content.append(body_text)

            if section_content:
                combined_content = f"{heading_text}:\n" + "\n".join(section_content)
                chunks.append(
                    DocumentChunk(
                        content=combined_content,
                        source=IngestionSource.PORTFOLIO,
                        section=section_type,
                        metadata={"heading": heading_text, "url": clean_url},
                    )
                )

    # Fallback: if no headings yielded chunks, extract clean body paragraphs
    if not chunks:
        logger.debug("No structured heading blocks found; extracting body paragraphs.")
        paragraphs = [p.get_text(separator=" ", strip=True) for p in soup.find_all("p")]
        for para in paragraphs:
            if len(para) >= 40:
                chunks.append(
                    DocumentChunk(
                        content=para,
                        source=IngestionSource.PORTFOLIO,
                        section=SectionType.OTHER,
                        metadata={"url": clean_url},
                    )
                )

    logger.info(f"Extracted {len(chunks)} chunks from portfolio ({clean_url}).")
    return chunks
