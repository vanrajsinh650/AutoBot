"""
REST API & SSE Event Stream Routes for AutoBot v2 Mission Control Dashboard.
Supports multi-user authentication, candidate profile management, job discovery,
deterministic matching, application preparation, and compliant application workflows.
"""

import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Set

from aiohttp import web
import yaml

from src.application.preparation import ApplicationPreparationService
from src.application.workflows import (
    AntiBotChallengeDetected,
    ExternalATSWorkflowManager,
    HumanApprovalRequiredError,
    LinkedInPolicyViolationError,
    LinkedInWorkflowManager,
)
from src.discovery.models import JobSourceConfig, NormalizedJob, SourceType
from src.discovery.registry import JobDiscoveryEngine
from src.matching.evaluator import JobFitEvaluator
from src.storage.auth import (
    authenticate_user,
    create_session,
    create_user,
    revoke_session,
    validate_session,
)
from src.storage.db import (
    DEFAULT_DB_PATH,
    end_session,
    get_candidate_profile,
    get_db_connection,
    get_job_preferences,
    get_resume_evidence,
    get_resume_versions,
    get_stats,
    init_db,
    is_already_applied,
    log_audit,
    save_application,
    save_candidate_profile,
    save_job_preferences,
    save_resume_evidence,
    save_resume_version,
    start_session,
)
from src.utils.config import get_config, get_env
from src.utils.logger import logger
from src.utils.security import delete_user_account_and_data, sanitize_for_logs


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_path(path_input: str | Path) -> Path:
    p = Path(path_input)
    if not p.is_absolute() and not p.exists() and (PROJECT_ROOT / p).exists():
        return PROJECT_ROOT / p
    return p


class AgentExecutionManager:
    """
    Manages background agent execution tasks and broadcasts live telemetry via SSE.
    """

    def __init__(self):
        self.active_task: Optional[asyncio.Task] = None
        self.is_running: bool = False
        self.current_node: str = "idle"
        self.subscribers: Set[web.StreamResponse] = set()
        self.recent_logs: List[Dict[str, Any]] = []

    def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        """Enqueue an event to all connected SSE clients with PII sanitization."""
        safe_data = sanitize_for_logs(data)
        payload = {
            "type": event_type,
            "data": safe_data,
            "timestamp": datetime.now().isoformat(),
        }
        self.recent_logs.append(payload)
        if len(self.recent_logs) > 200:
            self.recent_logs.pop(0)

        # Broadcast to active SSE streams
        for ws in list(self.subscribers):
            try:
                msg = f"event: {event_type}\ndata: {json.dumps(safe_data)}\n\n".encode("utf-8")
                async def _send(res=ws, m=msg):
                    try:
                        await res.write(m)
                    except Exception:
                        self.subscribers.discard(res)
                asyncio.create_task(_send())
            except Exception:
                self.subscribers.discard(ws)


execution_manager = AgentExecutionManager()


def get_current_user_id(request: web.Request, allow_fallback: bool = True) -> Optional[int]:
    """
    Extract user_id from session header/cookie.
    If allow_fallback is True, defaults to 1 for legacy backwards compatibility.
    If allow_fallback is False, returns None when unauthenticated.
    """
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token:
        token = request.cookies.get("auth_token") or request.query.get("token")

    if token:
        session = validate_session(token)
        if session:
            return session["user_id"]

    return 1 if allow_fallback else None


# ── Legacy & Dashboard Telemetry Handlers ──────────────────────────

