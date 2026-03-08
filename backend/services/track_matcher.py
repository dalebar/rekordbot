"""Track matcher — matches parsed XML tracks against the existing database.

Determines whether a parsed track already exists in rekordbot by file path
(primary) or SHA-256 hash (secondary). Detects metadata conflicts for matched
tracks so the user can review differences.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.models.track import Track
from backend.services.converter import compute_file_hash
from backend.services.xml_parser import ParsedTrack

logger = logging.getLogger(__name__)

# BPM difference threshold below which no conflict is flagged
_BPM_THRESHOLD = 0.5


@dataclass
class FieldConflict:
    """A metadata difference between Rekordbox and rekordbot."""

    field: str
    rekordbox_value: Any
    rekordbot_value: Any
    recommended: str  # "rekordbox" or "rekordbot"


@dataclass
class MatchResult:
    """Result of attempting to match a parsed track to the database."""

    match_type: str  # "path", "hash", or "new"
    existing_track: Track | None = None
    conflicts: list[FieldConflict] = field(default_factory=list)


def detect_conflicts(parsed: ParsedTrack, existing: Track) -> list[FieldConflict]:
    """Compare fields between a parsed XML track and an existing DB track.

    Only flags conflicts when both sides have values and they differ.
    When only one side has a value, no conflict — auto-merge will fill the gap.

    Args:
        parsed: Track data from the Rekordbox XML.
        existing: Existing Track record in the database.

    Returns:
        List of FieldConflict objects describing each difference.
    """
    conflicts: list[FieldConflict] = []

    # BPM: conflict if difference > 0.5
    if (
        parsed.bpm is not None
        and existing.bpm is not None
        and abs(parsed.bpm - existing.bpm) > _BPM_THRESHOLD
    ):
        conflicts.append(
            FieldConflict(
                field="bpm",
                rekordbox_value=parsed.bpm,
                rekordbot_value=existing.bpm,
                recommended="rekordbox",
            )
        )

    # Key: conflict if different
    if parsed.key is not None and existing.key is not None and parsed.key != existing.key:
        conflicts.append(
            FieldConflict(
                field="key",
                rekordbox_value=parsed.key,
                rekordbot_value=existing.key,
                recommended="rekordbox",
            )
        )

    # Genre: conflict if different (always flag, recommend rekordbox)
    if parsed.genre is not None and existing.genre is not None and parsed.genre != existing.genre:
        conflicts.append(
            FieldConflict(
                field="genre",
                rekordbox_value=parsed.genre,
                rekordbot_value=existing.genre,
                recommended="rekordbox",
            )
        )

    # Rating: conflict if different
    if (
        parsed.rating is not None
        and existing.rating is not None
        and parsed.rating != existing.rating
    ):
        conflicts.append(
            FieldConflict(
                field="rating",
                rekordbox_value=parsed.rating,
                rekordbot_value=existing.rating,
                recommended="rekordbox",
            )
        )

    # String fields: conflict only when both are non-empty and different
    string_fields = [
        ("title", parsed.title, existing.title),
        ("artist", parsed.artist, existing.artist),
        ("album", parsed.album, existing.album),
        ("comment", parsed.comment, existing.comment),
    ]
    for field_name, xml_val, db_val in string_fields:
        if xml_val and db_val and xml_val != db_val:
            conflicts.append(
                FieldConflict(
                    field=field_name,
                    rekordbox_value=xml_val,
                    rekordbot_value=db_val,
                    recommended="rekordbox",
                )
            )

    return conflicts


def find_path_match(location: str, db: Session) -> Track | None:
    """Find a track by matching file path.

    Args:
        location: Decoded absolute file path from XML.
        db: SQLAlchemy session.

    Returns:
        Matching Track, or None.
    """
    return db.query(Track).filter(Track.file_path == location).first()


def find_hash_match(file_path: str, db: Session) -> Track | None:
    """Find a track by computing SHA-256 hash and matching.

    Args:
        file_path: Path to the file on disk.
        db: SQLAlchemy session.

    Returns:
        Matching Track, or None if file doesn't exist or no hash match.
    """
    path = Path(file_path)
    if not path.exists():
        return None

    file_hash = compute_file_hash(path)
    return db.query(Track).filter(Track.file_hash == file_hash).first()


def find_match(parsed: ParsedTrack, db: Session) -> MatchResult:
    """Run the full match strategy for a parsed track.

    Strategy (ordered):
    1. Path match: compare location against file_path in DB
    2. Hash match: compute SHA-256 and compare against file_hash in DB
    3. No match: track is new

    Args:
        parsed: Parsed track from XML.
        db: SQLAlchemy session.

    Returns:
        MatchResult with match type, existing track (if found), and conflicts.
    """
    # Try path match first
    existing = find_path_match(parsed.location, db)
    if existing is not None:
        conflicts = detect_conflicts(parsed, existing)
        logger.debug("Path match found for %s (track %d)", parsed.location, existing.id)
        return MatchResult(
            match_type="path",
            existing_track=existing,
            conflicts=conflicts,
        )

    # Try hash match
    existing = find_hash_match(parsed.location, db)
    if existing is not None:
        conflicts = detect_conflicts(parsed, existing)
        logger.debug(
            "Hash match found for %s (track %d at %s)",
            parsed.location,
            existing.id,
            existing.file_path,
        )
        return MatchResult(
            match_type="hash",
            existing_track=existing,
            conflicts=conflicts,
        )

    # No match
    return MatchResult(match_type="new")
