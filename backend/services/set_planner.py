"""Set planner service — orchestrates AI-powered DJ set planning.

Provides CRUD operations for set plans, lock/unlock track management,
segment recalculation, and shuffle operations (replace and reorder modes)
via Claude API calls. SSE progress events emitted for async operations.
"""

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.exceptions import SetPlanError
from backend.models.crate import CrateTrack
from backend.models.set_plan import SetPlan, SetSegment, SetTrack
from backend.models.track import Track
from backend.services.claude_client import ClaudeClient
from backend.services.set_prompt_builder import (
    build_initial_prompt,
    build_reorder_prompt,
    build_replace_prompt,
    parse_initial_result,
    parse_reorder_result,
    parse_replace_result,
)

logger = logging.getLogger(__name__)


@dataclass
class SetPlanSummary:
    """Summary of a set plan for list views.

    Attributes:
        id: Set plan ID.
        name: Display name.
        description: Set description.
        track_count: Number of active (non-candidate) tracks.
        candidate_count: Number of candidate tracks.
        status: Current status.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id: int
    name: str
    description: str
    track_count: int
    candidate_count: int
    status: str
    created_at: str
    updated_at: str


@dataclass
class SetPlanDetail:
    """Full detail of a set plan including tracks and segments.

    Attributes:
        id: Set plan ID.
        name: Display name.
        description: Set description.
        duration_minutes: Target set duration.
        target_bpm_start: Starting BPM target.
        target_bpm_end: Ending BPM target.
        energy_arc: Energy shape description.
        source_type: Track source type.
        source_crate_ids: Crate IDs for sourcing.
        harmonic_mixing: Whether harmonic mixing is enabled.
        status: Current status.
        tracks: Ordered list of active tracks with metadata.
        candidates: Candidate pool tracks.
        segments: Segment definitions.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    id: int
    name: str
    description: str
    duration_minutes: int | None
    target_bpm_start: float | None
    target_bpm_end: float | None
    energy_arc: str | None
    source_type: str
    source_crate_ids: list[int] | None
    harmonic_mixing: bool
    status: str
    tracks: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    segments: list[dict[str, Any]]
    created_at: str
    updated_at: str


@dataclass
class ShuffleResult:
    """Result of a shuffle operation.

    Attributes:
        mode: Shuffle mode ("replace" or "reorder").
        tracks_changed: Number of tracks changed.
        errors: Error messages.
    """

    mode: str
    tracks_changed: int = 0
    errors: list[str] = field(default_factory=list)


class SetPlanner:
    """Orchestrates set planning operations with Claude integration.

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
        """Whether a planning operation is currently running."""
        return self._processing

    def cancel(self) -> None:
        """Request cancellation of the current operation."""
        self._cancel_event.set()
        logger.info("Set planning cancellation requested")

    async def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Push an SSE event to the event queue."""
        await self._event_queue.put({"event": event_type, "data": data})

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
                if event["event"] in ("set_plan_complete", "set_shuffle_complete"):
                    break
            except TimeoutError:
                yield {"event": "keepalive", "data": ""}


def create_set(
    name: str,
    description: str,
    db_session: Session,
    source_type: str = "library",
    source_crate_ids: list[int] | None = None,
    duration_minutes: int | None = None,
    target_bpm_start: float | None = None,
    target_bpm_end: float | None = None,
    energy_arc: str | None = None,
    harmonic_mixing: bool = False,
) -> SetPlan:
    """Create a new set plan record.

    Args:
        name: Display name for the set.
        description: User's set description.
        db_session: SQLAlchemy session.
        source_type: Track source ("library", "crates", or "both").
        source_crate_ids: List of crate IDs when sourcing from crates.
        duration_minutes: Target set duration.
        target_bpm_start: Starting BPM target.
        target_bpm_end: Ending BPM target.
        energy_arc: Energy shape description.
        harmonic_mixing: Whether to prefer harmonic mixing.

    Returns:
        Created SetPlan instance.
    """
    crate_ids_json = json.dumps(source_crate_ids) if source_crate_ids else None

    plan = SetPlan(
        name=name,
        description=description,
        duration_minutes=duration_minutes,
        target_bpm_start=target_bpm_start,
        target_bpm_end=target_bpm_end,
        energy_arc=energy_arc,
        source_type=source_type,
        source_crate_ids=crate_ids_json,
        harmonic_mixing=harmonic_mixing,
        status="draft",
    )
    db_session.add(plan)
    db_session.commit()

    logger.info("Created set plan %d: %s", plan.id, name)
    return plan


