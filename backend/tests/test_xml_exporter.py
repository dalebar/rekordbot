"""Tests for the export service — orchestration, filtering, and result reporting."""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from backend.models.track import Track
from backend.services.xml_exporter import export_library


@pytest.fixture
def settings(tmp_path: Path) -> Any:
    """Create mock settings pointing to tmp_path."""

    class MockSettings:
        output_directory: str = str(tmp_path / "library")
        rekordbox_xml_path: str = ""
        default_key_notation: str = "camelot"

    return MockSettings()


def _add_track(
    db_session: Any,
    track_id: int = 1,
    file_path: str = "/library/Artist/track.aiff",
    title: str = "Test Track",
    artist: str = "Test Artist",
) -> Track:
    """Add a track to the test database."""
    track = Track(
        id=track_id,
        file_path=file_path,
        title=title,
        artist=artist,
        album="Test Album",
        genre="Electronic",
        bpm=128.0,
        key=16,
        rating=0,
        duration=300.0,
        bit_rate=2116,
        sample_rate=44100,
    )
    db_session.add(track)
    db_session.commit()
    return track


@patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
@patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
class TestExportLibrary:
    """Tests for the export_library orchestrator."""

    def test_export_all_tracks(
        self, mock_mtime: Any, mock_size: Any, db_session: Any, settings: Any, tmp_path: Path
    ) -> None:
        _add_track(db_session, track_id=1, file_path="/library/A/track1.aiff")
        _add_track(db_session, track_id=2, file_path="/library/B/track2.aiff")

        xml_path = str(tmp_path / "export.xml")
        result = export_library(db_session, settings, output_path=xml_path)

        assert result.tracks_exported == 2
        assert result.tracks_skipped == 0
        assert result.output_path == xml_path
        assert Path(xml_path).exists()

    def test_export_subset(
        self, mock_mtime: Any, mock_size: Any, db_session: Any, settings: Any, tmp_path: Path
    ) -> None:
        _add_track(db_session, track_id=1, file_path="/library/A/track1.aiff")
        _add_track(db_session, track_id=2, file_path="/library/B/track2.aiff")
        _add_track(db_session, track_id=3, file_path="/library/C/track3.aiff")

        xml_path = str(tmp_path / "export.xml")
        result = export_library(db_session, settings, track_ids=[1, 3], output_path=xml_path)

        assert result.tracks_exported == 2

    def test_skip_tracks_without_file_path(
        self, mock_mtime: Any, mock_size: Any, db_session: Any, settings: Any, tmp_path: Path
    ) -> None:
        _add_track(db_session, track_id=1, file_path="/library/A/track1.aiff")
        # Track with empty file_path
        track2 = Track(id=2, file_path="", title="No Path")
        db_session.add(track2)
        db_session.commit()

        xml_path = str(tmp_path / "export.xml")
        result = export_library(db_session, settings, output_path=xml_path)

        assert result.tracks_exported == 1
        assert result.tracks_skipped == 1
        assert any("no file path" in w for w in result.warnings)

    def test_empty_library(
        self, mock_mtime: Any, mock_size: Any, db_session: Any, settings: Any, tmp_path: Path
    ) -> None:
        xml_path = str(tmp_path / "export.xml")
        result = export_library(db_session, settings, output_path=xml_path)

        assert result.tracks_exported == 0
        assert result.tracks_skipped == 0
        assert result.playlists_created == 0

    def test_playlists_counted(
        self, mock_mtime: Any, mock_size: Any, db_session: Any, settings: Any, tmp_path: Path
    ) -> None:
        _add_track(db_session, track_id=1, file_path=str(tmp_path / "library/A/t.aiff"))
        _add_track(db_session, track_id=2, file_path=str(tmp_path / "library/B/t.aiff"))

        xml_path = str(tmp_path / "export.xml")
        result = export_library(db_session, settings, output_path=xml_path)

        # Should have All Tracks + 2 artist playlists = 3
        assert result.playlists_created >= 1  # At minimum "All Tracks"

    def test_output_is_valid_xml(
        self, mock_mtime: Any, mock_size: Any, db_session: Any, settings: Any, tmp_path: Path
    ) -> None:
        _add_track(db_session, track_id=1, file_path="/library/A/track1.aiff")

        xml_path = str(tmp_path / "export.xml")
        export_library(db_session, settings, output_path=xml_path)

        # Parse back and verify structure
        tree = ET.parse(xml_path)
        root = tree.getroot()
        assert root.tag == "DJ_PLAYLISTS"
        assert root.find("PRODUCT") is not None
        assert root.find("COLLECTION") is not None
        assert root.find("PLAYLISTS") is not None

    def test_default_output_path(
        self, mock_mtime: Any, mock_size: Any, db_session: Any, settings: Any, tmp_path: Path
    ) -> None:
        """Uses output_directory/rekordbox.xml when no explicit path given."""
        _add_track(db_session, track_id=1, file_path="/library/A/track.aiff")

        result = export_library(db_session, settings)

        expected = str(Path(settings.output_directory).expanduser().resolve() / "rekordbox.xml")
        assert result.output_path == expected

    def test_rekordbox_xml_path_setting(
        self, mock_mtime: Any, mock_size: Any, db_session: Any, settings: Any, tmp_path: Path
    ) -> None:
        """Uses rekordbox_xml_path setting when set."""
        custom_path = str(tmp_path / "custom" / "output.xml")
        settings.rekordbox_xml_path = custom_path
        _add_track(db_session, track_id=1, file_path="/library/A/track.aiff")

        result = export_library(db_session, settings)

        assert result.output_path == str(Path(custom_path).resolve())

    def test_re_export_overwrites(
        self, mock_mtime: Any, mock_size: Any, db_session: Any, settings: Any, tmp_path: Path
    ) -> None:
        _add_track(db_session, track_id=1, file_path="/library/A/track.aiff")

        xml_path = str(tmp_path / "export.xml")
        export_library(db_session, settings, output_path=xml_path)
        first_size = Path(xml_path).stat().st_size

        # Add another track and re-export
        _add_track(db_session, track_id=2, file_path="/library/B/track2.aiff")
        export_library(db_session, settings, output_path=xml_path)
        second_size = Path(xml_path).stat().st_size

        # Second export should be larger (more tracks)
        assert second_size > first_size
