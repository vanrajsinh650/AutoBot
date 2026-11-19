"""
SQLite persistence storage for AutoBot v2.
Supports multi-tenant isolation, structured candidate profiles, application tracking,
and legacy backwards compatibility.
"""

from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple, Union

from src.storage.migrations import run_migrations


DEFAULT_DB_PATH = "logs/autobot.db"


def get_db_path() -> str:
    """Return active database path from environment or default."""
    return os.environ.get("AUTOBOT_DB_PATH", DEFAULT_DB_PATH)


def _sqlite_regexp(pattern: Any, text: Any) -> bool:
    """Safe regex evaluator for SQLite REGEXP operator with null/type guarding."""
    if pattern is None or text is None:
        return False
    try:
        return bool(re.search(str(pattern), str(text), re.IGNORECASE))
    except Exception:
        return False


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Create and return a configured sqlite3 connection with Row factory and PRAGMA foreign_keys=ON.
    Includes a hard guard preventing pytest from accessing the live production database.
    """
    target_path = db_path if db_path is not None else get_db_path()

    # Hard guard: Prevent test suites from writing to or reading from live production database
    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        resolved = Path(target_path).resolve()
        prod_resolved = Path(DEFAULT_DB_PATH).resolve()
        if resolved == prod_resolved and os.environ.get("AUTOBOT_ALLOW_LIVE_DB_IN_TESTS") != "1":
            raise RuntimeError(
                f"CRITICAL HARD GUARD: Pytest attempted to open production database '{target_path}'. "
                f"Tests must use an isolated temporary database (set AUTOBOT_DB_PATH or use isolated test fixture)."
            )

    if target_path != ":memory:":
        parent_dir = Path(target_path).parent
        parent_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(parent_dir, 0o700)
        except Exception:
            pass

    conn = sqlite3.connect(target_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    conn.create_function("REGEXP", 2, _sqlite_regexp)

    if target_path != ":memory:" and Path(target_path).exists():
        try:
            os.chmod(target_path, 0o600)
        except Exception:
            pass
    return conn


def is_admin_user(user_id: int, db_path: Optional[str] = None) -> bool:
    """Check if the given user_id has administrator privileges."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        row = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
        if row and row["is_admin"] == 1:
            return True
        if user_id == 1:
            return True
    return False


def init_db(db_path: Optional[str] = None) -> None:
    """Initialize database tables with migrations and indexes."""
    with get_db_connection(db_path) as conn:
        run_migrations(conn)


