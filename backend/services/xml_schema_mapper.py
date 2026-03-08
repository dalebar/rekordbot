"""XML schema mapper — maps Track model fields to Rekordbox XML TRACK attributes.

Handles type formatting, fallback values, and warning collection for tracks
that have missing or invalid metadata.
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from backend.services.key_notation import key_to_display
from backend.services.location_encoder import encode_location

logger = logging.getLogger(__name__)

# Rating scale: 0–5 stars → Rekordbox non-linear values
_RATING_MAP: dict[int, int] = {
    0: 0,
    1: 51,
    2: 102,
    3: 153,
    4: 204,
    5: 255,
}

# File extension → Kind string
_KIND_MAP: dict[str, str] = {
    ".aiff": "AIFF File",
    ".aif": "AIFF File",
    ".mp3": "MP3 File",
    ".m4a": "M4A File",
    ".wav": "WAV File",
    ".flac": "FLAC File",
}


@dataclass
class TrackXmlResult:
    """Result of mapping a Track to XML attributes.

    Attributes:
        attrs: All attributes as strings, ready for ElementTree.
        warnings: Issues encountered (missing file, null required field, etc.).
    """

    attrs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def format_bpm(bpm: float | None) -> str:
    """Format BPM as a two-decimal float string.

    Args:
        bpm: BPM value, or None.

    Returns:
        Formatted string like "128.00", or "0.00" if None.
    """
    if bpm is None:
        return "0.00"
    return f"{bpm:.2f}"


def format_rating(rating: int | None) -> str:
    """Convert 0–5 star rating to Rekordbox non-linear scale string.

    Args:
        rating: Star rating (0–5), or None.

    Returns:
        Rekordbox rating value as string (0, 51, 102, 153, 204, or 255).
    """
    if rating is None or rating not in _RATING_MAP:
        return "0"
    return str(_RATING_MAP[rating])


def format_kind(output_path: str) -> str:
    """Derive file kind string from file extension.

    Args:
        output_path: File path to derive extension from.

    Returns:
        Kind string like "AIFF File", "MP3 File", or "Audio File" for unknown.
    """
    ext = Path(output_path).suffix.lower()
    return _KIND_MAP.get(ext, "Audio File")


def format_date(dt: datetime | str | None) -> str:
    """Format a datetime or date string as yyyy-mm-dd.

    Args:
        dt: A datetime object, ISO date string, or None.

    Returns:
        Formatted date string, or empty string if None.
    """
    if dt is None:
        return ""
    if isinstance(dt, str):
        return dt[:10] if len(dt) >= 10 else dt
    return dt.strftime("%Y-%m-%d")


def compute_bitrate(
    sample_rate: int | None,
    bit_depth: int | None,
    channels: int | None,
) -> int:
    """Compute bitrate in kbps for lossless audio.

    Args:
        sample_rate: Sample rate in Hz (e.g. 44100).
        bit_depth: Bits per sample (e.g. 16, 24).
        channels: Number of audio channels (e.g. 2 for stereo).

    Returns:
        Bitrate in kbps, or 0 if any input is missing.
    """
    if not sample_rate or not bit_depth or not channels:
        return 0
    return (sample_rate * bit_depth * channels) // 1000


def _resolve_bitrate(track: object) -> int:
    """Resolve the correct bitrate for a track.

    - Lossy files (MP3, AAC): use source_bitrate from ffprobe
    - Lossless files (AIFF, WAV, FLAC): compute from sample_rate × bit_depth × channels

    Args:
        track: Track model instance.

    Returns:
        Bitrate in kbps, or 0 if undetermined.
    """
    is_lossy = getattr(track, "is_lossy", None)
    source_bitrate = getattr(track, "source_bitrate", None)

    if is_lossy and source_bitrate:
        return int(source_bitrate)

    # Lossless: compute from audio properties
    sample_rate = getattr(track, "sample_rate", None)
    bit_depth = getattr(track, "bit_depth", None) or getattr(track, "source_bit_depth", None)
    channels = getattr(track, "channels", None)

    computed = compute_bitrate(sample_rate, bit_depth, channels)
    if computed:
        return computed

    # Fallback: use source_bitrate if available even for non-lossy
    if source_bitrate:
        return int(source_bitrate)

    return 0


def get_file_size(path: str) -> int:
    """Get file size in bytes, returning 0 if file doesn't exist.

    Args:
        path: Absolute file path.

    Returns:
        File size in bytes, or 0 if not found.
    """
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _get_file_mtime(path: str) -> str:
    """Get file modification date as yyyy-mm-dd string.

    Args:
        path: Absolute file path.

    Returns:
        Date string, or empty string if file not found.
    """
    try:
        mtime = os.path.getmtime(path)
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
    except OSError:
        return ""


def track_to_xml_attrs(
    track: object,
    track_id: int,
    key_notation: str,
) -> TrackXmlResult:
    """Map a Track model instance to Rekordbox XML TRACK attributes.

    Args:
        track: Track model instance with metadata fields.
        track_id: Sequential TrackID to assign (1-indexed).
        key_notation: Key notation preference ("camelot", "open_key", "classical").

    Returns:
        TrackXmlResult with attribute dict and any warnings.
    """
    warnings: list[str] = []
    file_path: str = getattr(track, "file_path", "")
    db_id: int = getattr(track, "id", 0)

    # Read file info from disk
    size = get_file_size(file_path)
    if size == 0 and file_path:
        warnings.append(f"Track {db_id}: file not found or size is 0 at {file_path}")

    date_modified = _get_file_mtime(file_path)

    # Title fallback: filename stem
    title = getattr(track, "title", None)
    if not title:
        title = Path(file_path).stem if file_path else "Untitled"

    # Artist fallback
    artist = getattr(track, "artist", None) or "Unknown Artist"

    # Key conversion
    key_int = getattr(track, "key", None)
    tonality = key_to_display(key_int, key_notation)

    # Duration as integer seconds (truncated)
    duration = getattr(track, "duration", None)
    total_time = str(int(duration)) if duration else "0"

    # Date added
    imported_at = getattr(track, "imported_at", None)
    date_added = format_date(imported_at)

    # Build required attributes
    attrs: dict[str, str] = {
        "TrackID": str(track_id),
        "Name": title,
        "Artist": artist,
        "Album": getattr(track, "album", None) or "",
        "Genre": getattr(track, "genre", None) or "",
        "Kind": format_kind(file_path),
        "Size": str(size),
        "TotalTime": total_time,
        "DiscNumber": str(getattr(track, "disc_number", None) or 0),
        "TrackNumber": str(getattr(track, "track_number", None) or 0),
        "Year": str(getattr(track, "year", None) or 0),
        "AverageBpm": format_bpm(getattr(track, "bpm", None)),
        "DateModified": date_modified,
        "DateAdded": date_added,
        "BitRate": str(_resolve_bitrate(track)),
        "SampleRate": str(getattr(track, "sample_rate", None) or 0),
        "Comments": getattr(track, "comment", None) or "",
        "PlayCount": "0",
        "Rating": format_rating(getattr(track, "rating", None)),
        "Location": encode_location(file_path) if file_path else "",
        "Tonality": tonality,
        "Colour": "0",
    }

    # Optional attributes — only include if set
    optional_fields = {
        "Composer": "composer",
        "AlbumArtist": "album_artist",
        "Grouping": "grouping",
        "Remixer": "remixer",
        "Label": "label",
        "Mix": "mix_name",
    }
    for xml_attr, model_field in optional_fields.items():
        value = getattr(track, model_field, None)
        if value is not None:
            attrs[xml_attr] = value

    return TrackXmlResult(attrs=attrs, warnings=warnings)
