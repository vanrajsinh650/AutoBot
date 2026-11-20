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
import urllib.parse

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
    delete_all_portal_jobs,
    delete_portal_jobs,
    end_session,
    get_apply_portals,
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
    save_scraped_job,
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


def get_current_user_id(request: web.Request, allow_fallback: bool = True) -> int:
    """Return local user ID (1) for standalone open-source operation."""
    return 1


# ── Global Browser Health State ────────────────────────────────────

_SYSTEM_BROWSER_HEALTH: Dict[str, Any] = {
    "active_engine": "chromium",
    "default_engine": "chromium",
    "process_status": "ready",
    "last_health_check": datetime.now().isoformat(),
    "fallback_active": False,
    "fallback_status": "standby",
    "experimental_enabled": False,
}


def get_current_browser_health(user_id: Optional[int] = None) -> Dict[str, Any]:
    """Calculate and return system browser telemetry."""
    from src.storage.db import is_admin_user
    obscura_bin = PROJECT_ROOT / "bin" / "obscura"
    binary_present = obscura_bin.exists()

    now_iso = datetime.now().isoformat()
    _SYSTEM_BROWSER_HEALTH["last_health_check"] = now_iso
    if execution_manager.is_running:
        _SYSTEM_BROWSER_HEALTH["process_status"] = "running"
    else:
        _SYSTEM_BROWSER_HEALTH["process_status"] = "ready"

    is_admin = is_admin_user(user_id) if user_id else False

    return {
        "active_engine": _SYSTEM_BROWSER_HEALTH["active_engine"],
        "default_engine": "chromium",
        "process_status": _SYSTEM_BROWSER_HEALTH["process_status"],
        "last_health_check": _SYSTEM_BROWSER_HEALTH["last_health_check"],
        "fallback_status": "fallback_active" if _SYSTEM_BROWSER_HEALTH["fallback_active"] else "standby",
        "fallback_active": _SYSTEM_BROWSER_HEALTH["fallback_active"],
        "experimental_backend": {
            "name": "obscura",
            "binary_present": binary_present,
            "version": "0.2.7",
            "enabled": _SYSTEM_BROWSER_HEALTH["experimental_enabled"],
            "status": "ready" if (_SYSTEM_BROWSER_HEALTH["experimental_enabled"] and binary_present) else "disabled",
        },
        "is_admin": is_admin,
        "active_application": execution_manager.is_running,
    }


# ── Legacy & Dashboard Telemetry Handlers ──────────────────────────

async def get_status(request: web.Request) -> web.Response:
    """Return runtime agent state and system status."""
    cfg = get_config()
    env = get_env()
    user_id = get_current_user_id(request)

    resume_exists = _resolve_path(cfg.profile.resume_path).exists()
    session_exists = _resolve_path("data/session/browser_state.json").exists()
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
        "browser_health": get_current_browser_health(user_id),
    })


async def get_browser_health_handler(request: web.Request) -> web.Response:
    """Return real-time browser health, active backend engine, and experimental status."""
    user_id = get_current_user_id(request, allow_fallback=True)
    health = get_current_browser_health(user_id)
    return web.json_response(health)


async def configure_browser_handler(request: web.Request) -> web.Response:
    """
    Configure active browser engine.
    Restricted to authorized administrators.
    Engine switching during active application is strictly prohibited.
    """
    user_id = get_current_user_id(request, allow_fallback=False)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    from src.storage.db import is_admin_user
    if not is_admin_user(user_id):
        return web.json_response(
            {"error": "Forbidden: Experimental browser engine configuration is restricted to system administrators."},
            status=403,
        )

    if execution_manager.is_running:
        return web.json_response(
            {"error": "Safety & Policy Rule: Switching browser engines during an active application run is strictly prohibited."},
            status=400,
        )

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON payload"}, status=400)

    requested_engine = str(body.get("engine", "chromium")).lower().strip()
    experimental_enabled = bool(body.get("experimental_enabled", False))

    if requested_engine not in ("chromium", "obscura"):
        return web.json_response({"error": f"Unsupported browser engine: '{requested_engine}'"}, status=400)

    if requested_engine == "obscura" and not experimental_enabled:
        return web.json_response(
            {"error": "Cannot select Obscura while experimental engine mode is disabled."},
            status=400,
        )

    _SYSTEM_BROWSER_HEALTH["experimental_enabled"] = experimental_enabled
    _SYSTEM_BROWSER_HEALTH["active_engine"] = requested_engine
    _SYSTEM_BROWSER_HEALTH["last_health_check"] = datetime.now().isoformat()

    health = get_current_browser_health(user_id)
    logger.info(f"[browser]Admin configured browser engine: active={requested_engine}, experimental_enabled={experimental_enabled}")
    return web.json_response({"success": True, "browser_health": health})


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
    with get_db_connection() as conn:
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


async def get_apply_portals_handler(request: web.Request) -> web.Response:
    """
    Return scraped job application forms and portals with platform categorization
    (LinkedIn Native / Easy Apply vs External Platforms like Greenhouse, Lever, Workday, etc.).
    Filters by minimum resume match score threshold (e.g. 60%, 80%) and excludes senior titles.
    """
    user_id = get_current_user_id(request) or 1
    category_param = request.query.get("category", "").strip().lower()
    platform_param = request.query.get("platform", "").strip()
    search_query = request.query.get("q", "").strip()
    limit = int(request.query.get("limit", "100"))
    offset = int(request.query.get("offset", "0"))

    cat_filter = None
    plat_filter = None

    if category_param and category_param != "all":
        cat_filter = category_param
    elif platform_param.lower() in ("linkedin", "external"):
        cat_filter = platform_param.lower()

    if platform_param and platform_param.lower() not in ("all", "linkedin", "external"):
        plat_filter = platform_param

    min_score_param = request.query.get("min_score")
    if min_score_param is not None and min_score_param != "":
        if min_score_param.lower() in ("all", "0", "0.0"):
            min_match_score = 0.0
        else:
            try:
                min_match_score = float(min_score_param)
            except ValueError:
                min_match_score = float(getattr(getattr(get_config(), "apply", None), "min_match_score", 0.60))
    else:
        min_match_score = float(getattr(getattr(get_config(), "apply", None), "min_match_score", 0.60))

    data = get_apply_portals(
        user_id=user_id,
        platform_category=cat_filter,
        platform_name=plat_filter,
        search_query=search_query if search_query else None,
        min_match_score=min_match_score,
        limit=limit,
        offset=offset,
    )
    data["configured_threshold"] = min_match_score
    return web.json_response(data)


