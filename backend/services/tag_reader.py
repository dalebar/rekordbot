"""Tag reader — reads metadata tags from audio files using mutagen.

Reads from output files (AIFF, MP3, M4A). Returns a TagData dataclass
with None for any missing fields. Never raises on missing or corrupt tags.
"""

import contextlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TagData:
    """Metadata tags read from an audio file.

    All fields are optional — None indicates the tag was not present.
    """

    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    genre: str | None = None
    year: int | None = None
    track_number: int | None = None
    comment: str | None = None
    label: str | None = None
    bpm: float | None = None
    key: str | None = None
    rating: int | None = None
    duration: float | None = None


def parse_track_number(value: str | None) -> int | None:
    """Parse a track number from TRCK tag value.

    Handles formats like "3", "3/12", and whitespace.

    Args:
        value: Raw TRCK tag value.

    Returns:
        Track number as integer, or None if unparseable.
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    # Handle "3/12" format — take the part before the slash
    if "/" in value:
        value = value.split("/")[0].strip()
    try:
        return int(value)
    except ValueError:
        return None


def parse_year(value: str | None) -> int | None:
    """Parse a year from TYER or TDRC tag value.

    Handles formats like "2024", "2024-03-15", and "2024-03-15T00:00:00".

    Args:
        value: Raw year/date tag value.

    Returns:
        Year as integer, or None if unparseable.
    """
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    # Extract leading numeric portion (handles "2024-03-15" and "2024")
    match = re.match(r"(\d+)", value)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


def _safe_str(value: object) -> str | None:
    """Safely convert a tag value to string, returning None for empty."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _safe_float(value: object) -> float | None:
    """Safely convert a tag value to float."""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


def _read_id3_tags(file_path: Path) -> TagData | None:
    """Read tags from ID3-tagged files (AIFF and MP3).

    Args:
        file_path: Path to the audio file.

    Returns:
        TagData with extracted values, or None on error.
    """
    from mutagen import File as MutagenFile  # type: ignore[import-not-found]

    try:
        audio = MutagenFile(str(file_path))
        if audio is None:
            logger.warning("mutagen could not open: %s", file_path)
            return None
    except Exception:
        logger.warning("Error opening file with mutagen: %s", file_path, exc_info=True)
        return None

    tags = audio.tags
    duration = audio.info.length if audio.info else None

    if tags is None:
        return TagData(duration=duration)

    def get_text(frame_id: str) -> str | None:
        """Get text value from an ID3 frame."""
        frame = tags.get(frame_id)  # type: ignore[union-attr]
        if frame is None:
            return None
        # ID3 text frames have a .text attribute (list of strings)
        if hasattr(frame, "text") and frame.text:
            return _safe_str(frame.text[0])
        return _safe_str(frame)

    # Extract year — prefer TDRC (v2.4) over TYER (v2.3)
    year_str = get_text("TDRC") or get_text("TYER")
    year = parse_year(year_str)

    # Extract track number
    track_number = parse_track_number(get_text("TRCK"))

    # Extract BPM
    bpm = _safe_float(get_text("TBPM"))

    # Extract comment — COMM frames have desc and lang attributes
    comment = None
    for key in tags:  # type: ignore[union-attr]
        if key.startswith("COMM"):
            comm_frame = tags[key]  # type: ignore[index]
            if hasattr(comm_frame, "text") and comm_frame.text:
                comment = _safe_str(comm_frame.text[0])
                break

    # Extract rating from POPM frame
    rating = None
    for key in tags:  # type: ignore[union-attr]
        if key.startswith("POPM"):
            popm_frame = tags[key]  # type: ignore[index]
            if hasattr(popm_frame, "rating"):
                rating = popm_frame.rating
                break

    return TagData(
        title=get_text("TIT2"),
        artist=get_text("TPE1"),
        album=get_text("TALB"),
        album_artist=get_text("TPE2"),
        genre=get_text("TCON"),
        year=year,
        track_number=track_number,
        comment=comment,
        label=get_text("TPUB"),
        bpm=bpm,
        key=get_text("TKEY"),
        rating=rating,
        duration=duration,
    )


def _read_mp4_tags(file_path: Path) -> TagData | None:
    """Read tags from MP4/M4A files.

    Args:
        file_path: Path to the M4A file.

    Returns:
        TagData with extracted values, or None on error.
    """
    from mutagen.mp4 import MP4  # type: ignore[import-not-found]

    try:
        audio = MP4(str(file_path))
    except Exception:
        logger.warning("Error opening M4A with mutagen: %s", file_path, exc_info=True)
        return None

    tags = audio.tags
    duration = audio.info.length if audio.info else None

    if tags is None:
        return TagData(duration=duration)

    def get_text(atom: str) -> str | None:
        """Get text value from an MP4 atom."""
        value = tags.get(atom)
        if value is None:
            return None
        if isinstance(value, list) and len(value) > 0:
            return _safe_str(value[0])
        return _safe_str(value)

    # Track number — stored as list of (track, total) tuples
    track_number = None
    trkn = tags.get("trkn")
    if trkn and isinstance(trkn, list) and len(trkn) > 0:
        track_tuple = trkn[0]
        if isinstance(track_tuple, tuple) and len(track_tuple) >= 1:
            track_number = track_tuple[0]

    # BPM — tmpo atom stores integer
    bpm = None
    tmpo = tags.get("tmpo")
    if tmpo and isinstance(tmpo, list) and len(tmpo) > 0:
        with contextlib.suppress(ValueError, TypeError):
            bpm = float(tmpo[0])

    # Key — freeform atom
    key = None
    initial_key = tags.get("----:com.apple.iTunes:INITIALKEY")
    if initial_key and isinstance(initial_key, list) and len(initial_key) > 0:
        raw = initial_key[0]
        if isinstance(raw, bytes):
            key = raw.decode("utf-8", errors="replace").strip() or None
        else:
            key = _safe_str(raw)

    # Year
    year = parse_year(get_text("\xa9day"))

    return TagData(
        title=get_text("\xa9nam"),
        artist=get_text("\xa9ART"),
        album=get_text("\xa9alb"),
        album_artist=get_text("aART"),
        genre=get_text("\xa9gen"),
        year=year,
        track_number=track_number,
        comment=get_text("\xa9cmt"),
        label=get_text("\xa9pub") or get_text("----:com.apple.iTunes:LABEL"),
        bpm=bpm,
        key=key,
        rating=None,  # MP4 doesn't have a standard rating atom
        duration=duration,
    )


def read_tags(file_path: Path) -> TagData | None:
    """Read metadata tags from an audio file.

    Supports AIFF, MP3 (ID3v2), and M4A (MP4 atoms).
    Returns None if the file cannot be read or is not a supported format.

    Args:
        file_path: Path to the audio file.

    Returns:
        TagData with extracted values, or None on error.
    """
    if not file_path.exists():
        logger.warning("File not found: %s", file_path)
        return None

    suffix = file_path.suffix.lower()

    if suffix in {".aiff", ".aif", ".mp3"}:
        return _read_id3_tags(file_path)
    elif suffix == ".m4a":
        return _read_mp4_tags(file_path)
    else:
        logger.debug("Unsupported format for tag reading: %s", suffix)
        return None
