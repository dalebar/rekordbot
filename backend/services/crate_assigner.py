"""Crate assigner — orchestrates batched Claude-based track assignment to crates.

Loads tracks, builds batched summaries, sends to Claude for matching,
and stores results as CrateTrack records. Supports refresh with
manual addition preservation and SSE progress events.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.models.crate import Crate, CrateTrack
from backend.models.track import Track
from backend.services.claude_client import ClaudeClient
from backend.services.crate_prompt_builder import (
    build_assignment_prompt,
    parse_assignment_result,
)
from backend.services.prompt_builder import build_track_summary

logger = logging.getLogger(__name__)


@dataclass
class AssignmentResult:
    """Result of a crate assignment operation.

    Attributes:
        total_tracks: Total tracks evaluated.
        matched: Number of tracks assigned to the crate.
        total_batches: Number of batches processed.
        errors: Error messages from failed batches.
    """

    total_tracks: int = 0
    matched: int = 0
    total_batches: int = 0
    errors: list[str] = field(default_factory=list)


class CrateAssigner:
    """Orchestrates track assignment to crates via Claude.

    Attributes:
        settings: Application settings.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cancel_event = asyncio.Event()
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._processing = False

    @property
    def is_processing(self) -> bool:
        """Whether an assignment pipeline is currently running."""
        return self._processing

    def cancel(self) -> None:
        """Request cancellation of the current assignment."""
        self._cancel_event.set()
        logger.info("Crate assignment cancellation requested")

    async def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Push an SSE event to the event queue."""
        await self._event_queue.put({"event": event_type, "data": data})

    async def assign_tracks(
        self,
        crate: Crate,
        tracks: list[Track],
        db_session: Session,
        claude_client: ClaudeClient,
    ) -> AssignmentResult:
        """Assign matching tracks to a crate using Claude.

        Args:
            crate: The crate to assign tracks to.
            tracks: List of candidate tracks to evaluate.
            db_session: SQLAlchemy session for storing assignments.
            claude_client: Configured Claude client for API calls.

        Returns:
            AssignmentResult with counts and errors.
        """
        self._processing = True
        self._cancel_event.clear()
        result = AssignmentResult(total_tracks=len(tracks))

        if not tracks:
            self._processing = False
            await self._emit_complete(crate.id, result)
            return result

        # Parse criteria from crate
        criteria = {}
        if crate.parsed_criteria:
            try:
                criteria = json.loads(crate.parsed_criteria)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Failed to parse criteria for crate %d", crate.id)

        # Build batches
        batch_size = self.settings.crate_assignment_batch_size
        batches = [tracks[i : i + batch_size] for i in range(0, len(tracks), batch_size)]
        result.total_batches = len(batches)

        logger.info(
            "Crate assignment started for crate %d: %d tracks in %d batches",
            crate.id,
            len(tracks),
            len(batches),
        )

        all_matched_ids: list[int] = []

        for batch_idx, batch in enumerate(batches, start=1):
            if self._cancel_event.is_set():
                logger.info("Crate assignment cancelled at batch %d/%d", batch_idx, len(batches))
                break

            matched_ids = await self._process_batch(
                crate=crate,
                batch=batch,
                batch_number=batch_idx,
                total_batches=len(batches),
                criteria=criteria,
                claude_client=claude_client,
                result=result,
            )
            all_matched_ids.extend(matched_ids)

        # Store assignments
        existing_track_ids = {
            ct.track_id
            for ct in db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate.id).all()
        }

        new_assignments = 0
        for track_id in all_matched_ids:
            if track_id not in existing_track_ids:
                db_session.add(
                    CrateTrack(
                        crate_id=crate.id,
                        track_id=track_id,
                        assignment_method="ai",
                    )
                )
                new_assignments += 1

        db_session.commit()
        result.matched = new_assignments

        self._processing = False
        await self._emit_complete(crate.id, result)

        logger.info(
            "Crate assignment complete for crate %d: %d matched out of %d",
            crate.id,
            result.matched,
            result.total_tracks,
        )
        return result

    async def _process_batch(
        self,
        crate: Crate,
        batch: list[Track],
        batch_number: int,
        total_batches: int,
        criteria: dict[str, Any],
        claude_client: ClaudeClient,
        result: AssignmentResult,
    ) -> list[int]:
        """Process a single batch of tracks for assignment.

        Returns:
            List of matched track IDs from this batch.
        """
        batch_track_ids = [t.id for t in batch]
        valid_ids = set(batch_track_ids)

        try:
            # Build track summaries
            summaries = [build_track_summary(track) for track in batch]
            track_summaries_text = "\n\n".join(summaries)

            # Build assignment prompt
            system_prompt, user_message, tool_schema = build_assignment_prompt(
                description=crate.description,
                criteria=criteria,
                track_summaries=track_summaries_text,
            )

            # Call Claude
            await claude_client.rate_limiter.acquire()
            response = await asyncio.to_thread(
                claude_client.client.messages.create,
                model=claude_client.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
                tools=[tool_schema],
                tool_choice={"type": "tool", "name": "assign_tracks"},
            )

            # Update token usage
            claude_client._usage.total_input_tokens += response.usage.input_tokens
            claude_client._usage.total_output_tokens += response.usage.output_tokens
            claude_client._usage.total_requests += 1

            # Extract matching IDs
            matched_ids: list[int] = []
            for block in response.content:
                if block.type == "tool_use" and block.name == "assign_tracks":
                    matched_ids = parse_assignment_result(block.input, valid_ids)
                    break

            logger.info(
                "Crate assignment batch %d/%d: %d/%d tracks matched",
                batch_number,
                total_batches,
                len(matched_ids),
                len(batch),
            )

        except Exception as e:
            logger.exception("Crate assignment batch %d/%d failed", batch_number, total_batches)
            result.errors.append(str(e))
            matched_ids = []

        # Emit progress
        await self._emit_event(
            "crate_assignment_progress",
            {
                "crate_id": crate.id,
                "batch_number": batch_number,
                "total_batches": total_batches,
                "tracks_processed": batch_number * self.settings.crate_assignment_batch_size,
                "tracks_total": result.total_tracks,
            },
        )

        return matched_ids

    async def _emit_complete(self, crate_id: int, result: AssignmentResult) -> None:
        """Emit the assignment complete event."""
        await self._emit_event(
            "crate_assignment_complete",
            {
                "crate_id": crate_id,
                "total_tracks": result.total_tracks,
                "matched": result.matched,
                "total_batches": result.total_batches,
                "errors": result.errors,
            },
        )

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
                if event["event"] == "crate_assignment_complete":
                    break
            except TimeoutError:
                yield {"event": "keepalive", "data": ""}

    def clear_ai_assignments(self, crate_id: int, db_session: Session) -> int:
        """Remove all AI-assigned tracks from a crate, preserving manual ones.

        Args:
            crate_id: The crate to clear.
            db_session: SQLAlchemy session.

        Returns:
            Number of assignments removed.
        """
        count = (
            db_session.query(CrateTrack)
            .filter(
                CrateTrack.crate_id == crate_id,
                CrateTrack.assignment_method == "ai",
            )
            .delete()
        )
        db_session.commit()
        logger.info("Cleared %d AI assignments from crate %d", count, crate_id)
        return count
