"""Tests for XML builder — structure validation, playlist generation, file output."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from backend.services.xml_builder import (
    build_collection,
    build_playlists,
    build_xml,
    generate_playlist_structure,
    write_xml,
)


@dataclass
class MockTrack:
    """Mock track for testing."""

    id: int = 1
    file_path: str = "/library/Artist/Album/track.aiff"
    title: str | None = "Test Track"
    artist: str | None = "Test Artist"
    album: str | None = "Test Album"
    album_artist: str | None = None
    genre: str | None = "Electronic"
    composer: str | None = None
    remixer: str | None = None
    label: str | None = None
    mix_name: str | None = None
    grouping: str | None = None
    comment: str | None = ""
    year: int | None = 2024
    track_number: int | None = 1
    disc_number: int | None = 0
    bpm: float | None = 128.0
    key: int | None = 16  # 8B / C major
    rating: int = 0
    duration: float | None = 300.0
    bit_rate: int | None = 2116
    sample_rate: int | None = 44100
    imported_at: Any = field(default_factory=lambda: datetime(2026, 1, 1))


def _make_track(**kwargs: Any) -> MockTrack:
    """Create a mock track with overrides."""
    if "track_id" in kwargs:
        kwargs["id"] = kwargs.pop("track_id")
    return MockTrack(**kwargs)


@patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
@patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
class TestBuildCollection:
    """Tests for COLLECTION element construction."""

    def test_entries_count(self, mock_mtime: Any, mock_size: Any) -> None:
        tracks = [_make_track(track_id=i) for i in range(1, 4)]
        collection, _, _ = build_collection(tracks, "camelot")
        assert collection.get("Entries") == "3"

    def test_track_ids_sequential(self, mock_mtime: Any, mock_size: Any) -> None:
        tracks = [_make_track(track_id=i) for i in [10, 20, 30]]
        collection, id_map, _ = build_collection(tracks, "camelot")

        track_elems = collection.findall("TRACK")
        assert len(track_elems) == 3
        assert track_elems[0].get("TrackID") == "1"
        assert track_elems[1].get("TrackID") == "2"
        assert track_elems[2].get("TrackID") == "3"

        # ID map should reflect DB ID → sequential XML ID
        assert id_map == {10: 1, 20: 2, 30: 3}

    def test_empty_collection(self, mock_mtime: Any, mock_size: Any) -> None:
        collection, id_map, warnings = build_collection([], "camelot")
        assert collection.get("Entries") == "0"
        assert len(id_map) == 0

    def test_track_attributes_present(self, mock_mtime: Any, mock_size: Any) -> None:
        tracks = [_make_track(title="My Track", artist="My Artist")]
        collection, _, _ = build_collection(tracks, "camelot")
        track_elem = collection.find("TRACK")
        assert track_elem is not None
        assert track_elem.get("Name") == "My Track"
        assert track_elem.get("Artist") == "My Artist"


@patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
@patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
class TestGeneratePlaylistStructure:
    """Tests for folder-based playlist generation."""

    def test_all_tracks_playlist(self, mock_mtime: Any, mock_size: Any) -> None:
        tracks = [
            _make_track(track_id=1, file_path="/library/Calibre/track1.aiff"),
            _make_track(track_id=2, file_path="/library/Bicep/track2.aiff"),
        ]
        track_id_map = {1: 1, 2: 2}
        node = generate_playlist_structure(tracks, track_id_map, "/library")

        # Find "All Tracks" playlist
        all_tracks = None
        for child in node:
            if child.get("Name") == "All Tracks":
                all_tracks = child
                break

        assert all_tracks is not None
        assert all_tracks.get("Type") == "1"
        assert all_tracks.get("KeyType") == "0"
        assert all_tracks.get("Entries") == "2"
        track_refs = all_tracks.findall("TRACK")
        assert len(track_refs) == 2

    def test_artist_playlists(self, mock_mtime: Any, mock_size: Any) -> None:
        tracks = [
            _make_track(track_id=1, file_path="/library/Calibre/track1.aiff"),
            _make_track(track_id=2, file_path="/library/Calibre/track2.aiff"),
            _make_track(track_id=3, file_path="/library/Bicep/track3.aiff"),
        ]
        track_id_map = {1: 1, 2: 2, 3: 3}
        node = generate_playlist_structure(tracks, track_id_map, "/library")

        # Should have 3 playlists: All Tracks + Bicep + Calibre
        playlists = [c for c in node if c.get("Type") == "1"]
        assert len(playlists) == 3

        names = {p.get("Name") for p in playlists}
        assert "All Tracks" in names
        assert "Bicep" in names
        assert "Calibre" in names

        # Calibre should have 2 tracks
        calibre = [p for p in playlists if p.get("Name") == "Calibre"][0]
        assert calibre.get("Entries") == "2"

    def test_rekordbot_node_count(self, mock_mtime: Any, mock_size: Any) -> None:
        tracks = [
            _make_track(track_id=1, file_path="/library/A/t.aiff"),
            _make_track(track_id=2, file_path="/library/B/t.aiff"),
        ]
        track_id_map = {1: 1, 2: 2}
        node = generate_playlist_structure(tracks, track_id_map, "/library")

        # Count = All Tracks + 2 artist playlists = 3
        assert node.get("Count") == "3"

    def test_playlists_sorted_alphabetically(self, mock_mtime: Any, mock_size: Any) -> None:
        tracks = [
            _make_track(track_id=1, file_path="/library/Zebra/t.aiff"),
            _make_track(track_id=2, file_path="/library/Alpha/t.aiff"),
            _make_track(track_id=3, file_path="/library/Middle/t.aiff"),
        ]
        track_id_map = {1: 1, 2: 2, 3: 3}
        node = generate_playlist_structure(tracks, track_id_map, "/library")

        playlists = [c for c in node if c.get("Type") == "1"]
        # All Tracks first, then Alpha, Middle, Zebra
        names = [p.get("Name") for p in playlists]
        assert names == ["All Tracks", "Alpha", "Middle", "Zebra"]


@patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
@patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
class TestBuildPlaylists:
    """Tests for the full PLAYLISTS element."""

    def test_root_node_structure(self, mock_mtime: Any, mock_size: Any) -> None:
        tracks = [_make_track(track_id=1, file_path="/library/A/t.aiff")]
        track_id_map = {1: 1}
        playlists = build_playlists(tracks, track_id_map, "/library")

        root_node = playlists.find("NODE")
        assert root_node is not None
        assert root_node.get("Type") == "0"
        assert root_node.get("Name") == "ROOT"
        assert root_node.get("Count") == "1"

        # rekordbot folder inside ROOT
        rekordbot_node = root_node.find("NODE")
        assert rekordbot_node is not None
        assert rekordbot_node.get("Name") == "rekordbot"
        assert rekordbot_node.get("Type") == "0"


@patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
@patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
class TestBuildXml:
    """Tests for complete XML document construction."""

    def test_root_element(self, mock_mtime: Any, mock_size: Any) -> None:
        tracks = [_make_track(track_id=1, file_path="/library/A/t.aiff")]
        tree, _, _ = build_xml(tracks, "camelot", "/library")
        root = tree.getroot()
        assert root.tag == "DJ_PLAYLISTS"
        assert root.get("Version") == "1.0.0"

    def test_product_element(self, mock_mtime: Any, mock_size: Any) -> None:
        tree, _, _ = build_xml([], "camelot", "/library")
        product = tree.getroot().find("PRODUCT")
        assert product is not None
        assert product.get("Name") == "rekordbot"
        assert product.get("Version") == "0.1.0"
        assert product.get("Company") == ""

    def test_collection_present(self, mock_mtime: Any, mock_size: Any) -> None:
        tracks = [_make_track(track_id=1, file_path="/library/A/t.aiff")]
        tree, _, _ = build_xml(tracks, "camelot", "/library")
        collection = tree.getroot().find("COLLECTION")
        assert collection is not None
        assert collection.get("Entries") == "1"

    def test_playlists_present(self, mock_mtime: Any, mock_size: Any) -> None:
        tree, _, _ = build_xml([], "camelot", "/library")
        playlists = tree.getroot().find("PLAYLISTS")
        assert playlists is not None

    def test_track_id_consistency(self, mock_mtime: Any, mock_size: Any) -> None:
        """TrackIDs in COLLECTION must match Key values in PLAYLISTS."""
        tracks = [
            _make_track(track_id=1, file_path="/library/A/t1.aiff"),
            _make_track(track_id=2, file_path="/library/B/t2.aiff"),
        ]
        tree, _, _ = build_xml(tracks, "camelot", "/library")

        # Get TrackIDs from COLLECTION
        collection = tree.getroot().find("COLLECTION")
        assert collection is not None
        collection_ids = {t.get("TrackID") for t in collection.findall("TRACK")}

        # Get Key values from PLAYLISTS
        playlists = tree.getroot().find("PLAYLISTS")
        assert playlists is not None
        playlist_keys: set[str | None] = set()
        for node in playlists.iter("NODE"):
            if node.get("Type") == "1":
                for track_ref in node.findall("TRACK"):
                    playlist_keys.add(track_ref.get("Key"))

        # Every key in playlists should be a valid TrackID in collection
        assert playlist_keys.issubset(collection_ids)


@patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
@patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
class TestWriteXml:
    """Tests for XML file output."""

    def test_write_creates_file(self, mock_mtime: Any, mock_size: Any, tmp_path: Path) -> None:
        tracks = [_make_track(track_id=1, file_path="/library/A/t.aiff")]
        tree, _, _ = build_xml(tracks, "camelot", "/library")

        output = tmp_path / "rekordbox.xml"
        write_xml(tree, output)

        assert output.exists()

    def test_write_valid_xml(self, mock_mtime: Any, mock_size: Any, tmp_path: Path) -> None:
        tracks = [_make_track(track_id=1, file_path="/library/A/t.aiff")]
        tree, _, _ = build_xml(tracks, "camelot", "/library")

        output = tmp_path / "rekordbox.xml"
        write_xml(tree, output)

        # Parse back and verify
        parsed = ET.parse(output)
        root = parsed.getroot()
        assert root.tag == "DJ_PLAYLISTS"

    def test_write_has_xml_declaration(
        self, mock_mtime: Any, mock_size: Any, tmp_path: Path
    ) -> None:
        tree, _, _ = build_xml([], "camelot", "/library")
        output = tmp_path / "rekordbox.xml"
        write_xml(tree, output)

        content = output.read_bytes()
        assert content.startswith(b"<?xml version='1.0' encoding='UTF-8'?>")

    def test_write_creates_parent_dirs(
        self, mock_mtime: Any, mock_size: Any, tmp_path: Path
    ) -> None:
        tree, _, _ = build_xml([], "camelot", "/library")
        output = tmp_path / "subdir" / "nested" / "rekordbox.xml"
        write_xml(tree, output)
        assert output.exists()

    def test_write_utf8_content(self, mock_mtime: Any, mock_size: Any, tmp_path: Path) -> None:
        tracks = [
            _make_track(
                track_id=1,
                file_path="/library/Âme/track.aiff",
                artist="Âme",
                title="Rêve",
            )
        ]
        tree, _, _ = build_xml(tracks, "camelot", "/library")
        output = tmp_path / "rekordbox.xml"
        write_xml(tree, output)

        content = output.read_text(encoding="utf-8")
        # Artist name should appear in Name attribute (or encoded in Location)
        assert "Âme" in content or "%C3%82me" in content
