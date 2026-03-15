"""Tagging API routes — analysis, tag editing, revert, and tag writing."""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]

from backend.config import settings
from backend.models.crate import CrateTrack
from backend.models.database import SessionLocal
from backend.models.set_plan import SetTrack
from backend.models.track import Track
from backend.services.analysis import AnalysisQueue, write_tags_batch
from backend.services.key_notation import key_to_display

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["tagging"])

# Module-level analysis queue (one active batch at a time)
_analysis_queue: AnalysisQueue | None = None


# --- Request/Response models ---


class AnalysisOptions(BaseModel):
    """Options for analysis."""

    bpm_range_min: int | None = None
    bpm_range_max: int | None = None
    skip_if_analysed: bool = True


class AnalyseRequest(BaseModel):
    """Request body for POST /api/tracks/analyse."""

    track_ids: list[int] | None = None
    options: AnalysisOptions | None = None


class AnalyseResponse(BaseModel):
    """Response for POST /api/tracks/analyse."""

    batch_id: str
    total_tracks: int
    message: str


class WriteTagsRequest(BaseModel):
    """Request body for POST /api/tracks/write-tags."""

    track_ids: list[int]


class WriteTagsResponse(BaseModel):
    """Response for POST /api/tracks/write-tags."""

    total: int
    succeeded: int
    failed: int


class TrackUpdate(BaseModel):
    """Partial update for a single track."""

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    genre: str | None = None
    year: int | None = None
    track_number: int | None = None
    comment: str | None = None
    label: str | None = None
    bpm: float | None = None
    key: int | None = None
    rating: int | None = None
    subgenre: str | None = None
    mood: str | None = None
    energy: int | None = None


class DeleteTracksRequest(BaseModel):
    """Request body for DELETE /api/tracks."""

    track_ids: list[int]
    delete_files: bool = False


class DeleteTracksResponse(BaseModel):
    """Response for DELETE /api/tracks."""

    deleted: int
    not_found: int
    file_errors: int


class BPMMultiplyRequest(BaseModel):
    """Request body for PUT /api/tracks/{id}/bpm-multiply."""

    factor: float


class TrackDetailResponse(BaseModel):
    """Full track detail for API responses."""

    id: int
    file_path: str
    source_path: str | None = None
    source_format: str | None = None
    source_codec: str | None = None
    source_bitrate: int | None = None
    output_format: str | None = None
    duration: float | None = None
    quality_warning: bool = False
    conversion_action: str | None = None
    imported_at: str | None = None

    # Metadata
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    genre: str | None = None
    year: int | None = None
    track_number: int | None = None
    comment: str | None = None
    label: str | None = None
    bpm: float | None = None
    key: int | None = None
    key_display: str | None = None
    rating: int = 0

    # Analysis
    analysis_status: str = "unanalysed"
    bpm_confidence: float | None = None
    key_confidence: float | None = None
    source_bpm: float | None = None
    source_key: int | None = None
    has_bpm_conflict: bool = False
    has_key_conflict: bool = False

    # AI tagging
    subgenre: str | None = None
    mood: str | None = None
    energy: int | None = None
    ai_confidence: str | None = None
    ai_reasoning: str | None = None
    source_genre: str | None = None
    ai_status: str = "untagged"

    # Organisation
    organisation_status: str = "unorganised"
    proposed_path: str | None = None
    previous_output_path: str | None = None
    organisation_confidence: float | None = None

    model_config = {"from_attributes": True}


class EnhancedTrackListResponse(BaseModel):
    """Response for GET /api/tracks with analysis metadata."""

    tracks: list[TrackDetailResponse]
    total: int
    limit: int
    offset: int


def _track_to_detail(track: Track) -> TrackDetailResponse:
    """Convert a Track model instance to a TrackDetailResponse."""
    key_display = key_to_display(track.key, settings.default_key_notation) if track.key else None

    # Detect conflicts between detected and source values
    has_bpm_conflict = (
        track.bpm is not None
        and track.source_bpm is not None
        and abs(track.bpm - track.source_bpm) > 0.5
    )
    has_key_conflict = (
        track.key is not None and track.source_key is not None and track.key != track.source_key
    )

    return TrackDetailResponse(
        id=track.id,
        file_path=track.file_path,
        source_path=track.source_path,
        source_format=track.source_format,
        source_codec=track.source_codec,
        source_bitrate=track.source_bitrate,
        output_format=track.output_format,
        duration=track.duration,
        quality_warning=track.quality_warning,
        conversion_action=track.conversion_action,
        imported_at=track.imported_at.isoformat() if track.imported_at else None,
        title=track.title,
        artist=track.artist,
        album=track.album,
        genre=track.genre,
        year=track.year,
        track_number=track.track_number,
        comment=track.comment,
        label=track.label,
        bpm=track.bpm,
        key=track.key,
        key_display=key_display,
        rating=track.rating,
        analysis_status=track.analysis_status,
        bpm_confidence=track.bpm_confidence,
        key_confidence=track.key_confidence,
        source_bpm=track.source_bpm,
        source_key=track.source_key,
        has_bpm_conflict=has_bpm_conflict,
        has_key_conflict=has_key_conflict,
        subgenre=track.subgenre,
        mood=track.mood,
        energy=track.energy,
        ai_confidence=track.ai_confidence,
        ai_reasoning=track.ai_reasoning,
        source_genre=track.source_genre,
        ai_status=track.ai_status,
        organisation_status=track.organisation_status,
        proposed_path=track.proposed_path,
        previous_output_path=track.previous_output_path,
        organisation_confidence=track.organisation_confidence,
    )


