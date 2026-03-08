"""Crate API routes — CRUD, assignment, and progress SSE."""

import asyncio
import logging

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]

from backend.config import settings
from backend.models.database import SessionLocal
from backend.models.track import Track
from backend.services.claude_client import ClaudeClient
from backend.services.crate_assigner import CrateAssigner
from backend.services.crate_manager import (
    add_tracks,
    create_crate,
    delete_crate,
    get_crate,
    list_crates,
    parse_description,
    refresh_crate,
    remove_tracks,
    update_crate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["crates"])

# Module-level assigner for SSE progress (one active operation at a time)
_assigner: CrateAssigner | None = None


# --- Request/Response models ---


class CrateCreateRequest(BaseModel):
    """Request body for POST /api/crates."""

    name: str
    description: str
    auto_refresh: bool = False


class CrateCreateResponse(BaseModel):
    """Response for POST /api/crates."""

    id: int
    name: str
    description: str
    auto_refresh: bool
    message: str


class CrateSummaryResponse(BaseModel):
    """A crate in the list response."""

    id: int
    name: str
    description: str
    track_count: int
    auto_refresh: bool
    created_at: str
    updated_at: str


class CrateDetailResponse(BaseModel):
    """Full crate detail response."""

    id: int
    name: str
    description: str
    parsed_criteria: dict | None = None
    auto_refresh: bool
    track_ids: list[int]
    track_count: int
    created_at: str
    updated_at: str


class CrateUpdateRequest(BaseModel):
    """Request body for PUT /api/crates/{id}."""

    name: str | None = None
    description: str | None = None
    auto_refresh: bool | None = None


class CrateUpdateResponse(BaseModel):
    """Response for PUT /api/crates/{id}."""

    id: int
    name: str
    description: str
    auto_refresh: bool
    description_changed: bool
    message: str


class TrackAddRequest(BaseModel):
    """Request body for POST /api/crates/{id}/tracks."""

    track_ids: list[int]


class TrackRemoveRequest(BaseModel):
    """Request body for DELETE /api/crates/{id}/tracks."""

    track_ids: list[int]


# --- Routes ---


@router.post("/crates", response_model=CrateCreateResponse)
async def create_crate_endpoint(request: CrateCreateRequest) -> CrateCreateResponse:
    """Create a new crate and start AI assignment."""
    global _assigner

    db_session = SessionLocal()
    try:
        crate = create_crate(request.name, request.description, request.auto_refresh, db_session)

        # Parse description and assign tracks in background
        async def _run_pipeline() -> None:
            global _assigner
            bg_session = SessionLocal()
            try:
                # Reload crate in this session
                from backend.models.crate import Crate

                bg_crate = bg_session.query(Crate).filter(Crate.id == crate.id).first()
                if bg_crate is None:
                    return

                # Parse description
                await parse_description(bg_crate, bg_session, settings)

                # Assign tracks
                tracks = bg_session.query(Track).all()
                if tracks:
                    claude_client = ClaudeClient(
                        api_key=settings.anthropic_api_key,
                        model=settings.ai_model,
                        max_requests_per_minute=settings.ai_max_requests_per_minute,
                    )
                    _assigner = CrateAssigner(settings)
                    await _assigner.assign_tracks(bg_crate, tracks, bg_session, claude_client)
            except Exception:
                logger.exception("Crate creation pipeline failed for crate %d", crate.id)
            finally:
                bg_session.close()

        asyncio.create_task(_run_pipeline())

        logger.info("Crate %d creation started: %s", crate.id, request.name)
        return CrateCreateResponse(
            id=crate.id,
            name=crate.name,
            description=crate.description,
            auto_refresh=crate.auto_refresh,
            message="Crate created, assignment started",
        )
    finally:
        db_session.close()