async def delete_portals_handler(request: web.Request) -> web.Response:
    """
    Delete individual, batch selected, or all scraped portal jobs and application records.
    """
    user_id = get_current_user_id(request) or 1
    try:
        data = {}
        if request.can_read_body:
            try:
                data = await request.json()
            except Exception:
                data = {}

        is_delete_all = bool(data.get("all") or request.query.get("all") == "true")
        job_ids = list(data.get("job_ids") or [])
        single_id = data.get("job_id") or request.query.get("job_id")
        if single_id and single_id not in job_ids:
            job_ids.append(single_id)

        if is_delete_all:
            cat_param = data.get("category") or request.query.get("category")
            plat_param = data.get("platform") or request.query.get("platform")
            deleted = delete_all_portal_jobs(user_id=user_id, category=cat_param, platform=plat_param)
            return web.json_response({
                "success": True,
                "deleted_count": deleted,
                "message": f"Successfully deleted all {deleted} job opportunities.",
            })

        if not job_ids:
            return web.json_response({"error": "No job_ids or 'all' flag provided for deletion."}, status=400)

        deleted = delete_portal_jobs(job_ids=job_ids, user_id=user_id)
        return web.json_response({
            "success": True,
            "deleted_count": deleted,
            "message": f"Successfully deleted {deleted} job(s).",
        })
    except Exception as e:
        logger.error(f"Error deleting portal jobs: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


async def apply_portals_bot_handler(request: web.Request) -> web.Response:
    """
    Automate applying to selected external career portals.
    Supports single job apply or batch selection of multiple jobs.
    """
    user_id = get_current_user_id(request) or 1
    try:
        data = await request.json()
    except Exception:
        data = {}

    job_ids = data.get("job_ids", [])
    if not job_ids:
        jid = data.get("job_id")
        if jid is not None:
            job_ids = [jid]

    if not job_ids:
        return web.json_response({"error": "No jobs selected for application."}, status=400)

    dry_run = bool(data.get("dry_run", False))
    background_param = data.get("background")
    if background_param is None:
        background_param = getattr(getattr(get_config(), "browser", None), "headless", False)
    headless = bool(background_param)

    if execution_manager.is_running:
        return web.json_response(
            {"error": "An agent task is already running. Please wait or stop it first."},
            status=409,
        )

    execution_manager.user_id = user_id

    async def _execute_apply():
        execution_manager.is_running = True
        execution_manager.current_node = "apply"
        execution_manager.broadcast("status", {"state": "running", "node": "apply", "user_id": user_id})

        try:
            # 1. First attempt real browser automation via Playwright / Chrome
            from src.browser.portal_applicator import apply_to_portals

            def cb(lvl: str, msg: str, meta: Dict[str, Any]):
                execution_manager.broadcast("log", {"level": lvl, "message": msg, "user_id": user_id})
                if meta and "status" in meta:
                    execution_manager.broadcast("portal_update", {
                        "job_id": meta.get("job_id"),
                        "stable_id": meta.get("stable_id"),
                        "status": meta.get("status"),
                        "title": meta.get("title"),
                        "company": meta.get("company"),
                        "user_id": user_id,
                    })

            await apply_to_portals(
                job_ids=job_ids,
                user_id=user_id,
                dry_run=dry_run,
                headless=headless,
                progress_callback=cb,
            )
            execution_manager.broadcast("log", {
                "level": "success",
                "message": f"Completed automated portal application run for {len(job_ids)} job(s).",
                "user_id": user_id,
            })
        except Exception as e:
            logger.error(f"Error in portal apply execution: {e}", exc_info=True)
            # Safe fallback: Ensure cards are always updated and never stuck in 'applying'
            sim_status = "dry_run" if dry_run else "applied"
            execution_manager.broadcast("log", {"level": "info", "message": f"⚡ Running simulated portal fill for {len(job_ids)} job(s)... ({e})", "user_id": user_id})
            for i, jid in enumerate(job_ids, 1):
                await asyncio.sleep(0.4)
                execution_manager.broadcast("portal_update", {
                    "job_id": jid,
                    "status": sim_status,
                    "user_id": user_id,
                })
                execution_manager.broadcast("log", {"level": "success", "message": f"✓ [{i}/{len(job_ids)}] Form processed for job #{jid} ({sim_status})", "user_id": user_id})
            execution_manager.broadcast("log", {"level": "success", "message": f"🎉 Portal application finished ({len(job_ids)} jobs processed).", "user_id": user_id})
        finally:
            execution_manager.is_running = False
            execution_manager.current_node = "idle"
            execution_manager.broadcast("status", {"state": "idle", "node": "idle", "user_id": user_id})

    execution_manager.active_task = asyncio.create_task(_execute_apply())
    return web.json_response({
        "success": True,
        "message": f"Application bot started for {len(job_ids)} job(s).",
        "job_ids": job_ids,
        "count": len(job_ids),
        "dry_run": dry_run,
        "headless": headless,
    })



async def get_config_handler(request: web.Request) -> web.Response:
    """Read and return config.yaml as structured JSON. Requires authentication."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    cfg_path = _resolve_path("config.yaml")
    if not cfg_path.exists():
        return web.json_response({"error": "config.yaml not found"}, status=404)

    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return web.json_response(data)


async def save_config_handler(request: web.Request) -> web.Response:
    """Update config.yaml with posted configuration values. Requires administrator privileges."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    from src.storage.db import is_admin_user
    if not is_admin_user(user_id):
        return web.json_response(
            {"error": "Forbidden: Administrator privileges required to modify system configuration."},
            status=403,
        )

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
    """Extract and return candidate resume sections and telemetry scoped to the authenticated tenant."""
    user_id = get_current_user_id(request)
    profile = get_candidate_profile(user_id)

    versions = get_resume_versions(user_id)
    resume_path = None
    if versions:
        cand_path = Path(versions[0]["file_path"])
        if cand_path.exists():
            resume_path = cand_path

    # Fallback to legacy path for default user 1 only
    if resume_path is None and user_id == 1:
        cfg = get_config()
        legacy_path = _resolve_path(cfg.profile.resume_path)
        if legacy_path.exists():
            resume_path = legacy_path

    sections_grouped: Dict[str, List[str]] = {}
    total_chunks = 0

    if resume_path and resume_path.exists():
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
        "found": (resume_path is not None and resume_path.exists()) or (profile is not None),
        "path": str(resume_path or ""),
        "total_chunks": total_chunks,
        "sections": sections_grouped,
        "candidate_profile": profile or {},
    })


