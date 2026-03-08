"""FastAPI application entry point for rekordbot."""

import logging
import os
import signal
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend.services.config_manager import apply_config_to_env, get_db_path, load_config

# Load config from JSON file BEFORE Settings instantiation.
# This sets env vars that pydantic-settings will pick up.
_config = load_config()
apply_config_to_env(_config)

# In packaged mode (--parent-pid present), use app data directory for DB.
if "--parent-pid" in sys.argv and "REKORDBOT_DB_URL" not in os.environ:
    os.environ["REKORDBOT_DB_URL"] = get_db_path()

from backend.config import settings  # noqa: E402
from backend.exceptions import RekordBotError  # noqa: E402
from backend.models.database import init_db  # noqa: E402
from backend.routes.ai_tagging import router as ai_tagging_router  # noqa: E402
from backend.routes.crates import router as crates_router  # noqa: E402
from backend.routes.export import router as export_router  # noqa: E402
from backend.routes.ingest import router as ingest_router  # noqa: E402
from backend.routes.organise import router as organise_router  # noqa: E402
from backend.routes.sets import router as sets_router  # noqa: E402
from backend.routes.settings import router as settings_router  # noqa: E402
from backend.routes.tagging import router as tagging_router  # noqa: E402

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan — initialise database on startup."""
    init_db()
    logger.info("rekordbot backend started on port %d", settings.port)
    yield


app = FastAPI(title="rekordbot", version="0.1.0", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:1420",
    ],
    allow_credentials=True,
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