def get_set(set_id: int, db_session: Session) -> SetPlanDetail:
    """Get full set detail including tracks and segments.

    Args:
        set_id: Set plan ID.
        db_session: SQLAlchemy session.

    Returns:
        SetPlanDetail with tracks, candidates, and segments.

    Raises:
        SetPlanError: If the set plan is not found.
    """
    plan = db_session.query(SetPlan).filter(SetPlan.id == set_id).first()
    if plan is None:
        raise SetPlanError(f"Set plan {set_id} not found", status_code=404)

    # Load tracks
    set_tracks = (
        db_session.query(SetTrack)
        .filter(SetTrack.set_id == set_id)
        .order_by(SetTrack.position)
        .all()
    )

    # Separate active and candidate tracks
    active_tracks = []
    candidate_tracks = []
    track_ids = [st.track_id for st in set_tracks]
    tracks_by_id = {}
    if track_ids:
        tracks = db_session.query(Track).filter(Track.id.in_(track_ids)).all()
        tracks_by_id = {t.id: t for t in tracks}

    for st in set_tracks:
        track = tracks_by_id.get(st.track_id)
        track_data = _build_track_data(st, track)
        if st.is_candidate:
            candidate_tracks.append(track_data)
        else:
            active_tracks.append(track_data)

    # Load segments
    segments = (
        db_session.query(SetSegment)
        .filter(SetSegment.set_id == set_id)
        .order_by(SetSegment.position)
        .all()
    )
    segment_data = [
        {
            "id": seg.id,
            "position": seg.position,
            "description": seg.description,
            "start_track_position": seg.start_track_position,
            "end_track_position": seg.end_track_position,
        }
        for seg in segments
    ]

    # Parse source crate IDs
    crate_ids = None
    if plan.source_crate_ids:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            crate_ids = json.loads(plan.source_crate_ids)

    return SetPlanDetail(
        id=plan.id,
        name=plan.name,
        description=plan.description,
        duration_minutes=plan.duration_minutes,
        target_bpm_start=plan.target_bpm_start,
        target_bpm_end=plan.target_bpm_end,
        energy_arc=plan.energy_arc,
        source_type=plan.source_type,
        source_crate_ids=crate_ids,
        harmonic_mixing=plan.harmonic_mixing,
        status=plan.status,
        tracks=active_tracks,
        candidates=candidate_tracks,
        segments=segment_data,
        created_at=plan.created_at.isoformat() if plan.created_at else "",
        updated_at=plan.updated_at.isoformat() if plan.updated_at else "",
    )


def list_sets(db_session: Session) -> list[SetPlanSummary]:
    """List all set plans with track counts.

    Args:
        db_session: SQLAlchemy session.

    Returns:
        List of SetPlanSummary objects.
    """
    plans = db_session.query(SetPlan).order_by(SetPlan.created_at.desc()).all()
    result = []
    for plan in plans:
        track_count = (
            db_session.query(SetTrack)
            .filter(SetTrack.set_id == plan.id, SetTrack.is_candidate.is_(False))
            .count()
        )
        candidate_count = (
            db_session.query(SetTrack)
            .filter(SetTrack.set_id == plan.id, SetTrack.is_candidate.is_(True))
            .count()
        )
        result.append(
            SetPlanSummary(
                id=plan.id,
                name=plan.name,
                description=plan.description,
                track_count=track_count,
                candidate_count=candidate_count,
                status=plan.status,
                created_at=plan.created_at.isoformat() if plan.created_at else "",
                updated_at=plan.updated_at.isoformat() if plan.updated_at else "",
            )
        )
    return result


def update_set(
    set_id: int,
    db_session: Session,
    name: str | None = None,
    description: str | None = None,
    duration_minutes: int | None = None,
    target_bpm_start: float | None = None,
    target_bpm_end: float | None = None,
    energy_arc: str | None = None,
    harmonic_mixing: bool | None = None,
) -> SetPlan:
    """Update set plan metadata (does NOT re-plan).

    Args:
        set_id: Set plan ID.
        db_session: SQLAlchemy session.
        name: New name, or None to keep.
        description: New description, or None to keep.
        duration_minutes: New duration, or None to keep.
        target_bpm_start: New start BPM, or None to keep.
        target_bpm_end: New end BPM, or None to keep.
        energy_arc: New energy arc, or None to keep.
        harmonic_mixing: New harmonic mixing flag, or None to keep.

    Returns:
        Updated SetPlan instance.

    Raises:
        SetPlanError: If the set plan is not found.
    """
    plan = db_session.query(SetPlan).filter(SetPlan.id == set_id).first()
    if plan is None:
        raise SetPlanError(f"Set plan {set_id} not found", status_code=404)

    if name is not None:
        plan.name = name
    if description is not None:
        plan.description = description
    if duration_minutes is not None:
        plan.duration_minutes = duration_minutes
    if target_bpm_start is not None:
        plan.target_bpm_start = target_bpm_start
    if target_bpm_end is not None:
        plan.target_bpm_end = target_bpm_end
    if energy_arc is not None:
        plan.energy_arc = energy_arc
    if harmonic_mixing is not None:
        plan.harmonic_mixing = harmonic_mixing

    db_session.commit()
    logger.info("Updated set plan %d", set_id)
    return plan


