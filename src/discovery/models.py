"""
Domain models for Job Discovery, Normalization, and Deduplication.
"""

from datetime import datetime
from enum import Enum
import hashlib
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EmploymentType(str, Enum):
    FULL_TIME = "full-time"
    INTERNSHIP = "internship"
    CONTRACT = "contract"
    PART_TIME = "part-time"
    OTHER = "other"


class SourceType(str, Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    MANUAL = "manual"
    USER_IMPORT = "user_import"


class JobSourceConfig(BaseModel):
    """Configuration record for a discovery job source."""
    name: str
    source_type: SourceType
    board_token_or_slug: str
    base_url: Optional[str] = None
    is_active: bool = True


class NormalizedJob(BaseModel):
    """
    Standardized, canonical representation of a discovered job vacancy.
    """
    stable_id: str
    source_name: str
    source_type: SourceType
    title: str
    company: str
    description: str
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    location: str = ""
    country: str = ""
    is_remote: bool = False
    salary_info: str = ""
    publication_date: str = ""
    application_url: str = ""
    requirements: List[str] = Field(default_factory=list)
    raw_data: Dict[str, Any] = Field(default_factory=dict)
    fingerprint: str = ""

    def compute_fingerprint(self) -> str:
        """Generate deterministic fallback fingerprint for cross-source deduplication."""
        norm_company = re.sub(r"[^a-z0-9]", "", self.company.lower())
        norm_title = re.sub(r"[^a-z0-9]", "", self.title.lower())
        desc_snippet = re.sub(r"\s+", " ", self.description[:200].lower()).strip()
        data = f"{norm_company}|{norm_title}|{desc_snippet}"
        return hashlib.sha256(data.encode("utf-8")).hexdigest()
