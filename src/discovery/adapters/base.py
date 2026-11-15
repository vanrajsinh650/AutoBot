"""
Base Job Source Adapter and normalization helpers.
"""

from abc import ABC, abstractmethod
import html
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType


def strip_html(raw_html: str) -> str:
    """Safely strip HTML tags and decode entities into clean plain text."""
    if not raw_html:
        return ""
    try:
        # Replace block tags with newline placeholders before parsing
        text = re.sub(r"(?i)<(br|p|div|li|h[1-6])\b[^>]*>", "\n", raw_html)
        soup = BeautifulSoup(text, "html.parser")
        clean = soup.get_text(separator=" ")
        # Normalize whitespace while preserving intentional paragraph breaks
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in clean.splitlines()]
        return "\n".join(line for line in lines if line).strip()
    except Exception:
        clean = re.sub(r"<[^>]+>", " ", raw_html)
        return html.unescape(clean).strip()


def classify_employment_type(text: str) -> EmploymentType:
    """Infer employment type from title, commitment, or description."""
    lower = text.lower()
    if any(k in lower for k in ["intern", "internship", "co-op", "trainee", "student"]):
        return EmploymentType.INTERNSHIP
    if any(k in lower for k in ["contract", "contractor", "freelance", "temp", "temporary"]):
        return EmploymentType.CONTRACT
    if any(k in lower for k in ["part-time", "part time"]):
        return EmploymentType.PART_TIME
    if any(k in lower for k in ["full-time", "full time", "permanent", "regular"]):
        return EmploymentType.FULL_TIME
    return EmploymentType.FULL_TIME


def detect_remote(location_str: str, text: str = "") -> bool:
    """Determine if a job allows remote work."""
    comb = f"{location_str} {text}".lower()
    return any(k in comb for k in ["remote", "anywhere", "work from home", "wfh", "telecommute"])


class BaseJobSourceAdapter(ABC):
    """Abstract interface for all job discovery source adapters."""

    def __init__(self, config: JobSourceConfig):
        self.config = config

    @abstractmethod
    async def fetch_jobs(self, session: Optional[Any] = None) -> List[NormalizedJob]:
        """Fetch and normalize job postings from this source."""
        pass
