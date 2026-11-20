"""
Job Source Registry & Discovery Orchestration Engine for AutoBot v2.3.1.
Manages sources, executes fetching across adapters with concurrency control,
normalizes, deduplicates, and tracks job freshness, sync runs & authoritative expiration.
"""

import asyncio
from datetime import datetime
import json
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

import aiohttp

from src.discovery.adapters.ashby import AshbyAdapter
from src.discovery.adapters.base import BaseJobSourceAdapter
from src.discovery.adapters.greenhouse import GreenhouseAdapter
from src.discovery.adapters.lever import LeverAdapter
from src.discovery.adapters.manual import ManualJobAdapter
from src.discovery.board_registry import BoardRegistry
from src.discovery.models import EmploymentType, JobSourceConfig, NormalizedJob, SourceType
from src.storage.db import get_db_connection, get_db_path, init_db
from src.utils.logger import logger


class FetchSourceResult(tuple):
    """3-tuple subclass preserving (src, jobs, error) unpacking with is_complete attribute."""

    def __new__(cls, src: JobSourceConfig, jobs: Optional[List[NormalizedJob]], error: Optional[Exception], is_complete: bool = False):
        return super().__new__(cls, (src, jobs, error))

    def __init__(self, src: JobSourceConfig, jobs: Optional[List[NormalizedJob]], error: Optional[Exception], is_complete: bool = False):
        self.src = src
        self.jobs = jobs
        self.error = error
        self.is_complete = is_complete


