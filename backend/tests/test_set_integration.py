"""Integration tests for Set Planner (Phase 5b).

End-to-end tests covering set creation, track management, segment editing,
lock/unlock, XML export with sets, and API route integration.
"""

import xml.etree.ElementTree as ET

import pytest

from backend.models.database import SessionLocal
from backend.models.set_plan import SetPlan, SetSegment, SetTrack
from backend.models.track import Track
from backend.services.set_planner import (
    add_track_at_position,
    create_set,
    get_set,
    list_sets,
    lock_track,
    move_track,
    recalculate_segments,
    remove_track,
    unlock_track,
    update_segment_description,
)
from backend.services.xml_builder import build_xml

_counter = 0


def _clean_tables():
    """Clean all set and track tables for test isolation."""
    from backend.models.database import init_db

    init_db()
    db = SessionLocal()
    try:
        db.query(SetTrack).delete()
        db.query(SetSegment).delete()
        db.query(SetPlan).delete()
        db.query(Track).delete()
        db.commit()
    finally:
        db.close()


def _create_track(db, title="Test", bpm=128.0, key=None, energy=None, mood=None, genre=None):
    """Create a track with unique file path."""
    global _counter
    _counter += 1
    track = Track(
        file_path=f"/test/integration_{title.lower()}_{_counter}.aiff",
        title=title,
        artist="Artist",
        bpm=bpm,
        genre=genre or "Techno",
        key=key,
        energy=energy,
        mood=mood,
    )
    db.add(track)
    db.flush()
    return track


