"""Tests for XML import service."""

import json
import textwrap
from pathlib import Path

import pytest

from backend.models.crate import Crate, CrateTrack
from backend.models.track import Track
from backend.services.xml_importer import (
    ImportProgress,
    run_import,
)


def _write_xml(tmp_path: Path, tracks_xml: str, playlists_xml: str = "") -> Path:
    """Helper to write a test Rekordbox XML file."""
    if not playlists_xml:
        playlists_xml = '<NODE Type="0" Name="ROOT" Count="0"/>'

    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<DJ_PLAYLISTS Version="1.0.0">\n'
        '  <PRODUCT Name="rekordbox" Version="6.7.4" Company="AlphaTheta"/>\n'
        f'  <COLLECTION Entries="0">{tracks_xml}</COLLECTION>\n'
        f"  <PLAYLISTS>{playlists_xml}</PLAYLISTS>\n"
        "</DJ_PLAYLISTS>\n"
    )
    xml_file = tmp_path / "test_library.xml"
    xml_file.write_text(content)
    return xml_file


def _make_audio_file(tmp_path: Path, name: str, content: bytes = b"fake audio") -> Path:
    """Create a fake audio file for testing."""
    audio_file = tmp_path / name
    audio_file.write_bytes(content)
    return audio_file


class TestImportNewTracks:
    """Test importing tracks that don't exist in the database."""

    def test_import_new_track(self, db_session, tmp_path):
        """Should create a new Track record from XML data."""
        audio = _make_audio_file(tmp_path, "track.aiff")
        from backend.services.location_encoder import encode_location

        location = encode_location(str(audio))

        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="Test Track" Artist="Test Artist" '
            f'AverageBpm="128.00" Tonality="8A" Rating="204" Genre="House" '
            f'TotalTime="300" Kind="AIFF File" '
            f'Location="{location}"/>',
        )

        summary = run_import(xml_file, db_session)

        assert summary.tracks_imported == 1
        assert summary.tracks_total == 1

        track = db_session.query(Track).filter(Track.file_path == str(audio)).first()
        assert track is not None
        assert track.title == "Test Track"
        assert track.artist == "Test Artist"
        assert track.bpm == 128.0
        assert track.key == 15  # 8A
        assert track.rating == 4  # 204 -> 4 stars
        assert track.genre == "House"
        assert track.import_source == "rekordbox_xml"
        assert track.conversion_action == "imported"
        assert track.analysis_status == "not_analysed"
        assert track.ai_status == "untagged"
        assert track.source_codec == "aiff"
        assert track.file_hash is not None

    def test_import_multiple_tracks(self, db_session, tmp_path):
        audio1 = _make_audio_file(tmp_path, "one.aiff", b"audio1")
        audio2 = _make_audio_file(tmp_path, "two.mp3", b"audio2")
        from backend.services.location_encoder import encode_location

        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="One" Location="{encode_location(str(audio1))}"/>'
            f'<TRACK TrackID="2" Name="Two" Location="{encode_location(str(audio2))}"/>',
        )

        summary = run_import(xml_file, db_session)
        assert summary.tracks_imported == 2


class TestImportWithMatches:
    """Test importing when tracks already exist in DB."""

    def test_path_match_no_conflicts_fills_gaps(self, db_session, tmp_path):
        """Matched track with no conflicts should fill empty fields."""
        audio = _make_audio_file(tmp_path, "existing.aiff")

        # Pre-existing track with some fields
        existing = Track(
            file_path=str(audio),
            title="Existing Title",
        )
        db_session.add(existing)
        db_session.flush()

        from backend.services.location_encoder import encode_location

        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="Existing Title" Artist="XML Artist" '
            f'Genre="House" Location="{encode_location(str(audio))}"/>',
        )

        summary = run_import(xml_file, db_session)
        assert summary.tracks_matched == 1
        assert summary.tracks_conflict == 0

        db_session.refresh(existing)
        assert existing.artist == "XML Artist"  # Filled from XML
        assert existing.genre == "House"  # Filled from XML
        assert existing.title == "Existing Title"  # Unchanged

    def test_path_match_with_conflicts(self, db_session, tmp_path):
        """Matched track with different values should create conflicts."""
        audio = _make_audio_file(tmp_path, "conflict.aiff")

        existing = Track(
            file_path=str(audio),
            title="DB Title",
            bpm=127.0,
            genre="Techno",
        )
        db_session.add(existing)
        db_session.flush()

        from backend.services.location_encoder import encode_location

        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="XML Title" AverageBpm="128.00" '
            f'Genre="House" Location="{encode_location(str(audio))}"/>',
        )

        summary = run_import(xml_file, db_session)
        assert summary.tracks_conflict == 1

        db_session.refresh(existing)
        assert existing.import_conflicts is not None
        conflicts = json.loads(existing.import_conflicts)
        fields = {c["field"] for c in conflicts}
        assert "bpm" in fields
        assert "title" in fields
        assert "genre" in fields


class TestImportSkipsMissingFiles:
    """Test that tracks with missing files are skipped."""

    def test_missing_file_skipped(self, db_session, tmp_path):
        from backend.services.location_encoder import encode_location

        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="Missing" '
            f'Location="{encode_location("/nonexistent/path/track.aiff")}"/>',
        )

        summary = run_import(xml_file, db_session)
        assert summary.tracks_skipped == 1
        assert len(summary.skipped_reasons) == 1
        assert "not found" in summary.skipped_reasons[0].lower()


