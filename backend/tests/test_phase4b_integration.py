"""Integration tests for Phase 4b — Rekordbox XML Import.

Tests the full round-trip: parse → import → conflicts → resolve → verify.
"""

import textwrap
from pathlib import Path

from backend.models.crate import Crate, CrateTrack
from backend.models.track import Track
from backend.services.conflict_resolver import (
    get_pending_conflicts,
    resolve_all_rekordbox,
    resolve_conflict,
)
from backend.services.location_encoder import encode_location
from backend.services.xml_importer import run_import


def _write_xml(tmp_path: Path, tracks_xml: str, playlists_xml: str = "") -> Path:
    """Write a test Rekordbox XML file."""
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
    xml_file = tmp_path / "library.xml"
    xml_file.write_text(content)
    return xml_file


class TestFullImportRoundTrip:
    """Test the complete import → conflict → resolve cycle."""

    def test_import_new_then_resolve_conflicts(self, db_session, tmp_path):
        """Import tracks, then re-import with different metadata, then resolve."""
        # Create audio files
        audio1 = tmp_path / "track1.aiff"
        audio1.write_bytes(b"audio content 1")
        audio2 = tmp_path / "track2.mp3"
        audio2.write_bytes(b"audio content 2")

        loc1 = encode_location(str(audio1))
        loc2 = encode_location(str(audio2))

        # First import — creates new tracks
        xml1 = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="Track One" Artist="Artist A" '
            f'AverageBpm="128.00" Genre="House" Rating="204" '
            f'Location="{loc1}"/>'
            f'<TRACK TrackID="2" Name="Track Two" Artist="Artist B" '
            f'AverageBpm="140.00" Genre="Techno" '
            f'Location="{loc2}"/>',
        )
        summary1 = run_import(xml1, db_session)
        assert summary1.tracks_imported == 2
        assert summary1.tracks_conflict == 0

        # Verify tracks exist
        t1 = db_session.query(Track).filter(Track.file_path == str(audio1)).first()
        t2 = db_session.query(Track).filter(Track.file_path == str(audio2)).first()
        assert t1 is not None
        assert t2 is not None
        assert t1.bpm == 128.0
        assert t2.bpm == 140.0
        assert t1.import_source == "rekordbox_xml"

        # Second import — same files, different metadata → conflicts
        xml2_file = tmp_path / "library2.xml"
        xml2_content = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<DJ_PLAYLISTS Version="1.0.0">\n'
            '  <PRODUCT Name="rekordbox" Version="6.7.4"/>\n'
            f'  <COLLECTION Entries="2">'
            f'<TRACK TrackID="1" Name="Track One REMIX" Artist="Artist A" '
            f'AverageBpm="130.00" Genre="Deep House" Rating="255" '
            f'Location="{loc1}"/>'
            f'<TRACK TrackID="2" Name="Track Two" Artist="Artist B" '
            f'AverageBpm="140.00" Genre="Techno" '
            f'Location="{loc2}"/>'
            f"</COLLECTION>\n"
            '  <PLAYLISTS><NODE Type="0" Name="ROOT" Count="0"/></PLAYLISTS>\n'
            "</DJ_PLAYLISTS>\n"
        )
        xml2_file.write_text(xml2_content)
        summary2 = run_import(xml2_file, db_session)

        # Track 1 should have conflicts (BPM, title, genre, rating changed)
        # Track 2 should match with no conflicts (identical)
        assert summary2.tracks_conflict >= 1
        assert summary2.tracks_matched >= 1

        # Check conflicts
        conflicts = get_pending_conflicts(db_session)
        assert len(conflicts) >= 1
        conflict_track_ids = {c["track_id"] for c in conflicts}
        assert t1.id in conflict_track_ids

        # Resolve — accept Rekordbox values for track 1
        t1_conflicts = [c for c in conflicts if c["track_id"] == t1.id][0]
        resolutions = {c["field"]: "rekordbox" for c in t1_conflicts["conflicts"]}
        resolve_conflict(t1.id, resolutions, db_session)

        # Verify resolved
        db_session.refresh(t1)
        assert t1.import_conflicts is None
        assert t1.bpm == 130.0
        assert t1.title == "Track One REMIX"
        assert t1.genre == "Deep House"