async def get_status(request: web.Request) -> web.Response:
    """Return runtime agent state and system status."""
    cfg = get_config()
    env = get_env()
    user_id = get_current_user_id(request)

    resume_exists = _resolve_path(cfg.profile.resume_path).exists()
    session_exists = _resolve_path("data/session/linkedin_state.json").exists()
    db_stats = get_stats(user_id=user_id)
    db_stats["total"] = sum(db_stats.values())

    return web.json_response({
        "status": "running" if execution_manager.is_running else "idle",
        "current_node": execution_manager.current_node,
        "resume_found": resume_exists,
        "resume_path": cfg.profile.resume_path,
        "session_saved": session_exists,
        "llm_provider": env.llm_provider,
        "llm_model": env.llm_model,
        "qdrant_url": env.qdrant_url,
        "qdrant_collection": env.qdrant_collection,
        "stats": db_stats,
        "user_id": user_id,
    })


async def get_stats_handler(request: web.Request) -> web.Response:
    """Return aggregate application counts."""
    user_id = get_current_user_id(request)
    stats = get_stats(user_id=user_id)
    stats["total"] = sum(stats.values())
    return web.json_response(stats)


async def get_jobs(request: web.Request) -> web.Response:
    """Return paginated, filterable list of processed applications from SQLite scoped by user."""
    user_id = get_current_user_id(request)
    status_filter = request.query.get("status", "").strip().lower()
    search_query = request.query.get("q", "").strip().lower()
    limit = int(request.query.get("limit", "50"))
    offset = int(request.query.get("offset", "0"))

    init_db()
    with get_db_connection(DEFAULT_DB_PATH) as conn:
        query = "SELECT * FROM applications WHERE user_id = ?"
        params: List[Any] = [user_id]

        if status_filter:
            query += " AND status = ?"
            params.append(status_filter)

        if search_query:
            query += " AND (LOWER(job_title) LIKE ? OR LOWER(company) LIKE ?)"
            params.extend([f"%{search_query}%", f"%{search_query}%"])

        query += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()

        # Count total
        count_query = "SELECT COUNT(*) FROM applications WHERE user_id = ?"
        count_params: List[Any] = [user_id]
        if status_filter:
            count_query += " AND status = ?"
            count_params.append(status_filter)
        if search_query:
            count_query += " AND (LOWER(job_title) LIKE ? OR LOWER(company) LIKE ?)"
            count_params.extend([f"%{search_query}%", f"%{search_query}%"])

        total = conn.execute(count_query, count_params).fetchone()[0]

    jobs = [dict(row) for row in rows]
    return web.json_response({"total": total, "jobs": jobs})


async def get_config_handler(request: web.Request) -> web.Response:
    """Read and return config.yaml as structured JSON."""
    cfg_path = _resolve_path("config.yaml")
    if not cfg_path.exists():
        return web.json_response({"error": "config.yaml not found"}, status=404)

    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return web.json_response(data)


async def save_config_handler(request: web.Request) -> web.Response:
    """Update config.yaml with posted configuration values."""
    try:
        new_cfg = await request.json()
        cfg_path = _resolve_path("config.yaml")

        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(new_cfg, f, default_flow_style=False, sort_keys=False)

        from src.utils.config import get_config
        get_config.cache_clear()

        logger.info("[web]✓ Updated config.yaml via web dashboard[/web]")
        return web.json_response({"success": True})
    except Exception as e:
        logger.error(f"Error updating config: {e}")
        return web.json_response({"error": str(e)}, status=400)


async def get_profile_handler(request: web.Request) -> web.Response:
    """Extract and return candidate resume sections and vector memory telemetry."""
    user_id = get_current_user_id(request)
    profile = get_candidate_profile(user_id)

    cfg = get_config()
    resume_path = _resolve_path(cfg.profile.resume_path)

    sections_grouped: Dict[str, List[str]] = {}
    total_chunks = 0

    if resume_path.exists():
        from src.ingestion.resume_parser import parse_resume
        try:
            chunks = parse_resume(resume_path)
            total_chunks = len(chunks)
            for c in chunks:
                sec = c.section.value
                sections_grouped.setdefault(sec, []).append(c.content)
        except Exception:
            pass

    return web.json_response({
        "found": resume_path.exists() or (profile is not None),
        "path": str(resume_path),
        "total_chunks": total_chunks,
        "sections": sections_grouped,
        "candidate_profile": profile or {},
    })