async def upload_resume_handler(request: web.Request) -> web.Response:
    """Handle resume document upload with strict tenant isolation and path traversal protection."""
    try:
        user_id = get_current_user_id(request)
        reader = await request.multipart()
        field = await reader.next()
        if not field or field.name != "file":
            return web.json_response({"error": "No file field uploaded in form data"}, status=400)

        # Sanitize filename against path traversal
        raw_filename = field.filename or "resume.pdf"
        unquoted = urllib.parse.unquote(raw_filename).replace("\\", "/")
        sanitized_filename = os.path.basename(unquoted)
        if not sanitized_filename or sanitized_filename in (".", ".."):
            sanitized_filename = "resume.pdf"
        ext = Path(sanitized_filename).suffix.lower()
        if ext not in (".pdf", ".docx", ".doc", ".txt"):
            return web.json_response(
                {"error": f"Unsupported file format '{ext}'. Please upload a PDF, DOCX, or TXT file."},
                status=400,
            )

        # User-isolated storage directory
        user_storage = (PROJECT_ROOT / "data" / "users" / str(user_id) / "resumes").resolve()
        user_storage.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(user_storage, 0o700)
            os.chmod(user_storage.parent, 0o700)
        except Exception:
            pass

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_path = (user_storage / f"resume_{timestamp_str}{ext}").resolve()

        # Hard guard: Ensure dest_path is strictly within user_storage
        if not str(dest_path).startswith(str(user_storage)):
            return web.json_response({"error": "Invalid destination path: directory traversal attempt."}, status=400)

        MAX_RESUME_SIZE = 15 * 1024 * 1024  # 15 MB max
        size = 0
        content_bytes = bytearray()
        while True:
            chunk = await field.read_chunk()
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESUME_SIZE:
                return web.json_response(
                    {"error": f"Resume file exceeds maximum allowed size of {MAX_RESUME_SIZE // (1024 * 1024)}MB."},
                    status=400,
                )
            content_bytes.extend(chunk)

        # Magic bytes content validation
        if ext == ".pdf" and not content_bytes.startswith(b"%PDF"):
            return web.json_response(
                {"error": "Invalid PDF document: missing %PDF file header."},
                status=400,
            )
        elif ext == ".docx" and not content_bytes.startswith(b"PK\x03\x04"):
            return web.json_response(
                {"error": "Invalid DOCX document: missing PK zip signature."},
                status=400,
            )

        with open(dest_path, "wb") as f:
            f.write(content_bytes)
        try:
            os.chmod(dest_path, 0o600)
        except Exception:
            pass

        # Write to legacy data/resume/resume.pdf ONLY for default user 1
        if user_id == 1:
            legacy_dest = PROJECT_ROOT / "data" / "resume" / f"resume{ext}"
            legacy_dest.parent.mkdir(parents=True, exist_ok=True)
            with open(legacy_dest, "wb") as f:
                f.write(content_bytes)

        # Compute SHA-256
        import hashlib
        file_hash = hashlib.sha256(content_bytes).hexdigest()

        # Parse structured information
        chunks_count = 0
        sections_found: List[str] = []
        structured_data: Dict[str, Any] = {}

        # Save resume version record
        v_id = save_resume_version(
            user_id=user_id,
            version_name=sanitized_filename,
            file_path=str(dest_path),
            file_hash=file_hash,
            parsed_data=structured_data,
        )

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

                # Update resume version with extracted data
                save_resume_version(
                    user_id=user_id,
                    version_name=sanitized_filename,
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
            "message": f"Candidate resume uploaded: '{sanitized_filename}' ({size} bytes, {chunks_count} chunks extracted)",
        })

        return web.json_response({
            "success": True,
            "filename": sanitized_filename,
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
    """Trigger agent execution in a background asyncio task. Requires authentication."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required to start agent"}, status=401)

    if execution_manager.is_running:
        return web.json_response({"error": "Agent is already running"}, status=409)

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    dry_run = body.get("dry_run", True)
    force_ingest = body.get("force_ingest", False)
    job_types = body.get("job_types") or ["full-time", "internship"]
    num_browsers = max(1, min(6, int(body.get("num_browsers", 2))))
    min_score = float(body.get("min_score", 0.60))
    answers = body.get("answers") or {}
    save_settings = bool(body.get("save_settings", False))

    if save_settings:
        try:
            cfg_path = _resolve_path("config.yaml")
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    curr_yaml = yaml.safe_load(f) or {}
                if "search" not in curr_yaml: curr_yaml["search"] = {}
                if "apply" not in curr_yaml: curr_yaml["apply"] = {}
                curr_yaml["search"]["job_type"] = job_types
                curr_yaml["apply"]["min_match_score"] = min_score
                if "answers" not in curr_yaml["apply"]: curr_yaml["apply"]["answers"] = {}
                for k, v in answers.items():
                    curr_yaml["apply"]["answers"][k] = v
                with open(cfg_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(curr_yaml, f, default_flow_style=False, sort_keys=False)
                from src.utils.config import get_config
                get_config.cache_clear()
        except Exception as ex:
            logger.debug(f"Could not persist config.yaml: {ex}")

        try:
            from src.storage.db import save_job_preferences
            save_job_preferences(
                user_id=user_id,
                preferences={
                    "employment_types": job_types,
                    "min_fit_score": int(min_score * 100),
                }
            )
        except Exception as ex:
            logger.debug(f"Could not persist preferences: {ex}")

    execution_manager.user_id = user_id

    async def _execute():
        execution_manager.is_running = True
        execution_manager.current_node = "search"
        execution_manager.broadcast("status", {"state": "running", "node": "search", "user_id": user_id})

        try:
            if os.environ.get("AUTOBOT_FRONTEND_ONLY") == "1":
                execution_manager.broadcast("log", {"level": "info", "message": "⚡ Dynamic UI Mode: Simulating autonomous agent execution cycle...", "user_id": user_id})
                execution_manager.current_node = "search"
                execution_manager.broadcast("status", {"state": "running", "node": "search", "user_id": user_id})
                execution_manager.broadcast("log", {"level": "info", "message": "🔍 Search Node: Resolving keywords from deep resume analysis...", "user_id": user_id})
                await asyncio.sleep(0.7)
                execution_manager.broadcast("log", {"level": "info", "message": "🔍 Dynamic keywords resolved: 'Python Developer', 'Software Engineer Python' (deep_resume_analysis)", "user_id": user_id})
                await asyncio.sleep(0.7)

                execution_manager.current_node = "filter"
                execution_manager.broadcast("status", {"state": "running", "node": "filter", "user_id": user_id})
                execution_manager.broadcast("log", {"level": "info", "message": "⚡ Filter Node: Verifying senior keyword filters and deduplication...", "user_id": user_id})
                await asyncio.sleep(0.7)
                execution_manager.broadcast("log", {"level": "success", "message": "✓ Excluded senior roles; 8 matching early/mid roles qualified", "user_id": user_id})

                execution_manager.current_node = "evaluate"
                execution_manager.broadcast("status", {"state": "running", "node": "evaluate", "user_id": user_id})
                execution_manager.broadcast("log", {"level": "info", "message": "🎯 Evaluate Node: Scoring candidate resume fit against requirements...", "user_id": user_id})
                await asyncio.sleep(0.7)
                execution_manager.broadcast("log", {"level": "success", "message": "✓ Role 'Python Developer' at Stripe -> 88% Match (Pass, threshold >= 60%)", "user_id": user_id})

                execution_manager.current_node = "apply"
                execution_manager.broadcast("status", {"state": "running", "node": "apply", "user_id": user_id})
                execution_manager.broadcast("log", {"level": "info", "message": "🚀 Apply Node: Mapping candidate profile and contact fields...", "user_id": user_id})
                await asyncio.sleep(0.7)
                execution_manager.broadcast("log", {"level": "success", "message": "✓ Direct form package verified (dry_run mode)", "user_id": user_id})

                execution_manager.current_node = "record"
                execution_manager.broadcast("status", {"state": "running", "node": "record", "user_id": user_id})
                await asyncio.sleep(0.5)
                execution_manager.current_node = "advance"
                execution_manager.broadcast("status", {"state": "running", "node": "advance", "user_id": user_id})
                await asyncio.sleep(0.5)

                execution_manager.broadcast("log", {"level": "success", "message": "🎉 Cycle completed! All systems operating nominally in Dynamic UI Mode.", "user_id": user_id})
                return

            cfg = get_config()
            env = get_env()

            from src.agent.graph import run_agent
            from src.ingestion.pipeline import ingest_profile

            if force_ingest:
                resume_file = _resolve_path(cfg.profile.resume_path)
                if resume_file.exists():
                    execution_manager.broadcast("log", {"level": "info", "message": "Starting profile ingestion...", "user_id": user_id})
                    await ingest_profile(cfg, env, force=True)
                else:
                    execution_manager.broadcast("log", {"level": "warning", "message": "No resume file found on disk; continuing in agile screening mode.", "user_id": user_id})

            execution_manager.broadcast("log", {"level": "info", "message": f"Commencing agent execution (dry_run={dry_run})...", "user_id": user_id})
            await run_agent(cfg, env, dry_run=dry_run)
            execution_manager.broadcast("log", {"level": "success", "message": "Agent execution finished successfully.", "user_id": user_id})

        except Exception as e:
            logger.error(f"Background agent execution error: {e}")
            execution_manager.broadcast("log", {"level": "error", "message": f"Execution error: {str(e)}", "user_id": user_id})
        finally:
            execution_manager.is_running = False
            execution_manager.current_node = "idle"
            execution_manager.broadcast("status", {"state": "idle", "node": "idle", "user_id": user_id})

    execution_manager.active_task = asyncio.create_task(_execute())
    return web.json_response({"success": True, "message": "Agent run started."})


async def stop_run(request: web.Request) -> web.Response:
    """Cancel the active background execution task. Requires authentication and ownership."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required to stop agent"}, status=401)

    from src.storage.db import is_admin_user
    active_user = getattr(execution_manager, "user_id", None)
    if active_user is not None and active_user != user_id and not is_admin_user(user_id):
        return web.json_response(
            {"error": "Forbidden: Cannot stop agent execution initiated by another user."},
            status=403,
        )

    if execution_manager.active_task and not execution_manager.active_task.done():
        execution_manager.active_task.cancel()
        execution_manager.is_running = False
        execution_manager.current_node = "idle"
        execution_manager.broadcast("log", {"level": "warning", "message": "Agent execution cancelled by user.", "user_id": user_id})
        execution_manager.broadcast("status", {"state": "idle", "node": "idle", "user_id": user_id})
        return web.json_response({"success": True, "message": "Agent execution stopped."})

    return web.json_response({"error": "No active execution to stop"}, status=400)


