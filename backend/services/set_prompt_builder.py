"""Set prompt builder — constructs prompts for set planning Claude operations.

Pure logic module with no I/O, no SDK dependency, and no database access.
Handles prompt construction for initial sequencing, replace-mode shuffle,
and reorder-mode shuffle, plus result parsing with validation.
"""

import logging
from typing import Any

from backend.services.key_notation import key_to_display
from backend.services.prompt_builder import build_track_summary

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a DJ set planner helping a DJ build an ordered track sequence. \
You understand BPM progression, energy flow, genre coherence, \
harmonic mixing (Camelot wheel), and mood transitions.

## Your role
Given a set description and a pool of available tracks, suggest an \
ordered sequence that creates a compelling DJ set. Consider:
- BPM progression: smooth transitions (±2 BPM ideal, ±5 acceptable)
- Energy flow: match the requested energy arc
- Genre coherence: group similar genres, use transitions for genre shifts
- Mood: match the overall or per-segment mood description
- Key compatibility (when requested): prefer Camelot-compatible transitions

## Energy arc patterns
- "slow build": start low energy, gradually increase
- "peak-valley-peak": build up, drop down, build again
- "constant high": maintain high energy throughout
- "wind down": start high, gradually decrease
- Custom descriptions should be interpreted intuitively

## Track selection
- Pick the best-fit tracks for the sequence positions
- Additional tracks go in the candidate pool for later swapping
- Sequence tracks should flow naturally from one to the next
- Candidates are backup options the DJ can swap in later\
"""

_REPLACE_SYSTEM_PROMPT = """\
You are a DJ set planner helping refine an existing set. \
Some tracks are LOCKED in place — you MUST NOT change them. \
Replace only the unlocked positions with better alternatives \
from the available track pool.

## Rules
- LOCKED tracks are fixed anchors — never replace them
- Each segment has its own mood description — match it
- Consider BPM flow between locked anchors and your replacements
- Consider energy progression within each segment
- When harmonic mixing is enabled, prefer key-compatible transitions\
"""

_REORDER_SYSTEM_PROMPT = """\
You are a DJ set planner helping optimise track order. \
Rearrange ONLY the unlocked tracks for better flow. \
Do NOT introduce new tracks or remove any.

