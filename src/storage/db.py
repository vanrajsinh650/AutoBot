"""
SQLite persistence storage for AutoBot v2.
Supports multi-tenant isolation, structured candidate profiles, application tracking,
and legacy backwards compatibility.
"""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from src.storage.migrations import run_migrations


DEFAULT_DB_PATH = "logs/autobot.db"


def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Create and return a configured sqlite3 connection with Row factory."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialize database tables with migrations and indexes."""
    with get_db_connection(db_path) as conn:
        run_migrations(conn)


def is_already_applied(
    job_id: str,
    db_path: str = DEFAULT_DB_PATH,
    user_id: Optional[int] = None,
) -> bool:
    """Check if a job has already been applied to (applied, dry_run, or submitted)."""
    if not job_id:
        return False
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        if user_id is not None:
            cursor = conn.execute(
                """
                SELECT id FROM applications
                WHERE job_id = ? AND user_id = ? AND status IN ('applied', 'dry_run', 'submitted')
                LIMIT 1
                """,
                (job_id, user_id),
            )
        else:
            cursor = conn.execute(
                """
                SELECT id FROM applications
                WHERE job_id = ? AND status IN ('applied', 'dry_run', 'submitted')
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
    user_id: int = 1,
) -> None:
    """Insert or update an application record in the database with strict tenant isolation."""
    init_db(db_path)
    now = datetime.now().isoformat()
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO applications (
                job_id, job_title, company, location,
                apply_type, match_score, status, url, applied_at, notes, user_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, job_id) DO UPDATE SET
                job_title = excluded.job_title,
                company = excluded.company,
                location = excluded.location,
                apply_type = excluded.apply_type,
                match_score = excluded.match_score,
                status = excluded.status,
                url = excluded.url,
                applied_at = excluded.applied_at,
                notes = excluded.notes
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
                now,
                notes or "",
                user_id,
            ),
        )
        conn.commit()


def update_application_status(
    user_id: int,
    job_id_or_stable_id: str,
    new_status: str,
    notes: str = "",
    db_path: str = DEFAULT_DB_PATH,
) -> bool:
    """
    Update application lifecycle status (e.g. interview, offer, rejected) for a specific user.
    Records transition in application_events and audit logs.
    """
    init_db(db_path)
    now = datetime.now().isoformat()
    with get_db_connection(db_path) as conn:
        # Check if record exists in applications table
        row = conn.execute(
            "SELECT id, job_id, job_title, company, notes FROM applications WHERE user_id = ? AND (job_id = ? OR id = ?)",
            (user_id, job_id_or_stable_id, int(job_id_or_stable_id) if job_id_or_stable_id.isdigit() else -1),
        ).fetchone()

        job_internal_id = 0
        if not row:
            # Check in jobs table
            job_row = conn.execute(
                "SELECT id, stable_id, title, company, location, application_url FROM jobs WHERE id = ? OR stable_id = ?",
                (int(job_id_or_stable_id) if job_id_or_stable_id.isdigit() else -1, job_id_or_stable_id),
            ).fetchone()
            if not job_row:
                return False

            job_internal_id = job_row["id"]
            conn.execute(
                """
                INSERT INTO applications (
                    job_id, job_title, company, location, apply_type, match_score, status, url, applied_at, notes, user_id
                ) VALUES (?, ?, ?, ?, 'manual', 0.8, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, job_id) DO UPDATE SET status = excluded.status, notes = excluded.notes
                """,
                (
                    job_row["stable_id"],
                    job_row["title"],
                    job_row["company"],
                    job_row["location"] or "",
                    new_status,
                    job_row["application_url"] or "",
                    now,
                    notes,
                    user_id,
                ),
            )
        else:
            updated_notes = notes if notes else (row["notes"] or "")
            conn.execute(
                "UPDATE applications SET status = ?, notes = ? WHERE id = ? AND user_id = ?",
                (new_status, updated_notes, row["id"], user_id),
            )
            job_internal_row = conn.execute("SELECT id FROM jobs WHERE stable_id = ?", (row["job_id"],)).fetchone()
            if job_internal_row:
                job_internal_id = job_internal_row["id"]

        # Record event in application_events if job internal id exists
        if job_internal_id:
            conn.execute(
                """
                INSERT INTO application_events (
                    user_id, job_id, event_type, status, user_confirmed, proof_notes, created_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (user_id, job_internal_id, new_status, new_status, notes, now),
            )
        conn.commit()

    log_audit(
        user_id=user_id,
        action="APPLICATION_STATUS_UPDATED",
        resource_type="applications",
        resource_id=job_id_or_stable_id,
        details={"new_status": new_status, "notes": notes},
        db_path=db_path,
    )
    return True


def get_stats(
    db_path: str = DEFAULT_DB_PATH,
    user_id: Optional[int] = None,
) -> Dict[str, int]:
    """Retrieve aggregate counts by status across all sessions, optionally scoped by user."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        if user_id is not None:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) as cnt
                FROM applications
                WHERE user_id = ?
                GROUP BY status
                """,
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute("""
                SELECT status, COUNT(*) as cnt
                FROM applications
                GROUP BY status
            """).fetchall()

    stats = {
        "applied": 0,
        "skipped": 0,
        "failed": 0,
        "dry_run": 0,
        "discovered": 0,
        "evaluated": 0,
        "prepared": 0,
        "submitted": 0,
        "interview": 0,
        "offer": 0,
        "rejected": 0,
    }
    for row in rows:
        st = row["status"]
        if st in stats:
            stats[st] = row["cnt"]
        else:
            stats[st] = row["cnt"]
    return stats


def get_applications(user_id: int, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve all application records for a specific user."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT * FROM applications WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


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


# ── Multi-Tenant Candidate Profile Methods ────────────────────────────

def get_candidate_profile(user_id: int, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """Get candidate profile for a user."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM candidate_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        for key in [
            "technical_skills", "primary_skills", "secondary_skills",
            "experience", "projects", "education", "certifications",
            "achievements", "contact_info"
        ]:
            if d.get(key) and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    pass
        return d


def save_candidate_profile(user_id: int, profile: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> None:
    """Save or update candidate profile with strict tenant ownership."""
    init_db(db_path)
    now = datetime.now().isoformat()
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO candidate_profiles (
                user_id, full_name, email, phone, location, country,
                headline, summary, technical_skills, primary_skills, secondary_skills,
                experience, projects, education, certifications, achievements, contact_info,
                linkedin_url, portfolio_url, github_url, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                full_name = excluded.full_name,
                email = excluded.email,
                phone = excluded.phone,
                location = excluded.location,
                country = excluded.country,
                headline = excluded.headline,
                summary = excluded.summary,
                technical_skills = excluded.technical_skills,
                primary_skills = excluded.primary_skills,
                secondary_skills = excluded.secondary_skills,
                experience = excluded.experience,
                projects = excluded.projects,
                education = excluded.education,
                certifications = excluded.certifications,
                achievements = excluded.achievements,
                contact_info = excluded.contact_info,
                linkedin_url = excluded.linkedin_url,
                portfolio_url = excluded.portfolio_url,
                github_url = excluded.github_url,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                profile.get("full_name", ""),
                profile.get("email", ""),
                profile.get("phone", ""),
                profile.get("location", ""),
                profile.get("country", ""),
                profile.get("headline", ""),
                profile.get("summary", ""),
                json.dumps(profile.get("technical_skills", [])),
                json.dumps(profile.get("primary_skills", [])),
                json.dumps(profile.get("secondary_skills", [])),
                json.dumps(profile.get("experience", [])),
                json.dumps(profile.get("projects", [])),
                json.dumps(profile.get("education", [])),
                json.dumps(profile.get("certifications", [])),
                json.dumps(profile.get("achievements", [])),
                json.dumps(profile.get("contact_info", {})),
                profile.get("linkedin_url", ""),
                profile.get("portfolio_url", ""),
                profile.get("github_url", ""),
                now,
                now,
            ),
        )
        conn.commit()


# ── Job Preferences Methods ───────────────────────────────────────────

def get_job_preferences(user_id: int, db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Retrieve job preferences for a user."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM job_preferences WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return {
                "employment_types": ["full-time"],
                "target_roles": ["Software Engineer"],
                "primary_skills": [],
                "secondary_skills": [],
                "experience_level": "mid-senior",
                "work_arrangement": "remote",
                "target_locations": [],
                "eligible_countries": ["India", "United States"],
                "min_salary": 0.0,
                "min_fit_threshold": 60.0,
            }
        d = dict(row)
        for key in [
            "employment_types", "target_roles", "primary_skills",
            "secondary_skills", "target_locations", "eligible_countries"
        ]:
            if d.get(key) and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    pass
        return d


def save_job_preferences(user_id: int, prefs: Dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> None:
    """Save or update job preferences for a user."""
    init_db(db_path)
    now = datetime.now().isoformat()
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO job_preferences (
                user_id, employment_types, target_roles, primary_skills, secondary_skills,
                experience_level, work_arrangement, target_locations, eligible_countries,
                min_salary, min_fit_threshold, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                employment_types = excluded.employment_types,
                target_roles = excluded.target_roles,
                primary_skills = excluded.primary_skills,
                secondary_skills = excluded.secondary_skills,
                experience_level = excluded.experience_level,
                work_arrangement = excluded.work_arrangement,
                target_locations = excluded.target_locations,
                eligible_countries = excluded.eligible_countries,
                min_salary = excluded.min_salary,
                min_fit_threshold = excluded.min_fit_threshold,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                json.dumps(prefs.get("employment_types", ["full-time"])),
                json.dumps(prefs.get("target_roles", [])),
                json.dumps(prefs.get("primary_skills", [])),
                json.dumps(prefs.get("secondary_skills", [])),
                prefs.get("experience_level", "mid-senior"),
                prefs.get("work_arrangement", "remote"),
                json.dumps(prefs.get("target_locations", [])),
                json.dumps(prefs.get("eligible_countries", [])),
                float(prefs.get("min_salary", 0.0)),
                float(prefs.get("min_fit_threshold", 60.0)),
                now,
                now,
            ),
        )
        conn.commit()


# ── Resume Versions & Evidence ────────────────────────────────────────

def save_resume_version(
    user_id: int,
    version_name: str,
    file_path: str,
    file_hash: str,
    parsed_data: Dict[str, Any],
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Save a resume version with user isolation."""
    init_db(db_path)
    now = datetime.now().isoformat()
    with get_db_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO resume_versions (
                user_id, version_name, file_path, file_hash, parsed_data, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (user_id, version_name, file_path, file_hash, json.dumps(parsed_data), now),
        )
        conn.commit()
        return cur.lastrowid


def get_resume_versions(user_id: int, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """List resume versions for a specific tenant."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM resume_versions WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["parsed_data"] = json.loads(d["parsed_data"])
            except Exception:
                pass
            result.append(d)
        return result


def save_resume_evidence(
    user_id: int,
    resume_version_id: int,
    section: str,
    content: str,
    metadata: Dict[str, Any],
    db_path: str = DEFAULT_DB_PATH,
) -> int:
    """Store explicit resume evidence chunk tied to user and resume version."""
    init_db(db_path)
    now = datetime.now().isoformat()
    with get_db_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO resume_evidence (
                user_id, resume_version_id, section, content, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, resume_version_id, section, content, json.dumps(metadata), now),
        )
        conn.commit()
        return cur.lastrowid


def get_resume_evidence(user_id: int, resume_version_id: Optional[int] = None, db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """Retrieve verified resume evidence for a user."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        if resume_version_id is not None:
            rows = conn.execute(
                "SELECT * FROM resume_evidence WHERE user_id = ? AND resume_version_id = ?",
                (user_id, resume_version_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM resume_evidence WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        res = []
        for r in rows:
            d = dict(r)
            try:
                d["metadata"] = json.loads(d["metadata"])
            except Exception:
                pass
            res.append(d)
        return res


# ── Audit Logging ─────────────────────────────────────────────────────

def log_audit(
    user_id: Optional[int],
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Any = None,
    ip_address: str = "",
    db_path: str = DEFAULT_DB_PATH,
) -> None:
    """Record a security audit log event."""
    init_db(db_path)
    now = datetime.now().isoformat()
    details_str = json.dumps(details) if isinstance(details, (dict, list)) else str(details or "")
    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO audit_logs (
                user_id, action, resource_type, resource_id, details, ip_address, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, action, resource_type, str(resource_id or ""), details_str, ip_address, now),
        )
        conn.commit()