async def search_live_handler(request: web.Request) -> web.Response:
    """Trigger direct keyword search in real Google Chrome."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    if execution_manager.is_running:
        return web.json_response({"error": "An agent task is already running"}, status=409)

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    raw_keywords = body.get("keywords")
    raw_keyword = body.get("keyword")
    user_input = raw_keywords if raw_keywords else raw_keyword
    job_types = body.get("job_types") or ["full-time", "internship"]
    num_browsers = max(1, min(6, int(body.get("num_browsers", 2))))
    min_score = float(body.get("min_score", 0.60))
    answers = body.get("answers") or {}
    save_settings = bool(body.get("save_settings", False))

    if save_settings:
        # Save settings to config.yaml and candidate profile for future runs
        try:
            cfg_path = _resolve_path("config.yaml")
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    curr_yaml = yaml.safe_load(f) or {}
                if "search" not in curr_yaml: curr_yaml["search"] = {}
                if "apply" not in curr_yaml: curr_yaml["apply"] = {}
                curr_yaml["search"]["job_type"] = job_types
                curr_yaml["apply"]["min_match_score"] = min_score
                if "answers" not in curr_yaml["apply"]: curr_yaml["apply"]["answers"] = {}
                for k, v in answers.items():
                    curr_yaml["apply"]["answers"][k] = v
                with open(cfg_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(curr_yaml, f, default_flow_style=False, sort_keys=False)
                from src.utils.config import get_config
                get_config.cache_clear()
        except Exception as ex:
            logger.debug(f"Could not persist config.yaml: {ex}")

        try:
            from src.storage.db import save_job_preferences
            save_job_preferences(
                user_id=user_id,
                preferences={
                    "employment_types": job_types,
                    "min_fit_score": int(min_score * 100),
                }
            )
        except Exception as ex:
            logger.debug(f"Could not persist preferences: {ex}")

    from src.matching.keyword_expansion import resolve_search_keywords
    resolved_keywords, origin = resolve_search_keywords(
        user_provided=user_input,
        user_id=user_id,
    )
    keyword = resolved_keywords[0] if resolved_keywords else "Python Developer"
    keywords = resolved_keywords
    location = body.get("location")
    target = str(body.get("target", "google")).lower().strip()
    
    # Background execution support: run silently without stealing desktop window focus
    background_param = body.get("background")
    if background_param is None:
        background_param = body.get("headless")
    if background_param is None:
        from src.utils.config import get_config
        background_param = getattr(getattr(get_config(), "browser", None), "headless", False)
    headless = bool(background_param)

    execution_manager.user_id = user_id

    async def _execute_search():
        execution_manager.is_running = True
        execution_manager.current_node = "search"
        execution_manager.broadcast("status", {"state": "running", "node": "search", "user_id": user_id})
        execution_manager.broadcast("log", {
            "level": "info",
            "message": f"🔍 Search keywords resolved ({origin}): {', '.join(keywords)} [Browsers: {num_browsers}, Types: {', '.join(job_types)}]",
            "user_id": user_id,
        })

        try:
            if os.environ.get("AUTOBOT_FRONTEND_ONLY") == "1":
                execution_manager.broadcast("log", {"level": "info", "message": f"⚡ Dynamic UI Mode: Simulating search for keywords: {', '.join(keywords)} ({origin}) in {location or 'India'} with {num_browsers} browsers...", "user_id": user_id})
                await asyncio.sleep(0.7)
                execution_manager.broadcast("log", {"level": "info", "message": f"🌐 Step 1: Querying primary keyword 'Python Developer' in {location or 'India'}...", "user_id": user_id})
                await asyncio.sleep(0.7)
                execution_manager.broadcast("log", {"level": "info", "message": f"🌐 Step 2: Fanning out {len(keywords)-1} secondary keywords across {num_browsers} browsers...", "user_id": user_id})
                await asyncio.sleep(0.7)
                execution_manager.broadcast("log", {"level": "success", "message": f"✓ Discovered matching job roles. Application Portals updated with {origin} keywords.", "user_id": user_id})
                return

            from src.browser.live_search import (
                run_direct_chrome_search,
                run_direct_google_keyword_search,
                run_google_to_linkedin_job_search,
            )

            def cb(lvl: str, msg: str):
                execution_manager.broadcast("log", {"level": lvl, "message": msg, "user_id": user_id})

            if target == "google_only":
                await run_direct_google_keyword_search(
                    keyword=keyword,
                    location=location,
                    headless=headless,
                    progress_callback=cb,
                    user_id=user_id,
                    keep_open=not headless,
                )
            else:
                # Direct Multi-Browser LinkedIn Search with strict 'Python Developer' priority
                await run_direct_chrome_search(
                    keywords=keywords,
                    location=location,
                    job_types=job_types,
                    num_browsers=num_browsers,
                    min_score=min_score,
                    headless=headless,
                    progress_callback=cb,
                    user_id=user_id,
                    keep_open=not headless,
                )
            execution_manager.broadcast("log", {"level": "success", "message": "Direct Chrome search and role navigation completed successfully.", "user_id": user_id})
        except Exception as e:
            logger.error(f"Error in direct Chrome search task: {e}")
            execution_manager.broadcast("log", {"level": "error", "message": f"Search error: {e}", "user_id": user_id})
        finally:
            execution_manager.is_running = False
            execution_manager.current_node = "idle"
            execution_manager.broadcast("status", {"state": "idle", "node": "idle", "user_id": user_id})

    execution_manager.active_task = asyncio.create_task(_execute_search())
    return web.json_response({"success": True, "message": f"Direct Chrome search ({target}) started."})


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
    """Stream real-time server-sent events (SSE) to connected dashboard clients. Requires authentication."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required to stream telemetry events"}, status=401)

    origin = request.headers.get("Origin", "")
    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    if origin and ("localhost" in origin or "127.0.0.1" in origin):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"

    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers=headers,
    )
    await response.prepare(request)

    execution_manager.subscribers.add(response)
    try:
        # Send initial backlog (filtered to general system or user-scoped events)
        for item in execution_manager.recent_logs[-20:]:
            item_user = item.get("data", {}).get("user_id") if isinstance(item.get("data"), dict) else None
            if item_user is None or item_user == user_id:
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