## Rules
- LOCKED tracks stay in their exact positions — never move them
- Rearrange unlocked tracks for optimal BPM flow, energy arc, and key compatibility
- Consider the locked tracks as fixed reference points
- Only return new positions for unlocked tracks\
"""

_INITIAL_TOOL_SCHEMA: dict[str, Any] = {
    "name": "plan_set",
    "description": "Return an ordered track sequence and candidate pool for a DJ set.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sequence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "track_id": {
                            "type": "integer",
                            "description": "Track ID for this position",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Why this track fits this position",
                        },
                    },
                    "required": ["track_id", "reasoning"],
                },
                "description": "Ordered track sequence (position determined by array index)",
            },
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "track_id": {
                            "type": "integer",
                            "description": "Track ID for the candidate pool",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Why this track is a good alternative",
                        },
                    },
                    "required": ["track_id", "reasoning"],
                },
                "description": "Additional tracks for the candidate pool (not in sequence)",
            },
        },
        "required": ["sequence", "candidates"],
    },
}

_REPLACE_TOOL_SCHEMA: dict[str, Any] = {
    "name": "replace_tracks",
    "description": "Return replacement tracks for unlocked positions in a DJ set.",
    "input_schema": {
        "type": "object",
        "properties": {
            "replacements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "position": {
                            "type": "integer",
                            "description": "Position number to replace (1-indexed)",
                        },
                        "track_id": {
                            "type": "integer",
                            "description": "Track ID to place at this position",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Why this replacement is better",
                        },
                    },
                    "required": ["position", "track_id", "reasoning"],
                },
            },
        },
        "required": ["replacements"],
    },
}

_REORDER_TOOL_SCHEMA: dict[str, Any] = {
    "name": "reorder_tracks",
    "description": "Return new positions for unlocked tracks in a DJ set.",
    "input_schema": {
        "type": "object",
        "properties": {
            "reordered": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "track_id": {
                            "type": "integer",
                            "description": "Track ID to reposition",
                        },
                        "new_position": {
                            "type": "integer",
                            "description": "New position (1-indexed)",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Why this position is better",
                        },
                    },
                    "required": ["track_id", "new_position", "reasoning"],
                },
            },
        },
        "required": ["reordered"],
    },
}


def _build_track_summary_for_set(
    track: Any,
    key_notation: str = "camelot",
) -> str:
    """Build a track summary with set-relevant metadata.

    Args:
        track: Track model instance.
        key_notation: Key display notation preference.

    Returns:
        Formatted track summary string.
    """
    key_display = None
    if track.key is not None:
        key_display = key_to_display(track.key, key_notation)

    summary = build_track_summary(track, key_display=key_display)

    # Add mood and energy if available
    mood = getattr(track, "mood", None)
    energy = getattr(track, "energy", None)
    subgenre = getattr(track, "subgenre", None)
    extras = []
    if mood:
        extras.append(f"  Mood: {mood}")
    if energy is not None:
        extras.append(f"  Energy: {energy}/10")
    if subgenre:
        extras.append(f"  Subgenre: {subgenre}")

    if extras:
        summary += "\n" + "\n".join(extras)

    return summary


def build_initial_prompt(
    description: str,
    tracks: list[Any],
    sequence_length: int,
    candidate_count: int,
    duration_minutes: int | None = None,
    target_bpm_start: float | None = None,
    target_bpm_end: float | None = None,
    energy_arc: str | None = None,
    harmonic_mixing: bool = False,
    key_notation: str = "camelot",
) -> tuple[str, str, dict[str, Any]]:
    """Build the prompt for initial set sequence suggestion.

    Args:
        description: User's set description.
        tracks: Available tracks to choose from.
        sequence_length: Number of tracks for the active sequence.
        candidate_count: Total number of tracks to suggest (sequence + candidates).
        duration_minutes: Target set duration in minutes, or None.
        target_bpm_start: Starting BPM target, or None.
        target_bpm_end: Ending BPM target, or None.
        energy_arc: Energy shape description, or None.
        harmonic_mixing: Whether to prefer harmonic mixing.
        key_notation: Key display notation.

    Returns:
        Tuple of (system_prompt, user_message, tool_schema).
    """
    # Build track summaries
    summaries = [_build_track_summary_for_set(t, key_notation) for t in tracks]
    tracks_text = "\n\n".join(summaries)

    # Build parameters section
    params = []
    if duration_minutes:
        params.append(f"- Target duration: {duration_minutes} minutes")
    if target_bpm_start:
        params.append(f"- Starting BPM: {target_bpm_start:.0f}")
    if target_bpm_end:
        params.append(f"- Ending BPM: {target_bpm_end:.0f}")
    if energy_arc:
        params.append(f"- Energy arc: {energy_arc}")
    if harmonic_mixing:
        params.append("- Harmonic mixing: enabled (prefer key-compatible transitions)")

    params_text = "\n".join(params) if params else "No specific parameters set."

    user_message = (
        f'## Set Description\n"{description}"\n\n'
        f"## Parameters\n{params_text}\n\n"
        f"## Instructions\n"
        f"Select {sequence_length} tracks for the sequence and "
        f"{candidate_count - sequence_length} additional candidates.\n"
        f"Total tracks to suggest: {candidate_count}\n\n"
        f"## Available Tracks ({len(tracks)} total)\n{tracks_text}\n\n"
        f"Use the plan_set tool to return your sequence and candidates."
    )

    return _SYSTEM_PROMPT, user_message, _INITIAL_TOOL_SCHEMA


def parse_initial_result(
    tool_input: dict[str, Any],
    valid_ids: set[int],
) -> tuple[list[int], list[int]]:
    """Parse and validate the initial set planning result.

    Args:
        tool_input: Parsed tool input from Claude's response.
        valid_ids: Set of valid track IDs.

    Returns:
        Tuple of (sequence_track_ids, candidate_track_ids).
        Both lists are deduplicated and filtered to valid IDs.
    """
    sequence_data = tool_input.get("sequence", [])
    candidates_data = tool_input.get("candidates", [])

    if not isinstance(sequence_data, list):
        logger.warning("Initial result 'sequence' is not a list: %s", type(sequence_data))
        return [], []

    # Parse sequence — maintain order, deduplicate
    seen: set[int] = set()
    sequence: list[int] = []
    for entry in sequence_data:
        if not isinstance(entry, dict):
            continue
        track_id = entry.get("track_id")
        if track_id is None:
            continue
        try:
            tid = int(track_id)
        except (ValueError, TypeError):
            continue
        if tid in valid_ids and tid not in seen:
            seen.add(tid)
            sequence.append(tid)

    # Parse candidates — exclude sequence tracks, deduplicate
    candidates: list[int] = []
    if isinstance(candidates_data, list):
        for entry in candidates_data:
            if not isinstance(entry, dict):
                continue
            track_id = entry.get("track_id")
            if track_id is None:
                continue
            try:
                tid = int(track_id)
            except (ValueError, TypeError):
                continue
            if tid in valid_ids and tid not in seen:
                seen.add(tid)
                candidates.append(tid)

    return sequence, candidates


def build_replace_prompt(
    description: str,
    locked_tracks: list[tuple[int, Any]],
    unlocked_positions: list[int],
    available_tracks: list[Any],
    segments: list[dict[str, Any]],
    total_positions: int,
    harmonic_mixing: bool = False,
    key_notation: str = "camelot",
) -> tuple[str, str, dict[str, Any]]:
    """Build the prompt for replace-mode shuffle.

    Args:
        description: Overall set description.
        locked_tracks: List of (position, track) tuples for locked tracks.
        unlocked_positions: List of unlocked position numbers.
        available_tracks: Tracks available for replacement.
        segments: Segment descriptions with position ranges.
        total_positions: Total number of positions in the sequence.
        harmonic_mixing: Whether to prefer harmonic mixing.
        key_notation: Key display notation.

    Returns:
        Tuple of (system_prompt, user_message, tool_schema).
    """
    # Build locked tracks section
    locked_lines = []
    for pos, track in locked_tracks:
        summary = _build_track_summary_for_set(track, key_notation)
        locked_lines.append(f"Position {pos} [LOCKED]:\n{summary}")
    locked_text = "\n\n".join(locked_lines) if locked_lines else "No locked tracks."

    # Build segments section
    segment_lines = []
    for seg in segments:
        desc = seg.get("description") or "(no specific description — use overall set description)"
        segment_lines.append(
            f"Segment {seg['position']}: positions {seg['start']}–{seg['end']}\n"
            f"  Description: {desc}"
        )
    segments_text = "\n".join(segment_lines) if segment_lines else "Single segment (whole set)."

    # Build available tracks
    avail_summaries = [_build_track_summary_for_set(t, key_notation) for t in available_tracks]
    avail_text = "\n\n".join(avail_summaries) if avail_summaries else "No available tracks."

    unlocked_text = ", ".join(str(p) for p in unlocked_positions)

    params = []
    if harmonic_mixing:
        params.append("- Harmonic mixing: enabled")
    params_text = "\n".join(params) if params else ""

    user_message = (
        f'## Set Description\n"{description}"\n\n'
        f"## Current Set State\n"
        f"Total positions: {total_positions}\n"
        f"Unlocked positions to fill: {unlocked_text}\n\n"
        f"### Locked Tracks (DO NOT REPLACE)\n{locked_text}\n\n"
        f"### Segments\n{segments_text}\n\n"
    )
    if params_text:
        user_message += f"## Parameters\n{params_text}\n\n"
    user_message += (
        f"## Available Tracks\n{avail_text}\n\n"
        f"Replace the unlocked positions with tracks from the available pool. "
        f"Match each segment's mood description."
    )

    return _REPLACE_SYSTEM_PROMPT, user_message, _REPLACE_TOOL_SCHEMA


def parse_replace_result(
    tool_input: dict[str, Any],
    valid_ids: set[int],
    unlocked_positions: set[int],
    locked_positions: set[int],
) -> list[tuple[int, int]]:
    """Parse and validate replace-mode shuffle result.

    Args:
        tool_input: Parsed tool input from Claude's response.
        valid_ids: Set of valid track IDs.
        unlocked_positions: Set of unlocked position numbers.
        locked_positions: Set of locked position numbers.

    Returns:
        List of (position, track_id) tuples for valid replacements.
    """
    replacements_data = tool_input.get("replacements", [])
    if not isinstance(replacements_data, list):
        logger.warning("Replace result 'replacements' is not a list")
        return []

    result: list[tuple[int, int]] = []
    for entry in replacements_data:
        if not isinstance(entry, dict):
            continue

        position = entry.get("position")
        track_id = entry.get("track_id")
        if position is None or track_id is None:
            continue

        try:
            pos = int(position)
            tid = int(track_id)
        except (ValueError, TypeError):
            continue

        if pos in locked_positions:
            logger.warning("Rejecting replacement at locked position %d", pos)
            continue

        if pos not in unlocked_positions:
            logger.warning("Rejecting replacement at invalid position %d", pos)
            continue

        if tid not in valid_ids:
            logger.warning("Rejecting invalid track ID %d", tid)
            continue

        result.append((pos, tid))

    return result


def build_reorder_prompt(
    description: str,
    current_sequence: list[tuple[int, Any, bool]],
    harmonic_mixing: bool = False,
    key_notation: str = "camelot",
) -> tuple[str, str, dict[str, Any]]:
    """Build the prompt for reorder-mode shuffle.

    Args:
        description: Overall set description.
        current_sequence: List of (position, track, is_locked) tuples.
        harmonic_mixing: Whether to prefer harmonic mixing.
        key_notation: Key display notation.

    Returns:
        Tuple of (system_prompt, user_message, tool_schema).
    """
    seq_lines = []
    for pos, track, is_locked in current_sequence:
        summary = _build_track_summary_for_set(track, key_notation)
        lock_indicator = " [LOCKED — DO NOT MOVE]" if is_locked else ""
        seq_lines.append(f"Position {pos}{lock_indicator}:\n{summary}")
    seq_text = "\n\n".join(seq_lines)

    params = []
    if harmonic_mixing:
        params.append("- Harmonic mixing: enabled")
    params_text = "\n".join(params) if params else ""

    user_message = f'## Set Description\n"{description}"\n\n## Current Sequence\n{seq_text}\n\n'
    if params_text:
        user_message += f"## Parameters\n{params_text}\n\n"
    user_message += (
        "Reorder ONLY the unlocked tracks for optimal BPM flow, "
        "energy progression, and key compatibility. "
        "Locked tracks MUST stay in their positions."
    )

    return _REORDER_SYSTEM_PROMPT, user_message, _REORDER_TOOL_SCHEMA


def parse_reorder_result(
    tool_input: dict[str, Any],
    locked_positions: set[int],
    locked_track_ids: dict[int, int],
    total_positions: int,
    all_track_ids: set[int],
) -> list[tuple[int, int]]:
    """Parse and validate reorder-mode shuffle result.

    Args:
        tool_input: Parsed tool input from Claude's response.
        locked_positions: Set of locked position numbers.
        locked_track_ids: Mapping of locked track_id → position.
        total_positions: Total positions in the sequence.
        all_track_ids: All valid track IDs in the sequence.

    Returns:
        List of (track_id, new_position) tuples for valid reorders.
    """
    reordered_data = tool_input.get("reordered", [])
    if not isinstance(reordered_data, list):
        logger.warning("Reorder result 'reordered' is not a list")
        return []

    result: list[tuple[int, int]] = []
    for entry in reordered_data:
        if not isinstance(entry, dict):
            continue

        track_id = entry.get("track_id")
        new_position = entry.get("new_position")
        if track_id is None or new_position is None:
            continue

        try:
            tid = int(track_id)
            new_pos = int(new_position)
        except (ValueError, TypeError):
            continue

        # Reject if track is locked
        if tid in locked_track_ids:
            logger.warning("Rejecting reorder of locked track %d", tid)
            continue

        # Reject if target position is locked
        if new_pos in locked_positions:
            logger.warning("Rejecting reorder to locked position %d", new_pos)
            continue

        # Reject if position out of bounds
        if new_pos < 1 or new_pos > total_positions:
            logger.warning("Rejecting out-of-bounds position %d", new_pos)
            continue

        # Reject if track not in sequence
        if tid not in all_track_ids:
            logger.warning("Rejecting unknown track ID %d", tid)
            continue

        result.append((tid, new_pos))

    return result
