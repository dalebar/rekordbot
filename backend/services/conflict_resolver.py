"""Conflict resolver — handles user decisions on import metadata conflicts.

Conflicts are stored as JSON in the Track.import_conflicts field. This module
reads, applies, and clears those conflicts based on user choices.
"""

import json
import logging

from sqlalchemy.orm import Session

from backend.models.track import Track

logger = logging.getLogger(__name__)

# Fields that can be resolved via conflict resolution
_RESOLVABLE_FIELDS = {"bpm", "key", "genre", "rating", "title", "artist", "album", "comment"}


def get_pending_conflicts(db: Session) -> list[dict]:
    """Load all tracks with unresolved import conflicts.

    Args:
        db: SQLAlchemy session.

    Returns:
        List of dicts with track_id and conflicts for each unresolved track.
    """
    tracks = db.query(Track).filter(Track.import_conflicts.isnot(None)).all()
    result = []
    for track in tracks:
        conflicts = json.loads(track.import_conflicts)  # type: ignore[arg-type]
        result.append(
            {
                "track_id": track.id,
                "title": track.title,
                "artist": track.artist,
                "file_path": track.file_path,
                "conflicts": conflicts,
            }
        )
    return result


def resolve_conflict(
    track_id: int,
    resolutions: dict[str, str],
    db: Session,
) -> Track:
    """Apply user's per-field resolution choices to a single track.

    For each field in resolutions:
    - "rekordbox": apply the Rekordbox XML value to the track
    - "rekordbot": keep the current DB value (no change)

    After all fields are resolved, clears import_conflicts.

    Args:
        track_id: DB track ID.
        resolutions: Maps field names to "rekordbox" or "rekordbot".
        db: SQLAlchemy session.

    Returns:
        The updated Track.

    Raises:
        ValueError: If the track is not found or has no conflicts.
    """
    track = db.query(Track).filter(Track.id == track_id).first()
    if track is None:
        raise ValueError(f"Track {track_id} not found")
    if track.import_conflicts is None:
        raise ValueError(f"Track {track_id} has no pending conflicts")

    conflicts = json.loads(track.import_conflicts)

    # Build a lookup from field name to rekordbox value
    conflict_map: dict[str, object] = {}
    for conflict in conflicts:
        conflict_map[conflict["field"]] = conflict["rekordbox_value"]

    # Apply resolutions
    for field_name, choice in resolutions.items():
        if field_name not in _RESOLVABLE_FIELDS:
            logger.warning("Skipping unrecognised field: %s", field_name)
            continue
        if choice == "rekordbox" and field_name in conflict_map:
            setattr(track, field_name, conflict_map[field_name])
            logger.info(
                "Track %d: resolved %s -> rekordbox value %s",
                track_id,
                field_name,
                conflict_map[field_name],
            )
        elif choice == "rekordbot":
            logger.info("Track %d: keeping rekordbot value for %s", track_id, field_name)

    # Clear conflicts
    track.import_conflicts = None
    db.flush()

    return track


def resolve_all_rekordbox(db: Session) -> int:
    """Bulk resolve: accept Rekordbox values for all conflicts.

    Args:
        db: SQLAlchemy session.

    Returns:
        Number of tracks resolved.
    """
    tracks = db.query(Track).filter(Track.import_conflicts.isnot(None)).all()
    count = 0
    for track in tracks:
        conflicts = json.loads(track.import_conflicts)  # type: ignore[arg-type]
        for conflict in conflicts:
            field_name = conflict["field"]
            if field_name in _RESOLVABLE_FIELDS:
                setattr(track, field_name, conflict["rekordbox_value"])
        track.import_conflicts = None
        count += 1

    db.flush()
    logger.info("Bulk resolved %d tracks with Rekordbox values", count)
    return count


def resolve_all_rekordbot(db: Session) -> int:
    """Bulk resolve: keep rekordbot values for all conflicts.

    Simply clears the import_conflicts field without changing any values.

    Args:
        db: SQLAlchemy session.

    Returns:
        Number of tracks resolved.
    """
    tracks = db.query(Track).filter(Track.import_conflicts.isnot(None)).all()
    count = 0
    for track in tracks:
        track.import_conflicts = None
        count += 1

    db.flush()
    logger.info("Bulk resolved %d tracks keeping rekordbot values", count)
    return count