class TestImportWithPlaylists:
    """Test playlist import as crates."""

    def test_full_playlist_import(self, db_session, tmp_path):
        """Import tracks and playlists, verify crate structure."""
        audio1 = tmp_path / "track1.aiff"
        audio1.write_bytes(b"content1")
        audio2 = tmp_path / "track2.aiff"
        audio2.write_bytes(b"content2")
        audio3 = tmp_path / "track3.mp3"
        audio3.write_bytes(b"content3")

        loc1 = encode_location(str(audio1))
        loc2 = encode_location(str(audio2))
        loc3 = encode_location(str(audio3))

        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="One" Location="{loc1}"/>'
            f'<TRACK TrackID="2" Name="Two" Location="{loc2}"/>'
            f'<TRACK TrackID="3" Name="Three" Location="{loc3}"/>',
            textwrap.dedent("""\
                <NODE Type="0" Name="ROOT" Count="1">
                    <NODE Type="0" Name="rekordbox" Count="2">
                        <NODE Name="All Tracks" Type="1" KeyType="0" Entries="3">
                            <TRACK Key="1"/>
                            <TRACK Key="2"/>
                            <TRACK Key="3"/>
                        </NODE>
                        <NODE Type="0" Name="Genre" Count="1">
                            <NODE Name="House" Type="1" KeyType="0" Entries="2">
                                <TRACK Key="1"/>
                                <TRACK Key="2"/>
                            </NODE>
                        </NODE>
                    </NODE>
                </NODE>
            """),
        )

        summary = run_import(xml_file, db_session)
        assert summary.tracks_imported == 3
        assert summary.playlists_imported == 2

        # Check crates
        all_tracks_crate = db_session.query(Crate).filter(Crate.name == "All Tracks").first()
        house_crate = db_session.query(Crate).filter(Crate.name == "Genre/House").first()
        assert all_tracks_crate is not None
        assert house_crate is not None

        # Check track assignments
        all_count = (
            db_session.query(CrateTrack).filter(CrateTrack.crate_id == all_tracks_crate.id).count()
        )
        house_count = (
            db_session.query(CrateTrack).filter(CrateTrack.crate_id == house_crate.id).count()
        )
        assert all_count == 3
        assert house_count == 2

        # Check assignment method
        assignment = (
            db_session.query(CrateTrack).filter(CrateTrack.crate_id == all_tracks_crate.id).first()
        )
        assert assignment is not None
        assert assignment.assignment_method == "imported"


class TestImportMatchStrategies:
    """Test different match strategies."""

    def test_hash_match_different_path(self, db_session, tmp_path):
        """Hash match should work when file was moved to a different path."""
        audio = tmp_path / "moved_track.aiff"
        audio.write_bytes(b"unique audio content for hash match")

        from backend.services.converter import compute_file_hash

        file_hash = compute_file_hash(audio)

        # Pre-existing track at a different path but same hash
        existing = Track(
            file_path="/original/location/track.aiff",
            file_hash=file_hash,
            title="Original Title",
        )
        db_session.add(existing)
        db_session.flush()

        loc = encode_location(str(audio))
        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="Original Title" Artist="New Artist" Location="{loc}"/>',
        )

        summary = run_import(xml_file, db_session)
        # Should match by hash, not create a new track
        assert summary.tracks_imported == 0
        assert summary.tracks_matched == 1

        db_session.refresh(existing)
        assert existing.artist == "New Artist"  # Filled from XML


class TestLargeXmlImport:
    """Test handling of larger XML files."""

    def test_many_tracks(self, db_session, tmp_path):
        """Import 50 tracks — verify progress and counts."""
        tracks_xml = ""
        for i in range(50):
            audio = tmp_path / f"track_{i}.aiff"
            audio.write_bytes(f"audio content {i}".encode())
            loc = encode_location(str(audio))
            tracks_xml += (
                f'<TRACK TrackID="{i + 1}" Name="Track {i}" '
                f'Artist="Artist" AverageBpm="128.00" Location="{loc}"/>'
            )

        xml_file = _write_xml(tmp_path, tracks_xml)

        progress_events: list[dict] = []

        def on_progress(p):
            progress_events.append({"processed": p.processed, "total": p.total})

        summary = run_import(xml_file, db_session, progress_callback=on_progress)
        assert summary.tracks_imported == 50
        assert summary.tracks_total == 50
        assert len(progress_events) == 50

        # All tracks should exist in DB
        count = db_session.query(Track).count()
        assert count == 50


class TestMissingFileHandling:
    """Test graceful handling of missing files."""

    def test_mixed_existing_and_missing(self, db_session, tmp_path):
        """Some files exist, some don't — should skip missing and import rest."""
        audio = tmp_path / "exists.aiff"
        audio.write_bytes(b"real audio")

        loc_exists = encode_location(str(audio))
        loc_missing = encode_location("/nonexistent/path/missing.aiff")

        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="Exists" Location="{loc_exists}"/>'
            f'<TRACK TrackID="2" Name="Missing" Location="{loc_missing}"/>',
        )

        summary = run_import(xml_file, db_session)
        assert summary.tracks_imported == 1
        assert summary.tracks_skipped == 1
        assert len(summary.skipped_reasons) == 1


class TestBulkConflictResolution:
    """Test bulk resolution scenarios."""

    def test_resolve_all_then_verify(self, db_session, tmp_path):
        """Import with conflicts, bulk resolve, verify values."""
        audio = tmp_path / "bulk_track.aiff"
        audio.write_bytes(b"bulk content")

        # Create existing track
        existing = Track(
            file_path=str(audio),
            title="Old Title",
            bpm=120.0,
            genre="Techno",
            rating=2,
        )
        db_session.add(existing)
        db_session.flush()

        loc = encode_location(str(audio))
        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="New Title" AverageBpm="128.00" '
            f'Genre="House" Rating="255" Location="{loc}"/>',
        )

        summary = run_import(xml_file, db_session)
        assert summary.tracks_conflict == 1

        # Bulk resolve with rekordbox values
        count = resolve_all_rekordbox(db_session)
        assert count == 1

        db_session.refresh(existing)
        assert existing.title == "New Title"
        assert existing.bpm == 128.0
        assert existing.genre == "House"
        assert existing.rating == 5  # 255 → 5 stars
        assert existing.import_conflicts is None
