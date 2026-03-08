"""Integration tests for Phase 4 — end-to-end export flow."""

import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import unquote

import pytest

from backend.models.track import Track
from backend.services.location_encoder import encode_location
from backend.services.xml_exporter import export_library


@pytest.fixture
def settings(tmp_path: Path) -> Any:
    """Create mock settings pointing to tmp_path."""

    class MockSettings:
        output_directory: str = str(tmp_path / "library")
        rekordbox_xml_path: str = ""
        default_key_notation: str = "camelot"

    return MockSettings()


def _create_track_file(tmp_path: Path, rel_path: str, size: int = 1024) -> str:
    """Create a dummy file and return its absolute path."""
    full_path = tmp_path / "library" / rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(b"x" * size)
    return str(full_path)


class TestEndToEndExport:
    """End-to-end: create tracks → export XML → parse → verify."""

    def test_full_export_flow(self, db_session: Any, settings: Any, tmp_path: Path) -> None:
        """Create tracks, export, parse back and verify all attributes."""
        # Create real files
        path1 = _create_track_file(tmp_path, "Calibre/Shelflife 6/Falls to You.aiff")
        path2 = _create_track_file(tmp_path, "Bicep/Isles/Glue.aiff")

        # Add tracks to DB
        t1 = Track(
            file_path=path1,
            title="Falls to You",
            artist="Calibre",
            album="Shelflife 6",
            genre="Drum & Bass",
            bpm=174.0,
            key=15,  # 8A / A minor
            rating=4,
            duration=342.5,
            bit_rate=2116,
            sample_rate=44100,
            imported_at=datetime(2026, 3, 1),
            label="Signature",
        )
        t2 = Track(
            file_path=path2,
            title="Glue",
            artist="Bicep",
            album="Isles",
            genre="Electronic",
            bpm=130.0,
            key=16,  # 8B / C major
            rating=5,
            duration=289.0,
            bit_rate=2116,
            sample_rate=44100,
            imported_at=datetime(2026, 2, 15),
        )
        db_session.add_all([t1, t2])
        db_session.commit()

        # Export
        xml_path = str(tmp_path / "rekordbox.xml")
        result = export_library(db_session, settings, output_path=xml_path)

        assert result.tracks_exported == 2
        assert result.tracks_skipped == 0
        assert Path(xml_path).exists()

        # Parse XML and verify
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Structure
        assert root.tag == "DJ_PLAYLISTS"
        assert root.get("Version") == "1.0.0"
        product = root.find("PRODUCT")
        assert product is not None
        assert product.get("Name") == "rekordbot"

        # Collection
        collection = root.find("COLLECTION")
        assert collection is not None
        assert collection.get("Entries") == "2"

        tracks = collection.findall("TRACK")
        assert len(tracks) == 2

        # Verify first track attributes
        track1 = tracks[0]
        assert track1.get("TrackID") == "1"
        assert track1.get("Name") == "Falls to You"
        assert track1.get("Artist") == "Calibre"
        assert track1.get("Album") == "Shelflife 6"
        assert track1.get("Genre") == "Drum & Bass"
        assert track1.get("AverageBpm") == "174.00"
        assert track1.get("Tonality") == "8A"
        assert track1.get("Rating") == "204"  # 4 stars
        assert track1.get("TotalTime") == "342"
        assert track1.get("Kind") == "AIFF File"
        assert int(track1.get("Size", "0")) > 0

        # Verify Location encoding
        location = track1.get("Location", "")
        assert location.startswith("file://localhost/")
        assert "Shelflife%206" in location
        assert "Falls%20to%20You" in location

        # Verify second track
        track2 = tracks[1]
        assert track2.get("Name") == "Glue"
        assert track2.get("Artist") == "Bicep"
        assert track2.get("Rating") == "255"  # 5 stars

        # Playlists
        playlists = root.find("PLAYLISTS")
        assert playlists is not None

        root_node = playlists.find("NODE")
        assert root_node is not None
        assert root_node.get("Name") == "ROOT"

        rekordbot_node = root_node.find("NODE")
        assert rekordbot_node is not None
        assert rekordbot_node.get("Name") == "rekordbot"

        # Find All Tracks playlist
        all_tracks_pl = None
        for node in rekordbot_node:
            if node.get("Name") == "All Tracks":
                all_tracks_pl = node
                break
        assert all_tracks_pl is not None
        assert all_tracks_pl.get("Entries") == "2"

    def test_re_export_after_metadata_change(
        self, db_session: Any, settings: Any, tmp_path: Path
    ) -> None:
        """Re-export after changing metadata produces updated XML."""
        path = _create_track_file(tmp_path, "Artist/track.aiff")
        track = Track(
            file_path=path,
            title="Original Title",
            artist="Artist",
            bpm=128.0,
            key=16,
        )
        db_session.add(track)
        db_session.commit()

        xml_path = str(tmp_path / "rekordbox.xml")

        # First export
        export_library(db_session, settings, output_path=xml_path)
        tree1 = ET.parse(xml_path)
        track1_elem = tree1.getroot().find("COLLECTION/TRACK")
        assert track1_elem is not None
        assert track1_elem.get("Name") == "Original Title"

        # Update metadata
        track.title = "Updated Title"
        track.bpm = 140.0
        db_session.commit()

        # Re-export
        export_library(db_session, settings, output_path=xml_path)
        tree2 = ET.parse(xml_path)
        track_elem = tree2.getroot().find("COLLECTION/TRACK")
        assert track_elem is not None
        assert track_elem.get("Name") == "Updated Title"
        assert track_elem.get("AverageBpm") == "140.00"


