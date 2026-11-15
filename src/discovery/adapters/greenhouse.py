"""
Greenhouse Public Job Board API Adapter for AutoBot v2.3.
Endpoint: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
Includes SSRF validation, size capping, workplace classification, and compensation extraction.
"""

import asyncio
from datetime import datetime
import json
from typing import Any, Dict, List, Optional
import aiohttp

from src.discovery.adapters.base import (
    BaseJobSourceAdapter,
    classify_employment_type,
    detect_remote,
    detect_workplace_type,
    extract_compensation,
    strip_html,
)
from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.discovery.security import (
    MAX_RESPONSE_BYTES,
    SSRFValidationError,
    safe_read_json,
    validate_ats_url,
    validate_board_slug,
)
from src.matching.eligibility import resolve_job_country
from src.utils.logger import logger


class GreenhouseAdapter(BaseJobSourceAdapter):
    """Adapter for fetching public jobs from Greenhouse Job Boards."""

    BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

    async def fetch_jobs(self, session: Optional[aiohttp.ClientSession] = None) -> List[NormalizedJob]:
        raw_board = self.config.board_token_or_slug.strip()
        try:
            board = validate_board_slug(raw_board)
        except SSRFValidationError as e:
            logger.error(f"[discovery]SSRF Blocked: Invalid Greenhouse board slug '{raw_board}': {e}")
            return []

        url = self.config.base_url or self.BASE_URL.format(board=board)
        try:
            validate_ats_url(url, expected_source_type=SourceType.GREENHOUSE)
        except SSRFValidationError as e:
            logger.error(f"[discovery]SSRF Blocked: Invalid Greenhouse destination '{url}': {e}")
            return []

        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        payload: Any = None
        for attempt in range(2):
            try:
                headers = {"User-Agent": "AutoBot/2.3 (+https://github.com/autobot-platform)"}
                timeout = aiohttp.ClientTimeout(total=20, connect=5, sock_read=15)
                async with session.get(url, headers=headers, timeout=timeout) as resp:
                    if resp.status == 429:
                        logger.warning(f"Rate limited (HTTP 429) by Greenhouse for '{board}'. Attempt {attempt+1}/2.")
                        if attempt == 0:
                            await asyncio.sleep(0.5)
                            continue
                        return []
                    elif resp.status in (500, 502, 503, 504):
                        logger.warning(f"Transient error (HTTP {resp.status}) from Greenhouse for '{board}'. Attempt {attempt+1}/2.")
                        if attempt == 0:
                            await asyncio.sleep(0.5)
                            continue
                        return []
                    elif resp.status != 200:
                        logger.warning(f"Greenhouse API returned HTTP {resp.status} for board '{board}'")
                        return []

                    try:
                        payload = await safe_read_json(resp, MAX_RESPONSE_BYTES)
                    except SSRFValidationError as e:
                        logger.error(f"[discovery]Greenhouse response for '{board}' size violation: {e}")
                        return []
                    break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                logger.warning(f"Network error querying Greenhouse for '{board}': {e}. Attempt {attempt+1}/2.")
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
                return []
            except Exception as e:
                logger.error(f"Failed to query Greenhouse API for '{board}': {e}")
                return []
            finally:
                if close_session and attempt == 1:
                    await session.close()

        if close_session and not session.closed:
            await session.close()

        raw_jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        normalized: List[NormalizedJob] = []
        now_iso = datetime.now().isoformat()

        for item in raw_jobs:
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("id", ""))
            title = str(item.get("title", "")).strip()
            if not title:
                continue

            loc_data = item.get("location") or {}
            location_name = loc_data.get("name", "") if isinstance(loc_data, dict) else str(loc_data or "")

            raw_content = item.get("content") or ""
            description = strip_html(raw_content)

            is_remote = detect_remote(location_name, title) or detect_remote("", description[:300])
            workplace_type = detect_workplace_type(location_name, f"{title} {description[:300]}")
            emp_type = classify_employment_type(f"{title} {description[:400]}")
            comp_min, comp_max, currency = extract_compensation(description)

            stable_id = f"greenhouse:{board}:{job_id}"
            app_url = item.get("absolute_url", f"https://boards.greenhouse.io/{board}/jobs/{job_id}")
            source_updated = item.get("updated_at") or now_iso

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
                workplace_type=workplace_type,
                status="active",
                compensation_min=comp_min,
                compensation_max=comp_max,
                currency=currency,
                publication_date=item.get("updated_at", now_iso),
                discovered_at=now_iso,
                source_updated_at=source_updated,
                last_verified_at=now_iso,
                application_url=app_url,
                raw_data=item,
            )
            job.fingerprint = job.compute_fingerprint()
            normalized.append(job)

        return normalized
