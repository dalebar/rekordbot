"""Tests for Crate and CrateTrack models."""

from sqlalchemy.exc import IntegrityError

from backend.models.crate import Crate, CrateTrack
from backend.models.track import Track


class TestCrateModel:
    """Tests for the Crate model."""

    def test_create_crate(self, db_session):
        """Create a crate with required fields."""
        crate = Crate(name="Deep & Dubby", description="Deep minimal house, hypnotic and warm")
        db_session.add(crate)
        db_session.flush()

        assert crate.id is not None
        assert crate.name == "Deep & Dubby"
        assert crate.description == "Deep minimal house, hypnotic and warm"
        assert crate.auto_refresh is False
        assert crate.parsed_criteria is None
        assert crate.created_at is not None
        assert crate.updated_at is not None

    def test_crate_with_parsed_criteria(self, db_session):
        """Crate stores parsed criteria as JSON text."""
        import json

        criteria = {"mood": ["hypnotic"], "bpm_min": 118, "bpm_max": 124}
        crate = Crate(
            name="Test",
            description="Test crate",
            parsed_criteria=json.dumps(criteria),
        )
        db_session.add(crate)
        db_session.flush()

        assert crate.parsed_criteria is not None
        loaded = json.loads(crate.parsed_criteria)
        assert loaded["mood"] == ["hypnotic"]
        assert loaded["bpm_min"] == 118

    def test_crate_repr(self, db_session):
        """Crate repr includes id and name."""
        crate = Crate(name="Peak Time", description="High energy")
        db_session.add(crate)
        db_session.flush()

        assert "Peak Time" in repr(crate)


class TestCrateTrackModel:
    """Tests for the CrateTrack association model."""

    def test_create_crate_track(self, db_session):
        """Create a crate-track association."""
        track = Track(file_path="/test/track.aiff")
        crate = Crate(name="Test", description="Test")
        db_session.add_all([track, crate])
        db_session.flush()

        ct = CrateTrack(crate_id=crate.id, track_id=track.id, assignment_method="ai")
        db_session.add(ct)
        db_session.flush()

        assert ct.id is not None
        assert ct.assignment_method == "ai"
        assert ct.created_at is not None

    def test_unique_constraint(self, db_session):
        """Cannot add same track to same crate twice."""
        track = Track(file_path="/test/unique.aiff")
        crate = Crate(name="Test", description="Test")
        db_session.add_all([track, crate])
        db_session.flush()

        ct1 = CrateTrack(crate_id=crate.id, track_id=track.id, assignment_method="ai")
        db_session.add(ct1)
        db_session.flush()

        ct2 = CrateTrack(crate_id=crate.id, track_id=track.id, assignment_method="manual")
        db_session.add(ct2)
        try:
            db_session.flush()
            raise AssertionError("Should have raised IntegrityError")
        except IntegrityError:
            db_session.rollback()

    def test_track_in_multiple_crates(self, db_session):
        """A track can be in multiple crates (overlapping)."""
        track = Track(file_path="/test/multi.aiff")
        crate1 = Crate(name="Crate 1", description="First")
        crate2 = Crate(name="Crate 2", description="Second")
        db_session.add_all([track, crate1, crate2])
        db_session.flush()

        ct1 = CrateTrack(crate_id=crate1.id, track_id=track.id, assignment_method="ai")
        ct2 = CrateTrack(crate_id=crate2.id, track_id=track.id, assignment_method="ai")
        db_session.add_all([ct1, ct2])
        db_session.flush()

        assert ct1.id is not None
        assert ct2.id is not None

    def test_crate_track_repr(self, db_session):
        """CrateTrack repr includes crate_id, track_id, and method."""
        track = Track(file_path="/test/repr.aiff")
        crate = Crate(name="Test", description="Test")
        db_session.add_all([track, crate])
        db_session.flush()

        ct = CrateTrack(crate_id=crate.id, track_id=track.id, assignment_method="manual")
        db_session.add(ct)
        db_session.flush()

        r = repr(ct)
        assert "manual" in r

    def test_cascade_delete_crate(self, db_session):
        """Deleting a crate cascades to CrateTrack records."""
        track = Track(file_path="/test/cascade.aiff")
        crate = Crate(name="Cascade", description="Test")
        db_session.add_all([track, crate])
        db_session.flush()

        ct = CrateTrack(crate_id=crate.id, track_id=track.id, assignment_method="ai")
        db_session.add(ct)
        db_session.flush()
        crate_id = crate.id

        # Access relationship to ensure it's loaded before delete
        assert len(crate.crate_tracks) == 1
        db_session.delete(crate)
        db_session.flush()
        db_session.expire_all()

        remaining = db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate_id).all()
        assert remaining == []
