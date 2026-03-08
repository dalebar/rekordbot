"""Organisation API routes — file organisation proposal, approval, and preferences."""

import asyncio
import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]

from backend.config import settings
from backend.exceptions import OrganisationError, RekordBotError
from backend.models.database import SessionLocal
from backend.models.track import Track
from backend.services.organiser import Organiser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["organisation"])

# Module-level organiser (one active operation at a time)
_organiser: Organiser | None = None


# --- Request/Response models ---


class OrganiseOptions(BaseModel):
    """Options for organisation proposal."""

    use_claude: bool = False
    skip_if_organised: bool = True
    confidence_threshold: float | None = None


class OrganiseRequest(BaseModel):
    """Request body for POST /api/organise/propose."""

    track_ids: list[int] | None = None
    options: OrganiseOptions | None = None


class OrganiseResponse(BaseModel):
    """Response for POST /api/organise/propose."""

    batch_id: str
    total_tracks: int
    message: str


class ApproveRequest(BaseModel):
    """Request body for POST /api/organise/approve."""

    mode: str = "auto_approved"  # "auto_approved", "specific", "all"
    track_ids: list[int] | None = None


class ApproveResponse(BaseModel):
    """Response for POST /api/organise/approve."""

    total_moved: int
    failed: int
    dirs_cleaned: int
    message: str


class ResolveRequest(BaseModel):
    """Request body for POST /api/organise/resolve/{id}."""

    action: str  # "accept", "custom", "skip"
    custom_path: str | None = None
    save_preference: bool = False
    preference_type: str | None = None


class PreferenceRuleCreate(BaseModel):
    """Request body for POST /api/preferences."""

    rule_type: str
    key: str
    value: str


class PreferenceRuleResponse(BaseModel):
    """Response for preference rule operations."""

    id: int
    rule_type: str
    key: str
    value: str
    created_at: str | None = None

    model_config = {"from_attributes": True}


class ProposalTrackResponse(BaseModel):
    """A single track in the proposal response."""

    track_id: int
    title: str | None = None
    artist: str | None = None
    current_path: str
    proposed_path: str | None = None
    confidence: float | None = None
    reasoning: str | None = None
    flags: list[str] | None = None


class ProposalResponse(BaseModel):
    """Response for GET /api/organise/proposal."""

    auto_approved: list[ProposalTrackResponse]
    needs_review: list[ProposalTrackResponse]
    failed: list[ProposalTrackResponse]
    summary: dict


# --- Routes ---


@router.post("/organise/propose", response_model=OrganiseResponse)
async def propose_organisation(request: OrganiseRequest) -> OrganiseResponse:
    """Generate organisation proposal (dry-run)."""
    global _organiser

    if _organiser is not None and _organiser.is_processing:
        return OrganiseResponse(
            batch_id="",
            total_tracks=0,
            message="An organisation operation is already running. Cancel it first.",
        )

    db_session = SessionLocal()
    try:
        # Build query
        query = db_session.query(Track)

        if request.track_ids:
            query = query.filter(Track.id.in_(request.track_ids))
        elif request.options and request.options.skip_if_organised:
            query = query.filter(Track.organisation_status == "unorganised")

        tracks = query.all()

        if not tracks:
            return OrganiseResponse(
                batch_id="",
                total_tracks=0,
                message="No tracks to organise.",
            )

        # Apply options
        org_settings = settings.model_copy()
        if request.options and request.options.confidence_threshold is not None:
            org_settings.organise_confidence_threshold = request.options.confidence_threshold

        batch_id = str(uuid.uuid4())
        _organiser = Organiser(org_settings)

        use_claude = request.options.use_claude if request.options else False

        # Start pipeline in background
        async def _run_pipeline() -> None:
            try:
                await _organiser.propose_organisation(tracks, db_session, use_claude)
            except Exception:
                logger.exception("Organisation proposal failed")
            finally:
                db_session.close()

        asyncio.create_task(_run_pipeline())

        logger.info(
            "Organisation proposal %s started: %d tracks",
            batch_id,
            len(tracks),
        )
        return OrganiseResponse(
            batch_id=batch_id,
            total_tracks=len(tracks),
            message="Organisation proposal started",
        )
    except Exception:
        db_session.close()
        raise


@router.get("/organise/progress")
async def organise_progress():
    """SSE endpoint streaming organisation progress events."""
    if _organiser is None:

        async def empty_stream():
            yield {"event": "error", "data": "No active organisation operation"}

        return EventSourceResponse(empty_stream())

    return EventSourceResponse(_organiser.event_generator())


@router.post("/organise/cancel")
async def organise_cancel() -> dict:
    """Cancel the current organisation operation."""
    if _organiser is None or not _organiser.is_processing:
        return {
            "status": "no_active_operation",
            "message": "No organisation operation is running.",
        }

    _organiser.cancel()
    return {"status": "cancelling", "message": "Cancellation requested."}


