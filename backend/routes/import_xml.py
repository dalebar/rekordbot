"""Rekordbox XML import API routes."""

import asyncio
import contextlib
import logging
from pathlib import Path
from threading import Event

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]

from backend.models.database import SessionLocal
from backend.services.conflict_resolver import (
    get_pending_conflicts,
    resolve_all_rekordbot,
    resolve_all_rekordbox,
    resolve_conflict,
)
from backend.services.xml_importer import ImportProgress, ImportSummary, run_import

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["import"])

# Module-level state for import management
_import_in_progress = False
_cancel_event: Event | None = None
_last_progress: ImportProgress | None = None
_last_summary: ImportSummary | None = None
_progress_queue: asyncio.Queue | None = None  # type: ignore[type-arg]


# --- Request/Response models ---


class ImportRequest(BaseModel):
    """Request body for POST /api/import/rekordbox."""

    file_path: str


class ImportResponse(BaseModel):
    """Response for POST /api/import/rekordbox."""

    status: str
    message: str


class ImportSummaryResponse(BaseModel):
    """Import summary in the response."""

    tracks_total: int
    tracks_imported: int
    tracks_matched: int
    tracks_conflict: int
    tracks_skipped: int
    skipped_reasons: list[str]
    playlists_imported: int
    playlists_skipped: int


class ConflictField(BaseModel):
    """A single field conflict."""

    field: str
    rekordbox_value: object
    rekordbot_value: object
    recommended: str


class ConflictTrack(BaseModel):
    """A track with conflicts."""

    track_id: int
    title: str | None
    artist: str | None
    file_path: str
    conflicts: list[ConflictField]


class ResolveRequest(BaseModel):
    """Request body for resolving a single track's conflicts."""

    resolutions: dict[str, str]


class ResolveAllRequest(BaseModel):
    """Request body for bulk conflict resolution."""

    strategy: str  # "rekordbox" or "rekordbot"


# --- Routes ---


@router.post("/import/rekordbox", response_model=ImportResponse)
async def start_import(request: ImportRequest) -> ImportResponse:
    """Start a Rekordbox XML import."""
    global _import_in_progress, _cancel_event, _last_progress, _last_summary, _progress_queue

    if _import_in_progress:
        return ImportResponse(
            status="error",
            message="An import is already in progress",
        )

    file_path = Path(request.file_path)
    if not file_path.exists():
        return ImportResponse(
            status="error",
            message=f"File not found: {request.file_path}",
        )

    _import_in_progress = True
    _cancel_event = Event()
    _last_progress = None
    _last_summary = None
    _progress_queue = asyncio.Queue()

    # Run import in background thread
    asyncio.get_event_loop().run_in_executor(
        None, _run_import_sync, file_path, _cancel_event, _progress_queue
    )

    return ImportResponse(
        status="started",
        message=f"Import started for {request.file_path}",
    )


