"""
Web Dashboard Server for AutoBot v2.
"""

from pathlib import Path
from aiohttp import web

from src.web.routes import (
    add_source_handler,
    approve_application_pack_handler,
    auth_login_handler,
    auth_logout_handler,
    auth_me_handler,
    auth_register_handler,
    configure_browser_handler,
    confirm_linkedin_submission_handler,
    delete_account_handler,
    discover_jobs_handler,
    download_application_pack_handler,
    evaluate_job_handler,
    get_audit_logs_handler,
    get_browser_health_handler,
    get_candidate_profile_handler,
    get_candidate_search_history_handler,
    get_config_handler,
    get_discovered_jobs_handler,
    get_jobs,
    get_preferences_handler,
    get_profile_handler,
    get_resume_versions_handler,
    get_sources_handler,
    get_sources_health_handler,
    get_sync_runs_handler,
    get_keyword_expansion_handler,
    get_matching_benchmark_handler,
    get_personalized_jobs_handler,
    get_stats_handler,
    get_status,
    get_tracker_handler,
    import_job_handler,
    logout_handler,
    prepare_application_handler,
    save_config_handler,
    sse_logs_stream,
    start_run,
    stop_run,
    submit_external_application_handler,
    update_application_status_handler,
    update_candidate_profile_handler,
    update_preferences_handler,
    upload_resume_handler,
)
from src.utils.logger import console, logger


STATIC_DIR = Path(__file__).parent / "static"

PUBLIC_EXACT_PATHS = {
    "/",
    "/api/status",
    "/api/browser/health",
    "/api/auth/register",
    "/api/auth/login",
}


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """
    Centralized Fail-Closed Authentication Middleware for AutoBot v2.1.
    Strictly verifies Bearer session tokens for all protected /api/* endpoints.
    Returns HTTP 401 on missing, expired, revoked, or invalid sessions.
    """
    path = request.path

    # Allow public endpoints and static assets
    if path in PUBLIC_EXACT_PATHS or path.startswith("/static/"):
        return await handler(request)

    # All other /api/ endpoints require valid authentication
    if path.startswith("/api/"):
        auth_header = request.headers.get("Authorization", "")
        token = None
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
        if not token:
            token = request.cookies.get("auth_token") or request.query.get("token")

        if not token:
            return web.json_response(
                {"error": "Authentication required. Missing Bearer token or auth cookie."},
                status=401,
            )

        from src.storage.auth import validate_session
        session = validate_session(token)
        if not session:
            return web.json_response(
                {"error": "Authentication required. Invalid, expired, or revoked session token."},
                status=401,
            )

        # Attach validated session data to request state
        request["user_id"] = session["user_id"]
        request["user_email"] = session.get("email")
        request["session"] = session

    return await handler(request)


async def index_handler(request: web.Request) -> web.FileResponse:
    """Serve the single-page application dashboard."""
    index_file = STATIC_DIR / "index.html"
    return web.FileResponse(index_file)


async def _start_scheduler(app: web.Application) -> None:
    """Initialize and start the background recurring job discovery scheduler."""
    from src.discovery.scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    scheduler.start()
    app["discovery_scheduler"] = scheduler


async def _stop_scheduler(app: web.Application) -> None:
    """Gracefully shutdown the background discovery scheduler."""
    scheduler = app.get("discovery_scheduler")
    if scheduler:
        await scheduler.stop()


def create_app() -> web.Application:
    """Build and configure the aiohttp Application instance with centralized auth middleware."""
    app = web.Application(middlewares=[auth_middleware])
    app.on_startup.append(_start_scheduler)
    app.on_cleanup.append(_stop_scheduler)

    # ── Legacy & Telemetry API Routes ─────────────────────────────
    app.router.add_get("/api/status", get_status)
    app.router.add_get("/api/browser/health", get_browser_health_handler)
    app.router.add_post("/api/browser/configure", configure_browser_handler)
    app.router.add_get("/api/stats", get_stats_handler)
    app.router.add_get("/api/jobs", get_jobs)
    app.router.add_get("/api/config", get_config_handler)
    app.router.add_post("/api/config", save_config_handler)
    app.router.add_get("/api/profile", get_profile_handler)
    app.router.add_post("/api/upload", upload_resume_handler)
    app.router.add_post("/api/upload-resume", upload_resume_handler)
    app.router.add_post("/api/run", start_run)
    app.router.add_post("/api/stop", stop_run)
    app.router.add_post("/api/logout", logout_handler)
    app.router.add_get("/api/events", sse_logs_stream)

    # ── Multi-User Authentication Routes ──────────────────────────
    app.router.add_post("/api/auth/register", auth_register_handler)
    app.router.add_post("/api/auth/login", auth_login_handler)
    app.router.add_post("/api/auth/logout", auth_logout_handler)
    app.router.add_get("/api/auth/me", auth_me_handler)

    # ── Candidate Profile & Preferences Routes ────────────────────
    app.router.add_get("/api/candidate/profile", get_candidate_profile_handler)
    app.router.add_put("/api/candidate/profile", update_candidate_profile_handler)
    app.router.add_get("/api/candidate/preferences", get_preferences_handler)
    app.router.add_put("/api/candidate/preferences", update_preferences_handler)
    app.router.add_get("/api/candidate/resumes", get_resume_versions_handler)
    app.router.add_get("/api/candidate/search-history", get_candidate_search_history_handler)

    # ── Job Discovery Routes ──────────────────────────────────────
    app.router.add_get("/api/discovery/sources", get_sources_handler)
    app.router.add_get("/api/discovery/sources/health", get_sources_health_handler)
    app.router.add_get("/api/discovery/sync-runs", get_sync_runs_handler)
    app.router.add_post("/api/discovery/sources", add_source_handler)
    app.router.add_post("/api/discovery/run", discover_jobs_handler)
    app.router.add_post("/api/discovery/import", import_job_handler)
    app.router.add_get("/api/discovery/jobs", get_discovered_jobs_handler)
    app.router.add_get("/api/discovery/personalized", get_personalized_jobs_handler)

    # ── Matching & Evaluation Routes ──────────────────────────────
    app.router.add_post("/api/matching/evaluate", evaluate_job_handler)
    app.router.add_get("/api/matching/expand-keywords", get_keyword_expansion_handler)
    app.router.add_get("/api/matching/benchmark", get_matching_benchmark_handler)

    # ── Application Preparation & Workflow Routes ─────────────────
    app.router.add_post("/api/application/prepare", prepare_application_handler)
    app.router.add_post("/api/application/approve", approve_application_pack_handler)
    app.router.add_post("/api/application/submit-external", submit_external_application_handler)
    app.router.add_post("/api/application/confirm-linkedin", confirm_linkedin_submission_handler)
    app.router.add_get("/api/application/download/{pack_id}", download_application_pack_handler)

    # ── Tracker & Privacy Routes ──────────────────────────────────
    app.router.add_get("/api/tracker/events", get_tracker_handler)
    app.router.add_post("/api/tracker/status", update_application_status_handler)
    app.router.add_get("/api/privacy/audit-logs", get_audit_logs_handler)
    app.router.add_post("/api/privacy/delete-account", delete_account_handler)

    # ── Static & Frontend Assets ──────────────────────────────────
    app.router.add_get("/", index_handler)
    app.router.add_static("/static/", path=STATIC_DIR, name="static")

    return app


def start_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the web server synchronously."""
    console.print(
        f"\n[bold cyan]🚀 AutoBot v2 Mission Control Dashboard starting at:[/bold cyan] "
        f"[bold underline green]http://{host}:{port}[/bold underline green]\n"
    )
    app = create_app()
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