def delete_set(set_id: int, db_session: Session) -> None:
    """Delete a set plan and cascade to tracks and segments.

    Args:
        set_id: Set plan ID.
        db_session: SQLAlchemy session.

    Raises:
        SetPlanError: If the set plan is not found.
    """
    plan = db_session.query(SetPlan).filter(SetPlan.id == set_id).first()
    if plan is None:
        raise SetPlanError(f"Set plan {set_id} not found", status_code=404)

    # Load relationships for ORM cascade
    _ = plan.set_tracks
    _ = plan.set_segments

    db_session.delete(plan)
    db_session.commit()
    logger.info("Deleted set plan %d", set_id)


def lock_track(set_id: int, position: int, db_session: Session) -> None:
    """Lock a track at a specific position.

    Args:
        set_id: Set plan ID.
        position: Track position to lock.
        db_session: SQLAlchemy session.

    Raises:
        SetPlanError: If the track is not found at the position.
    """
    st = (
        db_session.query(SetTrack)
        .filter(
            SetTrack.set_id == set_id,
            SetTrack.position == position,
            SetTrack.is_candidate.is_(False),
        )
        .first()
    )
    if st is None:
        raise SetPlanError(f"No track at position {position} in set {set_id}", status_code=404)

    st.is_locked = True
    db_session.commit()
    recalculate_segments(set_id, db_session)
    logger.info("Locked track at position %d in set %d", position, set_id)


def unlock_track(set_id: int, position: int, db_session: Session) -> None:
    """Unlock a track at a specific position.

    Args:
        set_id: Set plan ID.
        position: Track position to unlock.
        db_session: SQLAlchemy session.

    Raises:
        SetPlanError: If the track is not found at the position.
    """
    st = (
        db_session.query(SetTrack)
        .filter(
            SetTrack.set_id == set_id,
            SetTrack.position == position,
            SetTrack.is_candidate.is_(False),
        )
        .first()
    )
    if st is None:
        raise SetPlanError(f"No track at position {position} in set {set_id}", status_code=404)

    st.is_locked = False
    db_session.commit()
    recalculate_segments(set_id, db_session)
    logger.info("Unlocked track at position %d in set %d", position, set_id)


def update_segment_description(
    segment_id: int, description: str | None, db_session: Session
) -> SetSegment:
    """Update a segment's mood description.

    Args:
        segment_id: Segment ID.
        description: New description, or None to clear.
        db_session: SQLAlchemy session.

    Returns:
        Updated segment.

    Raises:
        SetPlanError: If the segment is not found.
    """
    segment = db_session.query(SetSegment).filter(SetSegment.id == segment_id).first()
    if segment is None:
        raise SetPlanError(f"Segment {segment_id} not found", status_code=404)

    segment.description = description
    db_session.commit()
    logger.info("Updated segment %d description", segment_id)
    return segment


