"""Crate prompt builder — constructs prompts for crate description parsing and track assignment.

Pure logic module with no I/O, no SDK dependency, and no database access.
Handles prompt construction, tool schema definitions, and result parsing
for two operations: interpreting crate descriptions and assigning tracks.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_CRITERIA_SYSTEM_PROMPT = """\
You are a music curation specialist helping a DJ build smart playlists ("crates"). \
Given a free-text description of a desired vibe, extract structured criteria \
that can be used to match tracks from a library.

## What to extract
- **mood**: List of mood keywords that describe the vibe (e.g. ["hypnotic", "warm", "deep"])
- **energy_min / energy_max**: Energy range on a 1–10 scale \
(1 = ambient, 5 = mid-energy, 10 = peak time)
- **bpm_min / bpm_max**: BPM range if mentioned or implied
- **genres**: List of electronic music genres that match the description \
(e.g. ["Deep House", "Minimal House", "Dub Techno"])
- **keywords**: Any other keywords or descriptors worth noting
- **exclude_genres**: Genres to explicitly exclude if mentioned
- **notes**: Your reasoning about what the user is looking for

## Guidelines
- Only fill in fields you can confidently infer from the description
- Leave fields empty/null if the description doesn't mention or imply them
- Be inclusive with genres — list all genres that could match, not just the most specific one
- For energy, infer from mood words: "chill" implies 2–4, \
"driving" implies 7–8, "peak time" implies 9–10
- For BPM, use genre conventions if not explicitly stated: \
house = 120–130, techno = 125–145, DnB = 170–180
- Use the parse_crate_criteria tool to return your structured result.\
"""

_CRITERIA_TOOL_SCHEMA: dict[str, Any] = {
    "name": "parse_crate_criteria",
    "description": "Extract structured criteria from a crate description.",
    "input_schema": {
        "type": "object",
        "properties": {
            "mood": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Mood keywords describing the vibe",
            },
            "energy_min": {
                "type": "integer",
                "description": "Minimum energy level (1–10)",
            },
            "energy_max": {
                "type": "integer",
                "description": "Maximum energy level (1–10)",
            },
            "bpm_min": {
                "type": "integer",
                "description": "Minimum BPM",
            },
            "bpm_max": {
                "type": "integer",
                "description": "Maximum BPM",
            },
            "genres": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Matching genre labels",
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Additional descriptive keywords",
            },
            "exclude_genres": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Genres to exclude",
            },
            "notes": {
                "type": "string",
                "description": "Reasoning about the user's intent",
            },
        },
        "required": [],
    },
}

_ASSIGNMENT_SYSTEM_PROMPT = """\
You are a music curation specialist helping a DJ build smart playlists ("crates"). \
Given a crate description, its parsed criteria, and a batch of track metadata, \
identify which tracks match the crate's vibe.

