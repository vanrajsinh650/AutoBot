"""
Ashby Public Job Postings API Adapter.
Endpoint: https://api.ashbyhq.com/posting-api/job-board/{organization_slug}
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
import aiohttp

from src.discovery.adapters.base import (
    BaseJobSourceAdapter,
    classify_employment_type,
    detect_remote,
    strip_html,
)
from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.utils.logger import logger


class AshbyAdapter(BaseJobSourceAdapter):
    """Adapter for fetching public postings from Ashby Job Board API."""

    BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{org}"

    async def fetch_jobs(self, session: Optional[aiohttp.ClientSession] = None) -> List[NormalizedJob]:
        org = self.config.board_token_or_slug.strip()
        url = self.config.base_url or self.BASE_URL.format(org=org)

        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"Ashby API returned HTTP {resp.status} for organization '{org}'")
                    return []
                payload = await resp.json()
        except Exception as e:
            logger.error(f"Failed to query Ashby API for '{org}': {e}")
            return []
        finally:
            if close_session:
                await session.close()

        raw_jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        normalized: List[NormalizedJob] = []

        for item in raw_jobs:
            job_id = str(item.get("id", ""))
            title = str(item.get("title", "")).strip()
            if not title:
                continue

            location_name = str(item.get("location", ""))
            desc_plain = item.get("descriptionPlain", "")
            if not desc_plain:
                desc_plain = strip_html(item.get("descriptionHtml", ""))

            raw_emp = str(item.get("employmentType", ""))
            emp_type = classify_employment_type(f"{raw_emp} {title}")

            is_remote = item.get("isRemote", False) or detect_remote(location_name, title)

            stable_id = f"ashby:{org}:{job_id}"
            app_url = item.get("jobUrl", f"https://jobs.ashbyhq.com/{org}/{job_id}")

            job = NormalizedJob(
                stable_id=stable_id,
                source_name=self.config.name,
                source_type=SourceType.ASHBY,
                title=title,
                company=self.config.name,
                description=desc_plain.strip(),
                employment_type=emp_type,
                location=location_name,
                is_remote=is_remote,
                publication_date=item.get("publishedAt", datetime.now().isoformat()),
                application_url=app_url,
                raw_data=item,
            )
            job.fingerprint = job.compute_fingerprint()
            normalized.append(job)

        logger.info(f"[discovery]Discovered {len(normalized)} jobs from Ashby org '{org}'[/discovery]")
        return normalized