def is_already_applied(
    job_id: str,
    db_path: Optional[str] = None,
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
    db_path: Optional[str] = None,
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


def detect_apply_platform(
    url: Optional[str] = "",
    source_name: Optional[str] = "",
    is_easy_apply: bool = False,
) -> Tuple[str, str]:
    """
    Detect the specific ATS or job platform and its high-level platform category.

    Returns:
        (platform_name, platform_category)
        where platform_category is either 'linkedin' or 'external'.
    """
    u = (url or "").lower().strip()
    s = (source_name or "").lower().strip()

    if is_easy_apply or "easy_apply" in u or "easy_apply" in s or "easy apply" in s:
        return ("LinkedIn (Easy Apply)", "linkedin")

    if "linkedin.com" in u or "lnkd.in" in u:
        if is_easy_apply:
            return ("LinkedIn (Easy Apply)", "linkedin")
        return ("LinkedIn", "linkedin")

    if "greenhouse.io" in u or "greenhouse" in s:
        return ("Greenhouse", "external")
    if "lever.co" in u or "lever" in s:
        return ("Lever", "external")
    if "ashbyhq.com" in u or "ashby" in s:
        return ("Ashby", "external")
    if "myworkdayjobs.com" in u or "workday" in u or "workday" in s:
        return ("Workday", "external")
    if "smartrecruiters.com" in u or "smartrecruiters" in s:
        return ("SmartRecruiters", "external")
    if "taleo.net" in u or "taleo" in s:
        return ("Taleo", "external")
    if "icims.com" in u or "icims" in s:
        return ("iCIMS", "external")
    if "jobvite.com" in u or "jobvite" in s:
        return ("Jobvite", "external")
    if "bamboohr.com" in u or "bamboohr" in s:
        return ("BambooHR", "external")
    if "workable.com" in u or "workable" in s:
        return ("Workable", "external")
    if "rippling.com" in u or "rippling" in s:
        return ("Rippling", "external")

    if s and s != "linkedin":
        return (source_name.title(), "external")
    if u and not ("linkedin.com" in u):
        return ("Company Career Portal", "external")

    return ("LinkedIn", "linkedin")


def save_scraped_job(
    title: str,
    company: str,
    location: str,
    description: str,
    apply_url: str,
    source_name: str = "LinkedIn",
    is_easy_apply: bool = False,
    job_id: Optional[str] = None,
    user_id: int = 1,
    db_path: Optional[str] = None,
    raw_data: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Save a scraped job posting with full description, apply form link, and platform metadata
    into both the 'jobs' repository table and the 'applications' tracking table.
    """
    init_db(db_path)
    platform_name, platform_category = detect_apply_platform(
        url=apply_url,
        source_name=source_name,
        is_easy_apply=is_easy_apply,
    )
    apply_type = "easy_apply" if (is_easy_apply or platform_category == "linkedin") else "external"

    clean_title = (title or "Untitled Role").strip()
    clean_company = (company or "Unknown Company").strip()
    clean_location = (location or "Remote").strip()
    clean_desc = (description or f"Role: {clean_title} at {clean_company}. Location: {clean_location}.").strip()
    clean_url = (apply_url or "").strip()

    fingerprint = hashlib.sha256(f"{clean_company.lower()}:{clean_title.lower()}:{clean_location.lower()}".encode()).hexdigest()
    stable_id = str(job_id).strip() if job_id else f"{source_name.lower().replace(' ', '_')}_{fingerprint[:12]}"
    now = datetime.now().isoformat()

    merged_raw = raw_data.copy() if isinstance(raw_data, dict) else {}
    merged_raw.update({
        "platform": platform_name,
        "platform_category": platform_category,
        "apply_type": apply_type,
        "apply_url": clean_url,
        "scraped_at": now,
        "is_easy_apply": is_easy_apply,
    })

    with get_db_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                stable_id, source_name, title, company, description,
                employment_type, location, application_url, raw_data, fingerprint, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stable_id) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                description = CASE WHEN length(excluded.description) > length(jobs.description) THEN excluded.description ELSE jobs.description END,
                location = excluded.location,
                application_url = CASE WHEN excluded.application_url != '' THEN excluded.application_url ELSE jobs.application_url END,
                raw_data = excluded.raw_data
            """,
            (
                stable_id,
                source_name,
                clean_title,
                clean_company,
                clean_desc,
                "full-time",
                clean_location,
                clean_url,
                json.dumps(merged_raw),
                fingerprint,
                now,
            ),
        )

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
                stable_id,
                clean_title,
                clean_company,
                clean_location,
                apply_type,
                0.85,
                "discovered",
                clean_url,
                now,
                f"Platform: {platform_name} ({platform_category}) | Apply Form: {clean_url}",
                user_id,
            ),
        )
        conn.commit()

    return stable_id