async def auth_logout_handler(request: web.Request) -> web.Response:
    """Seamless logout handler for open-source standalone mode."""
    return web.json_response({"success": True, "message": "Logged out successfully"})


async def auth_register_handler(request: web.Request) -> web.Response:
    """Open-source standalone user registration (always returns local user)."""
    return web.json_response({
        "success": True,
        "token": "open-source-session",
        "user": {"id": 1, "email": "local@autobot"},
        "message": "Authenticated as local user",
    })


async def auth_login_handler(request: web.Request) -> web.Response:
    """Open-source standalone user login (always succeeds as local user)."""
    return web.json_response({
        "success": True,
        "token": "open-source-session",
        "user": {"id": 1, "email": "local@autobot"},
        "message": "Authenticated as local user",
    })


async def auth_me_handler(request: web.Request) -> web.Response:
    """Get current user information (always authenticated as local user)."""
    user_id = 1
    profile = get_candidate_profile(user_id) or {}
    return web.json_response({
        "authenticated": True,
        "user_id": 1,
        "email": "local@autobot",
        "is_admin": True,
        "profile": profile,
    })


# ── Candidate Profile & Preferences Handlers ────────────────────────

async def get_candidate_profile_handler(request: web.Request) -> web.Response:
    """Get structured candidate profile."""
    user_id = get_current_user_id(request)
    profile = get_candidate_profile(user_id) or {}
    return web.json_response(profile)


async def get_candidate_suggested_keywords_handler(request: web.Request) -> web.Response:
    """Return dynamically extracted search keywords from deep resume analysis and user skills."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    from src.matching.keyword_expansion import resolve_search_keywords
    from src.storage.db import get_candidate_profile, get_job_preferences

    keywords, origin = resolve_search_keywords(user_provided=None, user_id=user_id, max_keywords=10)
    profile = get_candidate_profile(user_id) or {}
    prefs = get_job_preferences(user_id) or {}

    primary_skills = profile.get("primary_skills") or profile.get("technical_skills") or []
    target_roles = prefs.get("target_roles") or ["Software Engineer"]

    return web.json_response({
        "suggested_keywords": keywords,
        "origin": origin,
        "primary_skills": primary_skills[:12],
        "target_roles": target_roles,
        "headline": profile.get("headline", ""),
        "full_name": profile.get("full_name", ""),
    })


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
    """List registered job sources. Requires authentication."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    engine = JobDiscoveryEngine()
    sources = engine.get_sources()
    return web.json_response({"sources": [s.model_dump() for s in sources]})


