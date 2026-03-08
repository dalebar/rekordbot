"""Tests for SetPlan, SetTrack, and SetSegment models."""

import pytest
from sqlalchemy.exc import IntegrityError

from backend.models.set_plan import SetPlan, SetSegment, SetTrack
from backend.models.track import Track


class TestSetPlanModel:
    """Tests for the SetPlan model."""

    def test_create_set_plan(self, db_session):
        """Create a set plan with all fields."""
        plan = SetPlan(
            name="Friday Warm-Up",
            description="Deep and groovy warm-up set",
            duration_minutes=60,
            target_bpm_start=120.0,
            target_bpm_end=126.0,
            energy_arc="slow build",
            source_type="library",
            harmonic_mixing=True,
            status="draft",
        )
        db_session.add(plan)
        db_session.flush()

        assert plan.id is not None
        assert plan.name == "Friday Warm-Up"
        assert plan.description == "Deep and groovy warm-up set"
        assert plan.duration_minutes == 60
        assert plan.target_bpm_start == 120.0
        assert plan.target_bpm_end == 126.0
        assert plan.energy_arc == "slow build"
        assert plan.source_type == "library"
        assert plan.harmonic_mixing is True
        assert plan.status == "draft"
        assert plan.created_at is not None

    def test_create_set_plan_minimal(self, db_session):
        """Create a set plan with only required fields."""
        plan = SetPlan(name="Quick Set", description="Just a test")
        db_session.add(plan)
        db_session.flush()

        assert plan.id is not None
        assert plan.duration_minutes is None
        assert plan.target_bpm_start is None
        assert plan.target_bpm_end is None
        assert plan.energy_arc is None
        assert plan.source_crate_ids is None
        assert plan.harmonic_mixing is False
        assert plan.status == "draft"

    def test_set_plan_with_source_crates(self, db_session):
        """Source crate IDs stored as JSON text."""
        plan = SetPlan(
            name="Crate Set",
            description="From crates",
            source_type="crates",
            source_crate_ids="[1, 2, 3]",
        )
        db_session.add(plan)
        db_session.flush()

        assert plan.source_crate_ids == "[1, 2, 3]"
        assert plan.source_type == "crates"


class TestSetTrackModel:
    """Tests for the SetTrack model."""

    def test_create_set_track(self, db_session):
        """Create a set track linking a plan to a track."""
        track = Track(file_path="/test/track.aiff", title="Test Track")
        db_session.add(track)
        db_session.flush()

        plan = SetPlan(name="Test Set", description="Testing")
        db_session.add(plan)
        db_session.flush()

        st = SetTrack(set_id=plan.id, track_id=track.id, position=1)
        db_session.add(st)
        db_session.flush()

        assert st.id is not None
        assert st.set_id == plan.id
        assert st.track_id == track.id
        assert st.position == 1
        assert st.is_locked is False
        assert st.is_candidate is False

    def test_unique_constraint_set_track(self, db_session):
        """Cannot add the same track to a set twice."""
        track = Track(file_path="/test/dup.aiff", title="Dup")
        db_session.add(track)
        db_session.flush()

        plan = SetPlan(name="Dup Set", description="Testing dups")
        db_session.add(plan)
        db_session.flush()

        st1 = SetTrack(set_id=plan.id, track_id=track.id, position=1)
        db_session.add(st1)
        db_session.flush()

        st2 = SetTrack(set_id=plan.id, track_id=track.id, position=2)
        db_session.add(st2)
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_cascade_delete_set_tracks(self, db_session):
        """Deleting a set plan cascades to its set tracks."""
        track = Track(file_path="/test/cascade.aiff", title="Cascade")
        db_session.add(track)
        db_session.flush()

        plan = SetPlan(name="Cascade Set", description="Testing cascade")
        db_session.add(plan)
        db_session.flush()

        st = SetTrack(set_id=plan.id, track_id=track.id, position=1)
        db_session.add(st)
        db_session.flush()

        plan_id = plan.id
        # Load relationship to trigger ORM cascade
        assert len(plan.set_tracks) == 1
        db_session.delete(plan)
        db_session.flush()
        db_session.expire_all()

        remaining = db_session.query(SetTrack).filter(SetTrack.set_id == plan_id).all()
        assert len(remaining) == 0

    def test_set_track_references_track(self, db_session):
        """SetTrack FK correctly references a track."""
        track = Track(file_path="/test/ref.aiff", title="Ref")
        db_session.add(track)
        db_session.flush()

        plan = SetPlan(name="Ref Set", description="Testing")
        db_session.add(plan)
        db_session.flush()

        st = SetTrack(set_id=plan.id, track_id=track.id, position=1)
        db_session.add(st)
        db_session.flush()

        loaded = db_session.query(SetTrack).filter(SetTrack.track_id == track.id).first()
        assert loaded is not None
        assert loaded.set_id == plan.id

    def test_locked_and_candidate_flags(self, db_session):
        """Set track lock and candidate flags."""
        track = Track(file_path="/test/flags.aiff", title="Flags")
        db_session.add(track)
        db_session.flush()

        plan = SetPlan(name="Flag Set", description="Testing flags")
        db_session.add(plan)
        db_session.flush()

        st = SetTrack(
            set_id=plan.id,
            track_id=track.id,
            position=0,
            is_locked=True,
            is_candidate=True,
        )
        db_session.add(st)
        db_session.flush()

        assert st.is_locked is True
        assert st.is_candidate is True


class TestSetSegmentModel:
    """Tests for the SetSegment model."""

    def test_create_segment(self, db_session):
        """Create a set segment."""
        plan = SetPlan(name="Seg Set", description="Testing segments")
        db_session.add(plan)
        db_session.flush()

        seg = SetSegment(
            set_id=plan.id,
            position=1,
            description="Dark and aggressive",
            start_track_position=1,
            end_track_position=5,
        )
        db_session.add(seg)
        db_session.flush()

        assert seg.id is not None
        assert seg.set_id == plan.id
        assert seg.position == 1
        assert seg.description == "Dark and aggressive"
        assert seg.start_track_position == 1
        assert seg.end_track_position == 5

    def test_cascade_delete_segments(self, db_session):
        """Deleting a set plan cascades to segments."""
        plan = SetPlan(name="Seg Cascade", description="Testing")
        db_session.add(plan)
        db_session.flush()

        seg = SetSegment(set_id=plan.id, position=1, start_track_position=1, end_track_position=3)
        db_session.add(seg)
        db_session.flush()

        plan_id = plan.id
        # Load relationship to trigger ORM cascade
        assert len(plan.set_segments) == 1
        db_session.delete(plan)
        db_session.flush()
        db_session.expire_all()

        remaining = db_session.query(SetSegment).filter(SetSegment.set_id == plan_id).all()
        assert len(remaining) == 0

    def test_segment_with_null_description(self, db_session):
        """Segment can have null description (user fills in later)."""
        plan = SetPlan(name="Null Desc", description="Testing")
        db_session.add(plan)
        db_session.flush()

        seg = SetSegment(set_id=plan.id, position=1, start_track_position=1, end_track_position=3)
        db_session.add(seg)
        db_session.flush()

        assert seg.description is None