def recalculate_segments(set_id: int, db_session: Session) -> list[SetSegment]:
    """Rebuild segments from locked track positions.

    Segments are derived from locked track boundaries:
    1. Find all locked positions, sorted
    2. Segment 1: position 1 → first locked position (or end)
    3. Subsequent: after each locked position → next locked (or end)
    4. Preserve descriptions where boundaries haven't changed.

    Args:
        set_id: Set plan ID.
        db_session: SQLAlchemy session.

    Returns:
        List of recalculated SetSegment instances.
    """
    # Get active tracks sorted by position
    active_tracks = (
        db_session.query(SetTrack)
        .filter(SetTrack.set_id == set_id, SetTrack.is_candidate.is_(False))
        .order_by(SetTrack.position)
        .all()
    )

    if not active_tracks:
        # No tracks — clear segments
        db_session.query(SetSegment).filter(SetSegment.set_id == set_id).delete()
        db_session.commit()
        return []

    max_position = active_tracks[-1].position

    # Find locked positions
    locked_positions = sorted(st.position for st in active_tracks if st.is_locked)

    # Calculate new segment boundaries
    new_boundaries: list[tuple[int, int]] = []
    if not locked_positions:
        # Single segment covering everything
        new_boundaries.append((1, max_position))
    else:
        # Before first locked position
        if locked_positions[0] > 1:
            new_boundaries.append((1, locked_positions[0]))
        else:
            new_boundaries.append((1, locked_positions[0]))

        # Between locked positions
        for i in range(len(locked_positions) - 1):
            start = locked_positions[i]
            end = locked_positions[i + 1]
            new_boundaries.append((start, end))

        # After last locked position
        if locked_positions[-1] < max_position:
            new_boundaries.append((locked_positions[-1], max_position))

    # Deduplicate boundaries (e.g., when two adjacent positions are both locked)
    unique_boundaries: list[tuple[int, int]] = []
    for b in new_boundaries:
        if not unique_boundaries or b != unique_boundaries[-1]:
            unique_boundaries.append(b)
    new_boundaries = unique_boundaries

    # Load existing segments for description preservation
    existing_segments = (
        db_session.query(SetSegment)
        .filter(SetSegment.set_id == set_id)
        .order_by(SetSegment.position)
        .all()
    )
    existing_by_range: dict[tuple[int, int], str | None] = {
        (seg.start_track_position, seg.end_track_position): seg.description
        for seg in existing_segments
    }

    # Clear old segments
    db_session.query(SetSegment).filter(SetSegment.set_id == set_id).delete()
    db_session.flush()

    # Create new segments
    new_segments = []
    for idx, (start, end) in enumerate(new_boundaries, start=1):
        # Preserve description if boundaries match
        description = existing_by_range.get((start, end))

        segment = SetSegment(
            set_id=set_id,
            position=idx,
            description=description,
            start_track_position=start,
            end_track_position=end,
        )
        db_session.add(segment)
        new_segments.append(segment)

    db_session.commit()

    # Update track segment assignments
    for st in active_tracks:
        for segment in new_segments:
            if segment.start_track_position <= st.position <= segment.end_track_position:
                st.segment_id = segment.id
                break
    db_session.commit()

    logger.info(
        "Recalculated %d segments for set %d",
        len(new_segments),
        set_id,
    )
    return new_segments


def remove_track(set_id: int, position: int, db_session: Session) -> None:
    """Remove a track from the sequence and move it to candidates.

    Reindexes positions after removal.

    Args:
        set_id: Set plan ID.
        position: Position to remove.
        db_session: SQLAlchemy session.

    Raises:
        SetPlanError: If no track at the position.
    """
    st = (
        db_session.query(SetTrack)
        .filter(
            SetTrack.set_id == set_id,
            SetTrack.position == position,
            SetTrack.is_candidate.is_(False),
        )
        .first()
    )
    if st is None:
        raise SetPlanError(f"No track at position {position} in set {set_id}", status_code=404)

    # Move to candidate pool
    st.is_candidate = True
    st.is_locked = False
    st.position = 0

    # Reindex positions
    _reindex_positions(set_id, db_session)
    recalculate_segments(set_id, db_session)

    logger.info("Removed track from position %d in set %d", position, set_id)


def add_track_at_position(set_id: int, track_id: int, position: int, db_session: Session) -> None:
    """Add a track at a specific position, shifting others down.

    If the track is already a candidate in this set, it moves from
    candidate to active. Otherwise a new SetTrack is created.

    Args:
        set_id: Set plan ID.
        track_id: Track to add.
        position: Position to insert at (1-indexed).
        db_session: SQLAlchemy session.

    Raises:
        SetPlanError: If the track is already in the active sequence.
    """
    # Check if track exists
    track = db_session.query(Track).filter(Track.id == track_id).first()
    if track is None:
        raise SetPlanError(f"Track {track_id} not found", status_code=404)

    # Check if already in the set
    existing = (
        db_session.query(SetTrack)
        .filter(SetTrack.set_id == set_id, SetTrack.track_id == track_id)
        .first()
    )

    if existing:
        if not existing.is_candidate:
            raise SetPlanError(
                f"Track {track_id} is already in the active sequence", status_code=409
            )
        # Move from candidate to active
        existing.is_candidate = False
        existing.position = position
    else:
        # Create new set track
        st = SetTrack(
            set_id=set_id,
            track_id=track_id,
            position=position,
            is_candidate=False,
        )
        db_session.add(st)

    # Shift positions >= insert point
    active_tracks = (
        db_session.query(SetTrack)
        .filter(
            SetTrack.set_id == set_id,
            SetTrack.is_candidate.is_(False),
            SetTrack.track_id != track_id,
            SetTrack.position >= position,
        )
        .order_by(SetTrack.position.desc())
        .all()
    )
    for st in active_tracks:
        st.position += 1

    db_session.commit()
    recalculate_segments(set_id, db_session)

    logger.info("Added track %d at position %d in set %d", track_id, position, set_id)


