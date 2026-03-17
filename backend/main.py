"""FastAPI application entry point for rekordbot."""

import logging
import logging.handlers
import os
import shutil
import signal
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.services.config_manager import apply_config_to_env, get_db_path, load_config
from backend.services.watchdog import parse_parent_pid, start_watchdog

# Load config from JSON file BEFORE Settings instantiation.
# This sets env vars that pydantic-settings will pick up.
_config = load_config()
apply_config_to_env(_config)

# In packaged mode (--parent-pid present), configure paths for .app bundle.
if "--parent-pid" in sys.argv:
    if "REKORDBOT_DB_URL" not in os.environ:
        os.environ["REKORDBOT_DB_URL"] = get_db_path()

    # Resolve bundled ffmpeg/ffprobe in .app bundle.
    # Sidecar is at Contents/MacOS/sidecar/rekordbot-server
    # Resources are at Contents/Resources/
    _resources_dir = Path(sys.executable).parent.parent.parent / "Resources"
    _bundled_ffmpeg = _resources_dir / "ffmpeg"
    if _bundled_ffmpeg.exists():
        os.environ.setdefault("REKORDBOT_FFMPEG_PATH", str(_bundled_ffmpeg))
    _bundled_ffprobe = _resources_dir / "ffprobe"
    if _bundled_ffprobe.exists():
        os.environ.setdefault("REKORDBOT_FFPROBE_PATH", str(_bundled_ffprobe))

from backend.config import settings  # noqa: E402
from backend.exceptions import RekordBotError  # noqa: E402
from backend.models.database import engine  # noqa: E402
from backend.routes.ai_tagging import router as ai_tagging_router  # noqa: E402
from backend.routes.crates import router as crates_router  # noqa: E402
from backend.routes.export import router as export_router  # noqa: E402
from backend.routes.import_xml import router as import_xml_router  # noqa: E402
from backend.routes.ingest import router as ingest_router  # noqa: E402
from backend.routes.organise import router as organise_router  # noqa: E402
from backend.routes.sets import router as sets_router  # noqa: E402
from backend.routes.settings import router as settings_router  # noqa: E402
from backend.routes.tagging import router as tagging_router  # noqa: E402
from backend.services.migration_runner import run_migrations  # noqa: E402

# Ensure UTF-8 output encoding in bundled mode (PyInstaller with piped
# stdout defaults to ASCII when not attached to a terminal).
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

# Configure logging
_log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
_log_format = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
_log_datefmt = "%H:%M:%S"

logging.basicConfig(level=_log_level, format=_log_format, datefmt=_log_datefmt)

# In packaged mode, also log to a rotating file for debugging
if "--parent-pid" in sys.argv:
    _log_dir = Path.home() / "Library" / "Application Support" / "rekordbot"
    _log_dir.mkdir(parents=True, exist_ok=True)
    _file_handler = logging.handlers.RotatingFileHandler(
        _log_dir / "rekordbot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    _file_handler.setLevel(_log_level)
    _file_handler.setFormatter(logging.Formatter(_log_format, datefmt=_log_datefmt))
    logging.getLogger().addHandler(_file_handler)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — run migrations and initialise on startup."""
    run_migrations(engine)
    logger.info("rekordbot backend started on port %d", settings.port)

    # Startup health checks (non-blocking — log warnings only)
    _run_startup_health_checks()

    # Start watchdog if running as sidecar (--parent-pid provided)
    parent_pid = parse_parent_pid()
    if parent_pid is not None:
        start_watchdog(parent_pid)

    yield


app = FastAPI(title="rekordbot", version="0.1.0", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UnhandledExceptionMiddleware(BaseHTTPMiddleware):
    """Catch unhandled exceptions and return a generic 500 JSON response."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        """Process request, catching any unhandled exceptions."""
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "detail": "An unexpected error occurred."},
            )


app.add_middleware(UnhandledExceptionMiddleware)

# Register routers
app.include_router(ingest_router)
app.include_router(tagging_router)
app.include_router(ai_tagging_router)
app.include_router(organise_router)
app.include_router(export_router)
app.include_router(import_xml_router)
app.include_router(crates_router)
app.include_router(sets_router)
app.include_router(settings_router)


@app.exception_handler(RekordBotError)
async def rekordbot_error_handler(request: Request, exc: RekordBotError) -> JSONResponse:
    """Handle known application errors with a consistent JSON response."""
    logger.error("%s: %s", exc.error, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "detail": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle pydantic validation errors with a consistent JSON response."""
    errors = exc.errors()
    detail = "; ".join(f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in errors)
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": detail},
    )


@app.get("/health")
async def health() -> dict:
    """Health check endpoint for sidecar readiness detection."""
    return {"status": "ok", "version": "0.1.0"}


@app.post("/shutdown")
async def shutdown() -> dict:
    """Graceful shutdown endpoint for sidecar lifecycle management."""
    logger.info("Shutdown requested")
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutting_down"}


def _run_startup_health_checks() -> None:
    """Run non-blocking health checks on startup and log warnings."""
    # Check ffmpeg
    if shutil.which(settings.ffmpeg_path) is None:
        logger.warning("ffmpeg not found at '%s' — ingestion will fail", settings.ffmpeg_path)

    # Check output directory
    output_dir = settings.output_directory
    if output_dir and output_dir != "~/rekordbot/library":
        from backend.services.config_manager import validate_output_directory

        valid, msg = validate_output_directory(output_dir)
        if not valid:
            logger.warning("Output directory issue: %s", msg)
    else:
        logger.info("No output directory configured yet")

    # Check API key
    if not settings.anthropic_api_key:
        logger.info("No API key configured — AI features disabled")


if __name__ == "__main__":
    import uvicorn

    # When running from PyInstaller, pass the app object directly since
    # the module can't be imported by name. Use the import string only
    # when --reload is requested (reload requires an import string).
    if "--reload" in sys.argv:
        uvicorn.run(
            "backend.main:app",
            host="127.0.0.1",
            port=settings.port,
            reload=True,
        )
    else:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=settings.port,
        )
