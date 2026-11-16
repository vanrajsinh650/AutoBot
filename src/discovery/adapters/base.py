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


def detect_workplace_type(location_str: str, text: str = "") -> str:
    """
    Classify workplace model: 'remote', 'hybrid', or 'on-site'.
    """
    comb = f"{location_str} {text}".lower()
    if "hybrid" in comb:
        return "hybrid"
    if detect_remote(location_str, text):
        return "remote"
    return "on-site"


def extract_compensation(text: str) -> tuple[Optional[float], Optional[float], str]:
    """
    Extract minimum compensation, maximum compensation, and currency symbol/code.
    Handles ranges like $120,000 - $160,000, 15 - 20 LPA, €80k - €110k, etc.
    """
    if not text:
        return None, None, ""

    # Detect currency
    currency = ""
    if "$" in text or "usd" in text.lower():
        currency = "USD"
    elif "€" in text or "eur" in text.lower():
        currency = "EUR"
    elif "£" in text or "gbp" in text.lower():
        currency = "GBP"
    elif "₹" in text or "inr" in text.lower() or "lpa" in text.lower():
        currency = "INR"

    # Match LPA (e.g., "15 - 20 LPA", "12 LPA")
    lpa_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*lpa", text, re.IGNORECASE)
    if lpa_match:
        return float(lpa_match.group(1)) * 100000, float(lpa_match.group(2)) * 100000, "INR"

    single_lpa = re.search(r"(\d+(?:\.\d+)?)\s*lpa", text, re.IGNORECASE)
    if single_lpa:
        val = float(single_lpa.group(1)) * 100000
        return val, val, "INR"

    # Match standard dollar/euro amounts e.g. "$120,000 - $160,000" or "$120k - $160k"
    range_match = re.search(
        r"[\$€£]?\s*(\d{2,3}(?:,\d{3})+|\d{2,3}k|\d{4,6})\s*(?:-|to)\s*[\$€£]?\s*(\d{2,3}(?:,\d{3})+|\d{2,3}k|\d{4,6})",
        text,
        re.IGNORECASE,
    )
    if range_match:
        def _parse(val_str: str) -> float:
            clean = val_str.lower().replace(",", "").replace("$", "").replace("€", "").replace("£", "").strip()
            if clean.endswith("k"):
                return float(clean[:-1]) * 1000.0
            return float(clean)

        try:
            return _parse(range_match.group(1)), _parse(range_match.group(2)), currency or "USD"
        except Exception:
            pass

    return None, None, currency


class BaseJobSourceAdapter(ABC):
    """Abstract interface for all job discovery source adapters."""

    def __init__(self, config: JobSourceConfig):
        self.config = config
        self.is_last_sync_complete: bool = False

    @abstractmethod
    async def fetch_jobs(self, session: Optional[Any] = None) -> List[NormalizedJob]:
        """Fetch and normalize job postings from this source."""
        pass

    async def fetch_jobs_detailed(
        self, session: Optional[Any] = None
    ) -> tuple[List[NormalizedJob], bool]:
        """
        Fetch and normalize jobs, returning (jobs, is_complete).
        is_complete indicates whether the response represents an authoritative,
        complete sync of the board without truncated pages or network aborts.
        """
        jobs = await self.fetch_jobs(session=session)
        return jobs, getattr(self, "is_last_sync_complete", True)