def move_track(set_id: int, from_position: int, to_position: int, db_session: Session) -> None:
    """Move a track from one position to another.

    Args:
        set_id: Set plan ID.
        from_position: Current position.
        to_position: Target position.
        db_session: SQLAlchemy session.

    Raises:
        SetPlanError: If no track at from_position.
    """
    if from_position == to_position:
        return

    st = (
        db_session.query(SetTrack)
        .filter(
            SetTrack.set_id == set_id,
            SetTrack.position == from_position,
            SetTrack.is_candidate.is_(False),
        )
        .first()
    )
    if st is None:
        raise SetPlanError(
            f"No track at position {from_position} in set {set_id}", status_code=404
        )

    # Shift other tracks
    if from_position < to_position:
        # Moving down: shift tracks between from+1 and to up by 1
        tracks_to_shift = (
            db_session.query(SetTrack)
            .filter(
                SetTrack.set_id == set_id,
                SetTrack.is_candidate.is_(False),
                SetTrack.position > from_position,
                SetTrack.position <= to_position,
            )
            .all()
        )
        for t in tracks_to_shift:
            t.position -= 1
    else:
        # Moving up: shift tracks between to and from-1 down by 1
        tracks_to_shift = (
            db_session.query(SetTrack)
            .filter(
                SetTrack.set_id == set_id,
                SetTrack.is_candidate.is_(False),
                SetTrack.position >= to_position,
                SetTrack.position < from_position,
            )
            .all()
        )
        for t in tracks_to_shift:
            t.position += 1

    st.position = to_position
    db_session.commit()
    recalculate_segments(set_id, db_session)

    logger.info(
        "Moved track from position %d to %d in set %d",
        from_position,
        to_position,
        set_id,
    )


def get_candidates(set_id: int, db_session: Session) -> list[dict[str, Any]]:
    """Get the candidate pool for a set.

    Args:
        set_id: Set plan ID.
        db_session: SQLAlchemy session.

    Returns:
        List of candidate track data dicts.
    """
    candidates = (
        db_session.query(SetTrack)
        .filter(SetTrack.set_id == set_id, SetTrack.is_candidate.is_(True))
        .all()
    )

    track_ids = [c.track_id for c in candidates]
    tracks_by_id = {}
    if track_ids:
        tracks = db_session.query(Track).filter(Track.id.in_(track_ids)).all()
        tracks_by_id = {t.id: t for t in tracks}

    return [_build_track_data(c, tracks_by_id.get(c.track_id)) for c in candidates]


async def plan_initial_sequence(
    set_id: int,
    db_session: Session,
    settings: Settings,
    planner: "SetPlanner",
    claude_client: ClaudeClient,
) -> None:
    """Generate the initial track sequence using Claude.

    Args:
        set_id: Set plan ID.
        db_session: SQLAlchemy session.
        settings: Application settings.
        planner: SetPlanner instance for SSE events.
        claude_client: Configured Claude client.
    """
    plan = db_session.query(SetPlan).filter(SetPlan.id == set_id).first()
    if plan is None:
        raise SetPlanError(f"Set plan {set_id} not found", status_code=404)

    plan.status = "planning"
    db_session.commit()

    try:
        # Gather source tracks
        source_tracks = _get_source_tracks(plan, db_session)
        if not source_tracks:
            raise SetPlanError("No tracks available for set planning")

        # Calculate sequence length
        if plan.duration_minutes:
            sequence_length = max(1, plan.duration_minutes // settings.set_track_duration_minutes)
        else:
            sequence_length = min(len(source_tracks), 10)

        sequence_length = min(sequence_length, settings.set_max_tracks)

        candidate_count = min(
            len(source_tracks),
            int(sequence_length * settings.set_candidate_multiplier),
        )
        candidate_count = max(candidate_count, sequence_length)

        await planner._emit_event(
            "set_plan_progress",
            {
                "set_id": set_id,
                "phase": "planning",
                "message": "Generating initial sequence...",
            },
        )

        # Build and send prompt
        system, user, tool = build_initial_prompt(
            description=plan.description,
            tracks=source_tracks,
            sequence_length=sequence_length,
            candidate_count=candidate_count,
            duration_minutes=plan.duration_minutes,
            target_bpm_start=plan.target_bpm_start,
            target_bpm_end=plan.target_bpm_end,
            energy_arc=plan.energy_arc,
            harmonic_mixing=plan.harmonic_mixing,
            key_notation=settings.default_key_notation,
        )

        await claude_client.rate_limiter.acquire()
        response = await asyncio.to_thread(  # type: ignore[arg-type]
            claude_client.client.messages.create,
            model=claude_client.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "plan_set"},
        )

        # Update token usage
        claude_client._usage.total_input_tokens += response.usage.input_tokens
        claude_client._usage.total_output_tokens += response.usage.output_tokens
        claude_client._usage.total_requests += 1

        # Parse result
        valid_ids = {t.id for t in source_tracks}
        tool_input = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "plan_set":
                tool_input = block.input
                break

        if tool_input is None:
            raise SetPlanError("Claude did not return a set plan")

        sequence_ids, candidate_ids = parse_initial_result(tool_input, valid_ids)

        if not sequence_ids:
            raise SetPlanError("Claude returned an empty sequence")

        # Store set tracks
        for pos, track_id in enumerate(sequence_ids, start=1):
            db_session.add(
                SetTrack(
                    set_id=set_id,
                    track_id=track_id,
                    position=pos,
                    is_candidate=False,
                )
            )

        for track_id in candidate_ids:
            db_session.add(
                SetTrack(
                    set_id=set_id,
                    track_id=track_id,
                    position=0,
                    is_candidate=True,
                )
            )

        plan.status = "complete"
        db_session.commit()

        # Create initial segment (whole set, no locks yet)
        recalculate_segments(set_id, db_session)

        logger.info(
            "Initial sequence planned for set %d: %d tracks, %d candidates",
            set_id,
            len(sequence_ids),
            len(candidate_ids),
        )

    except Exception as e:
        plan.status = "draft"
        db_session.commit()
        logger.exception("Initial planning failed for set %d", set_id)
        if not isinstance(e, SetPlanError):
            raise SetPlanError(f"Planning failed: {e}") from e
        raise

    finally:
        await planner._emit_event(
            "set_plan_complete",
            {
                "set_id": set_id,
                "status": plan.status,
                "tracks": len(sequence_ids) if "sequence_ids" in dir() else 0,
                "candidates": len(candidate_ids) if "candidate_ids" in dir() else 0,
            },
        )