## Guidelines
- Include every track that matches the crate's overall vibe — crates are pools, not curated lists
- Consider all criteria dimensions: mood, energy, BPM, genre, keywords
- A track doesn't need to match every criterion — use your judgement about overall fit
- When in doubt, include the track (better to have extras than miss good matches)
- Use the assign_tracks tool to return matching track IDs.\
"""

_ASSIGNMENT_TOOL_SCHEMA: dict[str, Any] = {
    "name": "assign_tracks",
    "description": "Return the IDs of tracks that match the crate's vibe.",
    "input_schema": {
        "type": "object",
        "properties": {
            "matching_track_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "IDs of tracks that match the crate criteria",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief explanation of matching strategy",
            },
        },
        "required": ["matching_track_ids"],
    },
}


def build_criteria_prompt(description: str) -> tuple[str, str, dict[str, Any]]:
    """Build the prompt for interpreting a crate description into structured criteria.

    Args:
        description: User's free-text crate description.

    Returns:
        Tuple of (system_prompt, user_message, tool_schema).
    """
    user_message = (
        f"Please interpret the following crate description and extract "
        f'structured criteria:\n\n"{description}"'
    )
    return _CRITERIA_SYSTEM_PROMPT, user_message, _CRITERIA_TOOL_SCHEMA


def parse_criteria_result(tool_input: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate Claude's criteria tool use response.

    Args:
        tool_input: The parsed tool input dict from Claude's ToolUseBlock.

    Returns:
        Validated criteria dict with standardised field names.
        Missing fields are set to None.
    """
    result: dict[str, Any] = {
        "mood": None,
        "energy_min": None,
        "energy_max": None,
        "bpm_min": None,
        "bpm_max": None,
        "genres": None,
        "keywords": None,
        "exclude_genres": None,
        "notes": None,
    }

    # Mood — must be a list
    mood = tool_input.get("mood")
    if mood is not None:
        if isinstance(mood, str):
            result["mood"] = [mood]
        elif isinstance(mood, list):
            result["mood"] = [str(m) for m in mood] if mood else None
        else:
            result["mood"] = None

    # Energy — clamp to 1–10
    for field in ("energy_min", "energy_max"):
        val = tool_input.get(field)
        if val is not None:
            try:
                int_val = int(val)
                result[field] = max(1, min(10, int_val))
            except (ValueError, TypeError):
                result[field] = None

    # BPM — must be positive
    for field in ("bpm_min", "bpm_max"):
        val = tool_input.get(field)
        if val is not None:
            try:
                int_val = int(val)
                result[field] = int_val if int_val > 0 else None
            except (ValueError, TypeError):
                result[field] = None

    # Genres — must be a list
    for field in ("genres", "keywords", "exclude_genres"):
        val = tool_input.get(field)
        if val is not None:
            if isinstance(val, list):
                result[field] = [str(v) for v in val] if val else None
            elif isinstance(val, str):
                result[field] = [val]
            else:
                result[field] = None

    # Notes — string
    notes = tool_input.get("notes")
    if notes is not None:
        result["notes"] = str(notes)

    return result


def build_assignment_prompt(
    description: str,
    criteria: dict[str, Any],
    track_summaries: str,
) -> tuple[str, str, dict[str, Any]]:
    """Build the prompt for assigning tracks to a crate.

    Args:
        description: Original crate description.
        criteria: Parsed criteria dict from parse_criteria_result().
        track_summaries: Formatted track metadata text.

    Returns:
        Tuple of (system_prompt, user_message, tool_schema).
    """
    # Format criteria for display
    criteria_lines = []
    for key, value in criteria.items():
        if value is not None:
            criteria_lines.append(f"  {key}: {json.dumps(value)}")
    criteria_text = "\n".join(criteria_lines) if criteria_lines else "  (no specific criteria)"

    user_message = (
        f"## Crate Description\n"
        f'"{description}"\n\n'
        f"## Parsed Criteria\n"
        f"{criteria_text}\n\n"
        f"## Tracks\n"
        f"{track_summaries}\n\n"
        f"Identify which tracks match this crate's vibe and return their IDs."
    )

    return _ASSIGNMENT_SYSTEM_PROMPT, user_message, _ASSIGNMENT_TOOL_SCHEMA


def parse_assignment_result(
    tool_input: dict[str, Any],
    valid_ids: set[int],
) -> list[int]:
    """Parse and validate Claude's track assignment tool use response.

    Args:
        tool_input: The parsed tool input dict from Claude's ToolUseBlock.
        valid_ids: Set of valid track IDs (for filtering invalid responses).

    Returns:
        Deduplicated list of valid matching track IDs.
    """
    ids = tool_input.get("matching_track_ids")
    if not isinstance(ids, list):
        if ids is not None:
            logger.warning("matching_track_ids is not a list: %s", type(ids))
        return []

    seen: set[int] = set()
    result: list[int] = []
    for track_id in ids:
        try:
            int_id = int(track_id)
        except (ValueError, TypeError):
            logger.warning("Invalid track ID in assignment result: %s", track_id)
            continue

        if int_id not in valid_ids:
            logger.warning("Track ID %d not in valid set, skipping", int_id)
            continue

        if int_id not in seen:
            seen.add(int_id)
            result.append(int_id)

    return result
