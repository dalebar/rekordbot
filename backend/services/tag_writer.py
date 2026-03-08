"""Tag writer — writes metadata tags to audio files using mutagen.

Writes ID3v2.3 tags to AIFF and MP3 files, MP4 atoms to M4A files.
Only called on explicit user action — never automatic. Preserves
existing tags not managed by rekordbot (album art, custom frames).
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from backend.exceptions import TagWriteError
from backend.services.key_notation import key_to_open_key_str

logger = logging.getLogger(__name__)


@dataclass
class TagWriteResult:
    """Result of writing tags to a single file.

    Attributes:
        success: Whether tag writing succeeded.
        file_path: Path to the file that was written.
        error: Error message if writing failed.
    """

    success: bool
    file_path: str
    error: str | None = None


@dataclass
class TagValues:
    """Tag values to write to a file.

    Only non-None fields will be written. Existing tags for None fields
    are preserved.
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
    key: int | None = None  # internal int 1–24, written as Open Key notation
    rating: int | None = None


def _write_id3_tags(file_path: Path, values: TagValues) -> TagWriteResult:
    """Write ID3v2.3 tags to an AIFF or MP3 file.

    Args:
        file_path: Path to the audio file.
        values: Tag values to write.

    Returns:
        TagWriteResult indicating success/failure.
    """
    from mutagen import File as MutagenFile  # type: ignore[import-not-found]
    from mutagen.id3 import (  # type: ignore[import-not-found]
        COMM,
        POPM,
        TALB,
        TBPM,
        TCON,
        TIT2,
        TKEY,
        TPE1,
        TPE2,
        TPUB,
        TRCK,
        TYER,
    )

    try:
        audio = MutagenFile(str(file_path))
        if audio is None:
            return TagWriteResult(
                success=False, file_path=str(file_path), error="Cannot open file"
            )

        # Ensure ID3 tags exist
        if audio.tags is None:
            audio.add_tags()

        tags = audio.tags

        # Write text frames — only update non-None values
        frame_map = {
            "TIT2": (TIT2, values.title),
            "TPE1": (TPE1, values.artist),
            "TALB": (TALB, values.album),
            "TPE2": (TPE2, values.album_artist),
            "TCON": (TCON, values.genre),
            "TPUB": (TPUB, values.label),
        }

        for frame_id, (frame_class, value) in frame_map.items():
            if value is not None:
                tags[frame_id] = frame_class(encoding=3, text=[value])  # type: ignore[index]

        # Year — write as TYER (ID3v2.3 compatible)
        if values.year is not None:
            tags["TYER"] = TYER(encoding=3, text=[str(values.year)])  # type: ignore[index]

        # Track number
        if values.track_number is not None:
            tags["TRCK"] = TRCK(encoding=3, text=[str(values.track_number)])  # type: ignore[index]

        # Comment
        if values.comment is not None:
            tags["COMM::eng"] = COMM(  # type: ignore[index]
                encoding=3, lang="eng", desc="", text=[values.comment]
            )

        # BPM
        if values.bpm is not None:
            tags["TBPM"] = TBPM(encoding=3, text=[f"{values.bpm:.2f}"])  # type: ignore[index]

        # Key — write as Open Key notation
        if values.key is not None:
            open_key = key_to_open_key_str(values.key)
            tags["TKEY"] = TKEY(encoding=3, text=[open_key])  # type: ignore[index]

        # Rating
        if values.rating is not None:
            tags["POPM:rekordbot"] = POPM(  # type: ignore[index]
                email="rekordbot", rating=values.rating, count=0
            )

        # Save as ID3v2.3, no ID3v1
        # AIFF (IffID3) doesn't support v1 parameter — only MP3 does
        is_mp3 = file_path.suffix.lower() == ".mp3"
        if is_mp3:
            audio.save(v2_version=3, v1=0)  # type: ignore[call-arg]
        else:
            audio.save(v2_version=3)  # type: ignore[call-arg]

        logger.info("Tags written to %s", file_path)
        return TagWriteResult(success=True, file_path=str(file_path))

    except Exception as e:
        logger.exception("Failed to write tags to %s", file_path)
        return TagWriteResult(success=False, file_path=str(file_path), error=str(e))


def _write_mp4_tags(file_path: Path, values: TagValues) -> TagWriteResult:
    """Write MP4 atoms to an M4A file.

    Args:
        file_path: Path to the M4A file.
        values: Tag values to write.

    Returns:
        TagWriteResult indicating success/failure.
    """
    from mutagen.mp4 import MP4, MP4FreeForm  # type: ignore[import-not-found]

    try:
        audio = MP4(str(file_path))

        if audio.tags is None:
            audio.add_tags()

        tags = audio.tags

        # Text atoms — only update non-None values
        atom_map = {
            "\xa9nam": values.title,
            "\xa9ART": values.artist,
            "\xa9alb": values.album,
            "aART": values.album_artist,
            "\xa9gen": values.genre,
            "\xa9cmt": values.comment,
        }

        for atom, value in atom_map.items():
            if value is not None:
                tags[atom] = [value]  # type: ignore[index]

        # Label — use standard publisher atom
        if values.label is not None:
            tags["\xa9pub"] = [values.label]  # type: ignore[index]

        # Year
        if values.year is not None:
            tags["\xa9day"] = [str(values.year)]  # type: ignore[index]

        # Track number — stored as (track, total) tuple
        if values.track_number is not None:
            tags["trkn"] = [(values.track_number, 0)]  # type: ignore[index]

        # BPM — tmpo atom is integer only
        if values.bpm is not None:
            tags["tmpo"] = [int(round(values.bpm))]  # type: ignore[index]

        # Key — freeform INITIALKEY atom
        if values.key is not None:
            open_key = key_to_open_key_str(values.key)
            tags["----:com.apple.iTunes:INITIALKEY"] = [  # type: ignore[index]
                MP4FreeForm(open_key.encode("utf-8"))
            ]

        audio.save()

        logger.info("MP4 tags written to %s", file_path)
        return TagWriteResult(success=True, file_path=str(file_path))

    except Exception as e:
        logger.exception("Failed to write MP4 tags to %s", file_path)
        return TagWriteResult(success=False, file_path=str(file_path), error=str(e))


def write_tags(file_path: Path, values: TagValues) -> TagWriteResult:
    """Write metadata tags to an audio file.

    Supports AIFF, MP3 (ID3v2.3, no v1), and M4A (MP4 atoms).
    Only writes non-None fields in values; existing tags are preserved.

    Args:
        file_path: Path to the audio file.
        values: Tag values to write.

    Returns:
        TagWriteResult indicating success/failure.

    Raises:
        TagWriteError: If the file doesn't exist or is not a supported format.
    """
    if not file_path.exists():
        raise TagWriteError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()

    if suffix in {".aiff", ".aif", ".mp3"}:
        return _write_id3_tags(file_path, values)
    elif suffix == ".m4a":
        return _write_mp4_tags(file_path, values)
    else:
        raise TagWriteError(f"Unsupported format for tag writing: {suffix}")
