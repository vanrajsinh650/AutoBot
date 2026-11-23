"""
Company Board Registry for AutoBot v2.3.
Provides persistent, configurable management of ATS company job boards,
SSRF validation, refresh intervals, health tracking, and concurrency limits.
"""

import asyncio
from datetime import datetime
import sqlite3
from typing import Dict, List, Optional, Tuple

from src.discovery.models import JobSourceConfig, SourceType
from src.discovery.security import SSRFValidationError, validate_ats_url, validate_board_slug
from src.storage.db import get_db_connection, get_db_path, init_db
from src.utils.logger import logger


# Default company boards: verified, public ATS endpoints with direct application forms
# (Greenhouse, Lever, Ashby). Zero login required, 100% guest forms.
DEFAULT_COMPANY_BOARDS: List[JobSourceConfig] = [
    JobSourceConfig(
        name="Cloudflare",
        source_type=SourceType.GREENHOUSE,
        board_token_or_slug="cloudflare",
        refresh_interval=3600,
        concurrency_limit=2,
    ),
    JobSourceConfig(
        name="Figma",
        source_type=SourceType.GREENHOUSE,
        board_token_or_slug="figma",
        refresh_interval=3600,
        concurrency_limit=2,
    ),
    JobSourceConfig(
        name="Datadog",
        source_type=SourceType.GREENHOUSE,
        board_token_or_slug="datadog",
        refresh_interval=3600,
        concurrency_limit=2,
    ),
    JobSourceConfig(
        name="Discord",
        source_type=SourceType.GREENHOUSE,
        board_token_or_slug="discord",
        refresh_interval=3600,
        concurrency_limit=2,
    ),
    JobSourceConfig(
        name="Ramp",
        source_type=SourceType.ASHBY,
        board_token_or_slug="ramp",
        refresh_interval=3600,
        concurrency_limit=2,
    ),
    JobSourceConfig(
        name="Notion",
        source_type=SourceType.ASHBY,
        board_token_or_slug="notion",
        refresh_interval=3600,
        concurrency_limit=2,
    ),
    JobSourceConfig(
        name="Lever Demo",
        source_type=SourceType.LEVER,
        board_token_or_slug="leverdemo",
        refresh_interval=3600,
        concurrency_limit=2,
    ),
]