def _run_import_sync(
    file_path: Path,
    cancel_event: Event,
    progress_queue: asyncio.Queue,  # type: ignore[type-arg]
) -> None:
    """Run the import in a sync thread."""
    global _import_in_progress, _last_summary, _last_progress

    db = SessionLocal()
    try:

        def progress_callback(progress: ImportProgress) -> None:
            global _last_progress
            _last_progress = progress
            with contextlib.suppress(asyncio.QueueFull):
                progress_queue.put_nowait(("progress", progress))

        def cancel_check() -> bool:
            return cancel_event.is_set()

        summary = run_import(
            file_path,
            db,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        _last_summary = summary
        with contextlib.suppress(asyncio.QueueFull):
            progress_queue.put_nowait(("complete", summary))

    except Exception as e:
        logger.exception("Import failed: %s", e)
        with contextlib.suppress(asyncio.QueueFull):
            progress_queue.put_nowait(("error", str(e)))
    finally:
        db.close()
        _import_in_progress = False


@router.get("/import/progress")
async def import_progress() -> EventSourceResponse:
    """SSE stream for import progress."""

    async def event_generator():
        if _progress_queue is None:
            yield {
                "event": "xml_import_error",
                "data": '{"error": "no_import", "detail": "No import in progress"}',
            }
            return

        import json

        while True:
            try:
                event_type, data = await asyncio.wait_for(_progress_queue.get(), timeout=30.0)
            except TimeoutError:
                # Send keepalive
                yield {"event": "keepalive", "data": "{}"}
                continue

            if event_type == "progress":
                yield {
                    "event": "xml_import_progress",
                    "data": json.dumps(
                        {
                            "processed": data.processed,
                            "total": data.total,
                            "imported": data.imported,
                            "matched": data.matched,
                            "skipped": data.skipped,
                            "conflicts": data.conflicts,
                        }
                    ),
                }
            elif event_type == "complete":
                yield {
                    "event": "xml_import_complete",
                    "data": json.dumps(
                        {
                            "summary": {
                                "tracks_total": data.tracks_total,
                                "tracks_imported": data.tracks_imported,
                                "tracks_matched": data.tracks_matched,
                                "tracks_conflict": data.tracks_conflict,
                                "tracks_skipped": data.tracks_skipped,
                                "skipped_reasons": data.skipped_reasons,
                                "playlists_imported": data.playlists_imported,
                                "playlists_skipped": data.playlists_skipped,
                            }
                        }
                    ),
                }
                return
            elif event_type == "error":
                yield {
                    "event": "xml_import_error",
                    "data": json.dumps(
                        {
                            "error": "import_failed",
                            "detail": data,
                        }
                    ),
                }
                return

    return EventSourceResponse(event_generator())


@router.post("/import/cancel")
async def cancel_import() -> dict:
    """Cancel an in-progress import."""
    if _cancel_event is None or not _import_in_progress:
        return {"status": "no_import", "message": "No import in progress"}

    _cancel_event.set()
    return {"status": "cancelling", "message": "Import cancellation requested"}


@router.get("/import/conflicts", response_model=list[ConflictTrack])
async def list_conflicts() -> list[ConflictTrack]:
    """Get all pending import conflicts."""
    db = SessionLocal()
    try:
        raw = get_pending_conflicts(db)
        return [
            ConflictTrack(
                track_id=item["track_id"],
                title=item["title"],
                artist=item["artist"],
                file_path=item["file_path"],
                conflicts=[
                    ConflictField(
                        field=c["field"],
                        rekordbox_value=c["rekordbox_value"],
                        rekordbot_value=c["rekordbot_value"],
                        recommended=c["recommended"],
                    )
                    for c in item["conflicts"]
                ],
            )
            for item in raw
        ]
    finally:
        db.close()


@router.post("/import/conflicts/{track_id}/resolve")
async def resolve_track_conflicts(track_id: int, request: ResolveRequest) -> dict:
    """Resolve conflicts for a single track."""
    db = SessionLocal()
    try:
        track = resolve_conflict(track_id, request.resolutions, db)
        db.commit()
        return {
            "status": "resolved",
            "track_id": track.id,
            "message": f"Resolved {len(request.resolutions)} conflicts",
        }
    except ValueError as e:
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


@router.post("/import/conflicts/resolve-all")
async def resolve_all_conflicts(request: ResolveAllRequest) -> dict:
    """Bulk resolve all import conflicts."""
    db = SessionLocal()
    try:
        if request.strategy == "rekordbox":
            count = resolve_all_rekordbox(db)
        elif request.strategy == "rekordbot":
            count = resolve_all_rekordbot(db)
        else:
            return {"status": "error", "message": f"Unknown strategy: {request.strategy}"}

        db.commit()
        return {
            "status": "resolved",
            "count": count,
            "strategy": request.strategy,
            "message": f"Resolved {count} tracks with {request.strategy} values",
        }
    finally:
        db.close()