# --- Routes ---


@router.post("/tracks/analyse", response_model=AnalyseResponse)
async def analyse_tracks(request: AnalyseRequest) -> AnalyseResponse:
    """Start analysis on selected tracks or all unanalysed tracks."""
    global _analysis_queue

    if _analysis_queue is not None and _analysis_queue.is_processing:
        return AnalyseResponse(
            batch_id="",
            total_tracks=0,
            message="An analysis batch is already running. Cancel it first.",
        )

    db_session = SessionLocal()
    try:
        # Build query for tracks to analyse
        query = db_session.query(Track)

        if request.track_ids:
            query = query.filter(Track.id.in_(request.track_ids))
        else:
            # Default: all unanalysed tracks
            query = query.filter(Track.analysis_status == "unanalysed")

        # Apply skip_if_analysed option
        if request.options and request.options.skip_if_analysed and request.track_ids:
            query = query.filter(Track.analysis_status != "analysed")

        tracks = query.all()

        if not tracks:
            return AnalyseResponse(
                batch_id="",
                total_tracks=0,
                message="No tracks to analyse.",
            )

        # Apply per-request option overrides
        queue_settings = settings.model_copy()
        if request.options:
            if request.options.bpm_range_min is not None:
                queue_settings.bpm_range_min = request.options.bpm_range_min
            if request.options.bpm_range_max is not None:
                queue_settings.bpm_range_max = request.options.bpm_range_max

        import uuid

        batch_id = str(uuid.uuid4())
        _analysis_queue = AnalysisQueue(queue_settings)

        # Start analysis in background
        async def _run_batch() -> None:
            try:
                await _analysis_queue.analyse_batch(tracks, db_session)
            except Exception:
                logger.exception("Analysis batch failed")
            finally:
                db_session.close()

        asyncio.create_task(_run_batch())

        logger.info("Analysis batch %s started with %d tracks", batch_id, len(tracks))
        return AnalyseResponse(
            batch_id=batch_id,
            total_tracks=len(tracks),
            message="Analysis started",
        )
    except Exception:
        db_session.close()
        raise


@router.get("/tracks/analyse/progress")
async def analysis_progress():
    """SSE endpoint streaming analysis progress events."""
    if _analysis_queue is None:

        async def empty_stream():
            yield {"event": "error", "data": "No active analysis batch"}

        return EventSourceResponse(empty_stream())

    return EventSourceResponse(_analysis_queue.event_generator())


@router.post("/tracks/analyse/cancel")
async def cancel_analysis() -> dict:
    """Cancel the current analysis batch."""
    if _analysis_queue is None or not _analysis_queue.is_processing:
        return {"status": "no_active_batch", "message": "No analysis batch is running."}

    _analysis_queue.cancel()
    return {"status": "cancelling", "message": "Cancellation requested."}


@router.post("/tracks/write-tags", response_model=WriteTagsResponse)
async def write_tags(request: WriteTagsRequest) -> WriteTagsResponse:
    """Write tags to files for selected tracks."""
    db_session = SessionLocal()
    try:
        tracks = db_session.query(Track).filter(Track.id.in_(request.track_ids)).all()

        if not tracks:
            return WriteTagsResponse(total=0, succeeded=0, failed=0)

        results = await write_tags_batch(tracks, db_session)

        # Update ai_status for AI-tagged tracks that were written successfully
        for track, result in zip(tracks, results, strict=False):
            if result.success and track.ai_status == "ai_tagged":
                track.ai_status = "ai_tags_written"
        db_session.commit()

        succeeded = sum(1 for r in results if r.success)
        failed = sum(1 for r in results if not r.success)

        return WriteTagsResponse(total=len(results), succeeded=succeeded, failed=failed)
    finally:
        db_session.close()


@router.put("/tracks/{track_id}")
async def update_track(track_id: int, update: TrackUpdate) -> TrackDetailResponse:
    """Update a single track's metadata (partial update)."""
    db_session = SessionLocal()
    try:
        track = db_session.query(Track).filter(Track.id == track_id).first()
        if track is None:
            from backend.exceptions import RekordBotError

            raise RekordBotError(
                error="track_not_found",
                detail=f"Track {track_id} not found",
                status_code=404,
            )

        # Apply only non-None fields from the update
        update_data = update.model_dump(exclude_unset=True)
        for field_name, value in update_data.items():
            setattr(track, field_name, value)

        db_session.commit()
        db_session.refresh(track)
        return _track_to_detail(track)
    finally:
        db_session.close()


