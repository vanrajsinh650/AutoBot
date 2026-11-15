"""
Lever Published Postings API Adapter.
Endpoint: https://api.lever.co/v0/postings/{company}?mode=json
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


class LeverAdapter(BaseJobSourceAdapter):
    """Adapter for fetching public postings from Lever API."""

    BASE_URL = "https://api.lever.co/v0/postings/{company}?mode=json"

    async def fetch_jobs(self, session: Optional[aiohttp.ClientSession] = None) -> List[NormalizedJob]:
        company = self.config.board_token_or_slug.strip()
        url = self.config.base_url or self.BASE_URL.format(company=company)

        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    logger.warning(f"Lever API returned HTTP {resp.status} for company '{company}'")
                    return []
                payload = await resp.json()
        except Exception as e:
            logger.error(f"Failed to query Lever API for '{company}': {e}")
            return []
        finally:
            if close_session:
                await session.close()

        if not isinstance(payload, list):
            return []

        normalized: List[NormalizedJob] = []

        for item in payload:
            job_id = str(item.get("id", ""))
            title = str(item.get("text", "")).strip()
            if not title:
                continue

            categories = item.get("categories", {})
            location_name = categories.get("location", "")
            commitment = categories.get("commitment", "")

            desc_plain = item.get("descriptionPlain", "")
            if not desc_plain:
                desc_plain = strip_html(item.get("description", ""))

            # Append lists/additional sections if present
            lists = item.get("lists", [])
            for lst in lists:
                text_block = lst.get("text", "")
                content_html = lst.get("content", "")
                desc_plain += f"\n\n{text_block}:\n" + strip_html(content_html)

            is_remote = detect_remote(location_name, commitment) or detect_remote("", title)
            emp_type = classify_employment_type(f"{commitment} {title} {desc_plain[:300]}")

            stable_id = f"lever:{company}:{job_id}"
            app_url = item.get("hostedUrl", f"https://jobs.lever.co/{company}/{job_id}")

            created_at = ""
            if item.get("createdAt"):
                try:
                    created_at = datetime.fromtimestamp(item["createdAt"] / 1000).isoformat()
                except Exception:
                    created_at = datetime.now().isoformat()

            job = NormalizedJob(
                stable_id=stable_id,
                source_name=self.config.name,
                source_type=SourceType.LEVER,
                title=title,
                company=self.config.name,
                description=desc_plain.strip(),
                employment_type=emp_type,
                location=location_name,
                is_remote=is_remote,
                publication_date=created_at or datetime.now().isoformat(),
                application_url=app_url,
                raw_data=item,
            )
            job.fingerprint = job.compute_fingerprint()
            normalized.append(job)

        logger.info(f"[discovery]Discovered {len(normalized)} jobs from Lever company '{company}'[/discovery]")
        return normalized
