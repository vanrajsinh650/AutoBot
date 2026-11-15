"""
Job Source Registry & Discovery Orchestration Engine.
Manages sources, executes fetching across adapters, normalizes, and deduplicates.
"""

import asyncio
from datetime import datetime
import json
from typing import Any, Dict, List, Optional, Set, Tuple

import aiohttp

from src.discovery.adapters.ashby import AshbyAdapter
from src.discovery.adapters.base import BaseJobSourceAdapter
from src.discovery.adapters.greenhouse import GreenhouseAdapter
from src.discovery.adapters.lever import LeverAdapter
from src.discovery.adapters.manual import ManualJobAdapter
from src.discovery.models import JobSourceConfig, NormalizedJob, SourceType
from src.storage.db import get_db_connection, get_db_path, init_db
from src.utils.logger import logger


class JobDiscoveryEngine:
    """
    Coordinates multi-source job discovery, deduplication, and persistence.
    """

    DEFAULT_SOURCES = [
        JobSourceConfig(name="Stripe", source_type=SourceType.GREENHOUSE, board_token_or_slug="stripe"),
        JobSourceConfig(name="Figma", source_type=SourceType.LEVER, board_token_or_slug="figma"),
        JobSourceConfig(name="OpenAI", source_type=SourceType.ASHBY, board_token_or_slug="openai"),
    ]

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_db_path()
        self._sources: List[JobSourceConfig] = list(self.DEFAULT_SOURCES)
        self.manual_adapter = ManualJobAdapter()

    def register_source(self, config: JobSourceConfig) -> None:
        """Register a new job source."""
        for i, existing in enumerate(self._sources):
            if existing.source_type == config.source_type and existing.board_token_or_slug == config.board_token_or_slug:
                self._sources[i] = config
                return
        self._sources.append(config)

    def get_sources(self) -> List[JobSourceConfig]:
        """Return all registered job sources."""
        return list(self._sources)

    def _get_adapter(self, config: JobSourceConfig) -> BaseJobSourceAdapter:
        """Instantiate the appropriate adapter for a configuration."""
        if config.source_type == SourceType.GREENHOUSE:
            return GreenhouseAdapter(config)
        elif config.source_type == SourceType.LEVER:
            return LeverAdapter(config)
        elif config.source_type == SourceType.ASHBY:
            return AshbyAdapter(config)
        else:
            return ManualJobAdapter(config)

    async def discover_jobs(
        self,
        sources: Optional[List[JobSourceConfig]] = None,
        keywords: Optional[List[str]] = None,
    ) -> List[NormalizedJob]:
        """
        Fetch from all active configured sources and deduplicate against database.
        """
        target_sources = sources if sources is not None else [s for s in self._sources if s.is_active]
        discovered_jobs: List[NormalizedJob] = []

        async with aiohttp.ClientSession() as session:
            tasks = []
            for src in target_sources:
                adapter = self._get_adapter(src)
                tasks.append(adapter.fetch_jobs(session=session))

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, list):
                    discovered_jobs.extend(res)
                elif isinstance(res, Exception):
                    logger.warning(f"Discovery adapter exception: {res}")

        # Filter by keywords if specified
        if keywords:
            kw_clean = [k.lower().strip() for k in keywords if k.strip()]
            if kw_clean:
                discovered_jobs = [
                    j for j in discovered_jobs
                    if any(kw in j.title.lower() or kw in j.description[:500].lower() for kw in kw_clean)
                ]

        # Deduplicate and persist to SQLite
        persisted = self.persist_jobs(discovered_jobs)
        logger.info(f"[discovery]Discovered {len(discovered_jobs)} total jobs, {len(persisted)} newly persisted[/discovery]")
        return persisted

    def persist_jobs(self, jobs: List[NormalizedJob]) -> List[NormalizedJob]:
        """
        Deduplicate jobs by stable_id and fingerprint, persisting new ones to database.
        Returns the list of newly persisted jobs.
        """
        init_db(self.db_path)
        newly_saved: List[NormalizedJob] = []
        now = datetime.now().isoformat()

        with get_db_connection(self.db_path) as conn:
            for job in jobs:
                # 1. Check stable_id
                row = conn.execute(
                    "SELECT id FROM jobs WHERE stable_id = ?",
                    (job.stable_id,),
                ).fetchone()
                if row:
                    continue

                # 2. Check fingerprint fallback
                fp = job.fingerprint or job.compute_fingerprint()
                fp_row = conn.execute(
                    "SELECT id FROM jobs WHERE fingerprint = ?",
                    (fp,),
                ).fetchone()
                if fp_row:
                    continue

                # Insert new job
                conn.execute(
                    """
                    INSERT INTO jobs (
                        stable_id, source_name, title, company, description,
                        employment_type, location, country, is_remote, salary_info,
                        publication_date, application_url, raw_data, fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.stable_id,
                        job.source_name,
                        job.title,
                        job.company,
                        job.description,
                        job.employment_type.value,
                        job.location,
                        job.country,
                        1 if job.is_remote else 0,
                        job.salary_info,
                        job.publication_date,
                        job.application_url,
                        json.dumps(job.raw_data),
                        fp,
                        now,
                    ),
                )
                newly_saved.append(job)

            conn.commit()

        return newly_saved
