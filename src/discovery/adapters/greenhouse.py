"""
Greenhouse Public Job Board API Adapter.
Endpoint: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
"""

import asyncio
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
from src.matching.eligibility import resolve_job_country
from src.utils.logger import logger


class GreenhouseAdapter(BaseJobSourceAdapter):
    """Adapter for fetching public jobs from Greenhouse Job Boards."""

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

    async def fetch_jobs(self, session: Optional[aiohttp.ClientSession] = None) -> List[NormalizedJob]:
        board = self.config.board_token_or_slug.strip()
        url = self.config.base_url or self.BASE_URL.format(board=board)

        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"Greenhouse API returned HTTP {resp.status} for board '{board}'")
                    return []
                payload = await resp.json()
        except Exception as e:
            logger.error(f"Failed to query Greenhouse API for '{board}': {e}")
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

            loc_data = item.get("location", {})
            location_name = loc_data.get("name", "") if isinstance(loc_data, dict) else str(loc_data or "")

            raw_content = item.get("content", "")
            description = strip_html(raw_content)

            is_remote = detect_remote(location_name, title) or detect_remote("", description[:300])
            emp_type = classify_employment_type(f"{title} {description[:400]}")

            stable_id = f"greenhouse:{board}:{job_id}"
            app_url = item.get("absolute_url", f"https://boards.greenhouse.io/{board}/jobs/{job_id}")

            job = NormalizedJob(
                stable_id=stable_id,
                source_name=self.config.name,
                source_type=SourceType.GREENHOUSE,
                title=title,
                company=self.config.name,
                description=description,
                employment_type=emp_type,
                location=location_name,
                country=resolve_job_country(location_name) or "",
                is_remote=is_remote,
                publication_date=item.get("updated_at", datetime.now().isoformat()),
                application_url=app_url,
                raw_data=item,
            )
            job.fingerprint = job.compute_fingerprint()
            normalized.append(job)

        logger.info(f"[discovery]Discovered {len(normalized)} jobs from Greenhouse board '{board}'[/discovery]")
        return normalized
