"""
SQLite persistence storage for AutoBot v2.

Educational Concept:
An autonomous agent that interacts with the real world must have durable transactional
state. If AutoBot crashes, restarts, or runs daily cron jobs:
1. Deduplication:
   Checking `is_already_applied(job_id)` prevents embarrassing duplicate applications
   to the same company/job, protecting user credibility and avoiding spam flags.
2. Analytics & Audit Trail:
   Persisting match scores, apply types, timestamps, and error diagnostics enables
   performance telemetry (e.g. "What percentage of Easy Apply jobs succeeded?").
3. Session Bookkeeping:
   Tracking discrete session records (started_at, ended_at, applied_count) enables
   session-based rate-limiting to adhere to LinkedIn anti-bot thresholds.
"""

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional


DEFAULT_DB_PATH = "logs/autobot.db"


def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create and return a configured sqlite3 connection with Row factory."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialize database tables with indexes."""
    with get_db_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id         TEXT UNIQUE NOT NULL,
                job_title      TEXT NOT NULL,
                company        TEXT NOT NULL,
                location       TEXT,
                apply_type     TEXT NOT NULL,       -- 'easy_apply' | 'external'
                match_score    REAL DEFAULT 0.0,
                status         TEXT NOT NULL,       -- 'applied' | 'skipped' | 'failed' | 'dry_run'
                url            TEXT,
                applied_at     TEXT NOT NULL,
                notes          TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at     TEXT NOT NULL,
                ended_at       TEXT,
                total_applied  INTEGER DEFAULT 0,
                total_skipped  INTEGER DEFAULT 0,
                total_failed   INTEGER DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_applications_job_id
            ON applications(job_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_applications_status
            ON applications(status)
        """)
        conn.commit()


def is_already_applied(job_id: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Check if a job has already been applied to (applied or dry_run)."""
    if not job_id:
        return False
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id FROM applications
            WHERE job_id = ? AND status IN ('applied', 'dry_run')
            LIMIT 1
            """,
            (job_id,),
        )
        return cursor.fetchone() is not None


def save_application(
    job_id: str,
    job_title: str,
    company: str,
    location: str,
    apply_type: str,
    match_score: float,
    status: str,
    url: str,
    notes: Optional[str] = None,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Insert or replace an application record in the database."""
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO applications (
                job_id, job_title, company, location,
                apply_type, match_score, status, url, applied_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_title,
                company,
                location,
                apply_type,
                round(float(match_score), 2),
                status,
                url,
                datetime.now().isoformat(),
                notes or "",
            ),
        )
        conn.commit()


def get_stats(db_path: str = DEFAULT_DB_PATH) -> Dict[str, int]:
    """Retrieve aggregate counts by status across all sessions."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        rows = conn.execute("""
            SELECT status, COUNT(*) as cnt
            FROM applications
            GROUP BY status
        """).fetchall()

    stats = {"applied": 0, "skipped": 0, "failed": 0, "dry_run": 0}
    for row in rows:
        st = row["status"]
        if st in stats:
            stats[st] = row["cnt"]
    return stats


def start_session(db_path: str = DEFAULT_DB_PATH) -> int:
    """Record the start of a new bot session, returning session_id."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO sessions (started_at) VALUES (?)",
            (datetime.now().isoformat(),),
        )
        conn.commit()
        return cursor.lastrowid


def end_session(
    session_id: int,
    applied: int,
    skipped: int,
    failed: int,
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Update a session with end timestamp and final metrics."""
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE sessions
            SET ended_at = ?, total_applied = ?, total_skipped = ?, total_failed = ?
            WHERE id = ?
            """,
            (
                datetime.now().isoformat(),
                applied,
                skipped,
                failed,
                session_id,
            ),
        )
        conn.commit()
