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
from backend.models.crate import Crate, CrateTrack
from backend.models.set_plan import SetPlan, SetTrack
from backend.models.track import Track
from backend.services.perf import Stage, get_recorder
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
    recorder = get_recorder()
    with recorder.stage(Stage.XML_EXPORT):
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

        with recorder.stage(Stage.XML_EXPORT_LOAD_TRACKS):
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

        # Load crates and sets for playlist generation
        with recorder.stage(Stage.XML_EXPORT_LOAD_CRATES):
            crates_data = _load_crates(db_session)
        with recorder.stage(Stage.XML_EXPORT_LOAD_SETS):
            sets_data = _load_sets(db_session)

        # Build XML
        with recorder.stage(Stage.XML_EXPORT_BUILD):
            tree, track_id_map, build_warnings = build_xml(
                exportable_tracks,
                settings.default_key_notation,
                output_directory,
                crates=crates_data,
                sets=sets_data,
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
        with recorder.stage(Stage.XML_EXPORT_WRITE):
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


def _load_crates(db_session: Session) -> list:
    """Load all crates with their track IDs for XML export.

    Args:
        db_session: SQLAlchemy session.

    Returns:
        List of (Crate, list[int]) tuples where the int list contains
        DB track IDs assigned to that crate.
    """
    crates = db_session.query(Crate).all()
    if not crates:
        return []

    result = []
    for crate in crates:
        track_ids = [
            ct.track_id
            for ct in db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate.id).all()
        ]
        if track_ids:
            result.append((crate, track_ids))

    return result


def _load_sets(db_session: Session) -> list:
    """Load all complete sets with their ordered track IDs for XML export.

    Only sets with status 'complete' are included. Track IDs are returned
    in position order to preserve the set sequence.

    Args:
        db_session: SQLAlchemy session.

    Returns:
        List of (SetPlan, list[int]) tuples where the int list contains
        DB track IDs in position order.
    """
    sets = db_session.query(SetPlan).filter(SetPlan.status == "complete").all()
    if not sets:
        return []

    result = []
    for set_plan in sets:
        set_tracks = (
            db_session.query(SetTrack)
            .filter(SetTrack.set_id == set_plan.id, SetTrack.is_candidate.is_(False))
            .order_by(SetTrack.position)
            .all()
        )
        track_ids = [st.track_id for st in set_tracks]
        if track_ids:
            result.append((set_plan, track_ids))

    return result
