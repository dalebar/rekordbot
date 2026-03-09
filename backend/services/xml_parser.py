"""Rekordbox XML parser — extracts track metadata and playlist structure.

Parses a Rekordbox XML file (exported via File → Export Library in Rekordbox 6/7)
and returns structured data for the import pipeline. Uses xml.etree.ElementTree
for parsing. Location URIs are decoded to absolute file paths (inverse of
location_encoder.py).
"""

import contextlib
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from backend.exceptions import XmlImportError
from backend.services.key_notation import parse_key_tag

logger = logging.getLogger(__name__)

# Rekordbox non-linear rating scale → 0–5 stars
_RATING_REVERSE_MAP: dict[int, int] = {
    0: 0,
    51: 1,
    102: 2,
    153: 3,
    204: 4,
    255: 5,
}

# Product-level node names to exclude from playlist name prefixes
_EXCLUDED_PREFIX_NAMES = {"ROOT", "rekordbox"}


@dataclass
class ParsedTrack:
    """A track extracted from Rekordbox XML."""

    location: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    genre: str | None = None
    bpm: float | None = None
    key: int | None = None
    rating: int | None = None
    duration: int | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    comment: str | None = None
    label: str | None = None
    remixer: str | None = None
    composer: str | None = None
    album_artist: str | None = None
    grouping: str | None = None
    year: int | None = None
    track_number: int | None = None
    disc_number: int | None = None
    date_added: str | None = None
    mix_name: str | None = None
    colour: str | None = None
    size: int | None = None
    kind: str | None = None


@dataclass
class ParsedPlaylist:
    """A playlist extracted from Rekordbox XML."""

    name: str
    track_keys: list[int] = field(default_factory=list)
    track_locations: list[str] = field(default_factory=list)


@dataclass
class ParsedLibrary:
    """Complete parsed Rekordbox library."""

    product_name: str | None = None
    product_version: str | None = None
    tracks: list[ParsedTrack] = field(default_factory=list)
    playlists: list[ParsedPlaylist] = field(default_factory=list)


def decode_location(location_uri: str | None) -> str | None:
    """Convert a Rekordbox Location URI back to an absolute file path.

    Strips the file://localhost/ prefix and percent-decodes each component.
    This is the inverse of location_encoder.encode_location().

    Args:
        location_uri: Rekordbox Location URI string.

    Returns:
        Decoded absolute file path, or None if the URI format is invalid.
    """
    if not location_uri:
        return None

    prefix = "file://localhost/"
    if not location_uri.startswith(prefix):
        return None

    # Strip prefix and decode
    encoded_path = location_uri[len(prefix) :]
    decoded = unquote(encoded_path)

    # Ensure it's an absolute path
    return "/" + decoded


def parse_bpm(value: str | None) -> float | None:
    """Parse a BPM string to float.

    Args:
        value: BPM string like "128.00", or None.

    Returns:
        BPM as float, or None if invalid/zero.
    """
    if not value:
        return None
    try:
        bpm = float(value)
        if bpm <= 0:
            return None
        return bpm
    except ValueError:
        return None


def parse_rating(value: str | None) -> int | None:
    """Convert Rekordbox non-linear rating to 0–5 scale.

    Args:
        value: Rating string ("0", "51", "102", "153", "204", "255"), or None.

    Returns:
        Star rating 0–5, or None if unrecognised.
    """
    if not value:
        return None
    try:
        raw = int(value)
    except ValueError:
        return None
    return _RATING_REVERSE_MAP.get(raw)


def parse_tonality(value: str | None) -> int | None:
    """Parse a key/tonality string to internal integer 1–24.

    Reuses the existing key_notation.parse_key_tag() which handles
    Camelot, Open Key, and classical notations.

    Args:
        value: Key string in any notation, or None.

    Returns:
        Internal key integer (1–24), or None if unrecognised.
    """
    return parse_key_tag(value)


def _parse_optional_str(element: ET.Element, attr: str) -> str | None:
    """Get a string attribute, returning None for empty strings."""
    value = element.get(attr)
    if not value:
        return None
    return value


def _parse_optional_int(element: ET.Element, attr: str) -> int | None:
    """Get an integer attribute, returning None for missing/zero/invalid."""
    value = element.get(attr)
    if not value:
        return None
    try:
        result = int(value)
        return result if result != 0 else None
    except ValueError:
        return None


def parse_track_element(element: ET.Element) -> ParsedTrack | None:
    """Extract metadata from a single TRACK XML element.

    Args:
        element: An XML TRACK element.

    Returns:
        ParsedTrack with extracted metadata, or None if Location is missing/invalid.
    """
    location_uri = element.get("Location")
    location = decode_location(location_uri)
    if location is None:
        return None

    return ParsedTrack(
        location=location,
        title=_parse_optional_str(element, "Name"),
        artist=_parse_optional_str(element, "Artist"),
        album=_parse_optional_str(element, "Album"),
        genre=_parse_optional_str(element, "Genre"),
        bpm=parse_bpm(element.get("AverageBpm")),
        key=parse_tonality(element.get("Tonality")),
        rating=parse_rating(element.get("Rating")),
        duration=_parse_optional_int(element, "TotalTime"),
        bitrate=_parse_optional_int(element, "BitRate"),
        sample_rate=_parse_optional_int(element, "SampleRate"),
        comment=_parse_optional_str(element, "Comments"),
        label=_parse_optional_str(element, "Label"),
        remixer=_parse_optional_str(element, "Remixer"),
        composer=_parse_optional_str(element, "Composer"),
        album_artist=_parse_optional_str(element, "AlbumArtist"),
        grouping=_parse_optional_str(element, "Grouping"),
        year=_parse_optional_int(element, "Year"),
        track_number=_parse_optional_int(element, "TrackNumber"),
        disc_number=_parse_optional_int(element, "DiscNumber"),
        date_added=_parse_optional_str(element, "DateAdded"),
        mix_name=_parse_optional_str(element, "Mix"),
        colour=_parse_optional_str(element, "Colour"),
        size=_parse_optional_int(element, "Size"),
        kind=_parse_optional_str(element, "Kind"),
    )


