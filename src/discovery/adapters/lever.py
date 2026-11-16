"""
Lever Published Postings API Adapter for AutoBot v2.3.1.
Endpoint: https://api.lever.co/v0/postings/{company}?mode=json
Includes SSRF validation, size capping, workplace classification, compensation extraction,
cursor/offset pagination, and granular individual item error isolation.
"""

import asyncio
from datetime import datetime
import json
from typing import Any, Dict, List, Optional, Set
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


class LeverAdapter(BaseJobSourceAdapter):
    """Adapter for fetching public postings from Lever API with pagination and error isolation."""

    BASE_URL = "https://api.lever.co/v0/postings/{company}?mode=json"
    PAGE_SIZE = 100
    MAX_PAGES = 50

    def __init__(self, config: JobSourceConfig):
        super().__init__(config)
        self.is_last_sync_complete: bool = False

    async def fetch_jobs(self, session: Optional[aiohttp.ClientSession] = None) -> List[NormalizedJob]:
        raw_company = self.config.board_token_or_slug.strip()
        self.is_last_sync_complete = False

        try:
            company = validate_board_slug(raw_company)
        except SSRFValidationError as e:
            logger.error(f"[discovery]SSRF Blocked: Invalid Lever board slug '{raw_company}': {e}")
            return []

        base_target_url = self.config.base_url or self.BASE_URL.format(company=company)
        try:
            validate_ats_url(base_target_url, expected_source_type=SourceType.LEVER)
        except SSRFValidationError as e:
            logger.error(f"[discovery]SSRF Blocked: Invalid Lever destination '{base_target_url}': {e}")
            return []

        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        all_normalized_jobs: List[NormalizedJob] = []
        seen_job_ids: Set[str] = set()
        skip = 0
        now_iso = datetime.now().isoformat()
        is_authoritative_complete = True

        try:
            for page_idx in range(self.MAX_PAGES):
                # Prepare query parameters
                params = {"limit": self.PAGE_SIZE, "skip": skip}
                payload: Any = None
                page_success = False

                for attempt in range(2):
                    try:
                        headers = {"User-Agent": "AutoBot/2.3.1 (+https://github.com/autobot-platform)"}
                        timeout = aiohttp.ClientTimeout(total=20, connect=5, sock_read=15)
                        async with session.get(base_target_url, params=params, headers=headers, timeout=timeout, allow_redirects=False) as resp:
                            if resp.status == 429:
                                logger.warning(f"Rate limited (HTTP 429) by Lever for '{company}' page {page_idx+1}. Attempt {attempt+1}/2.")
                                if attempt == 0:
                                    await asyncio.sleep(0.5)
                                    continue
                                is_authoritative_complete = False
                                break
                            elif resp.status in (500, 502, 503, 504):
                                logger.warning(f"Transient error (HTTP {resp.status}) from Lever for '{company}' page {page_idx+1}. Attempt {attempt+1}/2.")
                                if attempt == 0:
                                    await asyncio.sleep(0.5)
                                    continue
                                is_authoritative_complete = False
                                break
                            elif resp.status != 200:
                                logger.warning(f"Lever API returned HTTP {resp.status} for company '{company}' page {page_idx+1}")
                                is_authoritative_complete = False
                                break

                            try:
                                payload = await safe_read_json(resp, MAX_RESPONSE_BYTES)
                                page_success = True
                            except SSRFValidationError as e:
                                logger.error(f"[discovery]Lever response for '{company}' size violation: {e}")
                                is_authoritative_complete = False
                                break
                            break
                    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                        logger.warning(f"Network error querying Lever for '{company}' page {page_idx+1}: {e}. Attempt {attempt+1}/2.")
                        if attempt == 0:
                            await asyncio.sleep(0.5)
                            continue
                        is_authoritative_complete = False
                        break
                    except Exception as e:
                        logger.error(f"Failed to query Lever API for '{company}' page {page_idx+1}: {e}")
                        is_authoritative_complete = False
                        break

                if not page_success or not isinstance(payload, list):
                    if page_idx == 0:
                        is_authoritative_complete = False
                    break

                # Process this page's items with granular error isolation
                page_count = 0
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    page_count += 1
                    try:
                        job_id = str(item.get("id", "")).strip()
                        title = str(item.get("text", "")).strip()
                        if not job_id or not title:
                            continue

                        stable_id = f"lever:{company}:{job_id}"
                        if stable_id in seen_job_ids:
                            # Avoid duplicates if Lever returns overlapping pages
                            continue
                        seen_job_ids.add(stable_id)

                        categories = item.get("categories") or {}
                        if not isinstance(categories, dict):
                            categories = {}
                        location_name = str(categories.get("location", "") or "").strip()
                        commitment = str(categories.get("commitment", "") or "").strip()

                        desc_plain = item.get("descriptionPlain", "")
                        if not desc_plain:
                            desc_plain = strip_html(item.get("description", ""))

                        lists = item.get("lists") or []
                        if isinstance(lists, list):
                            for lst in lists:
                                if not isinstance(lst, dict):
                                    continue
                                text_block = lst.get("text", "")
                                content_html = lst.get("content", "")
                                desc_plain += f"\n\n{text_block}:\n" + strip_html(content_html)

                        is_remote = detect_remote(location_name, commitment) or detect_remote("", title)
                        workplace_type = detect_workplace_type(location_name, f"{commitment} {title}")
                        emp_type = classify_employment_type(f"{commitment} {title} {desc_plain[:300]}")
                        comp_min, comp_max, currency = extract_compensation(desc_plain)

                        app_url = item.get("hostedUrl", f"https://jobs.lever.co/{company}/{job_id}")

                        created_at = now_iso
                        if item.get("createdAt"):
                            try:
                                created_at = datetime.fromtimestamp(item["createdAt"] / 1000).isoformat()
                            except Exception:
                                created_at = now_iso

                        job = NormalizedJob(
                            stable_id=stable_id,
                            source_name=self.config.name,
                            source_type=SourceType.LEVER,
                            title=title,
                            company=self.config.name,
                            description=desc_plain.strip(),
                            employment_type=emp_type,
                            location=location_name,
                            country=resolve_job_country(location_name) or "",
                            is_remote=is_remote,
                            workplace_type=workplace_type,
                            status="active",
                            compensation_min=comp_min,
                            compensation_max=comp_max,
                            currency=currency,
                            publication_date=created_at,
                            discovered_at=now_iso,
                            source_updated_at=created_at,
                            last_verified_at=now_iso,
                            application_url=app_url,
                            raw_data=item,
                        )
                        job.fingerprint = job.compute_fingerprint()
                        all_normalized_jobs.append(job)
                    except Exception as item_err:
                        logger.warning(f"[discovery]Skipped malformed Lever job item in '{company}': {item_err}")
                        continue

                # Pagination check: if fewer items than page size returned, we reached the end
                if len(payload) < self.PAGE_SIZE:
                    # Successfully reached the end of all pages
                    break

                skip += len(payload)

        finally:
            if close_session and not session.closed:
                await session.close()

        self.is_last_sync_complete = is_authoritative_complete
        return all_normalized_jobs