async def upload_resume_handler(request: web.Request) -> web.Response:
    """Handle resume document upload with tenant isolation."""
    try:
        user_id = get_current_user_id(request)
        reader = await request.multipart()
        field = await reader.next()
        if not field or field.name != "file":
            return web.json_response({"error": "No file field uploaded in form data"}, status=400)

        filename = field.filename or "resume.pdf"
        ext = Path(filename).suffix.lower()
        if ext not in (".pdf", ".docx", ".doc", ".txt"):
            return web.json_response(
                {"error": f"Unsupported file format '{ext}'. Please upload a PDF, DOCX, or TXT file."},
                status=400,
            )

        # User-isolated storage directory
        user_storage = PROJECT_ROOT / "data" / "users" / str(user_id) / "resumes"
        user_storage.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_path = user_storage / f"resume_{timestamp_str}{ext}"

        # Also write to legacy data/resume/resume.pdf for backward compatibility
        legacy_dest = PROJECT_ROOT / "data" / "resume" / f"resume{ext}"
        legacy_dest.parent.mkdir(parents=True, exist_ok=True)

        size = 0
        content_bytes = bytearray()
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            content_bytes.extend(chunk)
            size += len(chunk)

        with open(dest_path, "wb") as f:
            f.write(content_bytes)
        with open(legacy_dest, "wb") as f:
            f.write(content_bytes)

        # Compute SHA-256
        import hashlib
        file_hash = hashlib.sha256(content_bytes).hexdigest()

        # Parse structured information
        chunks_count = 0
        sections_found: List[str] = []
        structured_data: Dict[str, Any] = {}

        if ext == ".pdf":
            try:
                from src.ingestion.resume_parser import parse_resume
                from src.ingestion.structured_resume import parse_structured_profile
                parsed_chunks = parse_resume(dest_path)
                chunks_count = len(parsed_chunks)
                sections_found = list({c.section.value for c in parsed_chunks})

                structured_data = parse_structured_profile(parsed_chunks)
                # Save into candidate profile
                save_candidate_profile(user_id, structured_data)

                # Save resume version
                v_id = save_resume_version(
                    user_id=user_id,
                    version_name=filename,
                    file_path=str(dest_path),
                    file_hash=file_hash,
                    parsed_data=structured_data,
                )

                # Save evidence chunks
                for c in parsed_chunks:
                    save_resume_evidence(
                        user_id=user_id,
                        resume_version_id=v_id,
                        section=c.section.value,
                        content=c.content,
                        metadata=c.metadata,
                    )
            except Exception as pe:
                logger.warning(f"Structured resume parsing error: {pe}")

        execution_manager.broadcast("log", {
            "level": "success",
            "message": f"Candidate resume uploaded: '{filename}' ({size} bytes, {chunks_count} chunks extracted)",
        })

        return web.json_response({
            "success": True,
            "filename": filename,
            "path": str(dest_path),
            "size_bytes": size,
            "chunks_count": chunks_count,
            "sections": sections_found,
            "structured_data": structured_data,
            "message": "Resume uploaded and indexed successfully!",
        })
    except Exception as e:
        logger.error(f"Error handling resume upload: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def start_run(request: web.Request) -> web.Response:
    """Trigger agent execution in a background asyncio task."""
    if execution_manager.is_running:
        return web.json_response({"error": "Agent is already running"}, status=409)

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    dry_run = body.get("dry_run", True)
    force_ingest = body.get("force_ingest", False)

    async def _execute():
        execution_manager.is_running = True
        execution_manager.current_node = "search"
        execution_manager.broadcast("status", {"state": "running", "node": "search"})

        try:
            cfg = get_config()
            env = get_env()

            from src.agent.graph import run_agent
            from src.ingestion.pipeline import ingest_profile

            if force_ingest:
                resume_file = _resolve_path(cfg.profile.resume_path)
                if resume_file.exists():
                    execution_manager.broadcast("log", {"level": "info", "message": "Starting profile ingestion..."})
                    await ingest_profile(cfg, env, force=True)
                else:
                    execution_manager.broadcast("log", {"level": "warning", "message": "No resume file found on disk; continuing in agile screening mode."})

            execution_manager.broadcast("log", {"level": "info", "message": f"Commencing agent execution (dry_run={dry_run})..."})
            await run_agent(cfg, env, dry_run=dry_run)
            execution_manager.broadcast("log", {"level": "success", "message": "Agent execution finished successfully."})

        except Exception as e:
            logger.error(f"Background agent execution error: {e}")
            execution_manager.broadcast("log", {"level": "error", "message": f"Execution error: {str(e)}"})
        finally:
            execution_manager.is_running = False
            execution_manager.current_node = "idle"
            execution_manager.broadcast("status", {"state": "idle", "node": "idle"})

    execution_manager.active_task = asyncio.create_task(_execute())
    return web.json_response({"success": True, "message": "Agent run started."})


async def stop_run(request: web.Request) -> web.Response:
    """Cancel the active background execution task."""
    if execution_manager.active_task and not execution_manager.active_task.done():
        execution_manager.active_task.cancel()
        execution_manager.is_running = False
        execution_manager.current_node = "idle"
        execution_manager.broadcast("log", {"level": "warning", "message": "Agent execution cancelled by user."})
        execution_manager.broadcast("status", {"state": "idle", "node": "idle"})
        return web.json_response({"success": True, "message": "Agent execution stopped."})

    return web.json_response({"error": "No active execution to stop"}, status=400)


async def logout_handler(request: web.Request) -> web.Response:
    """Clear session state and browser user data."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if token:
        revoke_session(token)

    session_file = _resolve_path("data/session/linkedin_state.json")
    user_data_dir = _resolve_path("data/session/user_data")

    cleared = False
    if session_file.exists():
        session_file.unlink()
        cleared = True
    if user_data_dir.exists():
        shutil.rmtree(user_data_dir, ignore_errors=True)
        cleared = True

    return web.json_response({
        "success": True,
        "cleared": cleared,
        "message": "Session cleared successfully.",
    })


async def sse_logs_stream(request: web.Request) -> web.StreamResponse:
    """Stream real-time server-sent events (SSE) to connected dashboard clients."""
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )
    await response.prepare(request)

    execution_manager.subscribers.add(response)
    try:
        # Send initial backlog
        for item in execution_manager.recent_logs[-20:]:
            msg = f"event: {item['type']}\ndata: {json.dumps(item['data'])}\n\n"
            await response.write(msg.encode("utf-8"))

        init_status = {
            "state": "running" if execution_manager.is_running else "idle",
            "node": execution_manager.current_node,
        }
        await response.write(f"event: status\ndata: {json.dumps(init_status)}\n\n".encode("utf-8"))

        while True:
            await asyncio.sleep(15)
            await response.write(b": ping\n\n")

    except (asyncio.CancelledError, ConnectionResetError, Exception):
        pass
    finally:
        execution_manager.subscribers.discard(response)

    return response


auth_logout_handler = logout_handler

async def auth_register_handler(request: web.Request) -> web.Response:
    """Register a new user account."""
    try:
        body = await request.json()
        email = body.get("email", "")
        password = body.get("password", "")

        success, user_id, msg = create_user(email=email, password=password)
        if not success:
            return web.json_response({"error": msg}, status=400)

        token = create_session(user_id=user_id, email=email)
        return web.json_response({
            "success": True,
            "token": token,
            "user": {"id": user_id, "email": email},
            "message": msg,
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def auth_login_handler(request: web.Request) -> web.Response:
    """Authenticate existing user credentials."""
    try:
        body = await request.json()
        email = body.get("email", "")
        password = body.get("password", "")

        success, user_data, msg = authenticate_user(email=email, password=password)
        if not success or not user_data:
            return web.json_response({"error": msg}, status=401)

        token = create_session(user_id=user_data["id"], email=user_data["email"])
        return web.json_response({
            "success": True,
            "token": token,
            "user": user_data,
            "message": msg,
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def auth_me_handler(request: web.Request) -> web.Response:
    """Get current authenticated user information."""
    user_id = get_current_user_id(request)
    profile = get_candidate_profile(user_id)
    return web.json_response({
        "authenticated": True,
        "user_id": user_id,
        "profile": profile,
    })


# ── Candidate Profile & Preferences Handlers ────────────────────────

async def get_candidate_profile_handler(request: web.Request) -> web.Response:
    """Get structured candidate profile."""
    user_id = get_current_user_id(request)
    profile = get_candidate_profile(user_id) or {}
    return web.json_response(profile)


async def update_candidate_profile_handler(request: web.Request) -> web.Response:
    """Allow user to update and correct extracted profile data."""
    try:
        user_id = get_current_user_id(request)
        data = await request.json()
        save_candidate_profile(user_id, data)
        return web.json_response({"success": True, "message": "Candidate profile updated."})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def get_preferences_handler(request: web.Request) -> web.Response:
    """Get candidate job search preferences."""
    user_id = get_current_user_id(request)
    prefs = get_job_preferences(user_id)
    return web.json_response(prefs)


async def update_preferences_handler(request: web.Request) -> web.Response:
    """Update candidate job search preferences."""
    try:
        user_id = get_current_user_id(request)
        data = await request.json()
        save_job_preferences(user_id, data)
        return web.json_response({"success": True, "message": "Job preferences saved."})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def get_resume_versions_handler(request: web.Request) -> web.Response:
    """List resume versions for current user."""
    user_id = get_current_user_id(request)
    versions = get_resume_versions(user_id)
    return web.json_response({"versions": versions})


# ── Job Discovery Handlers ──────────────────────────────────────────

async def get_sources_handler(request: web.Request) -> web.Response:
    """List registered job sources."""
    engine = JobDiscoveryEngine()
    sources = engine.get_sources()
    return web.json_response({"sources": [s.model_dump() for s in sources]})


async def add_source_handler(request: web.Request) -> web.Response:
    """Register a new job source."""
    try:
        data = await request.json()
        src = JobSourceConfig(**data)
        engine = JobDiscoveryEngine()
        engine.register_source(src)
        return web.json_response({"success": True, "source": src.model_dump()})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def discover_jobs_handler(request: web.Request) -> web.Response:
    """Run discovery across sources, normalize and deduplicate."""
    try:
        engine = JobDiscoveryEngine()
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        keywords = body.get("keywords")
        jobs = await engine.discover_jobs(keywords=keywords)
        return web.json_response({
            "success": True,
            "discovered_count": len(jobs),
            "jobs": [j.model_dump() for j in jobs],
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def import_job_handler(request: web.Request) -> web.Response:
    """User-submitted job description import (including LinkedIn)."""
    try:
        user_id = get_current_user_id(request)
        data = await request.json()
        title = data.get("title", "").strip()
        company = data.get("company", "").strip()
        description = data.get("description", "").strip()
        app_url = data.get("application_url", "").strip()

        if not title or not company or not description:
            return web.json_response({"error": "Title, company, and description are required."}, status=400)

        # Route via LinkedInWorkflowManager if URL is LinkedIn, else manual
        manager = LinkedInWorkflowManager()
        job = manager.import_job(
            user_id=user_id,
            title=title,
            company=company,
            description=description,
            application_url=app_url,
            location=data.get("location", ""),
            salary_info=data.get("salary_info", ""),
        )

        return web.json_response({
            "success": True,
            "job": job.model_dump(),
            "message": "Job imported successfully without automated scraping.",
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def get_discovered_jobs_handler(request: web.Request) -> web.Response:
    """List jobs available in the repository database with filters."""
    init_db()
    limit = int(request.query.get("limit", "50"))
    offset = int(request.query.get("offset", "0"))
    query = request.query.get("q", "").strip().lower()
    source = request.query.get("source", "").strip().lower()

    with get_db_connection(DEFAULT_DB_PATH) as conn:
        sql = "SELECT * FROM jobs WHERE 1=1"
        params = []
        if query:
            sql += " AND (LOWER(title) LIKE ? OR LOWER(company) LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        if source:
            sql += " AND LOWER(source_name) = ?"
            params.append(source)

        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()

    return web.json_response({"jobs": [dict(r) for r in rows]})


# ── Matching & Eligibility Handlers ─────────────────────────────────

async def evaluate_job_handler(request: web.Request) -> web.Response:
    """Evaluate job match and eligibility deterministically."""
    try:
        user_id = get_current_user_id(request)
        data = await request.json()
        job_id = data.get("job_id")
        stable_id = data.get("stable_id")

        with get_db_connection(DEFAULT_DB_PATH) as conn:
            if stable_id:
                row = conn.execute("SELECT * FROM jobs WHERE stable_id = ?", (stable_id,)).fetchone()
            else:
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

            if not row:
                return web.json_response({"error": "Job not found in database"}, status=404)

            job = NormalizedJob(
                stable_id=row["stable_id"],
                source_name=row["source_name"],
                source_type=SourceType.MANUAL,
                title=row["title"],
                company=row["company"],
                description=row["description"],
                employment_type=row["employment_type"],
                location=row["location"],
                country=row["country"],
                is_remote=bool(row["is_remote"]),
                salary_info=row["salary_info"],
                publication_date=row["publication_date"],
                application_url=row["application_url"],
            )

        evaluator = JobFitEvaluator()
        result = evaluator.evaluate_job(user_id=user_id, job=job)
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ── Application Preparation & Workflows Handlers ────────────────────

async def prepare_application_handler(request: web.Request) -> web.Response:
    """Prepare application pack for human candidate review."""
    try:
        user_id = get_current_user_id(request)
        data = await request.json()
        stable_id = data.get("stable_id")

        with get_db_connection(DEFAULT_DB_PATH) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE stable_id = ?", (stable_id,)).fetchone()
            if not row:
                return web.json_response({"error": "Job not found"}, status=404)

            job = NormalizedJob(
                stable_id=row["stable_id"],
                source_name=row["source_name"],
                source_type=SourceType.MANUAL,
                title=row["title"],
                company=row["company"],
                description=row["description"],
                employment_type=row["employment_type"],
                location=row["location"],
                country=row["country"],
                is_remote=bool(row["is_remote"]),
                salary_info=row["salary_info"],
                publication_date=row["publication_date"],
                application_url=row["application_url"],
            )

        prep = ApplicationPreparationService()
        pack = prep.prepare_application_pack(user_id=user_id, job=job)
        return web.json_response(pack)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def approve_application_pack_handler(request: web.Request) -> web.Response:
    """Record candidate review and explicit approval of an application pack."""
    try:
        user_id = get_current_user_id(request)
        data = await request.json()
        pack_id = int(data.get("pack_id", 0))
        approved = bool(data.get("approved", True))

        prep = ApplicationPreparationService()
        ok = prep.set_user_approval(user_id=user_id, pack_id=pack_id, approved=approved)
        if not ok:
            return web.json_response({"error": "Pack not found or not owned by user"}, status=404)

        return web.json_response({"success": True, "user_approved": approved})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def submit_external_application_handler(request: web.Request) -> web.Response:
    """Execute assisted application for authorized external ATS."""
    try:
        user_id = get_current_user_id(request)
        data = await request.json()
        pack_id = data.get("pack_id")
        dry_run = bool(data.get("dry_run", False))

        with get_db_connection(DEFAULT_DB_PATH) as conn:
            pack_row = conn.execute("SELECT * FROM application_packs WHERE id = ? AND user_id = ?", (pack_id, user_id)).fetchone()
            if not pack_row:
                return web.json_response({"error": "Application pack not found"}, status=404)

            pack_dict = dict(pack_row)
            job_row = conn.execute("SELECT * FROM jobs WHERE id = ?", (pack_dict["job_id"],)).fetchone()
            if not job_row:
                return web.json_response({"error": "Associated job record not found"}, status=404)

            job = NormalizedJob(
                stable_id=job_row["stable_id"],
                source_name=job_row["source_name"],
                source_type=SourceType.MANUAL,
                title=job_row["title"],
                company=job_row["company"],
                description=job_row["description"],
                employment_type=job_row["employment_type"],
                location=job_row["location"],
                country=job_row["country"],
                is_remote=bool(job_row["is_remote"]),
                salary_info=job_row["salary_info"],
                publication_date=job_row["publication_date"],
                application_url=job_row["application_url"],
            )

        manager = ExternalATSWorkflowManager()
        result = manager.execute_assisted_application(
            user_id=user_id,
            job=job,
            pack=pack_dict,
            dry_run=dry_run,
        )
        return web.json_response(result)
    except (HumanApprovalRequiredError, LinkedInPolicyViolationError, AntiBotChallengeDetected, PermissionError) as pe:
        return web.json_response({"error": str(pe)}, status=403)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def confirm_linkedin_submission_handler(request: web.Request) -> web.Response:
    """Record verified candidate manual submission on LinkedIn."""
    try:
        user_id = get_current_user_id(request)
        data = await request.json()
        stable_id = data.get("stable_id", "")
        confirmed = bool(data.get("confirmed", True))
        notes = data.get("notes", "")

        manager = LinkedInWorkflowManager()
        ok = manager.record_submission(
            user_id=user_id,
            job_stable_id=stable_id,
            user_confirmed=confirmed,
            notes=notes,
        )
        if not ok:
            return web.json_response({"error": "Failed to record submission: confirmation required or job missing."}, status=400)

        return web.json_response({"success": True, "message": "Application recorded in tracker as submitted."})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ── Tracker & Privacy Handlers ──────────────────────────────────────

async def get_tracker_handler(request: web.Request) -> web.Response:
    """Return applications grouped by lifecycle status."""
    user_id = get_current_user_id(request)
    init_db()
    with get_db_connection(DEFAULT_DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.job_id, e.event_type, e.status, e.user_confirmed, e.created_at,
                   j.title, j.company, j.location, j.application_url, j.stable_id
            FROM application_events e
            JOIN jobs j ON e.job_id = j.id
            WHERE e.user_id = ?
            ORDER BY e.id DESC
            """,
            (user_id,),
        ).fetchall()

    return web.json_response({"events": [dict(r) for r in rows]})