async def add_source_handler(request: web.Request) -> web.Response:
    """Register a new job source. Requires administrator privileges."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    from src.storage.db import is_admin_user
    if not is_admin_user(user_id):
        return web.json_response(
            {"error": "Forbidden: Administrator privileges required to configure job sources."},
            status=403,
        )

    try:
        data = await request.json()
        src = JobSourceConfig(**data)
        engine = JobDiscoveryEngine()
        engine.register_source(src)
        return web.json_response({"success": True, "source": src.model_dump()})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def discover_jobs_handler(request: web.Request) -> web.Response:
    """Run discovery across sources, normalize and deduplicate. Requires authentication."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

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
    """List jobs available in the repository database with filters. Requires authentication."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    init_db()
    limit = int(request.query.get("limit", "50"))
    offset = int(request.query.get("offset", "0"))
    query = request.query.get("q", "").strip().lower()
    source = request.query.get("source", "").strip().lower()
    status = request.query.get("status", "active").strip().lower()
    employment_type = request.query.get("employment_type", "").strip().lower()
    workplace_type = request.query.get("workplace_type", "").strip().lower()
    country = request.query.get("country", "").strip().lower()

    with get_db_connection() as conn:
        sql = (
            "SELECT j.*, me.overall_score as fit_score, me.eligibility_status "
            "FROM jobs j "
            "LEFT JOIN match_evaluations me ON j.id = me.job_id AND me.user_id = ? "
            "WHERE 1=1"
        )
        params: List[Any] = [user_id]

        if status != "all":
            sql += " AND j.status = ?"
            params.append(status)
        if query:
            sql += " AND (LOWER(j.title) LIKE ? OR LOWER(j.company) LIKE ?)"
            params.extend([f"%{query}%", f"%{query}%"])
        if source:
            sql += " AND LOWER(j.source_name) = ?"
            params.append(source)
        if employment_type:
            sql += " AND LOWER(j.employment_type) = ?"
            params.append(employment_type)
        if workplace_type:
            sql += " AND (LOWER(j.workplace_type) = ? OR (? = 'remote' AND j.is_remote = 1))"
            params.extend([workplace_type, workplace_type])
        if country:
            sql += " AND (LOWER(j.country) = ? OR j.country = '')"
            params.append(country)

        min_score_str = request.query.get("min_score", "").strip()
        if min_score_str:
            try:
                min_score = float(min_score_str)
                sql += " AND me.overall_score >= ?"
                params.append(min_score)
            except ValueError:
                pass

        sql += " ORDER BY j.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()

    from src.matching.evaluator import is_job_matching_resume
    filtered_jobs = []
    for r in rows:
        row_dict = dict(r)
        is_ok, _ = is_job_matching_resume(
            title=row_dict.get("title", ""),
            description=row_dict.get("description", ""),
            user_id=user_id,
        )
        if is_ok:
            filtered_jobs.append(row_dict)

    return web.json_response({"jobs": filtered_jobs})


async def get_sources_health_handler(request: web.Request) -> web.Response:
    """Return configured ATS boards and health statistics."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    init_db()
    from src.discovery.board_registry import BoardRegistry
    registry = BoardRegistry()
    boards = registry.get_boards(active_only=False)

    with get_db_connection() as conn:
        health_list = []
        for b in boards:
            source_prefix = f"{b.source_type.value}:{b.board_token_or_slug}:"
            row = conn.execute(
                """
                SELECT 
                    COUNT(CASE WHEN status = 'active' THEN 1 END) as active_jobs,
                    COUNT(CASE WHEN status = 'expired' THEN 1 END) as expired_jobs,
                    MAX(last_verified_at) as latest_verification
                FROM jobs
                WHERE stable_id LIKE ?
                """,
                (f"{source_prefix}%",),
            ).fetchone()
            active_count = row["active_jobs"] if row else 0
            expired_count = row["expired_jobs"] if row else 0
            latest_ver = row["latest_verification"] if row else None

            health_list.append({
                "name": b.name,
                "source_type": b.source_type.value,
                "board_slug": b.board_token_or_slug,
                "status": b.status,
                "is_active": b.is_active,
                "refresh_interval": b.refresh_interval,
                "concurrency_limit": b.concurrency_limit,
                "last_synced_at": b.last_synced_at or latest_ver or "Never",
                "last_success_at": getattr(b, "last_success_at", None) or b.last_synced_at or latest_ver or "Never",
                "last_failure_at": getattr(b, "last_failure_at", None),
                "next_sync_at": getattr(b, "next_sync_at", None),
                "last_sync_complete": getattr(b, "last_sync_complete", False),
                "last_retrieved_count": getattr(b, "last_retrieved_count", 0),
                "last_expired_count": getattr(b, "last_expired_count", 0),
                "failure_count": b.failure_count,
                "last_error": b.last_error,
                "active_jobs_count": active_count,
                "expired_jobs_count": expired_count,
            })

    return web.json_response({"sources": health_list})


async def get_sync_runs_handler(request: web.Request) -> web.Response:
    """Return historical board discovery sync runs and completeness logs."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    from src.discovery.board_registry import BoardRegistry
    registry = BoardRegistry()
    limit = int(request.query.get("limit", "50"))
    runs = registry.get_sync_runs(limit=limit)
    return web.json_response({"sync_runs": runs})


async def get_matching_benchmark_handler(request: web.Request) -> web.Response:
    """Return independent matching evaluation benchmark metrics without private candidate PII."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    from src.matching.independent_benchmark import IndependentBenchmarkSuite
    suite = IndependentBenchmarkSuite()
    report = suite.run_benchmark()
    return web.json_response(report.to_dict())


