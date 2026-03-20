"""AI tagging API routes — Claude-powered genre/mood/energy inference."""

import asyncio
import logging
import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]

from backend.config import settings
from backend.exceptions import AiTagError
from backend.models.database import SessionLocal
from backend.models.track import Track
from backend.services.ai_tagger import AiTagger
from backend.services.claude_client import ClaudeClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["ai-tagging"])

# Module-level AI tagger (one active pipeline at a time)
_ai_tagger: AiTagger | None = None


# --- Request/Response models ---


class AiTagOptions(BaseModel):
    """Options for AI tagging."""

    skip_if_tagged: bool = True
    model: str | None = None


class AiTagRequest(BaseModel):
    """Request body for POST /api/tracks/ai-tag."""

    track_ids: list[int] | None = None
    options: AiTagOptions | None = None


class AiTagResponse(BaseModel):
    """Response for POST /api/tracks/ai-tag."""

    batch_id: str
    total_tracks: int
    total_batches: int
    message: str


class AiTagStatusResponse(BaseModel):
    """Response for GET /api/tracks/ai-tag/status."""

    status: str
    token_usage: dict | None = None


class ValidateKeyResponse(BaseModel):
    """Response for POST /api/tracks/ai-tag/validate-key."""

    valid: bool
    model: str | None = None
    error: str | None = None


# --- Routes ---


@router.post("/tracks/ai-tag", response_model=AiTagResponse)
async def ai_tag_tracks(request: AiTagRequest) -> AiTagResponse:
    """Start AI tagging on selected tracks or all untagged tracks."""
    global _ai_tagger

    if _ai_tagger is not None and _ai_tagger.is_processing:
        return AiTagResponse(
            batch_id="",
            total_tracks=0,
            total_batches=0,
            message="An AI tagging batch is already running. Cancel it first.",
        )

    if not settings.anthropic_api_key:
        raise AiTagError(
            "Anthropic API key is not configured. "
            "Set REKORDBOT_ANTHROPIC_API_KEY in your .env file.",
            status_code=400,
        )

    db_session = SessionLocal()
    try:
        # Build query
        query = db_session.query(Track)

        if request.track_ids:
            query = query.filter(Track.id.in_(request.track_ids))
        else:
            query = query.filter(Track.ai_status == "untagged")

        # Apply skip_if_tagged option
        if request.options and request.options.skip_if_tagged and request.track_ids:
            query = query.filter(Track.ai_status == "untagged")

        tracks = query.all()

        if not tracks:
            return AiTagResponse(
                batch_id="",
                total_tracks=0,
                total_batches=0,
                message="No tracks to tag.",
            )

        # Determine model
        model = settings.ai_model
        if request.options and request.options.model:
            model = request.options.model

        tag_settings = settings.model_copy()
        tag_settings.ai_model = model

        batch_id = str(uuid.uuid4())
        _ai_tagger = AiTagger(tag_settings)

        # Calculate batch count
        from backend.services.prompt_builder import group_tracks_into_batches

        batches = group_tracks_into_batches(tracks, tag_settings.ai_batch_size)
        total_batches = len(batches)

        # Start pipeline in background
        async def _run_pipeline() -> None:
            try:
                await _ai_tagger.tag_tracks(tracks, db_session)
            except Exception:
                logger.exception("AI tagging pipeline failed")
            finally:
                db_session.close()

        asyncio.create_task(_run_pipeline())

        logger.info(
            "AI tagging batch %s started: %d tracks in %d batches",
            batch_id,
            len(tracks),
            total_batches,
        )
        return AiTagResponse(
            batch_id=batch_id,
            total_tracks=len(tracks),
            total_batches=total_batches,
            message="AI tagging started",
        )
    except Exception:
        db_session.close()
        raise


@router.get("/tracks/ai-tag/progress")
async def ai_tag_progress():
    """SSE endpoint streaming AI tagging progress events."""
    if _ai_tagger is None:

        async def empty_stream():
            yield {"event": "error", "data": "No active AI tagging batch"}

        return EventSourceResponse(empty_stream())

    return EventSourceResponse(_ai_tagger.event_generator())


@router.post("/tracks/ai-tag/cancel")
async def ai_tag_cancel() -> dict:
    """Cancel the current AI tagging pipeline."""
    if _ai_tagger is None or not _ai_tagger.is_processing:
        return {
            "status": "no_active_batch",
            "message": "No AI tagging batch is running.",
        }

    _ai_tagger.cancel()
    return {"status": "cancelling", "message": "Cancellation requested."}


@router.get("/tracks/ai-tag/status", response_model=AiTagStatusResponse)
async def ai_tag_status() -> AiTagStatusResponse:
    """Get current AI tagging status and token usage."""
    if _ai_tagger is None:
        return AiTagStatusResponse(status="idle")

    if _ai_tagger.is_processing:
        result = _ai_tagger.pipeline_result
        return AiTagStatusResponse(
            status="running",
            token_usage={
                "total_input_tokens": result.total_input_tokens,
                "total_output_tokens": result.total_output_tokens,
                "total_requests": result.total_batches,
                "estimated_cost_usd": result.estimated_cost_usd,
            },
        )

    result = _ai_tagger.pipeline_result
    return AiTagStatusResponse(
        status="idle",
        token_usage={
            "total_input_tokens": result.total_input_tokens,
            "total_output_tokens": result.total_output_tokens,
            "total_requests": result.total_batches,
            "estimated_cost_usd": result.estimated_cost_usd,
        },
    )


@router.post("/tracks/ai-tag/validate-key", response_model=ValidateKeyResponse)
async def validate_api_key() -> ValidateKeyResponse:
    """Validate the configured Anthropic API key."""
    logger.info("Validating API key, key present: %s", bool(settings.anthropic_api_key))
    if not settings.anthropic_api_key:
        return ValidateKeyResponse(
            valid=False,
            error="No API key configured. " "Set REKORDBOT_ANTHROPIC_API_KEY in your .env file.",
        )

    try:
        client = ClaudeClient(
            api_key=settings.anthropic_api_key,
            model=settings.ai_model,
        )
        await client.validate_api_key()
        return ValidateKeyResponse(valid=True, model=settings.ai_model)
    except AiTagError as e:
        # Distinguish auth failures (invalid key) from transient API errors
        # (429 rate limit, 529 overload). If the API didn't explicitly reject
        # the key, assume it's valid — don't disable the button for transient issues.
        is_auth_failure = (
            "Invalid" in (e.detail or "") or "authentication" in (e.detail or "").lower()
        )
        if is_auth_failure:
            return ValidateKeyResponse(valid=False, error=e.detail)
        logger.warning("API key validation got transient error: %s", e.detail)
        return ValidateKeyResponse(
            valid=True,
            error=f"Key appears valid but API returned an error: {e.detail}",
        )
