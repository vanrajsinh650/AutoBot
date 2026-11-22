"""
Web Dashboard Server for AutoBot v2.
"""

from pathlib import Path
from aiohttp import web

from src.web.routes import (
    add_source_handler,
    apply_direct_link_handler,
    apply_portals_bot_handler,
    approve_application_pack_handler,
    auth_login_handler,
    auth_logout_handler,
    auth_me_handler,
    auth_register_handler,
    configure_browser_handler,
    confirm_linkedin_submission_handler,
    delete_account_handler,
    delete_portals_handler,
    discover_jobs_handler,
    download_application_pack_handler,
    evaluate_job_handler,
    get_apply_portals_handler,
    get_audit_logs_handler,
    get_browser_health_handler,
    get_candidate_profile_handler,
    get_candidate_search_history_handler,
    get_candidate_suggested_keywords_handler,
    get_config_handler,
    get_discovered_jobs_handler,
    get_jobs,
    get_preferences_handler,
    get_profile_handler,
    get_proof_handler,
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
    open_job_form_handler,
    prepare_application_handler,
    resolve_apply_url_handler,
    save_config_handler,
    search_live_handler,
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
    "/api/events",
    "/api/apply-portals",
    "/api/apply-portals/delete",
    "/api/portals/apply",
}


# Typed aiohttp keys to prevent NotAppKeyWarning
SCHEDULER_KEY: Any = web.AppKey("discovery_scheduler", object) if hasattr(web, "AppKey") else "discovery_scheduler"
USER_ID_KEY: Any = web.RequestKey("user_id", object) if hasattr(web, "RequestKey") else "user_id"
USER_EMAIL_KEY: Any = web.RequestKey("user_email", object) if hasattr(web, "RequestKey") else "user_email"
SESSION_KEY: Any = web.RequestKey("session", object) if hasattr(web, "RequestKey") else "session"


@web.middleware
async def cache_control_middleware(request: web.Request, handler):
    """Ensure static assets and dashboard HTML are never stuck in stale browser cache."""
    response = await handler(request)
    path = request.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """
    Open-Source Standalone Context Middleware for AutoBot.
    Always operates as the local user (user_id=1, admin role)
    with zero authentication barriers or login requirements.
    """
    request[USER_ID_KEY] = 1
    request[USER_EMAIL_KEY] = "local@autobot"
    request[SESSION_KEY] = {"user_id": 1, "role": "admin", "email": "local@autobot"}
    return await handler(request)


async def index_handler(request: web.Request) -> web.FileResponse:
    """Serve the single-page application dashboard with strict cache busting."""
    index_file = STATIC_DIR / "index.html"
    res = web.FileResponse(index_file)
    res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    res.headers["Pragma"] = "no-cache"
    res.headers["Expires"] = "0"
    return res


async def _start_scheduler(app: web.Application) -> None:
    """Initialize and start the background recurring job discovery scheduler."""
    import os
    if (
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("AUTOBOT_DISABLE_SCHEDULER") == "1"
        or os.environ.get("AUTOBOT_FRONTEND_ONLY") == "1"
    ):
        return
    from src.discovery.scheduler import DiscoveryScheduler
    scheduler = DiscoveryScheduler()
    scheduler.start()
    app[SCHEDULER_KEY] = scheduler


async def _stop_scheduler(app: web.Application) -> None:
    """Gracefully shutdown the background discovery scheduler."""
    scheduler = app.get(SCHEDULER_KEY)
    if scheduler:
        await scheduler.stop()


def create_app() -> web.Application:
    """Build and configure the aiohttp Application instance with centralized auth middleware."""
    app = web.Application(middlewares=[cache_control_middleware, auth_middleware])
    app.on_startup.append(_start_scheduler)
    app.on_cleanup.append(_stop_scheduler)

    # ── Legacy & Telemetry API Routes ─────────────────────────────
    app.router.add_get("/api/status", get_status)
    app.router.add_get("/api/browser/health", get_browser_health_handler)
    app.router.add_post("/api/browser/configure", configure_browser_handler)
    app.router.add_get("/api/stats", get_stats_handler)
    app.router.add_get("/api/jobs", get_jobs)
    app.router.add_get("/api/jobs/{id}/open-form", open_job_form_handler)
    app.router.add_get("/api/jobs/{id}/resolve-apply-url", resolve_apply_url_handler)
    app.router.add_post("/api/jobs/{id}/resolve-apply-url", resolve_apply_url_handler)
    app.router.add_get("/api/apply-portals", get_apply_portals_handler)
    app.router.add_post("/api/apply-portals/delete", delete_portals_handler)
    app.router.add_delete("/api/apply-portals/delete", delete_portals_handler)
    app.router.add_post("/api/portals/apply", apply_portals_bot_handler)
    app.router.add_post("/api/portals/apply-direct", apply_direct_link_handler)
    app.router.add_post("/api/application/direct-apply", apply_direct_link_handler)
    app.router.add_get("/api/proofs/{filename}", get_proof_handler)
    app.router.add_get("/api/config", get_config_handler)
    app.router.add_post("/api/config", save_config_handler)
    app.router.add_get("/api/profile", get_profile_handler)
    app.router.add_post("/api/upload", upload_resume_handler)
    app.router.add_post("/api/upload-resume", upload_resume_handler)
    app.router.add_post("/api/run", start_run)
    app.router.add_post("/api/search/live", search_live_handler)
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
    app.router.add_get("/api/candidate/suggested-keywords", get_candidate_suggested_keywords_handler)
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