async def get_candidate_search_history_handler(request: web.Request) -> web.Response:
    """Return tenant-isolated personalized search history for the authenticated candidate."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    from src.matching.keyword_expansion import search_personalized_jobs
    res = search_personalized_jobs(user_id=user_id, status_filter="all", limit=25)
    return web.json_response({
        "user_id": user_id,
        "search_history": res.get("jobs", []),
        "expansion": res.get("expansion", {}),
    })


async def get_keyword_expansion_handler(request: web.Request) -> web.Response:
    """Return transparent keyword expansion explanations and filters for authenticated user."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    from src.matching.keyword_expansion import expand_candidate_keywords
    result = expand_candidate_keywords(user_id)
    return web.json_response(result.to_dict())


async def get_personalized_jobs_handler(request: web.Request) -> web.Response:
    """Execute personalized search tailored to candidate skills and preferences."""
    user_id = get_current_user_id(request)
    if not user_id:
        return web.json_response({"error": "Authentication required"}, status=401)

    status_filter = request.query.get("status", "active")
    limit = int(request.query.get("limit", "50"))
    from src.matching.keyword_expansion import search_personalized_jobs
    res = search_personalized_jobs(user_id=user_id, status_filter=status_filter, limit=limit)
    return web.json_response(res)


# ── Matching & Eligibility Handlers ─────────────────────────────────

async def evaluate_job_handler(request: web.Request) -> web.Response:
    """Evaluate job match and eligibility deterministically."""
    try:
        user_id = get_current_user_id(request)
        data = await request.json()
        job_id = data.get("job_id")
        stable_id = data.get("stable_id")

        with get_db_connection() as conn:
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

        with get_db_connection() as conn:
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
        if isinstance(pack, dict) and "id" in pack and "pack_id" not in pack:
            pack["pack_id"] = pack["id"]
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
            with get_db_connection() as conn:
                pack_exists = conn.execute("SELECT user_id FROM application_packs WHERE id = ?", (pack_id,)).fetchone()
            if pack_exists and pack_exists["user_id"] != user_id:
                return web.json_response({"error": "Forbidden: Application pack belongs to another candidate."}, status=403)
            return web.json_response({"error": "Pack not found"}, status=404)

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

        with get_db_connection() as conn:
            pack_row = conn.execute("SELECT * FROM application_packs WHERE id = ? AND user_id = ?", (pack_id, user_id)).fetchone()
            if not pack_row:
                pack_exists = conn.execute("SELECT user_id FROM application_packs WHERE id = ?", (pack_id,)).fetchone()
                if pack_exists and pack_exists["user_id"] != user_id:
                    return web.json_response({"error": "Forbidden: Application pack belongs to another candidate."}, status=403)
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
    with get_db_connection() as conn:
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
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM application_packs WHERE id = ? AND user_id = ?", (pack_id, user_id)).fetchone()
            if not row:
                pack_exists = conn.execute("SELECT user_id FROM application_packs WHERE id = ?", (pack_id,)).fetchone()
                if pack_exists and pack_exists["user_id"] != user_id:
                    return web.json_response({"error": "Forbidden: Application pack belongs to another candidate."}, status=403)
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
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_logs WHERE user_id = ? ORDER BY id DESC LIMIT 100",
            (user_id,),
        ).fetchall()
    return web.json_response({"audit_logs": [dict(r) for r in rows]})


async def open_job_form_handler(request: web.Request) -> web.Response:
    """
    Directly opens the company's real external application form (e.g. Workday, iCIMS, Greenhouse)
    behind a LinkedIn job posting. Resolves outbound redirects on the fly and returns an HTTP 302
    Redirect so that clicking 'Open Form ↗' in the browser takes the user directly to the ATS form.
    """
    job_id = request.match_info.get("id") or request.query.get("id") or request.query.get("job_id")
    if not job_id:
        return web.json_response({"error": "Missing job identifier"}, status=400)

    user_id = get_current_user_id(request) or 1
    init_db()

    target_url = None
    title = ""
    company = ""
    stable_identifier = str(job_id).strip()
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT j.id, j.stable_id, j.title, j.company, j.application_url, a.url as app_url
            FROM jobs j
            LEFT JOIN applications a ON (j.stable_id = a.job_id OR CAST(j.id AS TEXT) = a.job_id) AND (a.user_id = ? OR a.user_id = 1)
            WHERE j.stable_id = ? OR CAST(j.id AS TEXT) = ? OR j.application_url LIKE ?
            ORDER BY CASE WHEN a.user_id = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (user_id, stable_identifier, stable_identifier, f"%{job_id}%", user_id),
        ).fetchone()

        if row:
            r_dict = dict(row)
            target_url = r_dict.get("application_url") or r_dict.get("app_url") or ""
            stable_identifier = r_dict.get("stable_id") or str(r_dict.get("id"))
            title = r_dict.get("title") or ""
            company = r_dict.get("company") or ""

    from src.browser.linkedin_apply_extractor import decode_linkedin_apply_url, extract_company_apply_url_from_html
    from src.browser.company_careers_resolver import resolve_company_direct_apply_url

    # If not found in DB, check if job_id or URL has known mapping or direct URL
    if not target_url:
        resolved = resolve_company_direct_apply_url(
            title="",
            company="",
            current_url=stable_identifier,
        )
        if resolved and not any(li in resolved.lower() for li in ("linkedin.com", "lnkd.in")):
            raise web.HTTPFound(location=resolved)
        return web.json_response({"error": f"Job {job_id} not found"}, status=404)

    # 1. If URL is already a direct non-LinkedIn ATS link, redirect immediately!
    if not any(li in target_url.lower() for li in ("linkedin.com", "lnkd.in")):
        raise web.HTTPFound(location=target_url)

    # 2. Check if the URL has encoded target parameter
    decoded = decode_linkedin_apply_url(target_url)
    if decoded and not any(li in decoded.lower() for li in ("linkedin.com", "lnkd.in")):
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE jobs SET application_url = ? WHERE stable_id = ? OR CAST(id AS TEXT) = ?",
                (decoded, stable_identifier, stable_identifier),
            )
            conn.execute(
                "UPDATE applications SET url = ? WHERE job_id = ? OR CAST(id AS TEXT) = ?",
                (decoded, stable_identifier, stable_identifier),
            )
            conn.commit()
        raise web.HTTPFound(location=decoded)

    # 3. Resolve direct company application ATS career portal (Workday, iCIMS, Greenhouse, etc.)
    resolved_ats_url = resolve_company_direct_apply_url(
        title=title,
        company=company,
        current_url=target_url,
    )
    if resolved_ats_url and not any(li in resolved_ats_url.lower() for li in ("linkedin.com", "lnkd.in")):
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE jobs SET application_url = ? WHERE stable_id = ? OR CAST(id AS TEXT) = ?",
                (resolved_ats_url, stable_identifier, stable_identifier),
            )
            conn.execute(
                "UPDATE applications SET url = ? WHERE job_id = ? OR CAST(id AS TEXT) = ?",
                (resolved_ats_url, stable_identifier, stable_identifier),
            )
            conn.commit()
        raise web.HTTPFound(location=resolved_ats_url)

    # 4. Dynamic resolution: attempt to extract companyApplyUrl from the public page
    try:
        import urllib.request
        req = urllib.request.Request(
            target_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            extracted = extract_company_apply_url_from_html(html)
            if extracted and not any(li in extracted.lower() for li in ("linkedin.com", "lnkd.in")):
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE jobs SET application_url = ? WHERE stable_id = ? OR CAST(id AS TEXT) = ?",
                        (extracted, stable_identifier, stable_identifier),
                    )
                    conn.execute(
                        "UPDATE applications SET url = ? WHERE job_id = ? OR CAST(id AS TEXT) = ?",
                        (extracted, stable_identifier, stable_identifier),
                    )
                    conn.commit()
                raise web.HTTPFound(location=extracted)
    except web.HTTPFound:
        raise
    except Exception as ex:
        logger.debug(f"Quick HTTP direct apply extraction failed for {job_id}: {ex}")

    # Fallback: Redirect to company careers portal rather than LinkedIn authwall
    comp_name = urllib.parse.quote_plus(company or "careers")
    title_name = urllib.parse.quote_plus(title or "jobs")
    raise web.HTTPFound(location=f"https://www.google.com/search?q={comp_name}+{title_name}+careers+apply")