async def shuffle_replace(
    set_id: int,
    db_session: Session,
    settings: Settings,
    planner: "SetPlanner",
    claude_client: ClaudeClient,
) -> ShuffleResult:
    """Replace unlocked tracks using Claude.

    Args:
        set_id: Set plan ID.
        db_session: SQLAlchemy session.
        settings: Application settings.
        planner: SetPlanner instance for SSE events.
        claude_client: Configured Claude client.

    Returns:
        ShuffleResult with change count.
    """
    result = ShuffleResult(mode="replace")

    plan = db_session.query(SetPlan).filter(SetPlan.id == set_id).first()
    if plan is None:
        raise SetPlanError(f"Set plan {set_id} not found", status_code=404)

    # Get current state
    active_tracks = (
        db_session.query(SetTrack)
        .filter(SetTrack.set_id == set_id, SetTrack.is_candidate.is_(False))
        .order_by(SetTrack.position)
        .all()
    )

    if not active_tracks:
        raise SetPlanError("Set has no active tracks")

    locked_tracks = []
    unlocked_positions = []
    locked_positions: set[int] = set()

    track_ids = [st.track_id for st in active_tracks]
    tracks_by_id: dict[int, Track] = {}
    if track_ids:
        tracks = db_session.query(Track).filter(Track.id.in_(track_ids)).all()
        tracks_by_id = {t.id: t for t in tracks}

    for st in active_tracks:
        track = tracks_by_id.get(st.track_id)
        if st.is_locked and track:
            locked_tracks.append((st.position, track))
            locked_positions.add(st.position)
        else:
            unlocked_positions.append(st.position)

    if not unlocked_positions:
        result.errors.append("All tracks are locked")
        return result

    # Get available tracks (candidates + source pool not in sequence)
    available_tracks = _get_available_tracks(plan, active_tracks, db_session)

    # Get segments
    segments = (
        db_session.query(SetSegment)
        .filter(SetSegment.set_id == set_id)
        .order_by(SetSegment.position)
        .all()
    )
    segment_data = [
        {
            "position": seg.position,
            "description": seg.description,
            "start": seg.start_track_position,
            "end": seg.end_track_position,
        }
        for seg in segments
    ]

    await planner._emit_event(
        "set_shuffle_progress",
        {"set_id": set_id, "mode": "replace", "message": "Shuffling tracks..."},
    )

    try:
        system, user, tool = build_replace_prompt(
            description=plan.description,
            locked_tracks=locked_tracks,
            unlocked_positions=unlocked_positions,
            available_tracks=available_tracks,
            segments=segment_data,
            total_positions=len(active_tracks),
            harmonic_mixing=plan.harmonic_mixing,
            key_notation=settings.default_key_notation,
        )

        await claude_client.rate_limiter.acquire()
        response = await asyncio.to_thread(  # type: ignore[arg-type]
            claude_client.client.messages.create,
            model=claude_client.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "replace_tracks"},
        )

        claude_client._usage.total_input_tokens += response.usage.input_tokens
        claude_client._usage.total_output_tokens += response.usage.output_tokens
        claude_client._usage.total_requests += 1

        tool_input = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "replace_tracks":
                tool_input = block.input
                break

        if tool_input is None:
            result.errors.append("Claude did not return replacements")
            return result

        valid_ids = {t.id for t in available_tracks}
        replacements = parse_replace_result(
            tool_input, valid_ids, set(unlocked_positions), locked_positions
        )

        # Apply replacements
        for pos, new_track_id in replacements:
            old_st = (
                db_session.query(SetTrack)
                .filter(
                    SetTrack.set_id == set_id,
                    SetTrack.position == pos,
                    SetTrack.is_candidate.is_(False),
                )
                .first()
            )
            if old_st:
                # Move old track to candidates
                old_st.is_candidate = True
                old_st.position = 0
                old_st.is_locked = False

            # Check if new track is already in the set
            new_st = (
                db_session.query(SetTrack)
                .filter(SetTrack.set_id == set_id, SetTrack.track_id == new_track_id)
                .first()
            )
            if new_st:
                new_st.is_candidate = False
                new_st.position = pos
            else:
                db_session.add(
                    SetTrack(
                        set_id=set_id,
                        track_id=new_track_id,
                        position=pos,
                        is_candidate=False,
                    )
                )

            result.tracks_changed += 1

        db_session.commit()
        recalculate_segments(set_id, db_session)

    except Exception as e:
        logger.exception("Shuffle replace failed for set %d", set_id)
        result.errors.append(str(e))

    finally:
        await planner._emit_event(
            "set_shuffle_complete",
            {
                "set_id": set_id,
                "mode": "replace",
                "tracks_changed": result.tracks_changed,
                "errors": result.errors,
            },
        )

    return result