def _collect_playlists(
    node: ET.Element,
    prefix_parts: list[str],
    result: list[ParsedPlaylist],
) -> None:
    """Recursively collect playlists from a NODE tree.

    Folder nodes (Type=0) contribute to the name prefix.
    Playlist nodes (Type=1) are collected with their full path name.

    Args:
        node: Current NODE element.
        prefix_parts: Path components from ancestor folders.
        result: Accumulator list for found playlists.
    """
    node_type = node.get("Type", "")
    node_name = node.get("Name", "")

    if node_type == "1":
        # This is a playlist — collect it
        full_name = "/".join(prefix_parts + [node_name]) if prefix_parts else node_name
        track_keys: list[int] = []
        for track_ref in node.findall("TRACK"):
            key = track_ref.get("Key")
            if key is not None:
                with contextlib.suppress(ValueError):
                    track_keys.append(int(key))
        result.append(ParsedPlaylist(name=full_name, track_keys=track_keys))
    elif node_type == "0":
        # This is a folder — recurse into children
        new_prefix = list(prefix_parts)
        if node_name not in _EXCLUDED_PREFIX_NAMES:
            new_prefix.append(node_name)
        for child in node.findall("NODE"):
            _collect_playlists(child, new_prefix, result)


def parse_playlists(root_node: ET.Element) -> list[ParsedPlaylist]:
    """Extract playlist structure from a PLAYLISTS ROOT node.

    Folder hierarchy is flattened into playlist name prefixes.
    ROOT and product-name nodes are excluded from the prefix.

    Args:
        root_node: The ROOT NODE element from the PLAYLISTS section.

    Returns:
        List of ParsedPlaylist with names and track Key references.
    """
    result: list[ParsedPlaylist] = []
    _collect_playlists(root_node, [], result)
    return result


def validate_xml_structure(file_path: Path) -> tuple[bool, str]:
    """Check that a file is valid Rekordbox XML.

    Validates: parseable XML, DJ_PLAYLISTS root, COLLECTION element,
    PLAYLISTS element.

    Args:
        file_path: Path to the XML file.

    Returns:
        Tuple of (valid, error_message). Error message is empty on success.
    """
    try:
        tree = ET.parse(file_path)
    except ET.ParseError as e:
        return False, f"Invalid XML: {e}"
    except OSError as e:
        return False, f"Cannot read file: {e}"

    root = tree.getroot()
    if root.tag != "DJ_PLAYLISTS":
        return False, f"Expected DJ_PLAYLISTS root element, found '{root.tag}'"

    if root.find("COLLECTION") is None:
        return False, "Missing COLLECTION element"

    if root.find("PLAYLISTS") is None:
        return False, "Missing PLAYLISTS element"

    return True, ""


def parse_rekordbox_xml(file_path: Path) -> ParsedLibrary:
    """Parse a complete Rekordbox XML file.

    Args:
        file_path: Path to the Rekordbox XML export file.

    Returns:
        ParsedLibrary with all tracks and playlists.

    Raises:
        XmlImportError: If the file is invalid or cannot be parsed.
    """
    # Validate structure first
    valid, error_msg = validate_xml_structure(file_path)
    if not valid:
        raise XmlImportError(error_msg, status_code=400)

    try:
        tree = ET.parse(file_path)
    except (ET.ParseError, OSError) as e:
        raise XmlImportError(f"Failed to parse XML: {e}", status_code=400) from e

    root = tree.getroot()
    library = ParsedLibrary()

    # Extract product info
    product = root.find("PRODUCT")
    if product is not None:
        library.product_name = product.get("Name")
        library.product_version = product.get("Version")

    # Parse tracks and build TrackID → location map
    track_id_map: dict[int, str] = {}
    collection = root.find("COLLECTION")
    if collection is not None:
        for track_elem in collection.findall("TRACK"):
            parsed_track = parse_track_element(track_elem)
            if parsed_track is not None:
                library.tracks.append(parsed_track)
                # Build TrackID → location map for playlist resolution
                track_id_str = track_elem.get("TrackID")
                if track_id_str:
                    with contextlib.suppress(ValueError):
                        track_id_map[int(track_id_str)] = parsed_track.location
            else:
                logger.debug(
                    "Skipping track element without valid Location: %s",
                    track_elem.get("Name", "unknown"),
                )

    logger.info("Parsed %d tracks from XML", len(library.tracks))

    # Parse playlists
    playlists_elem = root.find("PLAYLISTS")
    if playlists_elem is not None:
        root_node = playlists_elem.find("NODE")
        if root_node is not None:
            library.playlists = parse_playlists(root_node)

            # Resolve track keys to locations
            for playlist in library.playlists:
                playlist.track_locations = [
                    track_id_map[key] for key in playlist.track_keys if key in track_id_map
                ]

    logger.info("Parsed %d playlists from XML", len(library.playlists))

    return library
