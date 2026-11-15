"""
REST API & SSE Event Stream Routes for AutoBot v2 Web Dashboard.
"""

import asyncio
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from aiohttp import web
import yaml

from src.agent.state import JobPosting
from src.storage.db import DEFAULT_DB_PATH, get_db_connection, get_stats
from src.utils.config import get_config, get_env
from src.utils.logger import logger

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
        self.subscribers: Set[web.Response] = set()
        self.recent_logs: List[Dict[str, Any]] = []

    def broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        """Enqueue an event to all connected SSE clients."""
        payload = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        self.recent_logs.append(payload)
        if len(self.recent_logs) > 200:
            self.recent_logs.pop(0)

        # Broadcast to active SSE streams
        for ws in list(self.subscribers):
            try:
                msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n".encode("utf-8")
                async def _send(res=ws, m=msg):
                    try:
                        await res.write(m)
                    except Exception:
                        self.subscribers.discard(res)
                asyncio.create_task(_send())
            except Exception:
                self.subscribers.discard(ws)


execution_manager = AgentExecutionManager()


# ── Route Handlers ─────────────────────────────────────────────────

async def get_status(request: web.Request) -> web.Response:
    """Return runtime agent state and system status."""
    cfg = get_config()
    env = get_env()

    resume_exists = _resolve_path(cfg.profile.resume_path).exists()
    session_exists = _resolve_path("data/session/linkedin_state.json").exists()
    db_stats = get_stats()
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
    })


async def get_stats_handler(request: web.Request) -> web.Response:
    """Return aggregate application counts."""
    stats = get_stats()
    stats["total"] = sum(stats.values())
    return web.json_response(stats)


async def get_jobs(request: web.Request) -> web.Response:
    """Return paginated, filterable list of processed applications from SQLite."""
    status_filter = request.query.get("status", "").strip().lower()
    search_query = request.query.get("q", "").strip().lower()
    limit = int(request.query.get("limit", "50"))
    offset = int(request.query.get("offset", "0"))

    with get_db_connection(DEFAULT_DB_PATH) as conn:
        query = "SELECT * FROM applications WHERE 1=1"
        params = []

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
        count_query = "SELECT COUNT(*) FROM applications WHERE 1=1"
        count_params = []
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

        # Clear cached config so next lookup picks up changes
        from src.utils.config import get_config
        get_config.cache_clear()

        logger.info("[web]✓ Updated config.yaml via web dashboard[/web]")
        return web.json_response({"success": True})
    except Exception as e:
        logger.error(f"Error updating config: {e}")
        return web.json_response({"error": str(e)}, status=400)


async def get_profile_handler(request: web.Request) -> web.Response:
    """Extract and return candidate resume sections and vector memory telemetry."""
    cfg = get_config()
    resume_path = _resolve_path(cfg.profile.resume_path)

    if not resume_path.exists():
        return web.json_response({
            "found": False,
            "path": str(resume_path),
            "sections": {},
            "total_chunks": 0,
        })

    from src.ingestion.resume_parser import parse_resume
    chunks = parse_resume(resume_path)

    sections_grouped: Dict[str, List[str]] = {}
    for c in chunks:
        sec = c.section.value
        sections_grouped.setdefault(sec, []).append(c.content)

    return web.json_response({
        "found": True,
        "path": str(resume_path),
        "total_chunks": len(chunks),
        "sections": sections_grouped,
    })


async def upload_resume_handler(request: web.Request) -> web.Response:
    """Handle resume PDF or document upload and trigger optional re-indexing."""
    try:
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

        # Ensure destination directory exists
        dest_dir = _resolve_path("data/resume")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"resume{ext}"

        # Write uploaded bytes
        size = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                f.write(chunk)

        # Update config.yaml with relative path
        cfg_path = _resolve_path("config.yaml")
        rel_path = f"data/resume/resume{ext}"
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                raw_cfg = yaml.safe_load(f) or {}
            raw_cfg.setdefault("profile", {})["resume_path"] = rel_path
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(raw_cfg, f, default_flow_style=False, sort_keys=False)
            from src.utils.config import get_config
            get_config.cache_clear()

        # Try parsing sections if it's a PDF
        chunks_count = 0
        sections_found = []
        if ext == ".pdf":
            try:
                from src.ingestion.resume_parser import parse_resume
                parsed_chunks = parse_resume(dest_path)
                chunks_count = len(parsed_chunks)
                sections_found = list({c.section.value for c in parsed_chunks})
            except Exception as pe:
                logger.warning(f"Resume uploaded but extraction preview failed: {pe}")

        execution_manager.broadcast("log", {
            "level": "success",
            "message": f"Candidate resume uploaded: '{filename}' ({size} bytes, {chunks_count} chunks extracted)",
        })

        return web.json_response({
            "success": True,
            "filename": filename,
            "path": rel_path,
            "size_bytes": size,
            "chunks_count": chunks_count,
            "sections": sections_found,
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
    """Clear saved session state and browser user data to disconnect/switch LinkedIn accounts."""
    import shutil
    session_file = _resolve_path("data/session/linkedin_state.json")
    user_data_dir = _resolve_path("data/session/user_data")

    cleared = False
    if session_file.exists():
        session_file.unlink()
        cleared = True
    if user_data_dir.exists():
        shutil.rmtree(user_data_dir, ignore_errors=True)
        cleared = True

    execution_manager.broadcast("log", {
        "level": "warning",
        "message": "LinkedIn session and Chrome profile cleared. Please log into your alternative account.",
    })
    return web.json_response({
        "success": True,
        "cleared": cleared,
        "message": "LinkedIn session cleared successfully. The next browser launch will prompt for your new login.",
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

        # Send initial status
        init_status = {
            "state": "running" if execution_manager.is_running else "idle",
            "node": execution_manager.current_node,
        }
        await response.write(f"event: status\ndata: {json.dumps(init_status)}\n\n".encode("utf-8"))

        # Keep connection open with periodic heartbeat ping
        while True:
            await asyncio.sleep(15)
            await response.write(b": ping\n\n")

    except (asyncio.CancelledError, ConnectionResetError, Exception):
        pass
    finally:
        execution_manager.subscribers.discard(response)

    return response
