"""Rekordbox XML export API routes."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import settings
from backend.models.database import SessionLocal
from backend.services.xml_exporter import export_library

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["export"])

# Module-level state for last export result
_last_export: dict | None = None


# --- Request/Response models ---


class ExportOptions(BaseModel):
    """Options for export request."""

    track_ids: list[int] | None = None
    output_path: str | None = None


class ExportRequest(BaseModel):
    """Request body for POST /api/export/rekordbox."""

    options: ExportOptions | None = None


class ExportResponse(BaseModel):
    """Response for POST /api/export/rekordbox."""

    tracks_exported: int
    tracks_skipped: int
    playlists_created: int
    output_path: str
    warnings: list[str]


class LastExportInfo(BaseModel):
    """Info about the last export."""

    timestamp: str
    tracks_exported: int
    output_path: str


class ExportStatusResponse(BaseModel):
    """Response for GET /api/export/rekordbox/status."""

    status: str
    last_export: LastExportInfo | None = None


# --- Routes ---


@router.post("/export/rekordbox", response_model=ExportResponse)
async def export_rekordbox(request: ExportRequest | None = None) -> ExportResponse:
    """Trigger Rekordbox XML export."""
    global _last_export

    track_ids = None
    output_path = None
    if request and request.options:
        track_ids = request.options.track_ids
        output_path = request.options.output_path

    db_session = SessionLocal()
    try:
        result = export_library(
            db_session,
            settings,
            track_ids=track_ids,
            output_path=output_path,
        )

        _last_export = {
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "tracks_exported": result.tracks_exported,
            "output_path": result.output_path,
        }

        logger.info(
            "Export complete: %d tracks, %d skipped, %d playlists",
            result.tracks_exported,
            result.tracks_skipped,
            result.playlists_created,
        )

        return ExportResponse(
            tracks_exported=result.tracks_exported,
            tracks_skipped=result.tracks_skipped,
            playlists_created=result.playlists_created,
            output_path=result.output_path,
            warnings=result.warnings,
        )
    finally:
        db_session.close()


@router.get("/export/rekordbox/status", response_model=ExportStatusResponse)
async def export_status() -> ExportStatusResponse:
    """Get current export status and last export info."""
    if _last_export is None:
        return ExportStatusResponse(status="idle")

    return ExportStatusResponse(
        status="idle",
        last_export=LastExportInfo(
            timestamp=_last_export["timestamp"],
            tracks_exported=_last_export["tracks_exported"],
            output_path=_last_export["output_path"],
        ),
    )