@router.put("/tracks/{track_id}/revert/{field}")
async def revert_field(track_id: int, field: str) -> TrackDetailResponse:
    """Revert a field to its original source value."""
    db_session = SessionLocal()
    try:
        track = db_session.query(Track).filter(Track.id == track_id).first()
        if track is None:
            from backend.exceptions import RekordBotError

            raise RekordBotError(
                error="track_not_found",
                detail=f"Track {track_id} not found",
                status_code=404,
            )

        if field == "bpm":
            if track.source_bpm is None:
                from backend.exceptions import RekordBotError

                raise RekordBotError(
                    error="no_source_value",
                    detail="No original BPM value to revert to",
                    status_code=404,
                )
            track.bpm = track.source_bpm
        elif field == "key":
            if track.source_key is None:
                from backend.exceptions import RekordBotError

                raise RekordBotError(
                    error="no_source_value",
                    detail="No original key value to revert to",
                    status_code=404,
                )
            track.key = track.source_key
        elif field == "genre":
            if track.source_genre is None:
                from backend.exceptions import RekordBotError

                raise RekordBotError(
                    error="no_source_value",
                    detail="No original genre value to revert to",
                    status_code=404,
                )
            track.genre = track.source_genre
        else:
            from backend.exceptions import RekordBotError

            raise RekordBotError(
                error="invalid_field",
                detail=f"Cannot revert field '{field}'. "
                "Only 'bpm', 'key', and 'genre' are supported.",
                status_code=400,
            )

        db_session.commit()
        db_session.refresh(track)
        return _track_to_detail(track)
    finally:
        db_session.close()


@router.put("/tracks/{track_id}/bpm-multiply")
async def bpm_multiply(track_id: int, request: BPMMultiplyRequest) -> TrackDetailResponse:
    """Double or halve a track's BPM."""
    if request.factor not in (2, 0.5):
        from backend.exceptions import RekordBotError

        raise RekordBotError(
            error="invalid_factor",
            detail="Factor must be 2 or 0.5",
            status_code=400,
        )

    db_session = SessionLocal()
    try:
        track = db_session.query(Track).filter(Track.id == track_id).first()
        if track is None:
            from backend.exceptions import RekordBotError

            raise RekordBotError(
                error="track_not_found",
                detail=f"Track {track_id} not found",
                status_code=404,
            )

        if track.bpm is None:
            from backend.exceptions import RekordBotError

            raise RekordBotError(
                error="no_bpm",
                detail="Track has no BPM value to multiply",
                status_code=400,
            )

        track.bpm = round(track.bpm * request.factor, 2)
        db_session.commit()
        db_session.refresh(track)
        return _track_to_detail(track)
    finally:
        db_session.close()


@router.get("/tracks", response_model=EnhancedTrackListResponse)
async def list_tracks(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> EnhancedTrackListResponse:
    """List all tracks with analysis metadata, sortable/filterable."""
    db_session = SessionLocal()
    try:
        total = db_session.query(Track).count()
        tracks = (
            db_session.query(Track).order_by(Track.id.desc()).offset(offset).limit(limit).all()
        )
        return EnhancedTrackListResponse(
            tracks=[_track_to_detail(t) for t in tracks],
            total=total,
            limit=limit,
            offset=offset,
        )
    finally:
        db_session.close()


@router.delete("/tracks", response_model=DeleteTracksResponse)
async def delete_tracks(request: DeleteTracksRequest) -> DeleteTracksResponse:
    """Delete tracks by ID, optionally removing output files from disk."""
    if not request.track_ids:
        return DeleteTracksResponse(deleted=0, not_found=0, file_errors=0)

    db_session = SessionLocal()
    try:
        tracks = db_session.query(Track).filter(Track.id.in_(request.track_ids)).all()
        found_ids = {t.id for t in tracks}
        not_found = len(request.track_ids) - len(found_ids)
        file_errors = 0

        if request.delete_files:
            for track in tracks:
                try:
                    file_path = Path(track.file_path)
                    if file_path.exists():
                        file_path.unlink()
                        logger.info("Deleted file: %s", track.file_path)
                    else:
                        logger.info("File already missing: %s", track.file_path)
                except OSError:
                    logger.exception("Failed to delete file: %s", track.file_path)
                    file_errors += 1

        # Delete associated CrateTrack and SetTrack rows, then tracks
        db_session.query(CrateTrack).filter(CrateTrack.track_id.in_(found_ids)).delete(
            synchronize_session="fetch"
        )
        db_session.query(SetTrack).filter(SetTrack.track_id.in_(found_ids)).delete(
            synchronize_session="fetch"
        )
        db_session.query(Track).filter(Track.id.in_(found_ids)).delete(synchronize_session="fetch")
        db_session.commit()

        logger.info("Deleted %d tracks (%d not found)", len(found_ids), not_found)
        return DeleteTracksResponse(
            deleted=len(found_ids),
            not_found=not_found,
            file_errors=file_errors,
        )
    finally:
        db_session.close()