class TestLocationEncodingRoundTrip:
    """Verify Location URIs decode back to valid file paths."""

    @pytest.mark.parametrize(
        "path",
        [
            "/Users/daleb/library/Simple/track.aiff",
            "/Users/daleb/library/With Spaces/My Track.aiff",
            "/Users/daleb/library/Âme/Rêve.aiff",
            "/Users/daleb/library/Above & Beyond/Track #1.mp3",
            "/Users/daleb/library/A/B/C/D/deeply nested.aiff",
            "/Users/daleb/library/Track (Original Mix).aiff",
            "/Users/daleb/library/Don't Stop.aiff",
        ],
    )
    def test_round_trip(self, path: str) -> None:
        """Encoding a path and decoding produces the original path."""
        encoded = encode_location(path)
        assert encoded.startswith("file://localhost/")
        decoded = unquote(encoded.replace("file://localhost", ""))
        assert decoded == path


class TestPlaylistStructureVerification:
    """Verify playlist structure matches the folder hierarchy."""

    def test_playlist_matches_folder_structure(
        self, db_session: Any, settings: Any, tmp_path: Path
    ) -> None:
        """Playlists should reflect the top-level folders."""
        paths = {
            "Calibre": [
                _create_track_file(tmp_path, "Calibre/track1.aiff"),
                _create_track_file(tmp_path, "Calibre/track2.aiff"),
            ],
            "Bicep": [
                _create_track_file(tmp_path, "Bicep/track3.aiff"),
            ],
            "Bonobo": [
                _create_track_file(tmp_path, "Bonobo/track4.aiff"),
                _create_track_file(tmp_path, "Bonobo/track5.aiff"),
                _create_track_file(tmp_path, "Bonobo/track6.aiff"),
            ],
        }

        track_id = 1
        for artist, file_paths in paths.items():
            for fp in file_paths:
                t = Track(
                    file_path=fp,
                    title=f"Track {track_id}",
                    artist=artist,
                    bpm=128.0,
                )
                db_session.add(t)
                track_id += 1
        db_session.commit()

        xml_path = str(tmp_path / "rekordbox.xml")
        result = export_library(db_session, settings, output_path=xml_path)

        assert result.tracks_exported == 6

        # Parse and verify playlists
        tree = ET.parse(xml_path)
        rekordbot_node = tree.getroot().find(".//NODE[@Name='rekordbot']")
        assert rekordbot_node is not None

        playlist_nodes = [n for n in rekordbot_node if n.get("Type") == "1"]
        playlist_map = {n.get("Name"): int(n.get("Entries", "0")) for n in playlist_nodes}

        assert "All Tracks" in playlist_map
        assert playlist_map["All Tracks"] == 6
        assert playlist_map.get("Bicep") == 1
        assert playlist_map.get("Bonobo") == 3
        assert playlist_map.get("Calibre") == 2

        # TrackIDs in playlists should match collection
        collection_elem = tree.getroot().find("COLLECTION")
        assert collection_elem is not None
        collection_ids = {t.get("TrackID") for t in collection_elem.findall("TRACK")}
        for node in playlist_nodes:
            for track_ref in node.findall("TRACK"):
                assert track_ref.get("Key") in collection_ids


class TestExportApiIntegration:
    """Integration tests via the API endpoints."""

    @patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
    @patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
    @pytest.mark.asyncio
    async def test_export_then_status(self, mock_mtime: Any, mock_size: Any, client: Any) -> None:
        """POST export then GET status returns last export info."""
        from backend.models.database import SessionLocal

        db = SessionLocal()
        t = Track(file_path="/lib/a/t.aiff", title="Test", artist="Artist")
        db.add(t)
        db.commit()
        db.close()

        # Export
        resp = await client.post("/api/export/rekordbox", json={})
        assert resp.status_code == 200
        assert resp.json()["tracks_exported"] == 1

        # Status
        resp = await client.get("/api/export/rekordbox/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["last_export"] is not None
        assert data["last_export"]["tracks_exported"] == 1
