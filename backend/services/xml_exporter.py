"""Export service — orchestrates Rekordbox XML generation pipeline.

Loads tracks from the database, builds the XML document via the builder,
and writes the output file. Reports export results with counts and warnings.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.exceptions import ExportError
from backend.models.track import Track
from backend.services.xml_builder import build_xml, write_xml

logger = logging.getLogger(__name__)


@dataclass
class ExportResult:
    """Result of a library export operation.

    Attributes:
        tracks_exported: Number of tracks included in the XML.
        tracks_skipped: Number of tracks skipped (missing file, no output path).
        playlists_created: Number of playlists generated.
        warnings: Per-track warnings (missing files, null fields, etc.).
        output_path: Absolute path to the written XML file.
    """

    tracks_exported: int = 0
    tracks_skipped: int = 0
    playlists_created: int = 0
    warnings: list[str] = field(default_factory=list)
    output_path: str = ""


def export_library(
    db_session: Session,
    settings: Settings,
    track_ids: list[int] | None = None,
    output_path: str | None = None,
) -> ExportResult:
    """Export the track library as a Rekordbox XML file.

    Args:
        db_session: SQLAlchemy session for reading tracks.
        settings: Application settings (output directory, key notation, XML path).
        track_ids: Optional list of specific track IDs to export. If None, exports all.
        output_path: Optional override for the XML output path.

    Returns:
        ExportResult with counts, warnings, and output path.

    Raises:
        ExportError: If the output directory is not writable.
    """
    # Determine output path
    xml_path = _resolve_output_path(output_path, settings)

    # Verify output directory is writable
    xml_dir = Path(xml_path).parent
    xml_dir.mkdir(parents=True, exist_ok=True)
    if not xml_dir.exists():
        raise ExportError(f"Output directory does not exist: {xml_dir}")

    # Load tracks
    query = db_session.query(Track)
    if track_ids is not None:
        query = query.filter(Track.id.in_(track_ids))

    all_tracks = query.all()

    # Filter to tracks with a valid file_path
    exportable_tracks = []
    skipped = 0
    warnings: list[str] = []

    for track in all_tracks:
        if not track.file_path:
            skipped += 1
            warnings.append(f"Track {track.id}: no file path, skipped")
            continue
        exportable_tracks.append(track)

    if not exportable_tracks:
        logger.info("No tracks to export")
        return ExportResult(
            tracks_exported=0,
            tracks_skipped=skipped,
            playlists_created=0,
            warnings=warnings,
            output_path=str(xml_path),
        )

    # Resolve output directory for playlist generation
    output_directory = str(Path(settings.output_directory).expanduser().resolve())

    # Build XML
    tree, track_id_map, build_warnings = build_xml(
        exportable_tracks,
        settings.default_key_notation,
        output_directory,
    )
    warnings.extend(build_warnings)

    # Count playlists (Type=1 nodes)
    root = tree.getroot()
    playlists_elem = root.find("PLAYLISTS")
    playlist_count = 0
    if playlists_elem is not None:
        for node in playlists_elem.iter("NODE"):
            if node.get("Type") == "1":
                playlist_count += 1

    # Write XML to disk
    write_xml(tree, Path(xml_path))

    logger.info(
        "Exported %d tracks (%d skipped) to %s",
        len(exportable_tracks),
        skipped,
        xml_path,
    )

    return ExportResult(
        tracks_exported=len(exportable_tracks),
        tracks_skipped=skipped,
        playlists_created=playlist_count,
        warnings=warnings,
        output_path=str(xml_path),
    )


def _resolve_output_path(output_path: str | None, settings: Settings) -> str:
    """Resolve the XML output file path.

    Priority:
    1. Explicit output_path argument
    2. settings.rekordbox_xml_path (if non-empty)
    3. {settings.output_directory}/rekordbox.xml

    Args:
        output_path: Explicit override, or None.
        settings: Application settings.

    Returns:
        Resolved absolute path as string.
    """
    if output_path:
        return str(Path(output_path).expanduser().resolve())

    if settings.rekordbox_xml_path:
        return str(Path(settings.rekordbox_xml_path).expanduser().resolve())

    output_dir = Path(settings.output_directory).expanduser().resolve()
    return str(output_dir / "rekordbox.xml")