class BoardRegistry:
    """
    Manages configured ATS company job boards with persistence in SQLite,
    health monitoring, refresh intervals, and concurrency limits.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_db_path()
        init_db(self.db_path)
        self._semaphores: Dict[str, asyncio.Semaphore] = {}
        self._seed_default_boards_if_empty()

    def _seed_default_boards_if_empty(self) -> None:
        """Seed default verified public ATS boards if table is empty."""
        with get_db_connection(self.db_path) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM job_sources")
            count = cur.fetchone()[0]
            if count == 0:
                now = datetime.now().isoformat()
                for b in DEFAULT_COMPANY_BOARDS:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO job_sources (
                            name, source_type, board_token_or_slug, base_url, is_active,
                            refresh_interval, status, last_synced_at, concurrency_limit,
                            failure_count, last_error, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            b.name,
                            b.source_type.value,
                            b.board_token_or_slug,
                            b.base_url,
                            1 if b.is_active else 0,
                            b.refresh_interval,
                            b.status,
                            "",
                            b.concurrency_limit,
                            0,
                            "",
                            now,
                        ),
                    )
                conn.commit()

    def get_boards(self, active_only: bool = False) -> List[JobSourceConfig]:
        """Fetch all registered boards from SQLite."""
        with get_db_connection(self.db_path) as conn:
            query = "SELECT * FROM job_sources"
            params: List[object] = []
            if active_only:
                query += " WHERE is_active = 1 AND status != 'paused'"
            query += " ORDER BY id ASC"

            rows = conn.execute(query, params).fetchall()
            configs: List[JobSourceConfig] = []
            for r in rows:
                row_dict = dict(r)
                # Map source_type string to Enum safely
                st_str = row_dict.get("source_type", "manual")
                try:
                    st = SourceType(st_str)
                except ValueError:
                    st = SourceType.MANUAL

                configs.append(
                    JobSourceConfig(
                        name=row_dict.get("name", ""),
                        source_type=st,
                        board_token_or_slug=row_dict.get("board_token_or_slug", ""),
                        base_url=row_dict.get("base_url"),
                        is_active=bool(row_dict.get("is_active", 1)),
                        refresh_interval=int(row_dict.get("refresh_interval", 3600)),
                        status=str(row_dict.get("status", "active")),
                        last_synced_at=row_dict.get("last_synced_at") or None,
                        concurrency_limit=int(row_dict.get("concurrency_limit", 2)),
                        failure_count=int(row_dict.get("failure_count", 0)),
                        last_error=str(row_dict.get("last_error", "")),
                        last_success_at=row_dict.get("last_success_at") or None,
                        last_failure_at=row_dict.get("last_failure_at") or None,
                        next_sync_at=row_dict.get("next_sync_at") or None,
                        last_sync_complete=bool(row_dict.get("last_sync_complete", 0)),
                        last_retrieved_count=int(row_dict.get("last_retrieved_count", 0)),
                        last_expired_count=int(row_dict.get("last_expired_count", 0)),
                    )
                )
            return configs

    def get_board(self, source_type: str, board_slug: str) -> Optional[JobSourceConfig]:
        """Fetch a specific board by source type and slug."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM job_sources WHERE source_type = ? AND board_token_or_slug = ?",
                (source_type.lower().strip(), board_slug.strip()),
            ).fetchone()
            if not row:
                return None
            row_dict = dict(row)
            try:
                st = SourceType(row_dict.get("source_type", "manual"))
            except ValueError:
                st = SourceType.MANUAL
            return JobSourceConfig(
                name=row_dict.get("name", ""),
                source_type=st,
                board_token_or_slug=row_dict.get("board_token_or_slug", ""),
                base_url=row_dict.get("base_url"),
                is_active=bool(row_dict.get("is_active", 1)),
                refresh_interval=int(row_dict.get("refresh_interval", 3600)),
                status=str(row_dict.get("status", "active")),
                last_synced_at=row_dict.get("last_synced_at") or None,
                concurrency_limit=int(row_dict.get("concurrency_limit", 2)),
                failure_count=int(row_dict.get("failure_count", 0)),
                last_error=str(row_dict.get("last_error", "")),
                last_success_at=row_dict.get("last_success_at") or None,
                last_failure_at=row_dict.get("last_failure_at") or None,
                next_sync_at=row_dict.get("next_sync_at") or None,
                last_sync_complete=bool(row_dict.get("last_sync_complete", 0)),
                last_retrieved_count=int(row_dict.get("last_retrieved_count", 0)),
                last_expired_count=int(row_dict.get("last_expired_count", 0)),
            )

    def add_board(
        self,
        name: str,
        source_type: str,
        board_slug: str,
        base_url: Optional[str] = None,
        refresh_interval: int = 3600,
        concurrency_limit: int = 2,
    ) -> JobSourceConfig:
        """
        Validate and register a new company board with SSRF protection.
        """
        # 1. Validate board slug
        valid_slug = validate_board_slug(board_slug)

        # 2. Validate source type
        st_clean = source_type.lower().strip()
        try:
            st_enum = SourceType(st_clean)
        except ValueError:
            raise SSRFValidationError(
                f"Unsupported source type '{source_type}'. Permitted: {[s.value for s in SourceType]}"
            )

        # 3. Validate base_url if provided
        if base_url:
            validate_ats_url(base_url, expected_source_type=st_enum)

        name_clean = name.strip() or f"{st_clean.capitalize()}:{valid_slug}"
        now = datetime.now().isoformat()

        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO job_sources (
                    name, source_type, board_token_or_slug, base_url, is_active,
                    refresh_interval, status, last_synced_at, concurrency_limit,
                    failure_count, last_error, created_at
                ) VALUES (?, ?, ?, ?, 1, ?, 'active', '', ?, 0, '', ?)
                ON CONFLICT(source_type, board_token_or_slug) DO UPDATE SET
                    name = excluded.name,
                    base_url = excluded.base_url,
                    refresh_interval = excluded.refresh_interval,
                    concurrency_limit = excluded.concurrency_limit,
                    is_active = 1,
                    status = 'active'
                """,
                (name_clean, st_clean, valid_slug, base_url, refresh_interval, concurrency_limit, now),
            )
            conn.commit()

        logger.info(f"[discovery]Registered company board '{name_clean}' ({st_clean}:{valid_slug})")
        return JobSourceConfig(
            name=name_clean,
            source_type=st_enum,
            board_token_or_slug=valid_slug,
            base_url=base_url,
            is_active=True,
            refresh_interval=refresh_interval,
            status="active",
            concurrency_limit=concurrency_limit,
        )

    def record_sync_success(
        self,
        source_type: str,
        board_slug: str,
        retrieved_count: int = 0,
        expired_count: int = 0,
        is_complete: bool = True,
    ) -> None:
        """Mark board synchronization successful and schedule next run."""
        now = datetime.now()
        now_iso = now.isoformat()
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT refresh_interval FROM job_sources WHERE source_type = ? AND board_token_or_slug = ?",
                (source_type.lower().strip(), board_slug.strip()),
            ).fetchone()
            interval = int(row[0]) if row and row[0] is not None else 3600
            next_sync = datetime.fromtimestamp(now.timestamp() + interval).isoformat()

            conn.execute(
                """
                UPDATE job_sources
                SET last_synced_at = ?,
                    last_success_at = ?,
                    next_sync_at = ?,
                    failure_count = 0,
                    last_error = '',
                    status = 'active',
                    last_sync_complete = ?,
                    last_retrieved_count = ?,
                    last_expired_count = ?
                WHERE source_type = ? AND board_token_or_slug = ?
                """,
                (
                    now_iso,
                    now_iso,
                    next_sync,
                    1 if is_complete else 0,
                    retrieved_count,
                    expired_count,
                    source_type.lower().strip(),
                    board_slug.strip(),
                ),
            )
            conn.commit()

    def record_sync_failure(
        self,
        source_type: str,
        board_slug: str,
        error_msg: str,
        is_complete: bool = False,
    ) -> None:
        """Record board synchronization error without false deactivation, scheduling exponential retry."""
        now = datetime.now()
        now_iso = now.isoformat()
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT failure_count, refresh_interval FROM job_sources WHERE source_type = ? AND board_token_or_slug = ?",
                (source_type.lower().strip(), board_slug.strip()),
            ).fetchone()
            fc = (row[0] if row and row[0] is not None else 0) + 1
            interval = (row[1] if row and row[1] is not None else 3600)
            # Bounded exponential backoff: 30s * 2^(fc), max interval
            backoff_sec = min(interval, 30 * (2 ** min(fc, 6)))
            next_sync = datetime.fromtimestamp(now.timestamp() + backoff_sec).isoformat()
            new_status = "error" if fc >= 5 else "active"

            conn.execute(
                """
                UPDATE job_sources
                SET failure_count = ?,
                    last_error = ?,
                    last_failure_at = ?,
                    next_sync_at = ?,
                    last_sync_complete = ?,
                    status = ?
                WHERE source_type = ? AND board_token_or_slug = ?
                """,
                (
                    fc,
                    str(error_msg)[:500],
                    now_iso,
                    next_sync,
                    1 if is_complete else 0,
                    new_status,
                    source_type.lower().strip(),
                    board_slug.strip(),
                ),
            )
            conn.commit()

    def record_sync_run(
        self,
        sync_run_id: str,
        source_name: str,
        source_type: str,
        board_slug: str,
        status: str,
        is_complete: bool,
        total_retrieved: int,
        new_jobs: int,
        updated_jobs: int,
        duplicates_removed: int,
        expired_jobs: int,
        error_message: str = "",
        started_at: str = "",
        completed_at: str = "",
    ) -> None:
        """Persist a completed sync run record into sync_runs."""
        with get_db_connection(self.db_path) as conn:
            # Find source_id if present
            src_row = conn.execute(
                "SELECT id FROM job_sources WHERE source_type = ? AND board_token_or_slug = ?",
                (source_type.lower().strip(), board_slug.strip()),
            ).fetchone()
            source_id = src_row[0] if src_row else None

            conn.execute(
                """
                INSERT OR REPLACE INTO sync_runs (
                    sync_run_id, source_id, source_name, source_type, board_slug,
                    status, is_complete, total_retrieved, new_jobs,
                    updated_jobs, duplicates_removed, expired_jobs,
                    error_message, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sync_run_id,
                    source_id,
                    source_name,
                    source_type.lower().strip(),
                    board_slug.strip(),
                    status,
                    1 if is_complete else 0,
                    total_retrieved,
                    new_jobs,
                    updated_jobs,
                    duplicates_removed,
                    expired_jobs,
                    str(error_message)[:500],
                    started_at,
                    completed_at,
                ),
            )
            conn.commit()

    def get_sync_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch historical sync runs."""
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_semaphore(self, source_type: str, limit: int = 2) -> asyncio.Semaphore:
        """Get or create concurrency semaphore for source type."""
        key = source_type.lower().strip()
        if key not in self._semaphores:
            self._semaphores[key] = asyncio.Semaphore(max(1, limit))
        return self._semaphores[key]