class TestSetCreationFlow:
    """End-to-end set creation and track management."""

    def setup_method(self):
        """Clean tables before each test."""
        _clean_tables()

    def test_create_set_add_tracks_get_detail(self):
        """Create a set, add tracks, and retrieve full detail."""
        db = SessionLocal()
        try:
            # Create tracks
            t1 = _create_track(db, "Opener", bpm=120.0, energy=3)
            t2 = _create_track(db, "Builder", bpm=124.0, energy=5)
            t3 = _create_track(db, "Peak", bpm=128.0, energy=8)
            db.commit()

            # Create set
            plan = create_set(
                name="Friday Night",
                description="Deep warm-up set",
                db_session=db,
                duration_minutes=60,
                target_bpm_start=120.0,
                target_bpm_end=130.0,
                energy_arc="slow build",
            )
            assert plan.status == "draft"

            # Add tracks
            for i, track in enumerate([t1, t2, t3], 1):
                db.add(SetTrack(set_id=plan.id, track_id=track.id, position=i, is_candidate=False))
            db.commit()

            recalculate_segments(plan.id, db)

            # Get detail
            detail = get_set(plan.id, db)
            assert detail.name == "Friday Night"
            assert len(detail.tracks) == 3
            assert len(detail.segments) >= 1
            assert detail.tracks[0]["title"] == "Opener"
            assert detail.tracks[2]["title"] == "Peak"
        finally:
            db.close()

    def test_lock_creates_segments(self):
        """Locking a track creates segment boundaries."""
        db = SessionLocal()
        try:
            tracks = [_create_track(db, f"T{i}", bpm=120.0 + i) for i in range(5)]
            db.commit()

            plan = create_set(name="Segment Test", description="Test", db_session=db)
            for i, t in enumerate(tracks, 1):
                db.add(SetTrack(set_id=plan.id, track_id=t.id, position=i, is_candidate=False))
            db.commit()
            recalculate_segments(plan.id, db)

            # Lock position 3 — should create 2 segments
            lock_track(plan.id, 3, db)

            detail = get_set(plan.id, db)
            assert len(detail.segments) == 2

            # Unlock — should go back to 1 segment
            unlock_track(plan.id, 3, db)
            detail = get_set(plan.id, db)
            assert len(detail.segments) == 1
        finally:
            db.close()

    def test_remove_and_add_track(self):
        """Remove a track (moves to candidates), then add a new one."""
        db = SessionLocal()
        try:
            tracks = [_create_track(db, f"T{i}", bpm=120.0 + i) for i in range(4)]
            db.commit()

            plan = create_set(name="Edit Test", description="Test", db_session=db)
            for i, t in enumerate(tracks, 1):
                db.add(SetTrack(set_id=plan.id, track_id=t.id, position=i, is_candidate=False))
            db.commit()
            recalculate_segments(plan.id, db)

            # Remove position 2 → 3 tracks remain
            remove_track(plan.id, 2, db)
            detail = get_set(plan.id, db)
            assert len(detail.tracks) == 3
            assert len(detail.candidates) == 1

            # Add a new track at position 2
            new_track = _create_track(db, "Replacement", bpm=125.0)
            db.commit()
            add_track_at_position(plan.id, new_track.id, 2, db)

            detail = get_set(plan.id, db)
            assert len(detail.tracks) == 4
            assert detail.tracks[1]["title"] == "Replacement"
        finally:
            db.close()

    def test_move_track_reorders(self):
        """Moving a track updates positions correctly."""
        db = SessionLocal()
        try:
            tracks = [_create_track(db, f"T{i}") for i in range(4)]
            db.commit()

            plan = create_set(name="Move Test", description="Test", db_session=db)
            for i, t in enumerate(tracks, 1):
                db.add(SetTrack(set_id=plan.id, track_id=t.id, position=i, is_candidate=False))
            db.commit()
            recalculate_segments(plan.id, db)

            # Move position 1 to position 3
            move_track(plan.id, 1, 3, db)

            detail = get_set(plan.id, db)
            positions = [t["position"] for t in detail.tracks]
            assert positions == [1, 2, 3, 4]
        finally:
            db.close()

    def test_segment_description_preserved(self):
        """Segment descriptions survive recalculation when boundaries unchanged."""
        db = SessionLocal()
        try:
            tracks = [_create_track(db, f"T{i}") for i in range(5)]
            db.commit()

            plan = create_set(name="Desc Test", description="Test", db_session=db)
            for i, t in enumerate(tracks, 1):
                db.add(SetTrack(set_id=plan.id, track_id=t.id, position=i, is_candidate=False))
            db.commit()
            recalculate_segments(plan.id, db)

            # Lock position 3
            lock_track(plan.id, 3, db)

            # Set description on first segment
            detail = get_set(plan.id, db)
            seg_id = detail.segments[0]["id"]
            update_segment_description(seg_id, "Dark and moody opener", db)

            # Recalculate again (e.g., after another lock)
            lock_track(plan.id, 5, db)

            detail = get_set(plan.id, db)
            # Find the segment that starts at position 1
            seg1 = next(s for s in detail.segments if s["start_track_position"] == 1)
            assert seg1["description"] == "Dark and moody opener"
        finally:
            db.close()

    def test_list_sets_with_counts(self):
        """List sets returns correct track and candidate counts."""
        db = SessionLocal()
        try:
            plan = create_set(name="Count Test", description="Test", db_session=db)
            t1 = _create_track(db, "Active1")
            t2 = _create_track(db, "Active2")
            t3 = _create_track(db, "Candidate1")
            db.add(SetTrack(set_id=plan.id, track_id=t1.id, position=1, is_candidate=False))
            db.add(SetTrack(set_id=plan.id, track_id=t2.id, position=2, is_candidate=False))
            db.add(SetTrack(set_id=plan.id, track_id=t3.id, position=0, is_candidate=True))
            db.commit()

            summaries = list_sets(db)
            s = next(s for s in summaries if s.id == plan.id)
            assert s.track_count == 2
            assert s.candidate_count == 1
        finally:
            db.close()