def get_apply_portals(
    user_id: int,
    platform_category: Optional[str] = None,
    search_query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Retrieve all scraped job postings with their direct apply form links,
    categorized by platform (LinkedIn vs External platforms like Greenhouse, Lever, etc.).
    """
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        sql = """
            SELECT 
                j.id as job_table_id,
                j.stable_id,
                j.source_name,
                j.title,
                j.company,
                j.location,
                j.description,
                j.application_url,
                j.raw_data,
                j.created_at,
                a.id as app_id,
                a.status as application_status,
                a.apply_type as app_apply_type,
                a.url as app_url,
                a.match_score
            FROM jobs j
            LEFT JOIN applications a ON j.stable_id = a.job_id AND a.user_id = ?
            WHERE 1=1
        """
        params: List[Any] = [user_id]

        if search_query:
            sql += " AND (LOWER(j.title) LIKE ? OR LOWER(j.company) LIKE ? OR LOWER(j.description) LIKE ?)"
            q = f"%{search_query.strip().lower()}%"
            params.extend([q, q, q])

        sql += " ORDER BY j.id DESC"
        rows = conn.execute(sql, params).fetchall()

    linkedin_count = 0
    external_count = 0
    platform_breakdown: Dict[str, int] = {}
    items: List[Dict[str, Any]] = []

    for r in rows:
        row_dict = dict(r)
        raw = {}
        try:
            if row_dict.get("raw_data"):
                raw = json.loads(row_dict["raw_data"])
        except Exception:
            raw = {}

        app_url = row_dict.get("application_url") or row_dict.get("app_url") or ""
        src_name = row_dict.get("source_name") or ""
        is_easy = bool(
            raw.get("is_easy_apply") 
            or row_dict.get("app_apply_type") == "easy_apply" 
            or "easy apply" in src_name.lower()
        )

        plat_name, plat_cat = detect_apply_platform(url=app_url, source_name=src_name, is_easy_apply=is_easy)

        if plat_cat == "linkedin":
            linkedin_count += 1
        else:
            external_count += 1

        platform_breakdown[plat_name] = platform_breakdown.get(plat_name, 0) + 1

        # Platform filter
        if platform_category and platform_category.lower() != "all":
            req_cat = platform_category.lower()
            if req_cat in ("linkedin", "linkedin_only") and plat_cat != "linkedin":
                continue
            if req_cat in ("external", "other", "other_platforms") and plat_cat != "external":
                continue
            if req_cat not in ("linkedin", "external") and plat_name.lower() != req_cat:
                continue

        items.append({
            "id": row_dict.get("job_table_id") or row_dict.get("app_id"),
            "stable_id": row_dict.get("stable_id"),
            "title": row_dict.get("title") or "Untitled Role",
            "company": row_dict.get("company") or "Unknown Company",
            "location": row_dict.get("location") or "Remote",
            "description": row_dict.get("description") or "",
            "apply_url": app_url,
            "source_name": src_name,
            "platform": plat_name,
            "platform_category": plat_cat,
            "apply_type": "Easy Apply" if is_easy else "External Apply",
            "match_score": row_dict.get("match_score") or 0.85,
            "status": row_dict.get("application_status") or "discovered",
            "created_at": row_dict.get("created_at") or "",
        })

    paginated_items = items[offset : offset + limit]

    return {
        "total": len(items),
        "linkedin_count": linkedin_count,
        "external_count": external_count,
        "platforms": platform_breakdown,
        "jobs": paginated_items,
    }


def update_application_status(
    user_id: int,
    job_id_or_stable_id: str,
    new_status: str,
    notes: str = "",
    db_path: Optional[str] = None,
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
    db_path: Optional[str] = None,
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


def get_applications(user_id: int, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all application records for a specific user."""
    init_db(db_path)
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            "SELECT * FROM applications WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def start_session(db_path: Optional[str] = None) -> int:
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
    db_path: Optional[str] = None,
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

def get_candidate_profile(user_id: int, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
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


def save_candidate_profile(user_id: int, profile: Dict[str, Any], db_path: Optional[str] = None) -> None:
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

def get_job_preferences(user_id: int, db_path: Optional[str] = None) -> Dict[str, Any]:
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


def save_job_preferences(user_id: int, prefs: Dict[str, Any], db_path: Optional[str] = None) -> None:
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
    db_path: Optional[str] = None,
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


def get_resume_versions(user_id: int, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
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
    db_path: Optional[str] = None,
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


def get_resume_evidence(user_id: int, resume_version_id: Optional[int] = None, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
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


# ── Audit Logging & Tamper-Evident Security ─────────────────────────

AUDIT_GENESIS_HASH = "GENESIS_0000000000000000000000000000000000000000000000000000000000000000"


def log_audit(
    user_id: Optional[int],
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    details: Any = None,
    ip_address: str = "",
    db_path: Optional[str] = None,
) -> str:
    """
    Record a cryptographically chained, tamper-evident security audit log event.
    Returns the SHA-256 entry hash.
    """
    init_db(db_path)
    now = datetime.now().isoformat()
    details_str = json.dumps(details, sort_keys=True) if isinstance(details, (dict, list)) else str(details or "")
    clean_res_id = str(resource_id or "")

    with get_db_connection(db_path) as conn:
        last_row = conn.execute("SELECT entry_hash FROM audit_logs ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = last_row["entry_hash"] if last_row and last_row["entry_hash"] else AUDIT_GENESIS_HASH

        payload = f"{prev_hash}|{user_id}|{action}|{resource_type}|{clean_res_id}|{details_str}|{now}"
        entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        conn.execute(
            """
            INSERT INTO audit_logs (
                user_id, action, resource_type, resource_id, details, ip_address, prev_hash, entry_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, action, resource_type, clean_res_id, details_str, ip_address, prev_hash, entry_hash, now),
        )
        conn.commit()
        return entry_hash


def verify_audit_log_tamper_evidence(db_path: Optional[str] = None) -> Tuple[bool, List[str]]:
    """
    Verify the cryptographic hash chain of the audit_logs table.
    Detects any unauthorized record modifications, deletions, or insertions.
    Returns (is_valid, list_of_violations).
    """
    init_db(db_path)
    violations: List[str] = []
    with get_db_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM audit_logs ORDER BY id ASC").fetchall()
        expected_prev = AUDIT_GENESIS_HASH
        for row in rows:
            entry_id = row["id"]
            row_prev = row["prev_hash"]
            row_hash = row["entry_hash"]

            # Backwards compatibility: skip unhashed legacy entries
            if not row_hash:
                continue

            if row_prev != expected_prev:
                violations.append(
                    f"Audit chain broken at Row {entry_id}: prev_hash mismatch. Expected '{expected_prev}', got '{row_prev}'"
                )

            # Recompute expected hash
            payload = f"{row_prev}|{row['user_id']}|{row['action']}|{row['resource_type']}|{row['resource_id'] or ''}|{row['details']}|{row['created_at']}"
            computed = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            if computed != row_hash:
                violations.append(
                    f"Audit record altered at Row {entry_id}: entry_hash mismatch. Computed '{computed}', stored '{row_hash}'"
                )
            expected_prev = row_hash

    return len(violations) == 0, violations


def backup_database(
    db_path: Optional[str] = None,
    backup_dir: Optional[Union[str, Path]] = None,
) -> Path:
    """
    Perform an atomic online backup of the SQLite database using SQLite's backup API.
    Enforces strict private permissions (0700 dir, 0600 file).
    """
    source_path = Path(db_path or get_db_path()).resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"Source database '{source_path}' does not exist.")

    target_dir = Path(backup_dir or (source_path.parent / "backups")).resolve()
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(target_dir, 0o700)
    except Exception:
        pass

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = target_dir / f"autobot_backup_{timestamp}.db"

    # Use SQLite online backup API
    with get_db_connection(str(source_path)) as src_conn:
        dest_conn = sqlite3.connect(str(backup_file))
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()

    try:
        os.chmod(backup_file, 0o600)
    except Exception:
        pass

    return backup_file


# ── Multi-Process Scheduler Leases ──────────────────────────────

def acquire_scheduler_lease(
    resource_key: str,
    owner_token: str,
    ttl_seconds: int = 60,
    metadata: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    """
    Atomically acquire or reclaim an expired database-backed lease for multi-process worker coordination.
    Guarantees mutual exclusion across separate OS processes or containers.
    Returns True if lease acquired or refreshed; False if currently held by an active worker.
    """
    now = datetime.now()
    now_iso = now.isoformat()
    expires_at_iso = (now + timedelta(seconds=ttl_seconds)).isoformat()
    meta = metadata or ""

    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        row = cursor.execute(
            "SELECT owner_token, expires_at FROM scheduler_leases WHERE resource_key = ?",
            (resource_key,),
        ).fetchone()

        if not row:
            # No existing lease -> acquire
            cursor.execute(
                """
                INSERT INTO scheduler_leases (resource_key, owner_token, acquired_at, expires_at, last_heartbeat_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (resource_key, owner_token, now_iso, expires_at_iso, now_iso, meta),
            )
            conn.commit()
            return True

        existing_token = row[0]
        existing_expires = row[1]

        # If same owner -> renew/extend
        if existing_token == owner_token:
            cursor.execute(
                """
                UPDATE scheduler_leases
                SET expires_at = ?, last_heartbeat_at = ?, metadata = ?
                WHERE resource_key = ? AND owner_token = ?
                """,
                (expires_at_iso, now_iso, meta, resource_key, owner_token),
            )
            conn.commit()
            return True

        # If existing lease expired -> crash recovery takeover
        try:
            exp_dt = datetime.fromisoformat(existing_expires)
            if now >= exp_dt:
                cursor.execute(
                    """
                    UPDATE scheduler_leases
                    SET owner_token = ?, acquired_at = ?, expires_at = ?, last_heartbeat_at = ?, metadata = ?
                    WHERE resource_key = ?
                    """,
                    (owner_token, now_iso, expires_at_iso, now_iso, meta, resource_key),
                )
                conn.commit()
                return True
        except Exception:
            # Malformed timestamp -> reclaim
            cursor.execute(
                """
                UPDATE scheduler_leases
                SET owner_token = ?, acquired_at = ?, expires_at = ?, last_heartbeat_at = ?, metadata = ?
                WHERE resource_key = ?
                """,
                (owner_token, now_iso, expires_at_iso, now_iso, meta, resource_key),
            )
            conn.commit()
            return True

        # Active unexpired lease held by another worker
        conn.commit()
        return False


def renew_scheduler_lease(
    resource_key: str,
    owner_token: str,
    ttl_seconds: int = 60,
    db_path: Optional[str] = None,
) -> bool:
    """
    Extend an existing lease if still held by the calling owner_token.
    """
    now = datetime.now()
    now_iso = now.isoformat()
    expires_at_iso = (now + timedelta(seconds=ttl_seconds)).isoformat()
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE scheduler_leases
            SET expires_at = ?, last_heartbeat_at = ?
            WHERE resource_key = ? AND owner_token = ? AND expires_at > ?
            """,
            (expires_at_iso, now_iso, resource_key, owner_token, now_iso),
        )
        conn.commit()
        return cursor.rowcount > 0


def release_scheduler_lease(
    resource_key: str,
    owner_token: str,
    db_path: Optional[str] = None,
) -> bool:
    """
    Safely release a lease only if the owner_token matches the current lease holder.
    Prevents a slow/delayed worker from releasing a lease reclaimed by another worker.
    """
    with get_db_connection(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM scheduler_leases WHERE resource_key = ? AND owner_token = ?",
            (resource_key, owner_token),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_scheduler_lease(
    resource_key: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Inspect active lease state for a specific resource key.
    """
    with get_db_connection(db_path) as conn:
        row = conn.execute(
            "SELECT resource_key, owner_token, acquired_at, expires_at, last_heartbeat_at, metadata FROM scheduler_leases WHERE resource_key = ?",
            (resource_key,),
        ).fetchone()
        if not row:
            return None
        return {
            "resource_key": row[0],
            "owner_token": row[1],
            "acquired_at": row[2],
            "expires_at": row[3],
            "last_heartbeat_at": row[4],
            "metadata": row[5],
        }


class StaleWorkerLeaseError(RuntimeError):
    """
    Raised when a worker attempts to commit sync results or job mutations after
    losing ownership of its database lease (lease fencing protection).
    """
    pass


def validate_lease_fencing(
    conn: sqlite3.Connection,
    resource_key: str,
    owner_token: str,
) -> bool:
    """
    Validate that owner_token currently holds an unexpired lease for resource_key within an active SQLite transaction.
    Guarantees that stale, delayed, or paused workers cannot commit mutations after lease loss.
    """
    row = conn.execute(
        "SELECT owner_token, expires_at FROM scheduler_leases WHERE resource_key = ?",
        (resource_key,),
    ).fetchone()
    if not row:
        return False
    current_token, expires_at_str = row[0], row[1]
    if current_token != owner_token:
        return False
    try:
        if datetime.now() >= datetime.fromisoformat(expires_at_str):
            return False
    except Exception:
        return False
    return True
