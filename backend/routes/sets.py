"""Set planner API routes — CRUD, shuffle, and progress SSE."""

import asyncio
import logging

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]

from backend.config import settings
from backend.models.database import SessionLocal
from backend.services.claude_client import ClaudeClient
from backend.services.set_planner import (
    SetPlanner,
    add_track_at_position,
    create_set,
    delete_set,
    get_candidates,
    get_set,
    list_sets,
    lock_track,
    move_track,
    plan_initial_sequence,
    remove_track,
    shuffle_reorder,
    shuffle_replace,
    unlock_track,
    update_segment_description,
    update_set,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sets"])

# Module-level planner for SSE progress (one active operation at a time)
_planner: SetPlanner | None = None


# --- Request/Response models ---


class SetCreateRequest(BaseModel):
    """Request body for POST /api/sets."""

    name: str
    description: str
    source_type: str = "library"
    source_crate_ids: list[int] | None = None
    duration_minutes: int | None = None
    target_bpm_start: float | None = None
    target_bpm_end: float | None = None
    energy_arc: str | None = None
    harmonic_mixing: bool = False


class SetCreateResponse(BaseModel):
    """Response for POST /api/sets."""

    id: int
    name: str
    description: str
    status: str
    message: str


class SetSummaryResponse(BaseModel):
    """A set in the list response."""

    id: int
    name: str
    description: str
    track_count: int
    candidate_count: int
    status: str
    created_at: str
    updated_at: str


class SetDetailResponse(BaseModel):
    """Full set detail response."""

    id: int
    name: str
    description: str
    duration_minutes: int | None = None
    target_bpm_start: float | None = None
    target_bpm_end: float | None = None
    energy_arc: str | None = None
    source_type: str
    source_crate_ids: list[int] | None = None
    harmonic_mixing: bool
    status: str
    tracks: list[dict]
    candidates: list[dict]
    segments: list[dict]
    created_at: str
    updated_at: str


class SetUpdateRequest(BaseModel):
    """Request body for PUT /api/sets/{id}."""

    name: str | None = None
    description: str | None = None
    duration_minutes: int | None = None
    target_bpm_start: float | None = None
    target_bpm_end: float | None = None
    energy_arc: str | None = None
    harmonic_mixing: bool | None = None


class SetUpdateResponse(BaseModel):
    """Response for PUT /api/sets/{id}."""

    id: int
    name: str
    description: str
    status: str
    message: str


class ShuffleRequest(BaseModel):
    """Request body for POST /api/sets/{id}/shuffle."""

    mode: str  # "replace" or "reorder"


class ShuffleResponse(BaseModel):
    """Response for POST /api/sets/{id}/shuffle."""

    mode: str
    tracks_changed: int
    errors: list[str]
    message: str


class TrackAddRequest(BaseModel):
    """Request body for POST /api/sets/{id}/tracks."""

    track_id: int
    position: int


class TrackMoveRequest(BaseModel):
    """Request body for POST /api/sets/{id}/tracks/move."""

    from_position: int
    to_position: int


class SegmentUpdateRequest(BaseModel):
    """Request body for PUT /api/sets/{id}/segments/{segment_id}."""

    description: str | None = None


# --- Routes ---


@router.post("/sets", response_model=SetCreateResponse)
async def create_set_endpoint(request: SetCreateRequest) -> SetCreateResponse:
    """Create a new set and start AI planning."""
    global _planner

    db_session = SessionLocal()
    try:
        plan = create_set(
            name=request.name,
            description=request.description,
            db_session=db_session,
            source_type=request.source_type,
            source_crate_ids=request.source_crate_ids,
            duration_minutes=request.duration_minutes,
            target_bpm_start=request.target_bpm_start,
            target_bpm_end=request.target_bpm_end,
            energy_arc=request.energy_arc,
            harmonic_mixing=request.harmonic_mixing,
        )

        # Start planning in background
        async def _run_planning() -> None:
            global _planner
            bg_session = SessionLocal()
            try:
                claude_client = ClaudeClient(
                    api_key=settings.anthropic_api_key,
                    model=settings.ai_model,
                    max_requests_per_minute=settings.ai_max_requests_per_minute,
                )
                _planner = SetPlanner(settings)
                await plan_initial_sequence(plan.id, bg_session, settings, _planner, claude_client)
            except Exception:
                logger.exception("Set planning failed for set %d", plan.id)
            finally:
                bg_session.close()

        asyncio.create_task(_run_planning())

        logger.info("Set %d creation started: %s", plan.id, request.name)
        return SetCreateResponse(
            id=plan.id,
            name=plan.name,
            description=plan.description,
            status=plan.status,
            message="Set created, planning started",
        )
    finally:
        db_session.close()


@router.get("/sets", response_model=list[SetSummaryResponse])
async def list_sets_endpoint() -> list[SetSummaryResponse]:
    """List all sets with track counts."""
    db_session = SessionLocal()
    try:
        summaries = list_sets(db_session)
        return [
            SetSummaryResponse(
                id=s.id,
                name=s.name,
                description=s.description,
                track_count=s.track_count,
                candidate_count=s.candidate_count,
                status=s.status,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in summaries
        ]
    finally:
        db_session.close()


@router.get("/sets/{set_id}", response_model=SetDetailResponse)
async def get_set_endpoint(set_id: int) -> SetDetailResponse:
    """Get set detail with tracks, candidates, and segments."""
    db_session = SessionLocal()
    try:
        detail = get_set(set_id, db_session)
        return SetDetailResponse(
            id=detail.id,
            name=detail.name,
            description=detail.description,
            duration_minutes=detail.duration_minutes,
            target_bpm_start=detail.target_bpm_start,
            target_bpm_end=detail.target_bpm_end,
            energy_arc=detail.energy_arc,
            source_type=detail.source_type,
            source_crate_ids=detail.source_crate_ids,
            harmonic_mixing=detail.harmonic_mixing,
            status=detail.status,
            tracks=detail.tracks,
            candidates=detail.candidates,
            segments=detail.segments,
            created_at=detail.created_at,
            updated_at=detail.updated_at,
        )
    finally:
        db_session.close()


@router.put("/sets/{set_id}", response_model=SetUpdateResponse)
async def update_set_endpoint(set_id: int, request: SetUpdateRequest) -> SetUpdateResponse:
    """Update set metadata."""
    db_session = SessionLocal()
    try:
        plan = update_set(
            set_id,
            db_session,
            name=request.name,
            description=request.description,
            duration_minutes=request.duration_minutes,
            target_bpm_start=request.target_bpm_start,
            target_bpm_end=request.target_bpm_end,
            energy_arc=request.energy_arc,
            harmonic_mixing=request.harmonic_mixing,
        )
        return SetUpdateResponse(
            id=plan.id,
            name=plan.name,
            description=plan.description,
            status=plan.status,
            message="Set updated",
        )
    finally:
        db_session.close()


@router.delete("/sets/{set_id}")
async def delete_set_endpoint(set_id: int) -> dict:
    """Delete a set and all its tracks and segments."""
    db_session = SessionLocal()
    try:
        delete_set(set_id, db_session)
        return {"status": "deleted", "set_id": set_id}
    finally:
        db_session.close()


@router.post("/sets/{set_id}/lock/{position}")
async def lock_track_endpoint(set_id: int, position: int) -> dict:
    """Lock a track at a position."""
    db_session = SessionLocal()
    try:
        lock_track(set_id, position, db_session)
        return {"status": "locked", "set_id": set_id, "position": position}
    finally:
        db_session.close()


@router.post("/sets/{set_id}/unlock/{position}")
async def unlock_track_endpoint(set_id: int, position: int) -> dict:
    """Unlock a track at a position."""
    db_session = SessionLocal()
    try:
        unlock_track(set_id, position, db_session)
        return {"status": "unlocked", "set_id": set_id, "position": position}
    finally:
        db_session.close()


@router.put("/sets/{set_id}/segments/{segment_id}")
async def update_segment_endpoint(
    set_id: int, segment_id: int, request: SegmentUpdateRequest
) -> dict:
    """Update a segment's description."""
    db_session = SessionLocal()
    try:
        segment = update_segment_description(segment_id, request.description, db_session)
        return {
            "status": "updated",
            "segment_id": segment.id,
            "description": segment.description,
        }
    finally:
        db_session.close()


@router.post("/sets/{set_id}/shuffle", response_model=ShuffleResponse)
async def shuffle_endpoint(set_id: int, request: ShuffleRequest) -> ShuffleResponse:
    """Shuffle unlocked tracks (replace or reorder mode)."""
    global _planner

    if request.mode not in ("replace", "reorder"):
        return ShuffleResponse(
            mode=request.mode,
            tracks_changed=0,
            errors=[f"Invalid shuffle mode: {request.mode}"],
            message="Invalid mode",
        )

    if _planner is not None and _planner.is_processing:
        return ShuffleResponse(
            mode=request.mode,
            tracks_changed=0,
            errors=["A planning operation is already running"],
            message="Busy",
        )

    async def _run_shuffle() -> None:
        global _planner
        bg_session = SessionLocal()
        try:
            claude_client = ClaudeClient(
                api_key=settings.anthropic_api_key,
                model=settings.ai_model,
                max_requests_per_minute=settings.ai_max_requests_per_minute,
            )
            _planner = SetPlanner(settings)
            if request.mode == "replace":
                await shuffle_replace(set_id, bg_session, settings, _planner, claude_client)
            else:
                await shuffle_reorder(set_id, bg_session, settings, _planner, claude_client)
        except Exception:
            logger.exception("Shuffle %s failed for set %d", request.mode, set_id)
        finally:
            bg_session.close()

    asyncio.create_task(_run_shuffle())

    return ShuffleResponse(
        mode=request.mode,
        tracks_changed=0,
        errors=[],
        message=f"Shuffle ({request.mode}) started",
    )


@router.post("/sets/{set_id}/tracks")
async def add_track_endpoint(set_id: int, request: TrackAddRequest) -> dict:
    """Add a track at a specific position."""
    db_session = SessionLocal()
    try:
        add_track_at_position(set_id, request.track_id, request.position, db_session)
        return {
            "status": "added",
            "set_id": set_id,
            "track_id": request.track_id,
            "position": request.position,
        }
    finally:
        db_session.close()


@router.delete("/sets/{set_id}/tracks/{position}")
async def remove_track_endpoint(set_id: int, position: int) -> dict:
    """Remove a track at a position (moves to candidates)."""
    db_session = SessionLocal()
    try:
        remove_track(set_id, position, db_session)
        return {"status": "removed", "set_id": set_id, "position": position}
    finally:
        db_session.close()


@router.post("/sets/{set_id}/tracks/move")
async def move_track_endpoint(set_id: int, request: TrackMoveRequest) -> dict:
    """Move a track from one position to another."""
    db_session = SessionLocal()
    try:
        move_track(set_id, request.from_position, request.to_position, db_session)
        return {
            "status": "moved",
            "set_id": set_id,
            "from_position": request.from_position,
            "to_position": request.to_position,
        }
    finally:
        db_session.close()


@router.get("/sets/{set_id}/candidates")
async def get_candidates_endpoint(set_id: int) -> list[dict]:
    """Get the candidate pool for a set."""
    db_session = SessionLocal()
    try:
        return get_candidates(set_id, db_session)
    finally:
        db_session.close()


@router.get("/sets/{set_id}/progress")
async def set_progress(set_id: int):
    """SSE endpoint streaming set planning/shuffle progress events."""
    if _planner is None:

        async def empty_stream():
            yield {"event": "error", "data": "No active planning operation"}

        return EventSourceResponse(empty_stream())

    return EventSourceResponse(_planner.event_generator())
