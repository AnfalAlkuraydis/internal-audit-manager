"""Local API: health, eight business tools and backend-enforced human reviews."""
import os
import logging
import asyncio
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError
from backend.config import Settings
from backend.auth import AuthConfig
from backend.database.connection import create_database
from backend.database.repository import DataConflict
from backend.services.audit import AuditService
from backend.services.errors import AuditError
from backend.api import create_router
from backend.workspace import create_workspace_router

def create_app(settings: Settings | None = None, *, engine=None, auth_config=None, runtime=None, enable_worker=None) -> FastAPI:
    """Construct the API without silently migrating, seeding or calling the model."""
    production = settings is None and engine is None
    settings = settings or Settings.from_env()
    root = Path(__file__).resolve().parents[1]
    engine = engine if engine is not None else create_database(
        root / os.getenv("AUDIT_DATABASE_PATH", "var/audit.sqlite"))
    service = AuditService(engine)
    auth = auth_config if auth_config is not None else AuthConfig.from_env()
    worker_enabled = production if enable_worker is None else enable_worker
    holder = {"runtime": runtime}
    runtime_lock = threading.Lock()

    def get_runtime():
        """Create checkpoint storage lazily; never perform inference during app construction."""
        with runtime_lock:
            if holder["runtime"] is None:
                if not inspect(engine).has_table("agent_sessions"):
                    raise AuditError("phase4_migration_required", 503)
                if os.getenv("EMAIL_MODE", "simulated") != "simulated":
                    raise AuditError("phase4_requires_simulated_email", 503)
                from backend.agent.orchestrator import AgentRuntime
                holder["runtime"] = AgentRuntime(service,
                    root / os.getenv("AUDIT_CHECKPOINT_PATH", "var/checkpoints.sqlite"))
            return holder["runtime"]

    @asynccontextmanager
    async def lifespan(app):
        """Keep follow-ups/workflow processing alive independently of browser activity."""
        stop = asyncio.Event()
        task = None
        if worker_enabled and os.getenv("AUDIT_WORKER_ENABLED", "1") == "1" and inspect(engine).has_table("agent_sessions"):
            active = get_runtime()

            async def worker():
                """Run bounded activations independently of the browser."""
                while not stop.is_set():
                    try:
                        await asyncio.to_thread(active.tick)
                    except Exception as error:
                        # Mail/database failures outside a graph must remain visible, without SQL or secrets.
                        app.state.worker_error_code = type(error).__name__
                        logging.getLogger(__name__).error("Audit worker failure: %s", type(error).__name__)
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=2)
                    except TimeoutError:
                        pass
            task = asyncio.create_task(worker())
        try:
            yield
        finally:
            stop.set()
            if task:
                await task
            if holder["runtime"] is not None:
                holder["runtime"].close()

    app = FastAPI(title="Internal Audit Manager", version="0.4.0", lifespan=lifespan)
    app.include_router(create_router(service, auth))
    app.include_router(create_workspace_router(service, auth, get_runtime))

    @app.exception_handler(AuditError)
    async def business_error(request, exc):
        """Expose safe workflow errors, not SQL or provider diagnostics."""
        return JSONResponse(status_code=exc.status, content={"error": exc.code})

    @app.exception_handler(ValidationError)
    async def invalid_input(request, exc):
        """Reject invalid internal tool/review schemas without echoing submitted data."""
        return JSONResponse(status_code=422, content={"error": "invalid_input"})

    @app.exception_handler(IntegrityError)
    async def integrity_error(request, exc):
        """Keep database constraint details and submitted values out of API responses."""
        return JSONResponse(status_code=409, content={"error": "record_integrity_conflict"})

    @app.exception_handler(DataConflict)
    async def conflicting_input(request, exc):
        """Reject changed stable record IDs without overwriting existing scope."""
        return JSONResponse(status_code=409, content={"error": "record_content_conflict"})

    @app.exception_handler(ValueError)
    async def invalid_scope(request, exc):
        """Reject invalid dataset/department relationships without echoing input values."""
        return JSONResponse(status_code=422, content={"error": "invalid_scope"})

    @app.exception_handler(OperationalError)
    async def unavailable(request, exc):
        """Report an unavailable/unmigrated local database without exposing its path."""
        return JSONResponse(status_code=503, content={"error": "database_unavailable"})

    @app.get("/health")
    def health() -> dict:
        """Report local health and settings presence without asserting live connectivity."""
        return {"status": "ok", "phase": 4, "llm_mode": settings.mode,
                "live_configured": not settings.missing_credentials, "live_verified": False}

    frontend = root / "frontend/dist"
    if frontend.is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="workspace-assets")

        @app.get("/", include_in_schema=False)
        def workspace_index():
            """Serve the local workspace without masking unknown API routes."""
            return FileResponse(frontend / "index.html")
    return app
