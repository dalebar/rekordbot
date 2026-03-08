"""XML builder — generates complete Rekordbox XML documents.

Constructs DJ_PLAYLISTS XML trees with COLLECTION and PLAYLISTS sections
using xml.etree.ElementTree. Handles track element creation, playlist
structure generation from folder hierarchy, and file output.
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.services.xml_schema_mapper import TrackXmlResult, track_to_xml_attrs

logger = logging.getLogger(__name__)

# Product info for the XML
PRODUCT_NAME = "rekordbot"
PRODUCT_VERSION = "0.1.0"
PRODUCT_COMPANY = ""


def build_collection(
    tracks: list,
    key_notation: str,
) -> tuple[ET.Element, dict[int, int], list[str]]:
    """Build the COLLECTION XML element from a list of tracks.

    Args:
        tracks: List of Track model instances.
        key_notation: Key notation preference for Tonality field.

    Returns:
        Tuple of (COLLECTION element, DB track ID → XML TrackID map, warnings list).
    """
    track_id_map: dict[int, int] = {}
    all_warnings: list[str] = []

    collection = ET.Element("COLLECTION")
    xml_track_id = 1

    for track in tracks:
        db_id: int = getattr(track, "id", 0)
        result: TrackXmlResult = track_to_xml_attrs(track, xml_track_id, key_notation)

        track_elem = ET.SubElement(collection, "TRACK")
        for attr_name, attr_value in result.attrs.items():
            track_elem.set(attr_name, attr_value)

        track_id_map[db_id] = xml_track_id
        all_warnings.extend(result.warnings)
        xml_track_id += 1

    collection.set("Entries", str(len(tracks)))
    return collection, track_id_map, all_warnings


def generate_playlist_structure(
    tracks: list,
    track_id_map: dict[int, int],
    output_directory: str,
) -> ET.Element:
    """Generate playlist NODEs from the organised folder hierarchy.

    Creates an "All Tracks" playlist containing every track, plus one
    playlist per top-level folder (typically artist names).

    Args:
        tracks: List of Track model instances.
        track_id_map: Mapping of DB track ID → XML TrackID.
        output_directory: Base output directory for deriving relative paths.

    Returns:
        The "rekordbot" folder NODE containing all playlists.
    """
    # Group tracks by top-level folder
    folder_tracks: dict[str, list[int]] = {}
    all_track_ids: list[int] = []

    output_dir = Path(output_directory).expanduser().resolve()

    for track in tracks:
        db_id: int = getattr(track, "id", 0)
        xml_id = track_id_map.get(db_id)
        if xml_id is None:
            continue

        all_track_ids.append(xml_id)

        file_path = getattr(track, "file_path", "")
        if not file_path:
            continue

        # Derive relative path from output directory
        try:
            rel_path = Path(file_path).resolve().relative_to(output_dir)
            top_folder = rel_path.parts[0] if rel_path.parts else None
        except ValueError:
            # File is not under output_directory — skip folder grouping
            top_folder = None

        if top_folder:
            if top_folder not in folder_tracks:
                folder_tracks[top_folder] = []
            folder_tracks[top_folder].append(xml_id)

    # Build the rekordbot folder node
    playlist_count = 1 + len(folder_tracks)  # All Tracks + per-folder playlists
    rekordbot_node = ET.Element("NODE")
    rekordbot_node.set("Type", "0")
    rekordbot_node.set("Name", "rekordbot")
    rekordbot_node.set("Count", str(playlist_count))

    # "All Tracks" playlist
    all_tracks_node = ET.SubElement(rekordbot_node, "NODE")
    all_tracks_node.set("Name", "All Tracks")
    all_tracks_node.set("Type", "1")
    all_tracks_node.set("KeyType", "0")
    all_tracks_node.set("Entries", str(len(all_track_ids)))
    for xml_id in all_track_ids:
        track_ref = ET.SubElement(all_tracks_node, "TRACK")
        track_ref.set("Key", str(xml_id))

    # Per-folder playlists (sorted alphabetically)
    for folder_name in sorted(folder_tracks.keys()):
        ids = folder_tracks[folder_name]
        folder_node = ET.SubElement(rekordbot_node, "NODE")
        folder_node.set("Name", folder_name)
        folder_node.set("Type", "1")
        folder_node.set("KeyType", "0")
        folder_node.set("Entries", str(len(ids)))
        for xml_id in ids:
            track_ref = ET.SubElement(folder_node, "TRACK")
            track_ref.set("Key", str(xml_id))

    return rekordbot_node


def build_crate_playlists(
    crates: list,
    track_id_map: dict[int, int],
    parent_node: ET.Element,
) -> None:
    """Add crate playlists to a parent NODE element.

    Each crate becomes a Type=1 playlist NODE with TRACK references.
    Crates are sorted alphabetically by name.

    Args:
        crates: List of (crate, track_ids) tuples where track_ids are DB IDs.
        track_id_map: Mapping of DB track ID → XML TrackID.
        parent_node: Parent NODE element to append crate playlists to.
    """
    for crate, crate_track_ids in sorted(crates, key=lambda c: c[0].name):
        # Map DB track IDs to XML TrackIDs
        xml_ids = []
        for db_id in crate_track_ids:
            xml_id = track_id_map.get(db_id)
            if xml_id is not None:
                xml_ids.append(xml_id)

        crate_node = ET.SubElement(parent_node, "NODE")
        crate_node.set("Name", crate.name)
        crate_node.set("Type", "1")
        crate_node.set("KeyType", "0")
        crate_node.set("Entries", str(len(xml_ids)))
        for xml_id in xml_ids:
            track_ref = ET.SubElement(crate_node, "TRACK")
            track_ref.set("Key", str(xml_id))


def build_set_playlists(
    sets: list,
    track_id_map: dict[int, int],
    parent_node: ET.Element,
) -> None:
    """Add set playlists to a parent NODE element.

    Each set becomes a Type=1 playlist NODE with TRACK references in
    position order. Unlike crate playlists, track order is preserved.
    Sets are sorted alphabetically by name.

    Args:
        sets: List of (set_plan, track_ids) tuples where track_ids are DB IDs
              in position order.
        track_id_map: Mapping of DB track ID → XML TrackID.
        parent_node: Parent NODE element to append set playlists to.
    """
    for set_plan, set_track_ids in sorted(sets, key=lambda s: s[0].name):
        xml_ids = []
        for db_id in set_track_ids:
            xml_id = track_id_map.get(db_id)
            if xml_id is not None:
                xml_ids.append(xml_id)

        set_node = ET.SubElement(parent_node, "NODE")
        set_node.set("Name", set_plan.name)
        set_node.set("Type", "1")
        set_node.set("KeyType", "0")
        set_node.set("Entries", str(len(xml_ids)))
        for xml_id in xml_ids:
            track_ref = ET.SubElement(set_node, "TRACK")
            track_ref.set("Key", str(xml_id))


def build_playlists(
    tracks: list,
    track_id_map: dict[int, int],
    output_directory: str,
    crates: list | None = None,
    sets: list | None = None,
) -> ET.Element:
    """Build the PLAYLISTS XML element with ROOT and folder structure.

    Args:
        tracks: List of Track model instances.
        track_id_map: Mapping of DB track ID → XML TrackID.
        output_directory: Base output directory for folder-based playlists.
        crates: Optional list of (crate, track_ids) tuples for crate playlists.
        sets: Optional list of (set_plan, track_ids) tuples for set playlists.

    Returns:
        PLAYLISTS element with full playlist tree.
    """
    playlists = ET.Element("PLAYLISTS")

    # ROOT node
    root_node = ET.SubElement(playlists, "NODE")
    root_node.set("Type", "0")
    root_node.set("Name", "ROOT")
    root_node.set("Count", "1")

    # rekordbot folder with playlists
    rekordbot_node = generate_playlist_structure(tracks, track_id_map, output_directory)

    # Add crate playlists after folder-based playlists
    if crates:
        build_crate_playlists(crates, track_id_map, rekordbot_node)
        current_count = int(rekordbot_node.get("Count", "0"))
        rekordbot_node.set("Count", str(current_count + len(crates)))

    # Add set playlists after crate playlists
    if sets:
        build_set_playlists(sets, track_id_map, rekordbot_node)
        current_count = int(rekordbot_node.get("Count", "0"))
        rekordbot_node.set("Count", str(current_count + len(sets)))

    root_node.append(rekordbot_node)

    return playlists


def build_xml(
    tracks: list,
    key_notation: str,
    output_directory: str,
    crates: list | None = None,
    sets: list | None = None,
) -> tuple[ET.ElementTree, dict[int, int], list[str]]:
    """Build a complete Rekordbox XML document.

    Args:
        tracks: List of Track model instances to export.
        key_notation: Key notation preference for Tonality field.
        output_directory: Base output directory for playlist generation.
        crates: Optional list of (crate, track_ids) tuples for crate playlists.
        sets: Optional list of (set_plan, track_ids) tuples for set playlists.

    Returns:
        Tuple of (ElementTree, track ID map, warnings list).
    """
    # Root element
    root = ET.Element("DJ_PLAYLISTS")
    root.set("Version", "1.0.0")

    # PRODUCT element
    product = ET.SubElement(root, "PRODUCT")
    product.set("Name", PRODUCT_NAME)
    product.set("Version", PRODUCT_VERSION)
    product.set("Company", PRODUCT_COMPANY)

    # COLLECTION
    collection, track_id_map, warnings = build_collection(tracks, key_notation)
    root.append(collection)

    # PLAYLISTS
    playlists = build_playlists(tracks, track_id_map, output_directory, crates=crates, sets=sets)
    root.append(playlists)

    tree = ET.ElementTree(root)
    logger.info(
        "Built XML: %d tracks, %d warnings",
        len(tracks),
        len(warnings),
    )

    return tree, track_id_map, warnings


def write_xml(tree: ET.ElementTree, output_path: Path) -> None:
    """Write an ElementTree to a file with XML declaration and UTF-8 encoding.

    Creates parent directories if they don't exist.

    Args:
        tree: The ElementTree to write.
        output_path: Destination file path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ET.indent(tree, space="  ")
    tree.write(
        str(output_path),
        encoding="UTF-8",
        xml_declaration=True,
    )

    logger.info("Wrote XML to %s", output_path)
