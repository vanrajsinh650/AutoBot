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


class SyncRunStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class SyncRunRecord(BaseModel):
    """Execution log and audit record for a single board synchronization run."""
    sync_run_id: str
    source_name: str
    source_type: SourceType
    board_slug: str
    status: SyncRunStatus = SyncRunStatus.IN_PROGRESS
    is_complete: bool = False
    total_retrieved: int = 0
    new_jobs: int = 0
    updated_jobs: int = 0
    duplicates_removed: int = 0
    expired_jobs: int = 0
    error_message: str = ""
    started_at: str
    completed_at: str = ""


class JobSourceConfig(BaseModel):
    """Configuration record for a discovery job source."""
    name: str
    source_type: SourceType
    board_token_or_slug: str
    base_url: Optional[str] = None
    is_active: bool = True
    refresh_interval: int = 3600
    status: str = "active"
    last_synced_at: Optional[str] = None
    concurrency_limit: int = 2
    failure_count: int = 0
    last_error: str = ""
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    next_sync_at: Optional[str] = None
    last_sync_complete: bool = False
    last_retrieved_count: int = 0
    last_expired_count: int = 0


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
    workplace_type: str = "on-site"  # "remote", "hybrid", "on-site"
    status: str = "active"           # "active", "expired", "unavailable"
    salary_info: str = ""
    compensation_min: Optional[float] = None
    compensation_max: Optional[float] = None
    currency: str = ""
    publication_date: str = ""
    discovered_at: str = ""
    source_updated_at: str = ""
    last_verified_at: str = ""
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
