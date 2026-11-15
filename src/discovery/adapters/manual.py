"""
Manual / User-Imported Job Description Adapter.
Handles user-supplied vacancies, including LinkedIn postings pasted by the candidate.
Ensures zero automated LinkedIn scraping or DOM manipulation occurs.
"""

from datetime import datetime
import hashlib
import re
from typing import Any, Dict, List, Optional

from src.discovery.adapters.base import (
    BaseJobSourceAdapter,
    classify_employment_type,
    detect_remote,
    strip_html,
)
from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.matching.eligibility import resolve_job_country


class ManualJobAdapter(BaseJobSourceAdapter):
    """Adapter for normalizing user-supplied or pasted job descriptions."""

    def __init__(self, config: Optional[JobSourceConfig] = None):
        cfg = config or JobSourceConfig(
            name="User Import",
            source_type=SourceType.MANUAL,
            board_token_or_slug="manual_import",
        )
        super().__init__(cfg)

    async def fetch_jobs(self, session: Optional[Any] = None) -> List[NormalizedJob]:
        """Manual adapter does not scrape; returns empty list if called without payload."""
        return []

    def import_job(
        self,
        title: str,
        company: str,
        description: str,
        location: str = "",
        employment_type: Optional[str] = None,
        is_remote: Optional[bool] = None,
        application_url: str = "",
        salary_info: str = "",
        source_label: str = "Manual Import",
    ) -> NormalizedJob:
        """
        Normalize and create a NormalizedJob instance from human-submitted data.
        """
        clean_title = title.strip()
        clean_company = company.strip()
        clean_desc = strip_html(description).strip()
        clean_loc = location.strip()

        emp_type = (
            EmploymentType(employment_type)
            if employment_type in [e.value for e in EmploymentType]
            else classify_employment_type(f"{clean_title} {clean_desc[:400]}")
        )

        remote = (
            bool(is_remote)
            if is_remote is not None
            else detect_remote(clean_loc, f"{clean_title} {clean_desc[:300]}")
        )

        # Generate stable ID from hash of company + title + snippet
        norm_key = f"{clean_company.lower()}:{clean_title.lower()}:{clean_desc[:120]}"
        hash_id = hashlib.sha256(norm_key.encode("utf-8")).hexdigest()[:16]
        stable_id = f"manual:{hash_id}"

        # Detect if it's a LinkedIn job supplied by user
        source_type = SourceType.USER_IMPORT if "linkedin" in application_url.lower() else SourceType.MANUAL

        job = NormalizedJob(
            stable_id=stable_id,
            source_name=source_label,
            source_type=source_type,
            title=clean_title,
            company=clean_company,
            description=clean_desc,
            employment_type=emp_type,
            location=clean_loc,
            country=resolve_job_country(clean_loc) or "",
            is_remote=remote,
            salary_info=salary_info,
            publication_date=datetime.now().isoformat(),
            application_url=application_url,
            raw_data={"submitted_by_user": True},
        )
        job.fingerprint = job.compute_fingerprint()
        return job
