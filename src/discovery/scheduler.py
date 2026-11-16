"""
Discovery Scheduler & Background Synchronization Worker for AutoBot v2.3.1.
Consumes per-board refresh_interval and concurrency_limit, prevents concurrent duplicate syncs,
implements bounded exponential backoff with jitter for rate limits / 5xx errors,
isolates failures per board, and supports graceful startup, shutdown, and restart recovery.
"""

import asyncio
from datetime import datetime
import json
import os
import random
from typing import Any, Dict, List, Optional
import uuid
import aiohttp

from src.discovery.board_registry import BoardRegistry
from src.discovery.models import JobSourceConfig, NormalizedJob
from src.discovery.registry import FetchSourceResult, JobDiscoveryEngine
from src.storage.db import (
    acquire_scheduler_lease,
    get_db_connection,
    get_db_path,
    get_scheduler_lease,
    init_db,
    release_scheduler_lease,
    renew_scheduler_lease,
)
from src.utils.logger import logger


class DiscoveryScheduler:
    """
    Background worker orchestrating recurring synchronization of registered ATS job boards.
    """

    def __init__(self, db_path: Optional[str] = None, poll_interval_sec: float = 5.0, worker_id: Optional[str] = None):
        self.db_path = db_path or get_db_path()
        init_db(self.db_path)
        self.engine = JobDiscoveryEngine(self.db_path)
        self.registry: BoardRegistry = self.engine.board_registry
        self.poll_interval_sec = poll_interval_sec
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._board_locks: Dict[str, asyncio.Lock] = {}

    def acquire_lease(self, resource_key: str, ttl_seconds: int = 60) -> Optional[str]:
        """
        Attempt to acquire a database-backed distributed lease across worker processes.
        Returns the unique ownership token if successful; None if lease held by another worker.
        """
        token = f"{self.worker_id}:{uuid.uuid4().hex[:12]}"
        meta = json.dumps({"worker_id": self.worker_id, "pid": os.getpid()})
        ok = acquire_scheduler_lease(resource_key, token, ttl_seconds=ttl_seconds, metadata=meta, db_path=self.db_path)
        return token if ok else None

    def renew_lease(self, resource_key: str, token: str, ttl_seconds: int = 60) -> bool:
        """Extend an active lease if still owned by token."""
        return renew_scheduler_lease(resource_key, token, ttl_seconds=ttl_seconds, db_path=self.db_path)

    def release_lease(self, resource_key: str, token: str) -> bool:
        """Safely release the lease matching the ownership token."""
        return release_scheduler_lease(resource_key, token, db_path=self.db_path)

    def _get_board_lock(self, source_type: str, board_slug: str) -> asyncio.Lock:
        """Get or initialize mutual exclusion lock for a specific ATS board."""
        key = f"{source_type.lower().strip()}:{board_slug.strip()}"
        if key not in self._board_locks:
            self._board_locks[key] = asyncio.Lock()
        return self._board_locks[key]

    def is_due_for_sync(self, source: JobSourceConfig) -> bool:
        """
        Check if a job source is due for synchronization based on its scheduled time.
        Supports restart recovery when next_sync_at is overdue or not set.
        """
        if not source.is_active or source.status == "paused":
            return False

        if not source.next_sync_at:
            # First run or restarted without schedule
            return True

        try:
            scheduled_time = datetime.fromisoformat(source.next_sync_at)
            return datetime.now() >= scheduled_time
        except Exception:
            return True

    def calculate_backoff(self, failure_count: int, refresh_interval: int) -> float:
        """
        Calculate bounded exponential backoff with jitter for transient errors and rate limits.
        Formula: min(refresh_interval, 10 * (2 ** min(failure_count, 6))) + uniform(0.5, 3.0)
        """
        base = min(float(refresh_interval), 10.0 * (2 ** min(failure_count, 6)))
        jitter = random.uniform(0.5, 3.0)
        return round(base + jitter, 2)

    async def sync_board(
        self,
        source: JobSourceConfig,
        session: aiohttp.ClientSession,
        force: bool = False,
    ) -> Optional[FetchSourceResult]:
        """
        Execute an isolated sync for a single board with concurrency and duplicate sync prevention.
        One failing board will never crash or halt other boards.
        """
        lock = self._get_board_lock(source.source_type.value, source.board_token_or_slug)

        if lock.locked():
            logger.info(
                f"[scheduler]Sync already in progress for '{source.name}' ({source.board_token_or_slug}). Skipping concurrent invocation."
            )
            return None

        if not force and not self.is_due_for_sync(source):
            return None

        resource_key = f"{source.source_type.value}:{source.board_token_or_slug}"
        # Multi-process lease acquisition to guard across separate worker processes
        lease_ttl = max(60, int(source.refresh_interval) if getattr(source, "refresh_interval", None) else 60)
        lease_token = self.acquire_lease(resource_key, ttl_seconds=lease_ttl)
        if not lease_token:
            logger.info(
                f"[scheduler]Board '{source.name}' ({resource_key}) is leased by another worker process. Skipping concurrent sync."
            )
            return None

        try:
            async with lock:
                logger.info(f"[scheduler]Starting sync for '{source.name}' ({source.source_type.value}:{source.board_token_or_slug})")
                try:
                    res: FetchSourceResult = await self.engine._fetch_single_source(source, session)
                    src, jobs, err = res
                    is_complete = res.is_complete

                    if err is None and isinstance(jobs, list):
                        # Persist jobs with explicit completeness state
                        self.engine.persist_and_update_freshness(src, jobs, is_complete=is_complete)
                        logger.info(
                            f"[scheduler]Sync completed for '{source.name}': {len(jobs)} jobs (is_complete={is_complete})"
                        )
                    else:
                        # Transient or 429 failure: calculate bounded jittered backoff
                        with get_db_connection(self.db_path) as conn:
                            row = conn.execute(
                                "SELECT failure_count FROM job_sources WHERE source_type = ? AND board_token_or_slug = ?",
                                (source.source_type.value, source.board_token_or_slug),
                            ).fetchone()
                            fc = (row[0] if row else 0)

                        backoff_delay = self.calculate_backoff(fc, source.refresh_interval)
                        next_retry = datetime.fromtimestamp(datetime.now().timestamp() + backoff_delay).isoformat()

                        with get_db_connection(self.db_path) as conn:
                            conn.execute(
                                """
                                UPDATE job_sources
                                SET next_sync_at = ?
                                WHERE source_type = ? AND board_token_or_slug = ?
                                """,
                                (next_retry, source.source_type.value, source.board_token_or_slug),
                            )
                            conn.commit()

                        logger.warning(
                            f"[scheduler]Sync failure on '{source.name}': {err}. Backoff retry scheduled at {next_retry} (+{backoff_delay}s)"
                        )

                    return res
                except Exception as e:
                    logger.error(f"[scheduler]Unhandled exception during sync of '{source.name}': {e}")
                    self.registry.record_sync_failure(source.source_type.value, source.board_token_or_slug, str(e))
                    return FetchSourceResult(source, None, e, is_complete=False)
        finally:
            self.release_lease(resource_key, lease_token)

    async def run_sync_cycle(self, session: Optional[aiohttp.ClientSession] = None) -> List[FetchSourceResult]:
        """Inspect all registered boards and trigger sync for due boards concurrently."""
        active_boards = self.registry.get_boards(active_only=True)
        due_boards = [b for b in active_boards if self.is_due_for_sync(b)]

        if not due_boards:
            return []

        logger.info(f"[scheduler]Found {len(due_boards)} boards due for sync.")
        close_session = False
        if session is None:
            session = aiohttp.ClientSession()
            close_session = True

        results: List[FetchSourceResult] = []
        try:
            tasks = [self.sync_board(board, session, force=False) for board in due_boards]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in raw_results:
                if isinstance(r, FetchSourceResult):
                    results.append(r)
                elif isinstance(r, Exception):
                    logger.error(f"[scheduler]Task exception in sync cycle: {r}")
        finally:
            if close_session and not session.closed:
                await session.close()

        return results

    async def _worker_loop(self) -> None:
        """Main background scheduling loop."""
        logger.info("[scheduler]Discovery background scheduler worker started.")
        async with aiohttp.ClientSession() as session:
            while self._running:
                try:
                    await self.run_sync_cycle(session)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"[scheduler]Unexpected error in scheduler loop: {e}")

                # Responsive sleeping in 0.5s ticks to support immediate cancellation
                ticks = max(1, int(self.poll_interval_sec * 2))
                for _ in range(ticks):
                    if not self._running:
                        break
                    try:
                        await asyncio.sleep(0.5)
                    except asyncio.CancelledError:
                        self._running = False
                        break

        logger.info("[scheduler]Discovery background scheduler worker stopped.")

    def start(self) -> None:
        """Start background worker task."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._worker_loop())
            logger.info("[scheduler]Scheduler service started.")

    async def stop(self) -> None:
        """Stop background worker task gracefully."""
        if self._running:
            self._running = False
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            logger.info("[scheduler]Scheduler service stopped gracefully.")
