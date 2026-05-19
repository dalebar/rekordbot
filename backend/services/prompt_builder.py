"""Prompt builder — constructs prompts and parses results for Claude AI tagging.

Pure logic module with no I/O, no SDK dependency, and no database access.
Handles system prompt generation, track summarisation, batch grouping,
tool schema definition, and result parsing with validation.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AiTagResult:
    """Parsed result for a single track from Claude's tool use response.

    Attributes:
        track_id: Database ID of the track.
        genre: AI-inferred primary genre.
        subgenre: More specific subgenre, or empty string.
        mood: Descriptive mood label.
        energy: Energy score 1-10.
        confidence: Self-assessed confidence: "high", "medium", or "low".
        reasoning: One-sentence explanation.
    """

    track_id: int
    genre: str
    subgenre: str
    mood: str
    energy: int
    confidence: str
    reasoning: str


_GENRE_LIST = """
- House: Deep House, Tech House, Progressive House, Acid House, \
Minimal House, Afro House, Melodic House, Funky House, Soulful House, Jackin House
- Techno: Melodic Techno, Acid Techno, Hard Techno, Industrial Techno, \
Minimal Techno, Detroit Techno, Dub Techno, Peak Time Techno
- Drum & Bass: Liquid DnB, Jungle, Neurofunk, Jump Up, Minimal DnB
- Trance: Progressive Trance, Psytrance, Uplifting Trance, Acid Trance, Tech Trance
- Bass Music: Dubstep, Future Bass, Riddim, UK Bass
- Garage: UK Garage, 2-Step, Speed Garage, Bassline
- Breakbeat: Breaks, Big Beat, Electro Breaks
- Ambient & Downtempo: Ambient, Downtempo, Chillout, IDM, Balearic
- Disco: Nu-Disco, Italo Disco, Cosmic Disco, Disco Edits
- Electro: Electro, Electronica
- Other: Hip-Hop, Trip-Hop, Funk, Soul, R&B, Reggae, Dub, \
Afrobeats, Amapiano, UK Funky, Grime
""".strip()

_MOOD_EXAMPLES = (
    "Euphoric, Dark, Hypnotic, Uplifting, Melancholic, Aggressive, "
    "Dreamy, Groovy, Energetic, Mysterious, Anthemic, Soulful, "
    "Atmospheric, Driving, Funky, Playful, Intense, Ethereal, Raw, "
    "Warm, Blissful, Haunting, Gritty, Nostalgic, Meditative"
)

SYSTEM_PROMPT = f"""\
You are a music metadata specialist helping a DJ organise their library. \
For each track, infer the genre, subgenre, mood, and energy level \
based on the available metadata.

## Genre Guidelines
Use genre labels commonly recognised by DJs. Prefer specific subgenres \
over broad categories. For example, use "Melodic Techno" rather than \
"Electronic" or "Dance".

Common electronic music genres (use these as a starting point, \
but you may use others when appropriate):
{_GENRE_LIST}

If the track doesn't fit neatly into electronic music \
(e.g. it's a rock or pop track a DJ might play), \
use an appropriate genre label from the broader music world.

## Mood
Use a single descriptive word or short phrase. \
Examples: {_MOOD_EXAMPLES}.

## Energy Scale (1\u201310)
1\u20132: Ambient, minimal, barely there. Intro/outro material.
3\u20134: Downtempo, chillout, warm-up. Gentle groove.
5\u20136: Mid-energy, cruising. Solid groove, not pushing.
7\u20138: Driving, building. Strong dancefloor energy.
9\u201310: Peak time, relentless. Maximum intensity.

## Confidence
Rate your confidence as "high", "medium", or "low":
- High: You recognise the artist/label/track or the metadata \
gives strong signals.
- Medium: Reasonable inference from available clues but some uncertainty.
- Low: Limited metadata, ambiguous signals, or unfamiliar artist/label.