async def shuffle_reorder(
    set_id: int,
    db_session: Session,
    settings: Settings,
    planner: "SetPlanner",
    claude_client: ClaudeClient,
) -> ShuffleResult:
    """Reorder unlocked tracks for optimal flow using Claude.

    Args:
        set_id: Set plan ID.
        db_session: SQLAlchemy session.
        settings: Application settings.
        planner: SetPlanner instance for SSE events.
        claude_client: Configured Claude client.

    Returns:
        ShuffleResult with change count.
    """
    result = ShuffleResult(mode="reorder")

    plan = db_session.query(SetPlan).filter(SetPlan.id == set_id).first()
    if plan is None:
        raise SetPlanError(f"Set plan {set_id} not found", status_code=404)

    active_tracks = (
        db_session.query(SetTrack)
        .filter(SetTrack.set_id == set_id, SetTrack.is_candidate.is_(False))
        .order_by(SetTrack.position)
        .all()
    )

    if not active_tracks:
        raise SetPlanError("Set has no active tracks")

    track_ids = [st.track_id for st in active_tracks]
    tracks_by_id: dict[int, Track] = {}
    if track_ids:
        tracks = db_session.query(Track).filter(Track.id.in_(track_ids)).all()
        tracks_by_id = {t.id: t for t in tracks}

    current_sequence = []
    locked_positions: set[int] = set()
    locked_track_ids: dict[int, int] = {}

    for st in active_tracks:
        track = tracks_by_id.get(st.track_id)
        if track is None:
            continue
        current_sequence.append((st.position, track, st.is_locked))
        if st.is_locked:
            locked_positions.add(st.position)
            locked_track_ids[st.track_id] = st.position

    unlocked_count = len(current_sequence) - len(locked_positions)
    if unlocked_count == 0:
        result.errors.append("All tracks are locked")
        return result

    await planner._emit_event(
        "set_shuffle_progress",
        {"set_id": set_id, "mode": "reorder", "message": "Reordering tracks..."},
    )

    try:
        system, user, tool = build_reorder_prompt(
            description=plan.description,
            current_sequence=current_sequence,
            harmonic_mixing=plan.harmonic_mixing,
            key_notation=settings.default_key_notation,
        )

        await claude_client.rate_limiter.acquire()
        response = await asyncio.to_thread(  # type: ignore[arg-type]
            claude_client.client.messages.create,
            model=claude_client.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "reorder_tracks"},
        )

        claude_client._usage.total_input_tokens += response.usage.input_tokens
        claude_client._usage.total_output_tokens += response.usage.output_tokens
        claude_client._usage.total_requests += 1

        tool_input = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "reorder_tracks":
                tool_input = block.input
                break

        if tool_input is None:
            result.errors.append("Claude did not return reorder data")
            return result

        all_track_ids = {st.track_id for st in active_tracks}
        reorders = parse_reorder_result(
            tool_input,
            locked_positions=locked_positions,
            locked_track_ids=locked_track_ids,
            total_positions=len(active_tracks),
            all_track_ids=all_track_ids,
        )

        # Apply reorders
        for track_id, new_pos in reorders:
            reorder_st = (
                db_session.query(SetTrack)
                .filter(
                    SetTrack.set_id == set_id,
                    SetTrack.track_id == track_id,
                    SetTrack.is_candidate.is_(False),
                )
                .first()
            )
            if reorder_st is not None and reorder_st.position != new_pos:
                reorder_st.position = new_pos
                result.tracks_changed += 1

        db_session.commit()
        recalculate_segments(set_id, db_session)

    except Exception as e:
        logger.exception("Shuffle reorder failed for set %d", set_id)
        result.errors.append(str(e))

    finally:
        await planner._emit_event(
            "set_shuffle_complete",
            {
                "set_id": set_id,
                "mode": "reorder",
                "tracks_changed": result.tracks_changed,
                "errors": result.errors,
            },
        )

    return result


