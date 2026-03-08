"""Claude reasoner — AI-powered placement suggestions for ambiguous tracks.

Sends tracks with low organisation confidence to Claude for folder placement
suggestions. Reuses the Phase 3 ClaudeClient for API calls, rate limiting,
and token tracking.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.services.confidence_scorer import ConfidenceResult
from backend.services.template_engine import ResolvedPath

logger = logging.getLogger(__name__)

VALID_CONFIDENCE = {"high", "medium", "low"}

ORGANISE_SYSTEM_PROMPT = """\
You are helping a DJ organise their music library into folders. The user has a \
folder template that determines the directory structure, but some tracks have \
ambiguous or missing metadata that makes automatic placement difficult.

For each track, suggest the best folder path and explain your reasoning. Consider:
- The user's folder template pattern
- Available metadata (artist, album, genre, BPM, key, etc.)
- Common DJ library conventions
- Whether the track is a VA compilation, bootleg, edit, or remix
- The artist's typical genre or style (from your knowledge)

When metadata is missing, make a reasonable inference from what IS available. \
For example:
- A filename like "Bicep - Glue (Original Mix).flac" tells you the artist \
and title even if tags are empty
- A BPM of 174 strongly suggests Drum & Bass
- A label name often implies a genre\
"""

ORGANISE_TOOL_SCHEMA: dict[str, Any] = {
    "name": "suggest_placement",
    "description": ("Suggest a folder path for an ambiguous track in the DJ's music library."),
    "input_schema": {
        "type": "object",
        "properties": {
            "track_id": {
                "type": "integer",
                "description": "The track ID from the input",
            },
            "suggested_path": {
                "type": "string",
                "description": "Suggested relative folder path (e.g. 'Bicep/Isles/Glue')",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Your confidence in this suggestion",
            },
            "reasoning": {
                "type": "string",
                "description": "One-sentence explanation of why you chose this path",
            },
        },
        "required": ["track_id", "suggested_path", "confidence", "reasoning"],
    },
}


@dataclass
class PlacementSuggestion:
    """A Claude-suggested folder path for an ambiguous track.

    Attributes:
        track_id: Database ID of the track.
        suggested_path: Suggested relative path without extension.
        confidence: Claude's self-assessed confidence: "high", "medium", or "low".
        reasoning: One-sentence explanation.
    """

    track_id: int
    suggested_path: str
    confidence: str
    reasoning: str


def build_organisation_prompt(
    track: Any,
    template: str,
    resolved_path: ResolvedPath,
    confidence_result: ConfidenceResult,
) -> tuple[str, str]:
    """Build the system prompt and user message for Claude placement reasoning.

    Args:
        track: Track model instance.
        template: The user's folder template string.
        resolved_path: Template resolution result for this track.
        confidence_result: Confidence scoring result.

    Returns:
        Tuple of (system_prompt, user_message).
    """
    # Build track summary
    lines = [
        f"Track #{track.id}:",
        f"  Template: {template}",
        f"  Current proposed path: {resolved_path.path}",
        f"  Confidence score: {confidence_result.score}",
    ]

    # Add metadata fields
    fields = [
        ("Title", getattr(track, "title", None)),
        ("Artist", getattr(track, "artist", None)),
        ("Album", getattr(track, "album", None)),
        ("Album Artist", getattr(track, "album_artist", None)),
        ("Genre", getattr(track, "genre", None)),
        ("Subgenre", getattr(track, "subgenre", None)),
        ("Label", getattr(track, "label", None)),
        ("Year", getattr(track, "year", None)),
        ("BPM", getattr(track, "bpm", None)),
        ("Key", getattr(track, "key", None)),
    ]
    for label, value in fields:
        if value is not None and value != "":
            if label == "BPM" and isinstance(value, float):
                lines.append(f"  {label}: {value:.2f}")
            else:
                lines.append(f"  {label}: {value}")

    # Add filename
    source_path = getattr(track, "source_path", None) or getattr(track, "file_path", None)
    if source_path:
        lines.append(f"  Filename: {Path(source_path).name}")

    # Add confidence reasons and flags
    if confidence_result.reasons:
        lines.append("  Confidence factors:")
        for reason in confidence_result.reasons:
            lines.append(f"    - {reason}")

    if confidence_result.flags:
        lines.append(f"  Flags: {', '.join(confidence_result.flags)}")

    # Add fallback info
    if resolved_path.fallbacks_used:
        lines.append(f"  Fallbacks used: {', '.join(resolved_path.fallbacks_used)}")
    if resolved_path.unresolved:
        lines.append(f"  Unresolved variables: {', '.join(resolved_path.unresolved)}")

    user_message = (
        "Please suggest the best folder path for this ambiguous track. "
        "Use the suggest_placement tool to return your result.\n\n" + "\n".join(lines)
    )

    return ORGANISE_SYSTEM_PROMPT, user_message


def parse_placement_result(
    tool_input: dict[str, Any],
    valid_track_ids: list[int],
) -> PlacementSuggestion | None:
    """Parse and validate Claude's tool use response into a PlacementSuggestion.

    Args:
        tool_input: The parsed tool input dict from Claude's ToolUseBlock.
        valid_track_ids: List of valid track IDs for this request.

    Returns:
        PlacementSuggestion if valid, None otherwise.
    """
    required_fields = {"track_id", "suggested_path", "confidence", "reasoning"}
    missing = required_fields - set(tool_input.keys())
    if missing:
        logger.warning("Placement result missing fields: %s", missing)
        return None

    track_id = tool_input["track_id"]
    if track_id not in valid_track_ids:
        logger.warning(
            "Placement result track_id %s not in valid IDs: %s",
            track_id,
            valid_track_ids,
        )
        return None

    # Validate confidence
    confidence = tool_input["confidence"]
    if confidence not in VALID_CONFIDENCE:
        logger.warning("Invalid confidence '%s', defaulting to 'low'", confidence)
        confidence = "low"

    return PlacementSuggestion(
        track_id=track_id,
        suggested_path=str(tool_input["suggested_path"]),
        confidence=confidence,
        reasoning=str(tool_input["reasoning"]),
    )


async def _call_claude_for_placement(
    claude_client: Any,
    system_prompt: str,
    user_message: str,
) -> Any:
    """Make the actual Claude API call for placement suggestions.

    Args:
        claude_client: ClaudeClient instance.
        system_prompt: System prompt.
        user_message: User message.

    Returns:
        Raw Anthropic Message response.
    """
    await claude_client.rate_limiter.acquire()
    return await asyncio.to_thread(
        claude_client.client.messages.create,
        model=claude_client.model,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        tools=[ORGANISE_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": "suggest_placement"},
    )


async def suggest_placement(
    track: Any,
    template: str,
    resolved_path: ResolvedPath,
    confidence_result: ConfidenceResult,
    claude_client: Any,
) -> PlacementSuggestion | None:
    """Send a single ambiguous track to Claude for a placement suggestion.

    Args:
        track: Track model instance.
        template: Folder template string.
        resolved_path: Template resolution result.
        confidence_result: Confidence scoring result.
        claude_client: ClaudeClient instance.

    Returns:
        PlacementSuggestion if Claude provided one, None otherwise.
    """
    system_prompt, user_message = build_organisation_prompt(
        track, template, resolved_path, confidence_result
    )

    try:
        response = await _call_claude_for_placement(claude_client, system_prompt, user_message)

        # Extract tool use result
        for block in response.content:
            if block.type == "tool_use" and block.name == "suggest_placement":
                return parse_placement_result(block.input, [track.id])

        logger.warning(
            "No suggest_placement tool use in Claude response for track %s",
            track.id,
        )
        return None

    except Exception:
        logger.exception("Claude placement suggestion failed for track %s", track.id)
        return None


async def suggest_placements_batch(
    tracks_data: list[tuple[Any, ResolvedPath, ConfidenceResult]],
    template: str,
    claude_client: Any,
) -> list[PlacementSuggestion]:
    """Send multiple ambiguous tracks to Claude for placement suggestions.

    Batches tracks into a single API call for efficiency.

    Args:
        tracks_data: List of (track, resolved_path, confidence_result) tuples.
        template: Folder template string.
        claude_client: ClaudeClient instance.

    Returns:
        List of PlacementSuggestion results.
    """
    if not tracks_data:
        return []

    results: list[PlacementSuggestion] = []

    # For now, process one at a time (could batch into single prompt later)
    for track, resolved_path, confidence_result in tracks_data:
        suggestion = await suggest_placement(
            track, template, resolved_path, confidence_result, claude_client
        )
        if suggestion:
            results.append(suggestion)

    return results
