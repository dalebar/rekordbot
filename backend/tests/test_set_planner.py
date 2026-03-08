"""Tests for set planner service."""

import pytest

from backend.models.set_plan import SetPlan, SetSegment, SetTrack
from backend.models.track import Track
from backend.services.set_planner import (
    add_track_at_position,
    create_set,
    delete_set,
    get_candidates,
    get_set,
    list_sets,
    lock_track,
    move_track,
    recalculate_segments,
    remove_track,
    unlock_track,
    update_segment_description,
    update_set,
)

_track_counter = 0


def _create_track(db_session, title="Test Track", bpm=128.0, key=None, **kwargs):
    """Helper to create a track with a unique file path."""
    global _track_counter
    _track_counter += 1
    track = Track(
        file_path=f"/test/{title.lower().replace(' ', '_')}_{_track_counter}.aiff",
        title=title,
        artist=kwargs.get("artist", "Test Artist"),
        bpm=bpm,
        key=key,
        genre=kwargs.get("genre", "Techno"),
    )
    db_session.add(track)
    db_session.flush()
    return track


def _create_set_with_tracks(db_session, num_tracks=5, name="Test Set"):
    """Helper to create a set with tracks in sequence."""
    plan = create_set(name, "A test set", db_session)
    tracks = []
    for i in range(num_tracks):
        t = _create_track(db_session, title=f"Track {i + 1}", bpm=120.0 + i * 2)
        tracks.append(t)
        db_session.add(
            SetTrack(
                set_id=plan.id,
                track_id=t.id,
                position=i + 1,
                is_candidate=False,
            )
        )
    db_session.commit()
    recalculate_segments(plan.id, db_session)
    return plan, tracks


class TestCreateSet:
    """Tests for create_set()."""

    def test_create_basic_set(self, db_session):
        """Create a set with required fields."""
        plan = create_set("Friday Set", "Deep warm-up", db_session)

        assert plan.id is not None
        assert plan.name == "Friday Set"
        assert plan.description == "Deep warm-up"
        assert plan.status == "draft"
        assert plan.source_type == "library"

    def test_create_with_all_params(self, db_session):
        """Create a set with all optional parameters."""
        plan = create_set(
            "Full Set",
            "Peak time techno",
            db_session,
            source_type="crates",
            source_crate_ids=[1, 2, 3],
            duration_minutes=90,
            target_bpm_start=126.0,
            target_bpm_end=134.0,
            energy_arc="slow build",
            harmonic_mixing=True,
        )

        assert plan.duration_minutes == 90
        assert plan.target_bpm_start == 126.0
        assert plan.target_bpm_end == 134.0
        assert plan.energy_arc == "slow build"
        assert plan.source_type == "crates"
        assert plan.harmonic_mixing is True
        assert plan.source_crate_ids == "[1, 2, 3]"


class TestGetSet:
    """Tests for get_set()."""

    def test_get_existing_set(self, db_session):
        """Get full details of an existing set."""
        plan, tracks = _create_set_with_tracks(db_session, 3)

        detail = get_set(plan.id, db_session)
        assert detail.name == "Test Set"
        assert len(detail.tracks) == 3
        assert detail.tracks[0]["position"] == 1

    def test_get_nonexistent_set(self, db_session):
        """Getting a non-existent set raises error."""
        from backend.exceptions import SetPlanError

        with pytest.raises(SetPlanError):
            get_set(999, db_session)


class TestListSets:
    """Tests for list_sets()."""

    def test_list_empty(self, db_session):
        """List returns empty when no sets exist."""
        result = list_sets(db_session)
        assert result == []

    def test_list_with_sets(self, db_session):
        """List returns all sets with counts."""
        plan1, _ = _create_set_with_tracks(db_session, 3, "Set 1")
        plan2, _ = _create_set_with_tracks(db_session, 5, "Set 2")

        result = list_sets(db_session)
        assert len(result) == 2
        names = {s.name for s in result}
        assert "Set 1" in names
        assert "Set 2" in names


class TestUpdateSet:
    """Tests for update_set()."""

    def test_update_name(self, db_session):
        """Update set name."""
        plan = create_set("Old Name", "Desc", db_session)
        updated = update_set(plan.id, db_session, name="New Name")
        assert updated.name == "New Name"

    def test_update_preserves_unchanged(self, db_session):
        """Update only changes specified fields."""
        plan = create_set("Keep", "Keep Desc", db_session, energy_arc="build")
        update_set(plan.id, db_session, name="Changed")
        refreshed = db_session.query(SetPlan).filter(SetPlan.id == plan.id).first()
        assert refreshed.name == "Changed"
        assert refreshed.description == "Keep Desc"
        assert refreshed.energy_arc == "build"