def _get_source_tracks(plan: SetPlan, db_session: Session) -> list[Track]:
    """Get tracks from the specified source (library, crates, or both).

    Args:
        plan: Set plan with source configuration.
        db_session: SQLAlchemy session.

    Returns:
        List of Track instances.
    """
    if plan.source_type == "library":
        return db_session.query(Track).all()

    crate_ids: list[int] = []
    if plan.source_crate_ids:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            crate_ids = json.loads(plan.source_crate_ids)

    if plan.source_type == "crates" and crate_ids:
        track_ids = [
            ct.track_id
            for ct in db_session.query(CrateTrack).filter(CrateTrack.crate_id.in_(crate_ids)).all()
        ]
        if track_ids:
            return db_session.query(Track).filter(Track.id.in_(track_ids)).all()
        return []

    if plan.source_type == "both":
        # Combine crate tracks with all library tracks (deduped by using all)
        return db_session.query(Track).all()

    return db_session.query(Track).all()


def _get_available_tracks(
    plan: SetPlan,
    active_set_tracks: list[SetTrack],
    db_session: Session,
) -> list[Track]:
    """Get tracks available for replacement (candidates + source pool).

    Args:
        plan: Set plan.
        active_set_tracks: Currently active set tracks.
        db_session: SQLAlchemy session.

    Returns:
        List of Track instances not currently in the active sequence.
    """
    active_track_ids = {st.track_id for st in active_set_tracks}

    # Get candidate tracks
    candidate_st = (
        db_session.query(SetTrack)
        .filter(SetTrack.set_id == plan.id, SetTrack.is_candidate.is_(True))
        .all()
    )
    candidate_ids = {c.track_id for c in candidate_st}

    # Get source tracks not in the active sequence
    source_tracks = _get_source_tracks(plan, db_session)
    available_ids = set()
    for t in source_tracks:
        if t.id not in active_track_ids:
            available_ids.add(t.id)

    # Combine candidate + available
    all_ids = candidate_ids | available_ids
    if not all_ids:
        return []

    return db_session.query(Track).filter(Track.id.in_(all_ids)).all()


def _build_track_data(set_track: SetTrack, track: Track | None) -> dict[str, Any]:
    """Build a track data dict for API responses.

    Args:
        set_track: SetTrack instance.
        track: Associated Track instance, or None.

    Returns:
        Dict with track metadata and set-specific fields.
    """
    data: dict[str, Any] = {
        "set_track_id": set_track.id,
        "track_id": set_track.track_id,
        "position": set_track.position,
        "is_locked": set_track.is_locked,
        "is_candidate": set_track.is_candidate,
        "segment_id": set_track.segment_id,
    }

    if track:
        data.update(
            {
                "title": track.title,
                "artist": track.artist,
                "bpm": track.bpm,
                "key": track.key,
                "genre": track.genre,
                "mood": track.mood,
                "energy": track.energy,
                "duration": track.duration,
            }
        )
    else:
        data.update(
            {
                "title": None,
                "artist": None,
                "bpm": None,
                "key": None,
                "genre": None,
                "mood": None,
                "energy": None,
                "duration": None,
            }
        )

    return data


def _reindex_positions(set_id: int, db_session: Session) -> None:
    """Reindex active track positions to be sequential from 1.

    Args:
        set_id: Set plan ID.
        db_session: SQLAlchemy session.
    """
    active_tracks = (
        db_session.query(SetTrack)
        .filter(SetTrack.set_id == set_id, SetTrack.is_candidate.is_(False))
        .order_by(SetTrack.position)
        .all()
    )

    for idx, st in enumerate(active_tracks, start=1):
        st.position = idx

    db_session.commit()
