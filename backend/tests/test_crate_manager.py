"""Tests for crate manager — CRUD and orchestration."""

import pytest

from backend.exceptions import CrateError
from backend.models.crate import Crate, CrateTrack
from backend.models.track import Track
from backend.services.crate_manager import (
    add_tracks,
    create_crate,
    delete_crate,
    get_crate,
    list_crates,
    remove_tracks,
    update_crate,
)


class TestListCrates:
    """Tests for list_crates()."""

    def test_empty_list(self, db_session):
        """No crates returns empty list."""
        result = list_crates(db_session)
        assert result == []

    def test_with_crates(self, db_session):
        """Lists crates with track counts."""
        crate1 = Crate(name="Crate 1", description="First")
        crate2 = Crate(name="Crate 2", description="Second")
        track = Track(file_path="/test/list.aiff")
        db_session.add_all([crate1, crate2, track])
        db_session.flush()

        db_session.add(CrateTrack(crate_id=crate1.id, track_id=track.id, assignment_method="ai"))
        db_session.flush()

        result = list_crates(db_session)
        assert len(result) == 2
        c1 = next(c for c in result if c.name == "Crate 1")
        c2 = next(c for c in result if c.name == "Crate 2")
        assert c1.track_count == 1
        assert c2.track_count == 0


class TestGetCrate:
    """Tests for get_crate()."""

    def test_found(self, db_session):
        """Get existing crate with track list."""
        track = Track(file_path="/test/get.aiff")
        crate = Crate(name="Test", description="Desc")
        db_session.add_all([track, crate])
        db_session.flush()

        db_session.add(CrateTrack(crate_id=crate.id, track_id=track.id, assignment_method="ai"))
        db_session.flush()

        result = get_crate(crate.id, db_session)
        assert result.name == "Test"
        assert result.track_ids == [track.id]
        assert result.track_count == 1

    def test_not_found(self, db_session):
        """Non-existent crate raises CrateError."""
        with pytest.raises(CrateError):
            get_crate(9999, db_session)


class TestCreateCrate:
    """Tests for create_crate()."""

    def test_create(self, db_session):
        """Create a crate with name and description."""
        crate = create_crate("Deep Dubby", "Deep minimal house", False, db_session)
        assert crate.id is not None
        assert crate.name == "Deep Dubby"
        assert crate.auto_refresh is False


class TestUpdateCrate:
    """Tests for update_crate()."""

    def test_update_name_only(self, db_session):
        """Updating name doesn't flag description change."""
        crate = Crate(name="Old", description="Desc")
        db_session.add(crate)
        db_session.flush()

        updated, changed = update_crate(crate.id, db_session, name="New")
        assert updated.name == "New"
        assert changed is False

    def test_update_description(self, db_session):
        """Updating description flags description change."""
        crate = Crate(name="Test", description="Old desc")
        db_session.add(crate)
        db_session.flush()

        updated, changed = update_crate(crate.id, db_session, description="New desc")
        assert updated.description == "New desc"
        assert changed is True

    def test_same_description_no_change(self, db_session):
        """Setting same description doesn't flag change."""
        crate = Crate(name="Test", description="Same")
        db_session.add(crate)
        db_session.flush()

        _, changed = update_crate(crate.id, db_session, description="Same")
        assert changed is False

    def test_not_found(self, db_session):
        """Non-existent crate raises CrateError."""
        with pytest.raises(CrateError):
            update_crate(9999, db_session, name="X")


class TestDeleteCrate:
    """Tests for delete_crate()."""

    def test_delete(self, db_session):
        """Delete a crate."""
        crate = Crate(name="Delete Me", description="Test")
        db_session.add(crate)
        db_session.flush()
        crate_id = crate.id

        delete_crate(crate_id, db_session)
        assert db_session.query(Crate).filter(Crate.id == crate_id).first() is None

    def test_not_found(self, db_session):
        """Non-existent crate raises CrateError."""
        with pytest.raises(CrateError):
            delete_crate(9999, db_session)


class TestAddTracks:
    """Tests for add_tracks()."""

    def test_add_new_tracks(self, db_session):
        """Add tracks to a crate manually."""
        track1 = Track(file_path="/test/add1.aiff")
        track2 = Track(file_path="/test/add2.aiff")
        crate = Crate(name="Test", description="Test")
        db_session.add_all([track1, track2, crate])
        db_session.flush()

        added = add_tracks(crate.id, [track1.id, track2.id], db_session)
        assert added == 2

        assignments = db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate.id).all()
        assert all(ct.assignment_method == "manual" for ct in assignments)

    def test_add_existing_skipped(self, db_session):
        """Already-present tracks are not duplicated."""
        track = Track(file_path="/test/addskip.aiff")
        crate = Crate(name="Test", description="Test")
        db_session.add_all([track, crate])
        db_session.flush()

        db_session.add(CrateTrack(crate_id=crate.id, track_id=track.id, assignment_method="ai"))
        db_session.flush()

        added = add_tracks(crate.id, [track.id], db_session)
        assert added == 0

    def test_not_found(self, db_session):
        """Non-existent crate raises CrateError."""
        with pytest.raises(CrateError):
            add_tracks(9999, [1], db_session)


class TestRemoveTracks:
    """Tests for remove_tracks()."""

    def test_remove_tracks(self, db_session):
        """Remove tracks from a crate."""
        track1 = Track(file_path="/test/rm1.aiff")
        track2 = Track(file_path="/test/rm2.aiff")
        crate = Crate(name="Test", description="Test")
        db_session.add_all([track1, track2, crate])
        db_session.flush()

        db_session.add(CrateTrack(crate_id=crate.id, track_id=track1.id, assignment_method="ai"))
        db_session.add(
            CrateTrack(crate_id=crate.id, track_id=track2.id, assignment_method="manual")
        )
        db_session.flush()

        removed = remove_tracks(crate.id, [track1.id], db_session)
        assert removed == 1

        remaining = db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate.id).all()
        assert len(remaining) == 1
        assert remaining[0].track_id == track2.id

    def test_not_found(self, db_session):
        """Non-existent crate raises CrateError."""
        with pytest.raises(CrateError):
            remove_tracks(9999, [1], db_session)