class TestDeleteSet:
    """Tests for delete_set()."""

    def test_delete_set(self, db_session):
        """Delete a set."""
        plan, _ = _create_set_with_tracks(db_session, 2)
        plan_id = plan.id
        delete_set(plan_id, db_session)

        assert db_session.query(SetPlan).filter(SetPlan.id == plan_id).first() is None

    def test_delete_nonexistent(self, db_session):
        """Delete non-existent set raises error."""
        from backend.exceptions import SetPlanError

        with pytest.raises(SetPlanError):
            delete_set(999, db_session)


class TestLockUnlock:
    """Tests for lock_track() and unlock_track()."""

    def test_lock_track(self, db_session):
        """Lock a track at a position."""
        plan, _ = _create_set_with_tracks(db_session, 3)
        lock_track(plan.id, 2, db_session)

        st = (
            db_session.query(SetTrack)
            .filter(SetTrack.set_id == plan.id, SetTrack.position == 2)
            .first()
        )
        assert st.is_locked is True

    def test_unlock_track(self, db_session):
        """Unlock a previously locked track."""
        plan, _ = _create_set_with_tracks(db_session, 3)
        lock_track(plan.id, 2, db_session)
        unlock_track(plan.id, 2, db_session)

        st = (
            db_session.query(SetTrack)
            .filter(SetTrack.set_id == plan.id, SetTrack.position == 2)
            .first()
        )
        assert st.is_locked is False

    def test_lock_nonexistent_position(self, db_session):
        """Lock at non-existent position raises error."""
        from backend.exceptions import SetPlanError

        plan, _ = _create_set_with_tracks(db_session, 3)
        with pytest.raises(SetPlanError):
            lock_track(plan.id, 99, db_session)


class TestRecalculateSegments:
    """Tests for recalculate_segments()."""

    def test_no_locks_single_segment(self, db_session):
        """No locked tracks → single segment covering all positions."""
        plan, _ = _create_set_with_tracks(db_session, 5)

        segments = (
            db_session.query(SetSegment)
            .filter(SetSegment.set_id == plan.id)
            .order_by(SetSegment.position)
            .all()
        )
        assert len(segments) == 1
        assert segments[0].start_track_position == 1
        assert segments[0].end_track_position == 5

    def test_one_lock_creates_segments(self, db_session):
        """One locked track creates segments around it."""
        plan, _ = _create_set_with_tracks(db_session, 5)
        lock_track(plan.id, 3, db_session)

        segments = (
            db_session.query(SetSegment)
            .filter(SetSegment.set_id == plan.id)
            .order_by(SetSegment.position)
            .all()
        )
        # Should have segments: 1-3 and 3-5
        assert len(segments) == 2
        assert segments[0].start_track_position == 1
        assert segments[0].end_track_position == 3
        assert segments[1].start_track_position == 3
        assert segments[1].end_track_position == 5

    def test_preserve_description_on_unchanged_boundaries(self, db_session):
        """Segment descriptions preserved when boundaries don't change."""
        plan, _ = _create_set_with_tracks(db_session, 5)
        lock_track(plan.id, 3, db_session)

        # Set a description
        segment = (
            db_session.query(SetSegment)
            .filter(SetSegment.set_id == plan.id, SetSegment.position == 1)
            .first()
        )
        update_segment_description(segment.id, "Dark and brooding", db_session)

        # Lock another track that doesn't change first segment boundaries
        # (lock track 5 — adds a segment but doesn't change 1-3)
        lock_track(plan.id, 5, db_session)

        segments = (
            db_session.query(SetSegment)
            .filter(SetSegment.set_id == plan.id)
            .order_by(SetSegment.position)
            .all()
        )

        # First segment (1-3) should still have its description
        first_seg = next(
            (s for s in segments if s.start_track_position == 1 and s.end_track_position == 3),
            None,
        )
        assert first_seg is not None
        assert first_seg.description == "Dark and brooding"

    def test_empty_set_no_segments(self, db_session):
        """Empty set produces no segments."""
        plan = create_set("Empty", "Empty set", db_session)
        segments = recalculate_segments(plan.id, db_session)
        assert len(segments) == 0


