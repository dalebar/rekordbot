"""AI tagger pipeline — orchestrates Claude-based genre/mood/energy tagging.

Coordinates batch processing, source genre preservation, SSE progress,
cancellation, and token usage accumulation. Separate from Phase 1's
ingestion and Phase 2's analysis pipelines.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.models.track import Track
from backend.services.claude_client import ClaudeClient, ClaudeResponse
from backend.services.key_notation import key_to_display
from backend.services.prompt_builder import (
    build_batch_message,
    build_system_prompt,
    get_tool_schema,
    group_tracks_into_batches,
)

logger = logging.getLogger(__name__)


@dataclass
class AiTagBatchResult:
    """Result of a single AI tagging batch.

    Attributes:
        batch_number: 1-based batch index.
        tracks_tagged: Number of tracks successfully tagged.
        tracks_failed: Number of tracks that failed.
        input_tokens: Input tokens used for this batch.
        output_tokens: Output tokens used for this batch.
        errors: Error messages for this batch.
    """

    batch_number: int
    tracks_tagged: int = 0
    tracks_failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class AiTagPipelineResult:
    """Result of the full AI tagging pipeline.

    Attributes:
        total_tracks: Total tracks processed.
        succeeded: Number of successfully tagged tracks.
        failed: Number of failed tracks.
        total_batches: Number of batches processed.
        total_input_tokens: Total input tokens consumed.
        total_output_tokens: Total output tokens consumed.
        estimated_cost_usd: Estimated cost in USD.
        errors: All error messages across batches.
    """

    total_tracks: int = 0
    succeeded: int = 0
    failed: int = 0
    total_batches: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    errors: list[str] = field(default_factory=list)


class AiTagger:
    """Orchestrates the AI tagging pipeline with SSE progress and cancellation.

    Attributes:
        settings: Application settings.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cancel_event = asyncio.Event()
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._processing = False
        self._pipeline_result = AiTagPipelineResult()

    @property
    def is_processing(self) -> bool:
        """Whether the pipeline is currently running."""
        return self._processing

    @property
    def pipeline_result(self) -> AiTagPipelineResult:
        """The current or last pipeline result."""
        return self._pipeline_result

    def cancel(self) -> None:
        """Request cancellation of the current pipeline."""
        self._cancel_event.set()
        logger.info("AI tagging cancellation requested")

    async def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Push an SSE event to the event queue."""
        await self._event_queue.put({"event": event_type, "data": data})

    async def tag_tracks(
        self,
        tracks: list[Track],
        db_session: Session,
    ) -> AiTagPipelineResult:
        """Run the full AI tagging pipeline on a list of tracks.

        Groups tracks into batches, sends each to Claude, updates DB,
        and emits SSE progress events. Supports cancellation and
        per-batch error isolation.

        Args:
            tracks: List of Track model instances to tag.
            db_session: SQLAlchemy session for database updates.

        Returns:
            AiTagPipelineResult with summary statistics.
        """
        self._processing = True
        self._cancel_event.clear()
        self._pipeline_result = AiTagPipelineResult(total_tracks=len(tracks))

        claude_client = ClaudeClient(
            api_key=self.settings.anthropic_api_key,
            model=self.settings.ai_model,
            max_requests_per_minute=self.settings.ai_max_requests_per_minute,
        )

        system_prompt = build_system_prompt()
        tool_schema = get_tool_schema()

        # Group into batches
        batches = group_tracks_into_batches(tracks, self.settings.ai_batch_size)
        self._pipeline_result.total_batches = len(batches)

        logger.info(
            "AI tagging pipeline started: %d tracks in %d batches",
            len(tracks),
            len(batches),
        )

        for batch_idx, batch in enumerate(batches, start=1):
            if self._cancel_event.is_set():
                logger.info("AI tagging cancelled at batch %d/%d", batch_idx, len(batches))
                break

            batch_result = await self._process_batch(
                batch=batch,
                batch_number=batch_idx,
                total_batches=len(batches),
                claude_client=claude_client,
                system_prompt=system_prompt,
                tool_schema=tool_schema,
                db_session=db_session,
            )

            self._pipeline_result.succeeded += batch_result.tracks_tagged
            self._pipeline_result.failed += batch_result.tracks_failed
            self._pipeline_result.total_input_tokens += batch_result.input_tokens
            self._pipeline_result.total_output_tokens += batch_result.output_tokens
            self._pipeline_result.errors.extend(batch_result.errors)

        # Update cost from client
        usage = claude_client.get_token_usage()
        self._pipeline_result.estimated_cost_usd = usage.estimated_cost_usd

        # Emit pipeline complete event
        await self._emit_event(
            "ai_tag_complete",
            {
                "total_tracks": self._pipeline_result.total_tracks,
                "succeeded": self._pipeline_result.succeeded,
                "failed": self._pipeline_result.failed,
                "total_batches": self._pipeline_result.total_batches,
                "token_usage": {
                    "input_tokens": self._pipeline_result.total_input_tokens,
                    "output_tokens": self._pipeline_result.total_output_tokens,
                    "estimated_cost_usd": self._pipeline_result.estimated_cost_usd,
                },
            },
        )

        self._processing = False
        logger.info(
            "AI tagging pipeline complete: %d succeeded, %d failed, " "$%.4f estimated cost",
            self._pipeline_result.succeeded,
            self._pipeline_result.failed,
            self._pipeline_result.estimated_cost_usd,
        )
        return self._pipeline_result

    async def _process_batch(
        self,
        batch: list[Track],
        batch_number: int,
        total_batches: int,
        claude_client: ClaudeClient,
        system_prompt: str,
        tool_schema: dict[str, Any],
        db_session: Session,
    ) -> AiTagBatchResult:
        """Process a single batch of tracks with error isolation.

        Args:
            batch: List of tracks in this batch.
            batch_number: 1-based batch index.
            total_batches: Total number of batches.
            claude_client: Configured Claude client.
            system_prompt: System prompt for Claude.
            tool_schema: Tool schema definition.
            db_session: SQLAlchemy session for DB updates.

        Returns:
            AiTagBatchResult for this batch.
        """
        result = AiTagBatchResult(batch_number=batch_number)
        batch_track_ids = [t.id for t in batch]

        try:
            # Build key displays for the batch
            key_displays = {}
            for track in batch:
                if track.key is not None:
                    display = key_to_display(track.key, self.settings.default_key_notation)
                    if display:
                        key_displays[track.id] = display

            user_message = build_batch_message(batch, key_displays)

            # Call Claude
            response: ClaudeResponse = await claude_client.tag_batch(
                system_prompt=system_prompt,
                user_message=user_message,
                tool_schema=tool_schema,
                batch_track_ids=batch_track_ids,
            )

            result.input_tokens = response.input_tokens
            result.output_tokens = response.output_tokens

            # Apply results to DB
            track_map = {t.id: t for t in batch}
            for tag_result in response.results:
                matched_track = track_map.get(tag_result.track_id)
                if matched_track is None:
                    continue

                # Preserve source genre before overwriting
                if matched_track.genre and matched_track.source_genre is None:
                    matched_track.source_genre = matched_track.genre

                matched_track.genre = tag_result.genre
                matched_track.subgenre = tag_result.subgenre
                matched_track.mood = tag_result.mood
                matched_track.energy = tag_result.energy
                matched_track.ai_confidence = tag_result.confidence
                matched_track.ai_reasoning = tag_result.reasoning
                matched_track.ai_status = "ai_tagged"
                result.tracks_tagged += 1

            # Mark tracks that weren't in the response as failed
            tagged_ids = {r.track_id for r in response.results}
            for track_id in batch_track_ids:
                if track_id not in tagged_ids:
                    matched_track = track_map.get(track_id)
                    if matched_track:
                        matched_track.ai_status = "ai_failed"
                    result.tracks_failed += 1

            db_session.commit()

        except Exception as e:
            logger.exception("AI tagging batch %d/%d failed", batch_number, total_batches)
            for track in batch:
                track.ai_status = "ai_failed"
            db_session.commit()
            result.tracks_failed = len(batch)
            result.errors.append(str(e))

        # Emit progress event
        await self._emit_event(
            "ai_tag_batch_progress",
            {
                "batch_number": batch_number,
                "total_batches": total_batches,
                "tracks_tagged": self._pipeline_result.succeeded + result.tracks_tagged,
                "tracks_total": self._pipeline_result.total_tracks,
                "tracks_failed": self._pipeline_result.failed + result.tracks_failed,
                "token_usage": {
                    "input_tokens": self._pipeline_result.total_input_tokens + result.input_tokens,
                    "output_tokens": self._pipeline_result.total_output_tokens
                    + result.output_tokens,
                    "estimated_cost_usd": claude_client.get_token_usage().estimated_cost_usd,
                },
            },
        )

        return result

    async def event_generator(self):
        """Async generator that yields SSE events.

        Yields:
            Dict with "event" and "data" keys for SSE formatting.
        """
        while True:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=30.0)
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"]),
                }
                if event["event"] == "ai_tag_complete":
                    break
            except TimeoutError:
                yield {"event": "keepalive", "data": ""}