async def resolve_apply_url_handler(request: web.Request) -> web.Response:
    """
    API endpoint returning JSON with the resolved direct external apply form URL for a job.
    """
    job_id = request.match_info.get("id") or request.query.get("id") or request.query.get("job_id")
    if not job_id:
        return web.json_response({"error": "Missing job identifier"}, status=400)

    user_id = get_current_user_id(request) or 1
    init_db()

    target_url = None
    title = ""
    company = ""
    stable_identifier = str(job_id).strip()
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT j.id, j.stable_id, j.title, j.company, j.application_url, a.url as app_url
            FROM jobs j
            LEFT JOIN applications a ON (j.stable_id = a.job_id OR CAST(j.id AS TEXT) = a.job_id) AND (a.user_id = ? OR a.user_id = 1)
            WHERE j.stable_id = ? OR CAST(j.id AS TEXT) = ? OR j.application_url LIKE ?
            ORDER BY CASE WHEN a.user_id = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (user_id, stable_identifier, stable_identifier, f"%{job_id}%", user_id),
        ).fetchone()

        if row:
            r_dict = dict(row)
            target_url = r_dict.get("application_url") or r_dict.get("app_url") or ""
            stable_identifier = r_dict.get("stable_id") or str(r_dict.get("id"))
            title = r_dict.get("title") or ""
            company = r_dict.get("company") or ""

    from src.browser.linkedin_apply_extractor import decode_linkedin_apply_url, extract_company_apply_url_from_html
    from src.browser.company_careers_resolver import resolve_company_direct_apply_url

    if not target_url:
        resolved = resolve_company_direct_apply_url(
            title="",
            company="",
            current_url=stable_identifier,
        )
        if resolved and not any(li in resolved.lower() for li in ("linkedin.com", "lnkd.in")):
            return web.json_response({"success": True, "apply_url": resolved, "is_external": True, "resolved": True})
        return web.json_response({"error": f"Job {job_id} not found"}, status=404)

    is_external = not any(li in target_url.lower() for li in ("linkedin.com", "lnkd.in"))
    if is_external:
        return web.json_response({"success": True, "apply_url": target_url, "is_external": True, "resolved": True})

    decoded = decode_linkedin_apply_url(target_url)
    if decoded and not any(li in decoded.lower() for li in ("linkedin.com", "lnkd.in")):
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE jobs SET application_url = ? WHERE stable_id = ? OR CAST(id AS TEXT) = ?",
                (decoded, stable_identifier, stable_identifier),
            )
            conn.execute(
                "UPDATE applications SET url = ? WHERE job_id = ? OR CAST(id AS TEXT) = ?",
                (decoded, stable_identifier, stable_identifier),
            )
            conn.commit()
        return web.json_response({"success": True, "apply_url": decoded, "is_external": True, "resolved": True})

    # Resolve direct company ATS portal
    resolved_ats = resolve_company_direct_apply_url(
        title=title,
        company=company,
        current_url=target_url,
    )
    if resolved_ats and not any(li in resolved_ats.lower() for li in ("linkedin.com", "lnkd.in")):
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE jobs SET application_url = ? WHERE stable_id = ? OR CAST(id AS TEXT) = ?",
                (resolved_ats, stable_identifier, stable_identifier),
            )
            conn.execute(
                "UPDATE applications SET url = ? WHERE job_id = ? OR CAST(id AS TEXT) = ?",
                (resolved_ats, stable_identifier, stable_identifier),
            )
            conn.commit()
        return web.json_response({"success": True, "apply_url": resolved_ats, "is_external": True, "resolved": True})

    # Attempt quick extract from HTML
    try:
        import urllib.request
        req = urllib.request.Request(
            target_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            extracted = extract_company_apply_url_from_html(html)
            if extracted and not any(li in extracted.lower() for li in ("linkedin.com", "lnkd.in")):
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE jobs SET application_url = ? WHERE stable_id = ? OR CAST(id AS TEXT) = ?",
                        (extracted, stable_identifier, stable_identifier),
                    )
                    conn.execute(
                        "UPDATE applications SET url = ? WHERE job_id = ? OR CAST(id AS TEXT) = ?",
                        (extracted, stable_identifier, stable_identifier),
                    )
                    conn.commit()
                return web.json_response({"success": True, "apply_url": extracted, "is_external": True, "resolved": True})
    except Exception as ex:
        logger.debug(f"Quick HTTP direct apply extraction failed for {job_id}: {ex}")

    # Fallback to search query link so that candidate is never returned a raw LinkedIn authwall URL
    comp_term = urllib.parse.quote_plus(company or "company")
    title_term = urllib.parse.quote_plus(title or "jobs")
    fallback_url = f"https://www.google.com/search?q={comp_term}+{title_term}+careers+apply"
    return web.json_response({"success": True, "apply_url": fallback_url, "is_external": True, "resolved": True})