class TestUpdateSegmentDescription:
    """Tests for update_segment_description()."""

    def test_update_description(self, db_session):
        """Update a segment's description."""
        plan, _ = _create_set_with_tracks(db_session, 3)

        segments = db_session.query(SetSegment).filter(SetSegment.set_id == plan.id).all()
        assert len(segments) > 0

        updated = update_segment_description(segments[0].id, "Warm and groovy", db_session)
        assert updated.description == "Warm and groovy"

    def test_update_nonexistent_segment(self, db_session):
        """Update non-existent segment raises error."""
        from backend.exceptions import SetPlanError

        with pytest.raises(SetPlanError):
            update_segment_description(999, "Test", db_session)


class TestRemoveTrack:
    """Tests for remove_track()."""

    def test_remove_track_from_sequence(self, db_session):
        """Remove a track moves it to candidates and reindexes."""
        plan, tracks = _create_set_with_tracks(db_session, 4)

        remove_track(plan.id, 2, db_session)

        # Position 2 track is now a candidate
        removed = (
            db_session.query(SetTrack)
            .filter(SetTrack.set_id == plan.id, SetTrack.track_id == tracks[1].id)
            .first()
        )
        assert removed.is_candidate is True

        # Remaining active tracks reindexed
        active = (
            db_session.query(SetTrack)
            .filter(SetTrack.set_id == plan.id, SetTrack.is_candidate.is_(False))
            .order_by(SetTrack.position)
            .all()
        )
        assert len(active) == 3
        assert [a.position for a in active] == [1, 2, 3]


class TestAddTrackAtPosition:
    """Tests for add_track_at_position()."""

    def test_add_new_track(self, db_session):
        """Add a track not currently in the set."""
        plan, _ = _create_set_with_tracks(db_session, 3)
        new_track = _create_track(db_session, title="New Track")

        add_track_at_position(plan.id, new_track.id, 2, db_session)

        active = (
            db_session.query(SetTrack)
            .filter(SetTrack.set_id == plan.id, SetTrack.is_candidate.is_(False))
            .order_by(SetTrack.position)
            .all()
        )
        assert len(active) == 4
        assert active[1].track_id == new_track.id
        assert active[1].position == 2

    def test_add_candidate_track(self, db_session):
        """Add a candidate track to the active sequence."""
        plan, _ = _create_set_with_tracks(db_session, 3)
        candidate_track = _create_track(db_session, title="Candidate")
        db_session.add(
            SetTrack(
                set_id=plan.id,
                track_id=candidate_track.id,
                position=0,
                is_candidate=True,
            )
        )
        db_session.commit()

        add_track_at_position(plan.id, candidate_track.id, 1, db_session)

        st = (
            db_session.query(SetTrack)
            .filter(SetTrack.set_id == plan.id, SetTrack.track_id == candidate_track.id)
            .first()
        )
        assert st.is_candidate is False
        assert st.position == 1


class TestMoveTrack:
    """Tests for move_track()."""

    def test_move_track_down(self, db_session):
        """Move a track to a later position."""
        plan, tracks = _create_set_with_tracks(db_session, 4)

        move_track(plan.id, 1, 3, db_session)

        active = (
            db_session.query(SetTrack)
            .filter(SetTrack.set_id == plan.id, SetTrack.is_candidate.is_(False))
            .order_by(SetTrack.position)
            .all()
        )
        assert active[2].track_id == tracks[0].id  # Track 1 moved to position 3

    def test_move_track_up(self, db_session):
        """Move a track to an earlier position."""
        plan, tracks = _create_set_with_tracks(db_session, 4)

        move_track(plan.id, 4, 1, db_session)

        active = (
            db_session.query(SetTrack)
            .filter(SetTrack.set_id == plan.id, SetTrack.is_candidate.is_(False))
            .order_by(SetTrack.position)
            .all()
        )
        assert active[0].track_id == tracks[3].id  # Track 4 moved to position 1

    def test_move_same_position(self, db_session):
        """Moving to same position is a no-op."""
        plan, _ = _create_set_with_tracks(db_session, 3)
        move_track(plan.id, 2, 2, db_session)  # Should not raise


class TestGetCandidates:
    """Tests for get_candidates()."""

    def test_get_candidates(self, db_session):
        """Get candidate tracks for a set."""
        plan, _ = _create_set_with_tracks(db_session, 3)
        candidate = _create_track(db_session, title="Candidate")
        db_session.add(
            SetTrack(
                set_id=plan.id,
                track_id=candidate.id,
                position=0,
                is_candidate=True,
            )
        )
        db_session.commit()

        candidates = get_candidates(plan.id, db_session)
        assert len(candidates) == 1
        assert candidates[0]["track_id"] == candidate.id
        assert candidates[0]["is_candidate"] is True
