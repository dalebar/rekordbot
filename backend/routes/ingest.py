"""Ingestion API routes — file processing, progress, and track listing."""

import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]

from backend.config import settings
from backend.models.database import SessionLocal
from backend.models.track import Track
from backend.services.queue import ProcessingQueue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["ingest"])

# Supported audio file extensions
SUPPORTED_EXTENSIONS = frozenset({".wav", ".flac", ".aiff", ".aif", ".mp3", ".m4a"})

# Module-level queue instance (one active batch at a time)
_queue: ProcessingQueue | None = None


class IngestOptions(BaseModel):
    """Per-ingest option overrides."""

    convert_aac_to_mp3: bool | None = None


class IngestRequest(BaseModel):
    """Request body for POST /api/ingest."""

    paths: list[str]
    options: IngestOptions | None = None


class IngestResponse(BaseModel):
    """Response for POST /api/ingest."""

    batch_id: str
    total_files: int
    message: str


class TrackResponse(BaseModel):
    """Serialized track for API responses."""

    id: int
    file_path: str
    source_path: str | None
    source_format: str | None
    source_codec: str | None
    source_bitrate: int | None
    output_format: str | None
    duration: float | None
    quality_warning: bool
    conversion_action: str | None
    imported_at: str | None

    model_config = {"from_attributes": True}


class TrackListResponse(BaseModel):
    """Response for GET /api/tracks."""

    tracks: list[TrackResponse]
    total: int
    limit: int
    offset: int


def _expand_paths(paths: list[str]) -> list[Path]:
    """Expand directories recursively and filter to supported audio files.

    Args:
        paths: List of file or directory paths.

    Returns:
        List of resolved file paths with supported extensions.
    """
    result: list[Path] = []
    for path_str in paths:
        path = Path(path_str).expanduser().resolve()
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS:
                    result.append(child)
        elif path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            result.append(path)
        else:
            logger.warning("Skipping unsupported or missing path: %s", path)
    return result


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest) -> IngestResponse:
    """Start processing a batch of audio files.

    Accepts file and directory paths, expands directories, filters to
    supported audio formats, and dispatches to the processing queue.
    """
    global _queue

    if _queue is not None and _queue.is_processing:
        return IngestResponse(
            batch_id="",
            total_files=0,
            message="A batch is already being processed. Cancel it first.",
        )

    # Expand paths and filter to supported files
    file_paths = _expand_paths(request.paths)
    if not file_paths:
        return IngestResponse(
            batch_id="",
            total_files=0,
            message="No supported audio files found in the provided paths.",
        )

    # Apply per-ingest options
    queue_settings = settings.model_copy()
    if request.options and request.options.convert_aac_to_mp3 is not None:
        queue_settings.convert_aac_to_mp3 = request.options.convert_aac_to_mp3

    batch_id = str(uuid.uuid4())
    _queue = ProcessingQueue(queue_settings)
    db_session = SessionLocal()

    # Start processing in background
    async def _run_batch() -> None:
        try:
            await _queue.process_batch(file_paths, db_session)
        except Exception:
            logger.exception("Batch processing failed")
        finally:
            db_session.close()

    asyncio.create_task(_run_batch())

    logger.info("Batch %s started with %d files", batch_id, len(file_paths))
    return IngestResponse(
        batch_id=batch_id,
        total_files=len(file_paths),
        message="Processing started",
    )


@router.get("/ingest/progress")
async def ingest_progress():
    """SSE endpoint streaming file processing progress events."""
    if _queue is None:

        async def empty_stream():
            yield {"event": "error", "data": "No active batch"}

        return EventSourceResponse(empty_stream())

    return EventSourceResponse(_queue.event_generator())


@router.post("/ingest/cancel")
async def ingest_cancel() -> dict:
    """Cancel the current batch processing."""
    if _queue is None or not _queue.is_processing:
        return {"status": "no_active_batch", "message": "No batch is currently processing."}

    _queue.cancel()
    return {"status": "cancelling", "message": "Cancellation requested."}


@router.get("/tracks", response_model=TrackListResponse)
async def list_tracks(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TrackListResponse:
    """List all tracks in the database with pagination."""
    db_session = SessionLocal()
    try:
        total = db_session.query(Track).count()
        tracks = (
            db_session.query(Track).order_by(Track.id.desc()).offset(offset).limit(limit).all()
        )
        return TrackListResponse(
            tracks=[
                TrackResponse(
                    id=t.id,
                    file_path=t.file_path,
                    source_path=t.source_path,
                    source_format=t.source_format,
                    source_codec=t.source_codec,
                    source_bitrate=t.source_bitrate,
                    output_format=t.output_format,
                    duration=t.duration,
                    quality_warning=t.quality_warning,
                    conversion_action=t.conversion_action,
                    imported_at=t.imported_at.isoformat() if t.imported_at else None,
                )
                for t in tracks
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
    finally:
        db_session.close()