## Instructions
- Use the tag_tracks tool to return your results.
- Provide a brief reasoning for each track \
(one sentence explaining your classification).
- If existing genre tags are present, consider them as a signal \
but don't blindly trust them \u2014 they are often wrong or overly broad.
- BPM is a strong genre signal (e.g. 170+ BPM suggests DnB \
or hard techno; 120-126 BPM suggests deep or tech house).
- Artist and label names are often the strongest signals. \
Use your knowledge of the music industry.
- When unsure between two genres, pick the more specific one \
and note your uncertainty in the reasoning.\
"""

TOOL_SCHEMA: dict[str, Any] = {
    "name": "tag_tracks",
    "description": (
        "Apply genre, mood, and energy tags to a batch of tracks "
        "based on analysis of their metadata."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "tracks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "track_id": {
                            "type": "integer",
                            "description": "The track ID from the input",
                        },
                        "genre": {
                            "type": "string",
                            "description": (
                                "Primary genre (e.g. 'Tech House', 'Melodic Techno', 'Liquid DnB')"
                            ),
                        },
                        "subgenre": {
                            "type": "string",
                            "description": (
                                "More specific subgenre if applicable, "
                                "or empty string if genre is already specific enough"
                            ),
                        },
                        "mood": {
                            "type": "string",
                            "description": ("Single word or short phrase describing the mood"),
                        },
                        "energy": {
                            "type": "integer",
                            "description": ("Energy level from 1 (ambient) to 10 (peak time)"),
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "Your confidence in this classification",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": ("One sentence explaining your classification"),
                        },
                    },
                    "required": [
                        "track_id",
                        "genre",
                        "subgenre",
                        "mood",
                        "energy",
                        "confidence",
                        "reasoning",
                    ],
                },
            }
        },
        "required": ["tracks"],
    },
}

VALID_CONFIDENCE = {"high", "medium", "low"}


def build_system_prompt() -> str:
    """Return the full system prompt for Claude AI tagging.

    Returns:
        The system prompt string with genre guidance, mood vocabulary,
        energy scale, and tool use instructions.
    """
    return SYSTEM_PROMPT


def build_track_summary(track: Any) -> str:
    """Format a single track's metadata for the prompt.

    Fields that are None or empty strings are omitted to reduce noise.

    Args:
        track: Track model instance (or any object with the expected attributes).

    Returns:
        Formatted track summary string.
    """
    lines = [f"Track #{track.id}:"]

    fields: list[tuple[str, Any]] = [
        ("Title", track.title),
        ("Artist", track.artist),
        ("Album", getattr(track, "album", None)),
        ("Label", getattr(track, "label", None)),
        ("Year", getattr(track, "year", None)),
        ("Existing Genre", getattr(track, "genre", None)),
        ("BPM", getattr(track, "bpm", None)),
        ("Comment", getattr(track, "comment", None)),
    ]

    for label, value in fields:
        if value is not None and value != "":
            if label == "BPM" and isinstance(value, float):
                lines.append(f"  {label}: {value:.2f}")
            else:
                lines.append(f"  {label}: {value}")

    # Filename from source_path or file_path
    source_path = getattr(track, "source_path", None)
    file_path = getattr(track, "file_path", None)
    path = source_path or file_path
    if path:
        filename = Path(path).name
        lines.append(f"  Filename: {filename}")

    return "\n".join(lines)


def build_batch_message(tracks: list[Any]) -> str:
    """Format a batch of track summaries as the user message.

    Args:
        tracks: List of Track model instances.

    Returns:
        User message string containing all track summaries.
    """
    summaries = [build_track_summary(track) for track in tracks]

    header = f"Please tag the following {len(tracks)} track(s):\n\n"
    return header + "\n\n".join(summaries)


def get_tool_schema() -> dict[str, Any]:
    """Return the tool schema definition for Claude's tag_tracks tool.

    Returns:
        Tool schema dictionary matching the Anthropic tool use format.
    """
    return TOOL_SCHEMA


def group_tracks_into_batches(tracks: list[Any], batch_size: int) -> list[list[Any]]:
    """Group tracks into batches, preferring same-artist grouping.

    Tracks by the same artist are grouped together within batches when possible.
    If an artist has more tracks than batch_size, they are split across batches.

    Args:
        tracks: List of Track model instances to group.
        batch_size: Maximum number of tracks per batch.

    Returns:
        List of batches, each batch being a list of tracks.
    """
    if not tracks:
        return []

    # Group by artist
    artist_groups: dict[str | None, list[Any]] = defaultdict(list)
    for track in tracks:
        artist = getattr(track, "artist", None)
        artist_groups[artist].append(track)

    # Build ordered list grouped by artist
    ordered: list[Any] = []
    for artist_tracks in artist_groups.values():
        ordered.extend(artist_tracks)

    # Split into batches
    batches = []
    for i in range(0, len(ordered), batch_size):
        batches.append(ordered[i : i + batch_size])

    return batches


def _validate_energy(value: Any) -> int:
    """Validate and clamp energy to 1-10 range.

    Args:
        value: Energy value from Claude's response.

    Returns:
        Clamped integer energy value.
    """
    return max(1, min(10, int(value)))


def _validate_confidence(value: Any) -> str:
    """Validate confidence is one of the accepted values.

    Args:
        value: Confidence string from Claude's response.

    Returns:
        Validated confidence string, defaulting to "low" if invalid.
    """
    if isinstance(value, str) and value in VALID_CONFIDENCE:
        return value
    return "low"


def parse_tool_result(tool_input: dict[str, Any], batch_track_ids: list[int]) -> list[AiTagResult]:
    """Parse and validate Claude's tool use response into AiTagResult objects.

    Filters out track IDs not in the batch, skips entries with missing
    required fields, clamps energy values, and validates confidence.

    Args:
        tool_input: The parsed tool input dict from Claude's ToolUseBlock.
        batch_track_ids: List of track IDs that were in the batch (for filtering).

    Returns:
        List of validated AiTagResult objects.
    """
    tracks_data = tool_input.get("tracks", [])
    if not isinstance(tracks_data, list):
        logger.warning("Tool result 'tracks' is not a list: %s", type(tracks_data))
        return []

    valid_ids = set(batch_track_ids)
    results: list[AiTagResult] = []
    required_fields = {"track_id", "genre", "mood", "energy", "confidence", "reasoning"}

    for entry in tracks_data:
        if not isinstance(entry, dict):
            logger.warning("Skipping non-dict track entry: %s", type(entry))
            continue

        # Check required fields
        missing = required_fields - set(entry.keys())
        if missing:
            logger.warning(
                "Skipping track entry missing fields %s: %s",
                missing,
                entry.get("track_id", "unknown"),
            )
            continue

        track_id = entry["track_id"]
        if track_id not in valid_ids:
            logger.warning(
                "Ignoring track_id %s not in batch (expected: %s)", track_id, batch_track_ids
            )
            continue

        try:
            result = AiTagResult(
                track_id=track_id,
                genre=str(entry["genre"]),
                subgenre=str(entry.get("subgenre", "")),
                mood=str(entry["mood"]),
                energy=_validate_energy(entry["energy"]),
                confidence=_validate_confidence(entry["confidence"]),
                reasoning=str(entry["reasoning"]),
            )
            results.append(result)
        except (ValueError, TypeError) as e:
            logger.warning("Failed to parse track entry %s: %s", track_id, e)
            continue

    return results