@router.get("/organise/proposal", response_model=ProposalResponse)
async def get_proposal() -> ProposalResponse:
    """Get current proposal (list of proposed moves)."""
    db_session = SessionLocal()
    try:
        auto_approved_tracks = (
            db_session.query(Track).filter(Track.organisation_status == "proposed").all()
        )
        review_tracks = (
            db_session.query(Track).filter(Track.organisation_status == "review_needed").all()
        )

        auto_approved = [
            ProposalTrackResponse(
                track_id=t.id,
                title=t.title,
                artist=t.artist,
                current_path=t.file_path,
                proposed_path=t.proposed_path,
                confidence=t.organisation_confidence,
                reasoning=t.organisation_reasoning,
            )
            for t in auto_approved_tracks
        ]

        needs_review = [
            ProposalTrackResponse(
                track_id=t.id,
                title=t.title,
                artist=t.artist,
                current_path=t.file_path,
                proposed_path=t.proposed_path,
                confidence=t.organisation_confidence,
                reasoning=t.organisation_reasoning,
            )
            for t in review_tracks
        ]

        summary = {
            "total": len(auto_approved) + len(needs_review),
            "auto_approved": len(auto_approved),
            "needs_review": len(needs_review),
            "failed": 0,
        }

        return ProposalResponse(
            auto_approved=auto_approved,
            needs_review=needs_review,
            failed=[],
            summary=summary,
        )
    finally:
        db_session.close()


@router.post("/organise/approve", response_model=ApproveResponse)
async def approve_organisation(request: ApproveRequest) -> ApproveResponse:
    """Approve and execute file moves."""
    global _organiser

    db_session = SessionLocal()
    try:
        # Build query based on mode
        query = db_session.query(Track)

        if request.mode == "auto_approved":
            query = query.filter(Track.organisation_status == "proposed")
        elif request.mode == "specific" and request.track_ids:
            query = query.filter(
                Track.id.in_(request.track_ids),
                Track.proposed_path.isnot(None),
            )
        elif request.mode == "all":
            query = query.filter(
                Track.organisation_status.in_(["proposed", "review_needed"]),
                Track.proposed_path.isnot(None),
            )
        else:
            return ApproveResponse(
                total_moved=0,
                failed=0,
                dirs_cleaned=0,
                message="Invalid mode or missing track_ids.",
            )

        tracks = query.all()

        if not tracks:
            return ApproveResponse(
                total_moved=0,
                failed=0,
                dirs_cleaned=0,
                message="No tracks to move.",
            )

        org_settings = settings.model_copy()
        organiser = Organiser(org_settings)
        result = await organiser.execute_organisation(tracks, db_session)

        return ApproveResponse(
            total_moved=result.total_moved,
            failed=result.failed,
            dirs_cleaned=result.dirs_cleaned,
            message=f"Moved {result.total_moved} files",
        )
    finally:
        db_session.close()


@router.post("/organise/resolve/{track_id}")
async def resolve_track(track_id: int, request: ResolveRequest) -> dict:
    """Resolve an ambiguous track (accept, edit, or skip)."""
    db_session = SessionLocal()
    try:
        track = db_session.query(Track).filter(Track.id == track_id).first()
        if track is None:
            raise RekordBotError(
                error="track_not_found",
                detail=f"Track {track_id} not found",
                status_code=404,
            )

        if request.action == "accept":
            # Accept the proposed path
            track.organisation_status = "proposed"
        elif request.action == "custom":
            if not request.custom_path:
                raise OrganisationError("custom_path is required when action is 'custom'")
            track.proposed_path = request.custom_path
            track.organisation_status = "proposed"
            track.organisation_reasoning = "Custom path set by user"
        elif request.action == "skip":
            track.organisation_status = "unorganised"
            track.proposed_path = None
            track.organisation_confidence = None
            track.organisation_reasoning = None
        else:
            raise OrganisationError(f"Invalid action: {request.action}")

        # Optionally create preference rule
        if request.save_preference and request.preference_type and track.artist:
            from backend.services.preference_store import create_rule

            if request.preference_type == "artist_folder":
                # Extract artist folder from proposed path
                from pathlib import Path

                if track.proposed_path:
                    parts = Path(track.proposed_path).parts
                    if len(parts) >= 2:
                        create_rule(
                            db_session,
                            "artist_folder",
                            track.artist,
                            parts[-len(parts)],  # First part after base
                        )

        db_session.commit()
        return {
            "status": "resolved",
            "track_id": track_id,
            "action": request.action,
            "organisation_status": track.organisation_status,
        }
    finally:
        db_session.close()


# --- Preferences routes ---


@router.get("/preferences")
async def list_preferences(rule_type: str | None = None) -> list[PreferenceRuleResponse]:
    """List preference rules."""
    from backend.services.preference_store import list_rules

    db_session = SessionLocal()
    try:
        rules = list_rules(db_session, rule_type=rule_type)
        return [
            PreferenceRuleResponse(
                id=r.id,
                rule_type=r.rule_type,
                key=r.key,
                value=r.value,
                created_at=r.created_at.isoformat() if r.created_at else None,
            )
            for r in rules
        ]
    finally:
        db_session.close()


@router.post("/preferences", response_model=PreferenceRuleResponse)
async def create_preference(request: PreferenceRuleCreate) -> PreferenceRuleResponse:
    """Create a preference rule."""
    from backend.services.preference_store import create_rule

    db_session = SessionLocal()
    try:
        rule = create_rule(db_session, request.rule_type, request.key, request.value)
        db_session.commit()
        return PreferenceRuleResponse(
            id=rule.id,
            rule_type=rule.rule_type,
            key=rule.key,
            value=rule.value,
            created_at=rule.created_at.isoformat() if rule.created_at else None,
        )
    finally:
        db_session.close()


@router.delete("/preferences/{rule_id}")
async def delete_preference(rule_id: int) -> dict:
    """Delete a preference rule."""
    from backend.services.preference_store import delete_rule

    db_session = SessionLocal()
    try:
        delete_rule(db_session, rule_id)
        db_session.commit()
        return {"status": "deleted", "rule_id": rule_id}
    finally:
        db_session.close()
