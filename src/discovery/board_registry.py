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


DEFAULT_COMPANY_BOARDS: List[JobSourceConfig] = [
    JobSourceConfig(
        name="Cloudflare",
        source_type=SourceType.GREENHOUSE,
        board_token_or_slug="cloudflare",
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
    JobSourceConfig(
        name="Ramp",
        source_type=SourceType.ASHBY,
        board_token_or_slug="ramp",
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

    def record_sync_success(self, source_type: str, board_slug: str) -> None:
        """Mark board synchronization successful."""
        now = datetime.now().isoformat()
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE job_sources
                SET last_synced_at = ?, failure_count = 0, last_error = '', status = 'active'
                WHERE source_type = ? AND board_token_or_slug = ?
                """,
                (now, source_type.lower().strip(), board_slug.strip()),
            )
            conn.commit()

    def record_sync_failure(self, source_type: str, board_slug: str, error_msg: str) -> None:
        """Record board synchronization error without false deactivation."""
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT failure_count FROM job_sources WHERE source_type = ? AND board_token_or_slug = ?",
                (source_type.lower().strip(), board_slug.strip()),
            ).fetchone()
            fc = (row[0] if row else 0) + 1
            new_status = "error" if fc >= 5 else "active"
            conn.execute(
                """
                UPDATE job_sources
                SET failure_count = ?, last_error = ?, status = ?
                WHERE source_type = ? AND board_token_or_slug = ?
                """,
                (fc, str(error_msg)[:500], new_status, source_type.lower().strip(), board_slug.strip()),
            )
            conn.commit()

    def get_semaphore(self, source_type: str, limit: int = 2) -> asyncio.Semaphore:
        """Get or create concurrency semaphore for source type."""
        key = source_type.lower().strip()
        if key not in self._semaphores:
            self._semaphores[key] = asyncio.Semaphore(max(1, limit))
        return self._semaphores[key]