async def update_application_status_handler(request: web.Request) -> web.Response:
    """Update application lifecycle status (e.g. interview, offer, rejected) in tracker."""
    try:
        user_id = get_current_user_id(request)
        data = await request.json()
        job_id = str(data.get("job_id") or data.get("stable_id") or "").strip()
        new_status = str(data.get("status") or "").strip().lower()
        notes = str(data.get("notes") or "").strip()

        valid_statuses = {
            "discovered", "evaluated", "prepared", "submitted",
            "interview", "offer", "rejected", "applied", "dry_run", "skipped", "failed"
        }
        if new_status not in valid_statuses:
            return web.json_response(
                {"error": f"Invalid status '{new_status}'. Allowed: {sorted(list(valid_statuses))}"},
                status=400,
            )

        if not job_id:
            return web.json_response({"error": "job_id or stable_id is required."}, status=400)

        from src.storage.db import update_application_status
        ok = update_application_status(
            user_id=user_id,
            job_id_or_stable_id=job_id,
            new_status=new_status,
            notes=notes,
        )
        if not ok:
            return web.json_response({"error": "Application or job record not found."}, status=404)

        return web.json_response({
            "success": True,
            "job_id": job_id,
            "status": new_status,
            "message": f"Application status successfully transitioned to '{new_status}'.",
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def download_application_pack_handler(request: web.Request) -> web.Response:
    """Download compiled application pack as plain text for candidate ease of use."""
    try:
        user_id = get_current_user_id(request)
        pack_id = int(request.match_info.get("pack_id") or request.query.get("pack_id") or 0)

        init_db()
        with get_db_connection(DEFAULT_DB_PATH) as conn:
            row = conn.execute("SELECT * FROM application_packs WHERE id = ? AND user_id = ?", (pack_id, user_id)).fetchone()
            if not row:
                return web.json_response({"error": "Application pack not found"}, status=404)

            d = dict(row)
            job_row = conn.execute("SELECT * FROM jobs WHERE id = ?", (d["job_id"],)).fetchone()
            company = job_row["company"] if job_row else "Job"
            title = job_row["title"] if job_row else "Role"

        # Format questions nicely
        q_drafts = []
        raw_q = []
        try:
            raw_q = json.loads(d.get("question_drafts", "[]"))
            for q in raw_q:
                q_drafts.append(f"Q: {q.get('question')}\nA: {q.get('draft_answer')}\n")
        except Exception:
            q_drafts = [str(d.get("question_drafts", ""))]

        if request.query.get("format") == "json" or "application/json" in request.headers.get("Accept", ""):
            payload = {
                "id": pack_id,
                "role": title,
                "company": company,
                "created_at": d.get("created_at", ""),
                "tailored_resume_summary": d.get("tailored_resume_summary", ""),
                "cover_letter": d.get("cover_letter", ""),
                "question_drafts": raw_q,
                "job_match_explanation": d.get("job_match_explanation", ""),
            }
            return web.json_response(
                payload,
                headers={"Content-Disposition": f'attachment; filename="autobot_{company}_{pack_id}.json"'},
            )

        text_content = (
            f"=== AUTOBOT APPLICATION PACK ===\n"
            f"Role: {title}\n"
            f"Company: {company}\n"
            f"Date Prepared: {d.get('created_at', '')}\n\n"
            f"--- 1. TAILORED RESUME SUMMARY ---\n{d.get('tailored_resume_summary', '')}\n\n"
            f"--- 2. COVER LETTER ---\n{d.get('cover_letter', '')}\n\n"
            f"--- 3. SCREENING QUESTION DRAFTS ---\n{''.join(q_drafts)}\n"
            f"--- 4. JOB MATCH EXPLANATION ---\n{d.get('job_match_explanation', '')}\n"
        )

        return web.Response(
            text=text_content,
            content_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="autobot_{company}_{pack_id}.txt"'},
        )
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def delete_account_handler(request: web.Request) -> web.Response:
    """Erase user profile, files, and tracker records (GDPR erasure). Requires authenticated session."""
    try:
        user_id = get_current_user_id(request, allow_fallback=False)
        if not user_id:
            return web.json_response({"error": "Authentication required to delete account."}, status=401)
        if user_id == 1:
            return web.json_response({"error": "Legacy system account cannot be erased."}, status=403)

        ok = delete_user_account_and_data(user_id=user_id)
        if ok:
            return web.json_response({"success": True, "message": "All personal data erased permanently."})
        return web.json_response({"error": "Failed to delete account"}, status=500)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def get_audit_logs_handler(request: web.Request) -> web.Response:
    """List security audit trail for user."""
    user_id = get_current_user_id(request)
    init_db()
    with get_db_connection(DEFAULT_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs WHERE user_id = ? ORDER BY id DESC LIMIT 100",
            (user_id,),
        ).fetchall()
    return web.json_response({"audit_logs": [dict(r) for r in rows]})