class TestImportPlaylists:
    """Test playlist-to-crate import."""

    def test_playlist_creates_crate(self, db_session, tmp_path):
        audio = _make_audio_file(tmp_path, "playlist_track.aiff")
        from backend.services.location_encoder import encode_location

        location = encode_location(str(audio))
        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="Track" Location="{location}"/>',
            textwrap.dedent("""\
                <NODE Type="0" Name="ROOT" Count="1">
                    <NODE Type="0" Name="rekordbox" Count="1">
                        <NODE Name="My Playlist" Type="1" KeyType="0" Entries="1">
                            <TRACK Key="1"/>
                        </NODE>
                    </NODE>
                </NODE>
            """),
        )

        summary = run_import(xml_file, db_session)
        assert summary.playlists_imported == 1

        crate = db_session.query(Crate).filter(Crate.name == "My Playlist").first()
        assert crate is not None
        assert crate.description == "Imported from Rekordbox XML"
        assert crate.auto_refresh is False

        # Check track assignment
        assignments = db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate.id).all()
        assert len(assignments) == 1
        assert assignments[0].assignment_method == "imported"

    def test_duplicate_crate_name_skipped(self, db_session, tmp_path):
        """Existing crate with same name should be skipped."""
        # Create existing crate
        existing_crate = Crate(name="My Playlist", description="Existing")
        db_session.add(existing_crate)
        db_session.flush()

        audio = _make_audio_file(tmp_path, "track.aiff")
        from backend.services.location_encoder import encode_location

        location = encode_location(str(audio))
        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="Track" Location="{location}"/>',
            textwrap.dedent("""\
                <NODE Type="0" Name="ROOT" Count="1">
                    <NODE Type="0" Name="rekordbox" Count="1">
                        <NODE Name="My Playlist" Type="1" KeyType="0" Entries="1">
                            <TRACK Key="1"/>
                        </NODE>
                    </NODE>
                </NODE>
            """),
        )

        summary = run_import(xml_file, db_session)
        assert summary.playlists_skipped == 1
        assert summary.playlists_imported == 0

    def test_nested_playlist_name(self, db_session, tmp_path):
        """Nested folder playlists should have folder prefix in crate name."""
        audio = _make_audio_file(tmp_path, "nested.aiff")
        from backend.services.location_encoder import encode_location

        location = encode_location(str(audio))
        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="Track" Location="{location}"/>',
            textwrap.dedent("""\
                <NODE Type="0" Name="ROOT" Count="1">
                    <NODE Type="0" Name="rekordbox" Count="1">
                        <NODE Type="0" Name="Genre" Count="1">
                            <NODE Name="Deep House" Type="1" KeyType="0" Entries="1">
                                <TRACK Key="1"/>
                            </NODE>
                        </NODE>
                    </NODE>
                </NODE>
            """),
        )

        run_import(xml_file, db_session)
        crate = db_session.query(Crate).filter(Crate.name == "Genre/Deep House").first()
        assert crate is not None


class TestImportCancellation:
    """Test import cancellation."""

    def test_cancel_stops_import(self, db_session, tmp_path):
        audio1 = _make_audio_file(tmp_path, "first.aiff", b"first")
        audio2 = _make_audio_file(tmp_path, "second.aiff", b"second")
        from backend.services.location_encoder import encode_location

        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="First" Location="{encode_location(str(audio1))}"/>'
            f'<TRACK TrackID="2" Name="Second" Location="{encode_location(str(audio2))}"/>',
        )

        # Cancel after first track
        call_count = 0

        def cancel_after_first():
            nonlocal call_count
            call_count += 1
            return call_count > 1

        summary = run_import(xml_file, db_session, cancel_check=cancel_after_first)
        # Should have processed only 1 track before cancelling
        assert summary.tracks_imported <= 1


class TestImportProgress:
    """Test progress callback."""

    def test_progress_callback_called(self, db_session, tmp_path):
        audio = _make_audio_file(tmp_path, "progress.aiff")
        from backend.services.location_encoder import encode_location

        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="Track" Location="{encode_location(str(audio))}"/>',
        )

        progress_events: list[ImportProgress] = []

        def on_progress(p: ImportProgress):
            # Copy current state
            progress_events.append(
                ImportProgress(
                    processed=p.processed,
                    total=p.total,
                    imported=p.imported,
                    matched=p.matched,
                    skipped=p.skipped,
                    conflicts=p.conflicts,
                )
            )

        run_import(xml_file, db_session, progress_callback=on_progress)
        assert len(progress_events) >= 1
        assert progress_events[-1].processed == 1
        assert progress_events[-1].total == 1


class TestImportInvalidXml:
    """Test handling of invalid XML files."""

    def test_invalid_xml_raises(self, db_session, tmp_path):
        from backend.exceptions import XmlImportError

        xml_file = tmp_path / "bad.xml"
        xml_file.write_text("not xml")

        with pytest.raises(XmlImportError):
            run_import(xml_file, db_session)
