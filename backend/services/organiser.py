"""Organisation pipeline — orchestrates file organisation proposal and execution.

Two-phase pipeline:
1. Propose: resolve templates, score confidence, optionally call Claude,
   store proposals in DB for user review.
2. Execute: move approved files, clean up empty directories, update DB.

Separate from Phase 1 ingestion, Phase 2 analysis, and Phase 3 AI tagging.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.models.track import Track
from backend.services.confidence_scorer import ConfidenceResult, score_track
from backend.services.file_mover import BatchMoveResult, move_files_batch
from backend.services.preference_store import apply_rules, get_rules_for_track
from backend.services.template_engine import ResolvedPath, build_output_path

logger = logging.getLogger(__name__)


@dataclass
class OrganisationProposal:
    """Summary of an organisation proposal.

    Attributes:
        total_tracks: Total tracks processed.
        auto_approved: Number of auto-approved tracks.
        needs_review: Number of tracks needing review.
        failed: Number of tracks that failed.
    """

    total_tracks: int = 0
    auto_approved: int = 0
    needs_review: int = 0
    failed: int = 0


@dataclass
class OrganisationResult:
    """Summary of an organisation execution.

    Attributes:
        total_moved: Number of files moved.
        skipped: Number of files already in place (no-op moves).
        failed: Number of failures.
        dirs_cleaned: Number of empty directories removed.
        results: Detailed per-file results.
    """

    total_moved: int = 0
    skipped: int = 0
    failed: int = 0
    dirs_cleaned: int = 0
    results: list[Any] = field(default_factory=list)


class Organiser:
    """Orchestrates the full file organisation flow with SSE progress and cancellation.

    Attributes:
        settings: Application settings.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cancel_event = asyncio.Event()
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._processing = False
        self._proposal = OrganisationProposal()

    @property
    def is_processing(self) -> bool:
        """Whether the pipeline is currently running."""
        return self._processing

    @property
    def proposal(self) -> OrganisationProposal:
        """The current or last proposal result."""
        return self._proposal

    def cancel(self) -> None:
        """Request cancellation of the current operation."""
        self._cancel_event.set()
        logger.info("Organisation cancellation requested")

    async def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Push an SSE event to the event queue."""
        await self._event_queue.put({"event": event_type, "data": data})

    async def propose_organisation(
        self,
        tracks: list[Track],
        db_session: Session,
        use_claude: bool = False,
    ) -> OrganisationProposal:
        """Generate organisation proposals for a list of tracks.

        Resolves templates, scores confidence, applies preference rules,
        optionally sends ambiguous tracks to Claude, and stores proposals in DB.

        Args:
            tracks: List of Track model instances to organise.
            db_session: SQLAlchemy session for DB updates.
            use_claude: Whether to use Claude for ambiguous tracks.

        Returns:
            OrganisationProposal with summary statistics.
        """
        self._processing = True
        self._cancel_event.clear()
        self._proposal = OrganisationProposal(total_tracks=len(tracks))

        output_dir = Path(self.settings.output_directory).expanduser()
        template = self.settings.folder_template
        threshold = self.settings.organise_confidence_threshold
        fallback = self.settings.organise_unknown_fallback

        logger.info(
            "Organisation proposal started: %d tracks, template=%s",
            len(tracks),
            template,
        )

        ambiguous_tracks: list[tuple[Track, ResolvedPath, ConfidenceResult]] = []

        for i, track in enumerate(tracks):
            if self._cancel_event.is_set():
                logger.info("Organisation cancelled at track %d/%d", i + 1, len(tracks))
                break

            try:
                # Get applicable preference rules
                preference_rules = get_rules_for_track(db_session, track)

                # Check for custom_path rule first
                custom_rule = next(
                    (r for r in preference_rules if r.rule_type == "custom_path"),
                    None,
                )

                if custom_rule:
                    # Custom path overrides everything
                    proposed = output_dir / custom_rule.value
                    track.proposed_path = str(proposed)
                    track.organisation_confidence = 1.0
                    track.organisation_reasoning = "Custom path rule applied"
                    track.organisation_status = "proposed"
                    self._proposal.auto_approved += 1
                else:
                    # Resolve template
                    resolved = build_output_path(template, track, output_dir, fallback)

                    # Apply preference rules
                    resolved = apply_rules(track, resolved, preference_rules, output_dir)

                    # Score confidence
                    confidence = score_track(track, resolved, preference_rules, threshold)

                    # Store proposal
                    track.proposed_path = str(resolved.path)
                    track.organisation_confidence = confidence.score
                    track.organisation_reasoning = "; ".join(confidence.reasons)

                    if confidence.auto_approve:
                        track.organisation_status = "proposed"
                        self._proposal.auto_approved += 1
                    else:
                        track.organisation_status = "review_needed"
                        self._proposal.needs_review += 1
                        ambiguous_tracks.append((track, resolved, confidence))

            except Exception:
                logger.exception("Failed to propose organisation for track %s", track.id)
                track.organisation_status = "review_needed"
                self._proposal.failed += 1

            # Emit progress
            await self._emit_event(
                "organise_progress",
                {
                    "phase": "proposing",
                    "tracks_processed": i + 1,
                    "tracks_total": len(tracks),
                    "auto_approved": self._proposal.auto_approved,
                    "needs_review": self._proposal.needs_review,
                    "failed": self._proposal.failed,
                },
            )

        # Optionally send ambiguous tracks to Claude
        if use_claude and ambiguous_tracks and self.settings.anthropic_api_key:
            await self._enrich_with_claude(ambiguous_tracks, template, db_session)

        db_session.commit()

        # Emit complete event
        await self._emit_event(
            "organise_propose_complete",
            {
                "total_tracks": self._proposal.total_tracks,
                "auto_approved": self._proposal.auto_approved,
                "needs_review": self._proposal.needs_review,
                "failed": self._proposal.failed,
            },
        )

        self._processing = False
        logger.info(
            "Organisation proposal complete: %d auto-approved, %d need review, %d failed",
            self._proposal.auto_approved,
            self._proposal.needs_review,
            self._proposal.failed,
        )
        return self._proposal

    async def _enrich_with_claude(
        self,
        ambiguous_tracks: list[tuple[Track, ResolvedPath, ConfidenceResult]],
        template: str,
        db_session: Session,
    ) -> None:
        """Send ambiguous tracks to Claude for placement suggestions.

        Args:
            ambiguous_tracks: List of (track, resolved_path, confidence) tuples.
            template: Folder template string.
            db_session: SQLAlchemy session.
        """
        try:
            from backend.services.claude_client import ClaudeClient
            from backend.services.claude_reasoner import suggest_placements_batch

            claude_client = ClaudeClient(
                api_key=self.settings.anthropic_api_key,
                model=self.settings.ai_model,
                max_requests_per_minute=self.settings.ai_max_requests_per_minute,
            )

            suggestions = await suggest_placements_batch(ambiguous_tracks, template, claude_client)

            # Apply suggestions to tracks
            suggestion_map = {s.track_id: s for s in suggestions}
            for track, _, _ in ambiguous_tracks:
                suggestion = suggestion_map.get(track.id)
                if suggestion:
                    track.organisation_reasoning = (
                        f"{track.organisation_reasoning}; Claude: {suggestion.reasoning}"
                    )

        except Exception:
            logger.exception("Claude enrichment failed for organisation")

    async def execute_organisation(
        self,
        tracks: list[Track],
        db_session: Session,
    ) -> OrganisationResult:
        """Execute approved file moves.

        Args:
            tracks: List of approved Track instances with proposed_path set.
            db_session: SQLAlchemy session.

        Returns:
            OrganisationResult with summary statistics.
        """
        self._processing = True
        self._cancel_event.clear()

        output_dir = Path(self.settings.output_directory).expanduser()

        # Build move list
        moves: list[tuple[Track, Path]] = []
        for track in tracks:
            if track.proposed_path:
                moves.append((track, Path(track.proposed_path)))

        if not moves:
            self._processing = False
            return OrganisationResult()

        logger.info("Organisation execution started: %d files to move", len(moves))

        # Execute moves
        batch_result: BatchMoveResult = await move_files_batch(
            moves, db_session, base_dir=output_dir
        )

        result = OrganisationResult(
            total_moved=batch_result.moved,
            skipped=batch_result.skipped,
            failed=batch_result.failed,
            dirs_cleaned=batch_result.dirs_cleaned,
            results=batch_result.results,
        )

        # Emit progress events
        await self._emit_event(
            "organise_move_complete",
            {
                "phase": "moving",
                "files_moved": result.total_moved,
                "files_skipped": result.skipped,
                "files_total": len(moves),
                "files_failed": result.failed,
                "dirs_cleaned": result.dirs_cleaned,
            },
        )

        self._processing = False
        logger.info(
            "Organisation execution complete: %d moved, %d failed, %d dirs cleaned",
            result.total_moved,
            result.failed,
            result.dirs_cleaned,
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
                if event["event"] in (
                    "organise_propose_complete",
                    "organise_move_complete",
                ):
                    break
            except TimeoutError:
                yield {"event": "keepalive", "data": ""}