@router.get("/crates", response_model=list[CrateSummaryResponse])
async def list_crates_endpoint() -> list[CrateSummaryResponse]:
    """List all crates with track counts."""
    db_session = SessionLocal()
    try:
        summaries = list_crates(db_session)
        return [
            CrateSummaryResponse(
                id=s.id,
                name=s.name,
                description=s.description,
                track_count=s.track_count,
                auto_refresh=s.auto_refresh,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in summaries
        ]
    finally:
        db_session.close()


@router.get("/crates/{crate_id}", response_model=CrateDetailResponse)
async def get_crate_endpoint(crate_id: int) -> CrateDetailResponse:
    """Get crate detail with track list."""
    db_session = SessionLocal()
    try:
        detail = get_crate(crate_id, db_session)
        return CrateDetailResponse(
            id=detail.id,
            name=detail.name,
            description=detail.description,
            parsed_criteria=detail.parsed_criteria,
            auto_refresh=detail.auto_refresh,
            track_ids=detail.track_ids,
            track_count=detail.track_count,
            created_at=detail.created_at,
            updated_at=detail.updated_at,
        )
    finally:
        db_session.close()


@router.put("/crates/{crate_id}", response_model=CrateUpdateResponse)
async def update_crate_endpoint(crate_id: int, request: CrateUpdateRequest) -> CrateUpdateResponse:
    """Update a crate. Description change triggers re-assignment."""
    global _assigner

    db_session = SessionLocal()
    try:
        crate, description_changed = update_crate(
            crate_id,
            db_session,
            name=request.name,
            description=request.description,
            auto_refresh=request.auto_refresh,
        )

        message = "Crate updated"

        # If description changed, re-parse and re-assign in background
        if description_changed:
            message = "Crate updated, re-assignment started"

            async def _run_reassign() -> None:
                global _assigner
                bg_session = SessionLocal()
                try:
                    from backend.models.crate import Crate

                    bg_crate = bg_session.query(Crate).filter(Crate.id == crate_id).first()
                    if bg_crate is None:
                        return

                    await parse_description(bg_crate, bg_session, settings)

                    _assigner = CrateAssigner(settings)
                    await refresh_crate(crate_id, bg_session, settings, _assigner)
                except Exception:
                    logger.exception("Re-assignment failed for crate %d", crate_id)
                finally:
                    bg_session.close()

            asyncio.create_task(_run_reassign())

        return CrateUpdateResponse(
            id=crate.id,
            name=crate.name,
            description=crate.description,
            auto_refresh=crate.auto_refresh,
            description_changed=description_changed,
            message=message,
        )
    finally:
        db_session.close()


@router.delete("/crates/{crate_id}")
async def delete_crate_endpoint(crate_id: int) -> dict:
    """Delete a crate and all its track assignments."""
    db_session = SessionLocal()
    try:
        delete_crate(crate_id, db_session)
        return {"status": "deleted", "crate_id": crate_id}
    finally:
        db_session.close()


@router.post("/crates/{crate_id}/refresh")
async def refresh_crate_endpoint(crate_id: int) -> dict:
    """Re-run AI assignment for a crate."""
    global _assigner

    if _assigner is not None and _assigner.is_processing:
        return {"status": "busy", "message": "An assignment operation is already running."}

    async def _run_refresh() -> None:
        global _assigner
        db_session = SessionLocal()
        try:
            _assigner = CrateAssigner(settings)
            await refresh_crate(crate_id, db_session, settings, _assigner)
        except Exception:
            logger.exception("Refresh failed for crate %d", crate_id)
        finally:
            db_session.close()

    asyncio.create_task(_run_refresh())
    return {"status": "started", "message": "Crate refresh started"}


@router.post("/crates/{crate_id}/tracks")
async def add_tracks_endpoint(crate_id: int, request: TrackAddRequest) -> dict:
    """Manually add tracks to a crate."""
    db_session = SessionLocal()
    try:
        added = add_tracks(crate_id, request.track_ids, db_session)
        return {"status": "ok", "added": added, "crate_id": crate_id}
    finally:
        db_session.close()


@router.delete("/crates/{crate_id}/tracks")
async def remove_tracks_endpoint(crate_id: int, request: TrackRemoveRequest) -> dict:
    """Remove tracks from a crate."""
    db_session = SessionLocal()
    try:
        removed = remove_tracks(crate_id, request.track_ids, db_session)
        return {"status": "ok", "removed": removed, "crate_id": crate_id}
    finally:
        db_session.close()


@router.get("/crates/{crate_id}/progress")
async def crate_progress(crate_id: int):
    """SSE endpoint streaming crate assignment progress events."""
    if _assigner is None:

        async def empty_stream():
            yield {"event": "error", "data": "No active assignment operation"}

        return EventSourceResponse(empty_stream())

    return EventSourceResponse(_assigner.event_generator())
