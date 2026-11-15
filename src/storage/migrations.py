"""
Database schema migrations for AutoBot v2.
Non-destructive migrations ensuring tenant isolation and backward compatibility.
"""

from datetime import datetime
import sqlite3
from typing import Optional

from src.utils.logger import logger


def run_migrations(conn: sqlite3.Connection) -> None:
    """Run all schema migrations idempotently against the given connection."""
    conn.execute("PRAGMA foreign_keys = ON")

    # 1. Migration tracking table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            description TEXT NOT NULL
        )
    """)

    # 2. Base tables (applications and sessions from legacy)
    # Using composite UNIQUE(user_id, job_id) to ensure complete tenant isolation
    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id         TEXT NOT NULL,
            job_title      TEXT NOT NULL,
            company        TEXT NOT NULL,
            location       TEXT,
            apply_type     TEXT NOT NULL,
            match_score    REAL DEFAULT 0.0,
            status         TEXT NOT NULL,
            url            TEXT,
            applied_at     TEXT NOT NULL,
            notes          TEXT,
            user_id        INTEGER DEFAULT 1,
            UNIQUE(user_id, job_id)
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

    # Ensure user_id column exists on applications table
    app_cols = [r[1] for r in conn.execute("PRAGMA table_info(applications)").fetchall()]
    if "user_id" not in app_cols:
        conn.execute("ALTER TABLE applications ADD COLUMN user_id INTEGER DEFAULT 1")

    # Migrate legacy applications table with job_id UNIQUE constraint to UNIQUE(user_id, job_id)
    cur_app = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='applications'").fetchone()
    if cur_app and cur_app[0]:
        app_sql = cur_app[0]
        if "UNIQUE(user_id, job_id)" not in app_sql and ("job_id TEXT UNIQUE" in app_sql or "job_id         TEXT UNIQUE" in app_sql):
            conn.execute("""
                CREATE TABLE IF NOT EXISTS applications_migrated (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id         TEXT NOT NULL,
                    job_title      TEXT NOT NULL,
                    company        TEXT NOT NULL,
                    location       TEXT,
                    apply_type     TEXT NOT NULL,
                    match_score    REAL DEFAULT 0.0,
                    status         TEXT NOT NULL,
                    url            TEXT,
                    applied_at     TEXT NOT NULL,
                    notes          TEXT,
                    user_id        INTEGER DEFAULT 1,
                    UNIQUE(user_id, job_id)
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO applications_migrated
                SELECT id, job_id, job_title, company, location, apply_type, match_score, status, url, applied_at, notes, COALESCE(user_id, 1)
                FROM applications
            """)
            conn.execute("DROP TABLE applications")
            conn.execute("ALTER TABLE applications_migrated RENAME TO applications")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_user_id ON applications(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_job_id ON applications(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status)")

    # 3. Multi-User Foundations: users
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            email          TEXT UNIQUE NOT NULL,
            password_hash  TEXT NOT NULL,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            is_active      INTEGER DEFAULT 1
        )
    """)

    # Create default user if none exists (for backward compatibility)
    cur = conn.execute("SELECT id FROM users WHERE id = 1")
    if cur.fetchone() is None:
        # Default placeholder user for legacy single-tenant data
        # Default password is an unguessable locked placeholder; user can register their own
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT OR IGNORE INTO users (id, email, password_hash, created_at, updated_at, is_active)
            VALUES (1, 'default@autobot.local', 'LOCKED_LEGACY_ACCOUNT', ?, ?, 1)
            """,
            (now, now),
        )

    # 3b. Persistent User Sessions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions (
            token          TEXT PRIMARY KEY,
            user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            email          TEXT NOT NULL,
            expires_at     TEXT NOT NULL,
            created_at     TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at)")

    # 4. candidate_profiles
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidate_profiles (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id            INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            full_name          TEXT NOT NULL,
            email              TEXT,
            phone              TEXT,
            location           TEXT,
            country            TEXT,
            headline           TEXT,
            summary            TEXT,
            technical_skills   TEXT DEFAULT '[]',
            primary_skills     TEXT DEFAULT '[]',
            secondary_skills   TEXT DEFAULT '[]',
            experience         TEXT DEFAULT '[]',
            projects           TEXT DEFAULT '[]',
            education          TEXT DEFAULT '[]',
            certifications     TEXT DEFAULT '[]',
            achievements       TEXT DEFAULT '[]',
            contact_info       TEXT DEFAULT '{}',
            linkedin_url       TEXT,
            portfolio_url      TEXT,
            github_url         TEXT,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_profiles_user_id ON candidate_profiles(user_id)")

    # 5. resume_versions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resume_versions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            version_name   TEXT NOT NULL,
            file_path      TEXT NOT NULL,
            file_hash      TEXT NOT NULL,
            parsed_data    TEXT DEFAULT '{}',
            is_active      INTEGER DEFAULT 1,
            created_at     TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_resume_versions_user_id ON resume_versions(user_id)")

    # 6. resume_evidence
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resume_evidence (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            resume_version_id INTEGER NOT NULL REFERENCES resume_versions(id) ON DELETE CASCADE,
            user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            section           TEXT NOT NULL,
            content           TEXT NOT NULL,
            metadata          TEXT DEFAULT '{}',
            created_at        TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_resume_evidence_user ON resume_evidence(user_id, resume_version_id)")

    # 7. job_preferences
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_preferences (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id            INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            employment_types   TEXT DEFAULT '["full-time"]',
            target_roles       TEXT DEFAULT '[]',
            primary_skills     TEXT DEFAULT '[]',
            secondary_skills   TEXT DEFAULT '[]',
            experience_level   TEXT DEFAULT 'mid-senior',
            work_arrangement   TEXT DEFAULT 'remote',
            target_locations   TEXT DEFAULT '[]',
            eligible_countries TEXT DEFAULT '[]',
            min_salary         REAL DEFAULT 0.0,
            min_fit_threshold  REAL DEFAULT 60.0,
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_preferences_user_id ON job_preferences(user_id)")

    # 8. job_sources
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_sources (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            name                 TEXT NOT NULL,
            source_type          TEXT NOT NULL,
            board_token_or_slug  TEXT NOT NULL,
            base_url             TEXT,
            is_active            INTEGER DEFAULT 1,
            created_at           TEXT NOT NULL,
            UNIQUE(source_type, board_token_or_slug)
        )
    """)

    # 9. jobs
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            stable_id        TEXT UNIQUE NOT NULL,
            source_id        INTEGER REFERENCES job_sources(id),
            source_name      TEXT NOT NULL,
            title            TEXT NOT NULL,
            company          TEXT NOT NULL,
            description      TEXT NOT NULL,
            employment_type  TEXT DEFAULT 'full-time',
            location         TEXT DEFAULT '',
            country          TEXT DEFAULT '',
            is_remote        INTEGER DEFAULT 0,
            salary_info      TEXT DEFAULT '',
            publication_date TEXT DEFAULT '',
            application_url  TEXT DEFAULT '',
            raw_data         TEXT DEFAULT '{}',
            fingerprint      TEXT NOT NULL,
            created_at       TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_stable_id ON jobs(stable_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company_title ON jobs(company, title)")

    # 10. job_requirements
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_requirements (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id        INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            req_type      TEXT NOT NULL,
            text          TEXT NOT NULL,
            weight        REAL DEFAULT 1.0,
            is_mandatory  INTEGER DEFAULT 0,
            created_at    TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_requirements_job_id ON job_requirements(job_id)")

    # 11. match_evaluations
    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_evaluations (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id                  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_id                   INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            resume_version_id        INTEGER REFERENCES resume_versions(id),
            eligibility_status       TEXT NOT NULL,
            overall_score            REAL NOT NULL,
            required_skills_score    REAL NOT NULL,
            responsibilities_score   REAL NOT NULL,
            target_role_score        REAL NOT NULL,
            experience_edu_score     REAL NOT NULL,
            preferred_skills_score   REAL NOT NULL,
            matched_requirements     TEXT DEFAULT '[]',
            missing_requirements     TEXT DEFAULT '[]',
            evidence_references      TEXT DEFAULT '[]',
            mandatory_failures       TEXT DEFAULT '[]',
            explanation              TEXT NOT NULL,
            created_at               TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_match_eval_user_job ON match_evaluations(user_id, job_id)")

    # 12. application_packs
    conn.execute("""
        CREATE TABLE IF NOT EXISTS application_packs (
            id                        INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id                   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_id                    INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            resume_version_id         INTEGER REFERENCES resume_versions(id),
            match_evaluation_id       INTEGER REFERENCES match_evaluations(id),
            tailored_resume_summary   TEXT DEFAULT '',
            tailored_experiences      TEXT DEFAULT '[]',
            cover_letter              TEXT DEFAULT '',
            question_drafts           TEXT DEFAULT '[]',
            missing_info_checklist    TEXT DEFAULT '[]',
            job_match_explanation    TEXT DEFAULT '',
            user_approved             INTEGER DEFAULT 0,
            created_at                TEXT NOT NULL,
            updated_at                TEXT NOT NULL
        )
    """)
    pack_cols = [r[1] for r in conn.execute("PRAGMA table_info(application_packs)").fetchall()]
    if "job_match_explanation" not in pack_cols:
        conn.execute("ALTER TABLE application_packs ADD COLUMN job_match_explanation TEXT DEFAULT ''")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_application_packs_user_job ON application_packs(user_id, job_id)")

    # 13. application_events
    conn.execute("""
        CREATE TABLE IF NOT EXISTS application_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_id          INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            pack_id         INTEGER REFERENCES application_packs(id),
            event_type      TEXT NOT NULL,
            status          TEXT NOT NULL,
            user_confirmed  INTEGER DEFAULT 0,
            proof_notes     TEXT DEFAULT '',
            created_at      TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_app_events_user ON application_events(user_id, job_id)")

    # 14. audit_logs
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER REFERENCES users(id),
            action         TEXT NOT NULL,
            resource_type  TEXT NOT NULL,
            resource_id    TEXT,
            details        TEXT DEFAULT '{}',
            ip_address     TEXT DEFAULT '',
            created_at     TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action)")

    # Legacy indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_job_id ON applications(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status)")

    conn.commit()
    logger.info("[db]✓ Database schema migrations applied successfully[/db]")