class TestXmlExportWithSets:
    """XML export integration with set playlists."""

    def setup_method(self):
        """Clean tables before each test."""
        _clean_tables()

    def test_set_playlist_in_xml(self):
        """Sets appear as ordered playlists in the XML."""
        db = SessionLocal()
        try:
            t1 = _create_track(db, "Track A", bpm=120.0)
            t2 = _create_track(db, "Track B", bpm=124.0)
            t3 = _create_track(db, "Track C", bpm=128.0)
            db.commit()

            plan = create_set(name="XML Set", description="Test", db_session=db)
            for i, t in enumerate([t1, t2, t3], 1):
                db.add(SetTrack(set_id=plan.id, track_id=t.id, position=i, is_candidate=False))
            db.commit()

            tracks = [t1, t2, t3]
            set_track_ids = [t.id for t in tracks]

            tree, track_id_map, warnings = build_xml(
                tracks,
                "camelot",
                "/output",
                sets=[(plan, set_track_ids)],
            )

            # Find set playlist node
            root = tree.getroot()
            playlist_names = []
            for node in root.iter("NODE"):
                if node.get("Type") == "1":
                    playlist_names.append(node.get("Name"))

            assert "XML Set" in playlist_names
        finally:
            db.close()

    def test_set_playlist_order_preserved(self):
        """Track order in the XML matches set position order."""
        db = SessionLocal()
        try:
            t1 = _create_track(db, "First")
            t2 = _create_track(db, "Second")
            t3 = _create_track(db, "Third")
            db.commit()

            plan = create_set(name="Order Test", description="Test", db_session=db)
            # Reverse order: t3, t1, t2
            db.add(SetTrack(set_id=plan.id, track_id=t3.id, position=1, is_candidate=False))
            db.add(SetTrack(set_id=plan.id, track_id=t1.id, position=2, is_candidate=False))
            db.add(SetTrack(set_id=plan.id, track_id=t2.id, position=3, is_candidate=False))
            db.commit()

            tracks = [t1, t2, t3]
            set_track_ids = [t3.id, t1.id, t2.id]  # Position order

            tree, track_id_map, warnings = build_xml(
                tracks,
                "camelot",
                "/output",
                sets=[(plan, set_track_ids)],
            )

            # Find set playlist and check order
            root = tree.getroot()
            for node in root.iter("NODE"):
                if node.get("Name") == "Order Test":
                    track_refs = list(node)
                    keys = [int(ref.get("Key", "0")) for ref in track_refs]
                    # Keys should be in order: t3's XML ID, t1's XML ID, t2's XML ID
                    assert keys == [
                        track_id_map[t3.id],
                        track_id_map[t1.id],
                        track_id_map[t2.id],
                    ]
                    break
        finally:
            db.close()

    def test_sets_coexist_with_crates(self):
        """Set and crate playlists both appear in the XML."""
        from unittest.mock import MagicMock

        db = SessionLocal()
        try:
            t1 = _create_track(db, "Shared Track")
            db.commit()

            plan = create_set(name="My Set", description="Test", db_session=db)
            db.add(SetTrack(set_id=plan.id, track_id=t1.id, position=1, is_candidate=False))
            db.commit()

            crate = MagicMock()
            crate.name = "My Crate"

            tree, track_id_map, warnings = build_xml(
                [t1],
                "camelot",
                "/output",
                crates=[(crate, [t1.id])],
                sets=[(plan, [t1.id])],
            )

            root = tree.getroot()
            playlist_names = []
            for node in root.iter("NODE"):
                if node.get("Type") == "1":
                    playlist_names.append(node.get("Name"))

            assert "My Set" in playlist_names
            assert "My Crate" in playlist_names
            assert "All Tracks" in playlist_names
        finally:
            db.close()


class TestSetRouteIntegration:
    """End-to-end API route tests."""

    @pytest.mark.asyncio
    async def test_create_lock_shuffle_export_flow(self, client):
        """Full lifecycle: create → add tracks → lock → export."""
        db = SessionLocal()
        try:
            # Create tracks
            tracks = [_create_track(db, f"Flow{i}", bpm=120.0 + i * 2) for i in range(4)]
            db.commit()

            plan = create_set(name="Flow Test", description="Test flow", db_session=db)
            plan.status = "complete"
            for i, t in enumerate(tracks, 1):
                db.add(SetTrack(set_id=plan.id, track_id=t.id, position=i, is_candidate=False))
            db.commit()
            recalculate_segments(plan.id, db)
            plan_id = plan.id
        finally:
            db.close()

        # Get set via API
        response = await client.get(f"/api/sets/{plan_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Flow Test"
        assert len(data["tracks"]) == 4

        # Lock track at position 2
        response = await client.post(f"/api/sets/{plan_id}/lock/2")
        assert response.status_code == 200

        # Verify segments changed
        response = await client.get(f"/api/sets/{plan_id}")
        data = response.json()
        assert len(data["segments"]) == 2

        # Unlock
        response = await client.post(f"/api/sets/{plan_id}/unlock/2")
        assert response.status_code == 200

        # Export
        import os
        import tempfile

        import backend.config as config_module

        with tempfile.TemporaryDirectory() as tmp_dir:
            original = config_module.settings.rekordbox_xml_path
            config_module.settings.rekordbox_xml_path = os.path.join(tmp_dir, "rekordbox.xml")
            try:
                response = await client.post(f"/api/sets/{plan_id}/export")
                assert response.status_code == 200
                assert response.json()["tracks_in_set"] == 4

                # Verify XML file was written and contains the set playlist
                xml_path = response.json()["output_path"]
                tree = ET.parse(xml_path)
                root = tree.getroot()
                playlist_names = [n.get("Name") for n in root.iter("NODE") if n.get("Type") == "1"]
                assert "Flow Test" in playlist_names
            finally:
                config_module.settings.rekordbox_xml_path = original
