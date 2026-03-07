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

from backend.config import settings
from backend.exceptions import RekordBotError
from backend.models.database import init_db

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