class JobDiscoveryEngine:
    """
    Coordinates multi-source job discovery, concurrency limiting, deduplication,
    freshness tracking, sync run auditing, and authoritative expiration gating.
    """

    DEFAULT_SOURCES = []

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_db_path()
        init_db(self.db_path)
        self.board_registry = BoardRegistry(self.db_path)
        self._sources: List[JobSourceConfig] = list(self.DEFAULT_SOURCES)
        self.manual_adapter = ManualJobAdapter()

    def register_source(self, config: JobSourceConfig) -> None:
        """Register or update a job source in memory and in the board registry."""
        for i, existing in enumerate(self._sources):
            if (
                existing.source_type == config.source_type
                and existing.board_token_or_slug == config.board_token_or_slug
            ):
                self._sources[i] = config
                self.board_registry.add_board(
                    name=config.name,
                    source_type=config.source_type.value,
                    board_slug=config.board_token_or_slug,
                    base_url=config.base_url,
                    refresh_interval=config.refresh_interval,
                    concurrency_limit=config.concurrency_limit,
                )
                return
        self._sources.append(config)
        self.board_registry.add_board(
            name=config.name,
            source_type=config.source_type.value,
            board_slug=config.board_token_or_slug,
            base_url=config.base_url,
            refresh_interval=config.refresh_interval,
            concurrency_limit=config.concurrency_limit,
        )

    def get_sources(self) -> List[JobSourceConfig]:
        """Return all registered job sources, syncing with SQLite registry."""
        persisted = self.board_registry.get_boards(active_only=False)
        if persisted:
            return persisted
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

    async def _fetch_single_source(
        self,
        src: JobSourceConfig,
        session: aiohttp.ClientSession,
    ) -> FetchSourceResult:
        """Fetch jobs for a single source under its concurrency semaphore, returning FetchSourceResult."""
        sync_run_id = f"sync_{src.source_type.value}_{src.board_token_or_slug}_{int(datetime.now().timestamp() * 1000)}"
        started_at = datetime.now().isoformat()
        sem = self.board_registry.get_semaphore(src.source_type.value, src.concurrency_limit)

        async with sem:
            adapter = self._get_adapter(src)
            try:
                if hasattr(adapter, "fetch_jobs_detailed"):
                    jobs, is_complete = await adapter.fetch_jobs_detailed(session=session)
                else:
                    jobs = await adapter.fetch_jobs(session=session)
                    is_complete = getattr(adapter, "is_last_sync_complete", True)

                return FetchSourceResult(src, jobs, None, is_complete=is_complete)
            except Exception as e:
                logger.warning(f"Error fetching from {src.name} ({src.board_token_or_slug}): {e}")
                self.board_registry.record_sync_failure(
                    src.source_type.value,
                    src.board_token_or_slug,
                    str(e),
                    is_complete=False,
                )
                self.board_registry.record_sync_run(
                    sync_run_id=sync_run_id,
                    source_name=src.name,
                    source_type=src.source_type.value,
                    board_slug=src.board_token_or_slug,
                    status="failed",
                    is_complete=False,
                    total_retrieved=0,
                    new_jobs=0,
                    updated_jobs=0,
                    duplicates_removed=0,
                    expired_jobs=0,
                    error_message=str(e),
                    started_at=started_at,
                    completed_at=datetime.now().isoformat(),
                )
                return FetchSourceResult(src, None, e, is_complete=False)

    async def discover_jobs(
        self,
        sources: Optional[List[JobSourceConfig]] = None,
        keywords: Optional[List[str]] = None,
        employment_type: Optional[str] = None,
        workplace_type: Optional[str] = None,
    ) -> List[NormalizedJob]:
        """
        Fetch from active sources with concurrency control, update freshness,
        detect expired listings, deduplicate, and persist to SQLite.
        """
        if sources is not None:
            target_sources = sources
        else:
            db_sources = self.board_registry.get_boards(active_only=True)
            target_sources = db_sources if db_sources else [s for s in self._sources if s.is_active]

        discovered_jobs: List[NormalizedJob] = []

        async with aiohttp.ClientSession() as session:
            tasks = [self._fetch_single_source(src, session) for src in target_sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for item in results:
                if isinstance(item, Exception):
                    logger.warning(f"Discovery task exception: {item}")
                    continue
                src, jobs, err = item
                is_complete = getattr(item, "is_complete", False)
                if err is None and isinstance(jobs, list):
                    # Successfully fetched: persist with explicit completeness status
                    self.persist_and_update_freshness(src, jobs, is_complete=is_complete)
                    discovered_jobs.extend(jobs)

        # Filter by keywords if specified
        if keywords:
            kw_clean = [k.lower().strip() for k in keywords if k.strip()]
            if kw_clean:
                discovered_jobs = [
                    j for j in discovered_jobs
                    if any(kw in j.title.lower() or kw in j.description[:500].lower() for kw in kw_clean)
                ]

        # Filter by employment_type if specified
        if employment_type:
            et_clean = employment_type.lower().strip()
            discovered_jobs = [j for j in discovered_jobs if j.employment_type.value == et_clean]

        # Filter by workplace_type if specified
        if workplace_type:
            wt_clean = workplace_type.lower().strip()
            discovered_jobs = [j for j in discovered_jobs if j.workplace_type == wt_clean]

        logger.info(f"[discovery]Discovered {len(discovered_jobs)} matching active jobs[/discovery]")
        return discovered_jobs

    def persist_and_update_freshness(
        self,
        source: JobSourceConfig,
        active_jobs: List[NormalizedJob],
        is_complete: bool = True,
        sync_run_id: Optional[str] = None,
        lease_token: Optional[str] = None,
    ) -> List[NormalizedJob]:
        """
        Persist newly discovered jobs, update last_verified_at on existing jobs,
        and mark vanished jobs from this source as expired ONLY IF is_complete is True.

        CRITICAL INVARIANTS:
        1. Never expire previously discovered jobs after a partial fetch, truncated response,
           parse failure, or incomplete pagination. Expire jobs only after a fully successful
           authoritative sync of the relevant board.
        2. Lease Fencing: If lease_token is provided, verify active lease ownership within
           the commit transaction; abort immediately if the lease was lost or expired.
        """
        init_db(self.db_path)
        now = datetime.now()
        now_iso = now.isoformat()
        sync_id = sync_run_id or f"sync_{source.source_type.value}_{source.board_token_or_slug}_{int(now.timestamp() * 1000)}"
        newly_saved: List[NormalizedJob] = []
        updated_count = 0
        duplicates_removed = 0
        expired_count = 0
        source_prefix = f"{source.source_type.value}:{source.board_token_or_slug}:"
        resource_key = f"{source.source_type.value}:{source.board_token_or_slug}"

        with get_db_connection(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Lease fencing check: verify worker still owns the unexpired lease before committing
            if lease_token:
                from src.storage.db import StaleWorkerLeaseError, validate_lease_fencing
                if not validate_lease_fencing(conn, resource_key, lease_token):
                    raise StaleWorkerLeaseError(
                        f"Fencing violation: Worker token '{lease_token}' lost lease ownership for '{resource_key}'. "
                        "Synchronization commit and job expiration aborted to prevent stale overwrites."
                    )
            # 1. Fetch currently active jobs for this source from database
            active_db_rows = conn.execute(
                "SELECT id, stable_id, status FROM jobs WHERE stable_id LIKE ?",
                (f"{source_prefix}%",),
            ).fetchall()
            db_job_map = {r["stable_id"]: r for r in active_db_rows}

            fetched_ids = {j.stable_id for j in active_jobs}

            # 2. Process fetched active jobs: insert new, update existing
            for job in active_jobs:
                fp = job.fingerprint or job.compute_fingerprint()
                if job.stable_id in db_job_map:
                    # Update existing vacancy
                    conn.execute(
                        """
                        UPDATE jobs
                        SET last_verified_at = ?,
                            status = 'active',
                            workplace_type = ?,
                            compensation_min = ?,
                            compensation_max = ?,
                            currency = ?,
                            source_updated_at = COALESCE(?, source_updated_at)
                        WHERE stable_id = ?
                        """,
                        (
                            now_iso,
                            job.workplace_type,
                            job.compensation_min,
                            job.compensation_max,
                            job.currency,
                            job.source_updated_at or now_iso,
                            job.stable_id,
                        ),
                    )
                    updated_count += 1
                else:
                    # Check fingerprint deduplication before inserting
                    fp_row = conn.execute(
                        "SELECT id FROM jobs WHERE fingerprint = ?",
                        (fp,),
                    ).fetchone()
                    if fp_row:
                        # Duplicate by fingerprint; update verified timestamp
                        conn.execute(
                            "UPDATE jobs SET last_verified_at = ?, status = 'active' WHERE id = ?",
                            (now_iso, fp_row["id"]),
                        )
                        duplicates_removed += 1
                        continue

                    # Insert new job
                    conn.execute(
                        """
                        INSERT INTO jobs (
                            stable_id, source_name, title, company, description,
                            employment_type, location, country, is_remote, salary_info,
                            workplace_type, status, compensation_min, compensation_max, currency,
                            publication_date, discovered_at, source_updated_at, last_verified_at,
                            application_url, raw_data, fingerprint, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                            job.workplace_type,
                            "active",
                            job.compensation_min,
                            job.compensation_max,
                            job.currency,
                            job.publication_date,
                            job.discovered_at or now_iso,
                            job.source_updated_at or now_iso,
                            now_iso,
                            job.application_url,
                            json.dumps(job.raw_data),
                            fp,
                            now_iso,
                        ),
                    )
                    newly_saved.append(job)

            # 3. Detect Expired Vacancies (Strictly Gated by is_complete):
            if is_complete:
                for stable_id, r in db_job_map.items():
                    if stable_id not in fetched_ids and r["status"] == "active":
                        conn.execute(
                            "UPDATE jobs SET status = 'expired', last_verified_at = ? WHERE stable_id = ?",
                            (now_iso, stable_id),
                        )
                        expired_count += 1
                        logger.info(f"[discovery]Marked vacancy '{stable_id}' as expired (authoritative board sync omission).")
            else:
                logger.warning(
                    f"[discovery]Preserved active vacancies for '{source.name}' ({source.board_token_or_slug}): "
                    f"sync is marked partial (is_complete={is_complete}). Mass expiration skipped."
                )

            conn.commit()

        # Update board health and schedule next run
        self.board_registry.record_sync_success(
            source_type=source.source_type.value,
            board_slug=source.board_token_or_slug,
            retrieved_count=len(active_jobs),
            expired_count=expired_count,
            is_complete=is_complete,
        )

        # Audit sync run in sync_runs table
        status_str = "completed" if is_complete else "partial"
        self.board_registry.record_sync_run(
            sync_run_id=sync_id,
            source_name=source.name,
            source_type=source.source_type.value,
            board_slug=source.board_token_or_slug,
            status=status_str,
            is_complete=is_complete,
            total_retrieved=len(active_jobs),
            new_jobs=len(newly_saved),
            updated_jobs=updated_count,
            duplicates_removed=duplicates_removed,
            expired_jobs=expired_count,
            error_message="" if is_complete else "Partial sync: incomplete pagination or truncated fetch",
            started_at=now_iso,
            completed_at=datetime.now().isoformat(),
        )

        return newly_saved

    def persist_jobs(self, jobs: List[NormalizedJob]) -> List[NormalizedJob]:
        """
        Deduplicate jobs by stable_id and fingerprint, persisting new ones to database.
        Maintains backward compatibility with tests.
        """
        init_db(self.db_path)
        newly_saved: List[NormalizedJob] = []
        now = datetime.now().isoformat()

        with get_db_connection(self.db_path) as conn:
            for job in jobs:
                row = conn.execute(
                    "SELECT id FROM jobs WHERE stable_id = ?",
                    (job.stable_id,),
                ).fetchone()
                if row:
                    # Update verified timestamp
                    conn.execute(
                        "UPDATE jobs SET last_verified_at = ?, status = 'active' WHERE id = ?",
                        (now, row["id"]),
                    )
                    continue

                fp = job.fingerprint or job.compute_fingerprint()
                fp_row = conn.execute(
                    "SELECT id FROM jobs WHERE fingerprint = ?",
                    (fp,),
                ).fetchone()
                if fp_row:
                    conn.execute(
                        "UPDATE jobs SET last_verified_at = ?, status = 'active' WHERE id = ?",
                        (now, fp_row["id"]),
                    )
                    continue

                conn.execute(
                    """
                    INSERT INTO jobs (
                        stable_id, source_name, title, company, description,
                        employment_type, location, country, is_remote, salary_info,
                        workplace_type, status, compensation_min, compensation_max, currency,
                        publication_date, discovered_at, source_updated_at, last_verified_at,
                        application_url, raw_data, fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        job.workplace_type,
                        "active",
                        job.compensation_min,
                        job.compensation_max,
                        job.currency,
                        job.publication_date,
                        job.discovered_at or now,
                        job.source_updated_at or now,
                        now,
                        job.application_url,
                        json.dumps(job.raw_data),
                        fp,
                        now,
                    ),
                )
                newly_saved.append(job)

            conn.commit()

        return newly_saved
