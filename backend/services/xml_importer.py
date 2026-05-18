"""XML import service — orchestrates the full Rekordbox XML import pipeline.

Validates, parses, matches, creates/updates tracks, and imports playlists
as crates. Reports progress via SSE events.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.models.crate import Crate, CrateTrack
from backend.models.track import Track
from backend.services.converter import compute_file_hash
from backend.services.perf import Stage, get_recorder
from backend.services.track_matcher import find_match
from backend.services.xml_parser import ParsedLibrary, ParsedTrack, parse_rekordbox_xml

logger = logging.getLogger(__name__)

# Kind string → source_codec mapping
_KIND_TO_CODEC: dict[str, str] = {
    "AIFF File": "aiff",
    "MP3 File": "mp3",
    "M4A File": "m4a",
    "WAV File": "wav",
    "FLAC File": "flac",
}


@dataclass
class ImportSummary:
    """Result of an XML import operation."""

    tracks_total: int = 0
    tracks_imported: int = 0
    tracks_matched: int = 0
    tracks_conflict: int = 0
    tracks_skipped: int = 0
    skipped_reasons: list[str] = field(default_factory=list)
    playlists_imported: int = 0
    playlists_skipped: int = 0


@dataclass
class ImportProgress:
    """Current import progress for SSE reporting."""

    processed: int = 0
    total: int = 0
    imported: int = 0
    matched: int = 0
    skipped: int = 0
    conflicts: int = 0


def _derive_codec(parsed: ParsedTrack) -> str | None:
    """Derive source codec from Kind attribute or file extension.

    Args:
        parsed: Parsed track data.

    Returns:
        Codec string like "aiff", "mp3", or None.
    """
    if parsed.kind:
        codec = _KIND_TO_CODEC.get(parsed.kind)
        if codec:
            return codec

    # Fallback to file extension
    ext = Path(parsed.location).suffix.lower()
    ext_map = {
        ".aiff": "aiff",
        ".aif": "aiff",
        ".mp3": "mp3",
        ".m4a": "m4a",
        ".wav": "wav",
        ".flac": "flac",
    }
    return ext_map.get(ext)


def _fill_empty_fields(existing: Track, parsed: ParsedTrack) -> None:
    """Fill empty fields on an existing track from parsed XML data.

    Only fills fields that are currently None/empty on the existing track.

    Args:
        existing: Existing Track record.
        parsed: Parsed track from XML.
    """
    fill_map: list[tuple[str, Any]] = [
        ("title", parsed.title),
        ("artist", parsed.artist),
        ("album", parsed.album),
        ("genre", parsed.genre),
        ("comment", parsed.comment),
        ("label", parsed.label),
        ("remixer", parsed.remixer),
        ("composer", parsed.composer),
        ("grouping", parsed.grouping),
        ("mix_name", parsed.mix_name),
    ]
    for field_name, xml_value in fill_map:
        if xml_value and not getattr(existing, field_name, None):
            setattr(existing, field_name, xml_value)

    # Numeric fields — fill if existing is None
    numeric_map: list[tuple[str, Any]] = [
        ("bpm", parsed.bpm),
        ("key", parsed.key),
        ("year", parsed.year),
        ("track_number", parsed.track_number),
        ("disc_number", parsed.disc_number),
        ("sample_rate", parsed.sample_rate),
        ("duration", parsed.duration),
    ]
    for field_name, xml_value in numeric_map:
        if xml_value is not None and getattr(existing, field_name, None) is None:
            setattr(existing, field_name, xml_value)

    # Rating — fill if existing is 0 (default) and XML has a value
    if parsed.rating is not None and parsed.rating > 0 and existing.rating == 0:
        existing.rating = parsed.rating


def _create_track_from_parsed(
    parsed: ParsedTrack,
    file_hash: str,
) -> Track:
    """Create a new Track record from parsed XML data.

    Args:
        parsed: Parsed track from XML.
        file_hash: Computed SHA-256 hash.

    Returns:
        New Track instance (not yet added to session).
    """
    codec = _derive_codec(parsed)
    return Track(
        file_path=parsed.location,
        file_hash=file_hash,
        source_path=parsed.location,
        source_codec=codec,
        source_bitrate=parsed.bitrate,
        title=parsed.title,
        artist=parsed.artist,
        album=parsed.album,
        genre=parsed.genre,
        bpm=parsed.bpm,
        key=parsed.key,
        rating=parsed.rating or 0,
        duration=parsed.duration,
        comment=parsed.comment,
        label=parsed.label,
        remixer=parsed.remixer,
        composer=parsed.composer,
        grouping=parsed.grouping,
        year=parsed.year,
        track_number=parsed.track_number,
        disc_number=parsed.disc_number,
        mix_name=parsed.mix_name,
        sample_rate=parsed.sample_rate,
        colour=parsed.colour,
        date_added=parsed.date_added,
        import_source="rekordbox_xml",
        conversion_action="imported",
        conversion_status="complete",
        imported_at=datetime.now(),
        analysis_status="not_analysed",
        ai_status="untagged",
        organisation_status="unorganised",
    )


def import_tracks(
    library: ParsedLibrary,
    db: Session,
    progress_callback: Any | None = None,
    cancel_check: Any | None = None,
) -> tuple[ImportSummary, dict[str, int]]:
    """Import parsed tracks into the database.

    Args:
        library: Parsed Rekordbox library.
        db: SQLAlchemy session.
        progress_callback: Optional callable(ImportProgress) for SSE updates.
        cancel_check: Optional callable() -> bool to check for cancellation.

    Returns:
        Tuple of (ImportSummary, location_to_track_id map for playlist import).
    """
    summary = ImportSummary(tracks_total=len(library.tracks))
    progress = ImportProgress(total=len(library.tracks))
    location_to_track_id: dict[str, int] = {}

    for parsed in library.tracks:
        # Check cancellation
        if cancel_check and cancel_check():
            logger.info("Import cancelled at %d/%d tracks", progress.processed, progress.total)
            break

        progress.processed += 1

        # Check file exists on disk
        if not Path(parsed.location).exists():
            summary.tracks_skipped += 1
            summary.skipped_reasons.append(f"File not found: {parsed.location}")
            progress.skipped += 1
            logger.warning("Skipping track — file not found: %s", parsed.location)
            if progress_callback:
                progress_callback(progress)
            continue

        # Match against existing DB
        match_result = find_match(parsed, db)

        if match_result.match_type == "new":
            # Create new track
            file_hash = compute_file_hash(Path(parsed.location))

            # Check hash isn't already in DB (dedup)
            existing_by_hash = db.query(Track).filter(Track.file_hash == file_hash).first()
            if existing_by_hash:
                # Treat as a match
                _fill_empty_fields(existing_by_hash, parsed)
                summary.tracks_matched += 1
                progress.matched += 1
                location_to_track_id[parsed.location] = existing_by_hash.id
            else:
                track = _create_track_from_parsed(parsed, file_hash)
                db.add(track)
                db.flush()
                summary.tracks_imported += 1
                progress.imported += 1
                location_to_track_id[parsed.location] = track.id
                logger.info("Imported new track: %s", parsed.location)

        elif match_result.existing_track is not None:
            existing = match_result.existing_track

            if match_result.conflicts:
                # Store conflicts as JSON for user review
                conflicts_json = json.dumps(
                    [
                        {
                            "field": c.field,
                            "rekordbox_value": c.rekordbox_value,
                            "rekordbot_value": c.rekordbot_value,
                            "recommended": c.recommended,
                        }
                        for c in match_result.conflicts
                    ]
                )
                existing.import_conflicts = conflicts_json
                summary.tracks_conflict += 1
                progress.conflicts += 1
                logger.info(
                    "Track %d has %d conflicts with XML",
                    existing.id,
                    len(match_result.conflicts),
                )
            else:
                # No conflicts — fill empty fields
                _fill_empty_fields(existing, parsed)
                summary.tracks_matched += 1
                progress.matched += 1

            location_to_track_id[parsed.location] = existing.id

        if progress_callback:
            progress_callback(progress)

    db.flush()
    return summary, location_to_track_id


def import_playlists(
    library: ParsedLibrary,
    location_to_track_id: dict[str, int],
    db: Session,
    summary: ImportSummary,
) -> None:
    """Import playlists as crates.

    Args:
        library: Parsed Rekordbox library.
        location_to_track_id: Map of file paths to DB track IDs.
        db: SQLAlchemy session.
        summary: ImportSummary to update with playlist counts.
    """
    for playlist in library.playlists:
        # Check if crate with same name already exists
        existing_crate = db.query(Crate).filter(Crate.name == playlist.name).first()
        if existing_crate:
            summary.playlists_skipped += 1
            logger.warning("Skipping duplicate crate name: %s", playlist.name)
            continue

        # Create crate
        crate = Crate(
            name=playlist.name,
            description="Imported from Rekordbox XML",
            auto_refresh=False,
        )
        db.add(crate)
        db.flush()

        # Add track assignments
        for location in playlist.track_locations:
            track_id = location_to_track_id.get(location)
            if track_id is not None:
                crate_track = CrateTrack(
                    crate_id=crate.id,
                    track_id=track_id,
                    assignment_method="imported",
                )
                db.add(crate_track)

        summary.playlists_imported += 1
        logger.info("Imported crate: %s (%d tracks)", playlist.name, len(playlist.track_locations))

    db.flush()


def run_import(
    file_path: Path,
    db: Session,
    progress_callback: Any | None = None,
    cancel_check: Any | None = None,
) -> ImportSummary:
    """Run the full XML import pipeline.

    Pipeline: validate → parse → match → create/update → import playlists.

    Args:
        file_path: Path to the Rekordbox XML file.
        db: SQLAlchemy session.
        progress_callback: Optional callable(ImportProgress) for SSE updates.
        cancel_check: Optional callable() -> bool for cancellation.

    Returns:
        ImportSummary with final counts.

    Raises:
        XmlImportError: If the XML file is invalid.
    """
    recorder = get_recorder()
    with recorder.stage(Stage.XML_IMPORT):
        logger.info("Starting XML import from %s", file_path)

        # Parse (validates internally)
        with recorder.stage(Stage.XML_IMPORT_PARSE):
            library = parse_rekordbox_xml(file_path)

        logger.info(
            "Parsed library: %s v%s, %d tracks, %d playlists",
            library.product_name,
            library.product_version,
            len(library.tracks),
            len(library.playlists),
        )

        # Import tracks
        with recorder.stage(Stage.XML_IMPORT_TRACKS):
            summary, location_to_track_id = import_tracks(
                library,
                db,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            )

        # Import playlists
        with recorder.stage(Stage.XML_IMPORT_PLAYLISTS):
            import_playlists(library, location_to_track_id, db, summary)

        with recorder.stage(Stage.XML_IMPORT_COMMIT):
            db.commit()

        logger.info(
            "Import complete: %d imported, %d matched, %d conflicts, %d skipped, "
            "%d playlists imported, %d playlists skipped",
            summary.tracks_imported,
            summary.tracks_matched,
            summary.tracks_conflict,
            summary.tracks_skipped,
            summary.playlists_imported,
            summary.playlists_skipped,
        )

        return summary
