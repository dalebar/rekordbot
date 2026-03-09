"""Tests for conflict resolver."""

import json

import pytest

from backend.models.track import Track
from backend.services.conflict_resolver import (
    get_pending_conflicts,
    resolve_all_rekordbot,
    resolve_all_rekordbox,
    resolve_conflict,
)


def _make_conflicts(*fields: tuple[str, object, object]) -> str:
    """Build a JSON conflict string from (field, rekordbox_val, rekordbot_val) tuples."""
    return json.dumps(
        [
            {
                "field": f,
                "rekordbox_value": rb_val,
                "rekordbot_value": rbot_val,
                "recommended": "rekordbox",
            }
            for f, rb_val, rbot_val in fields
        ]
    )


class TestGetPendingConflicts:
    """Test loading unresolved conflicts."""

    def test_returns_tracks_with_conflicts(self, db_session):
        track = Track(
            file_path="/test/track1.aiff",
            title="Track One",
            import_conflicts=_make_conflicts(("bpm", 128.0, 127.0)),
        )
        db_session.add(track)
        db_session.flush()

        result = get_pending_conflicts(db_session)
        assert len(result) == 1
        assert result[0]["track_id"] == track.id
        assert len(result[0]["conflicts"]) == 1

    def test_excludes_resolved_tracks(self, db_session):
        track1 = Track(
            file_path="/test/resolved.aiff",
            import_conflicts=None,
        )
        track2 = Track(
            file_path="/test/pending.aiff",
            import_conflicts=_make_conflicts(("genre", "House", "Techno")),
        )
        db_session.add_all([track1, track2])
        db_session.flush()

        result = get_pending_conflicts(db_session)
        assert len(result) == 1
        assert result[0]["track_id"] == track2.id

    def test_returns_empty_when_no_conflicts(self, db_session):
        track = Track(file_path="/test/clean.aiff")
        db_session.add(track)
        db_session.flush()

        result = get_pending_conflicts(db_session)
        assert result == []


class TestResolveConflict:
    """Test per-track, per-field conflict resolution."""

    def test_accept_rekordbox_value(self, db_session):
        """Choosing 'rekordbox' should apply the XML value."""
        track = Track(
            file_path="/test/conflict.aiff",
            bpm=127.0,
            genre="House",
            import_conflicts=_make_conflicts(
                ("bpm", 128.0, 127.0),
                ("genre", "Deep House", "House"),
            ),
        )
        db_session.add(track)
        db_session.flush()

        result = resolve_conflict(
            track.id,
            {"bpm": "rekordbox", "genre": "rekordbox"},
            db_session,
        )
        assert result.bpm == 128.0
        assert result.genre == "Deep House"
        assert result.import_conflicts is None

    def test_keep_rekordbot_value(self, db_session):
        """Choosing 'rekordbot' should keep the existing value."""
        track = Track(
            file_path="/test/keep.aiff",
            bpm=127.0,
            import_conflicts=_make_conflicts(("bpm", 128.0, 127.0)),
        )
        db_session.add(track)
        db_session.flush()

        result = resolve_conflict(
            track.id,
            {"bpm": "rekordbot"},
            db_session,
        )
        assert result.bpm == 127.0
        assert result.import_conflicts is None

    def test_mixed_resolutions(self, db_session):
        """Each field can be resolved independently."""
        track = Track(
            file_path="/test/mixed.aiff",
            bpm=127.0,
            genre="House",
            import_conflicts=_make_conflicts(
                ("bpm", 128.0, 127.0),
                ("genre", "Deep House", "House"),
            ),
        )
        db_session.add(track)
        db_session.flush()

        result = resolve_conflict(
            track.id,
            {"bpm": "rekordbox", "genre": "rekordbot"},
            db_session,
        )
        assert result.bpm == 128.0
        assert result.genre == "House"
        assert result.import_conflicts is None

    def test_nonexistent_track_raises(self, db_session):
        with pytest.raises(ValueError, match="not found"):
            resolve_conflict(99999, {"bpm": "rekordbox"}, db_session)

    def test_no_conflicts_raises(self, db_session):
        track = Track(file_path="/test/no_conflict.aiff")
        db_session.add(track)
        db_session.flush()

        with pytest.raises(ValueError, match="no pending conflicts"):
            resolve_conflict(track.id, {"bpm": "rekordbox"}, db_session)


class TestResolveAllRekordbox:
    """Test bulk resolution with Rekordbox values."""

    def test_applies_all_rekordbox_values(self, db_session):
        track1 = Track(
            file_path="/test/bulk1.aiff",
            bpm=127.0,
            genre="House",
            import_conflicts=_make_conflicts(
                ("bpm", 128.0, 127.0),
                ("genre", "Deep House", "House"),
            ),
        )
        track2 = Track(
            file_path="/test/bulk2.aiff",
            rating=3,
            import_conflicts=_make_conflicts(("rating", 5, 3)),
        )
        db_session.add_all([track1, track2])
        db_session.flush()

        count = resolve_all_rekordbox(db_session)
        assert count == 2
        assert track1.bpm == 128.0
        assert track1.genre == "Deep House"
        assert track1.import_conflicts is None
        assert track2.rating == 5
        assert track2.import_conflicts is None

    def test_returns_zero_when_no_conflicts(self, db_session):
        count = resolve_all_rekordbox(db_session)
        assert count == 0


class TestResolveAllRekordbot:
    """Test bulk resolution keeping rekordbot values."""

    def test_clears_conflicts_without_changing_values(self, db_session):
        track = Track(
            file_path="/test/keep_all.aiff",
            bpm=127.0,
            genre="House",
            import_conflicts=_make_conflicts(
                ("bpm", 128.0, 127.0),
                ("genre", "Deep House", "House"),
            ),
        )
        db_session.add(track)
        db_session.flush()

        count = resolve_all_rekordbot(db_session)
        assert count == 1
        assert track.bpm == 127.0
        assert track.genre == "House"
        assert track.import_conflicts is None
