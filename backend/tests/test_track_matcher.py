"""Tests for track matcher — conflict detection written FIRST (TDD)."""

from backend.models.track import Track
from backend.services.track_matcher import (
    detect_conflicts,
    find_hash_match,
    find_match,
    find_path_match,
)
from backend.services.xml_parser import ParsedTrack

# --- detect_conflicts() tests (TDD — written first) ---


class TestDetectConflicts:
    """Test conflict detection between parsed XML track and existing DB track."""

    def _make_parsed(self, **kwargs: object) -> ParsedTrack:
        defaults: dict[str, object] = {"location": "/test/track.aiff"}
        defaults.update(kwargs)
        return ParsedTrack(**defaults)  # type: ignore[arg-type]

    def _make_track(self, **kwargs) -> Track:
        track = Track(file_path="/test/track.aiff")
        for key, value in kwargs.items():
            setattr(track, key, value)
        return track

    def test_no_conflicts_when_identical(self):
        """No conflicts when all values match."""
        parsed = self._make_parsed(
            title="Track", artist="Artist", bpm=128.0, key=15, rating=4, genre="House"
        )
        existing = self._make_track(
            title="Track", artist="Artist", bpm=128.0, key=15, rating=4, genre="House"
        )
        conflicts = detect_conflicts(parsed, existing)
        assert conflicts == []

    def test_bpm_conflict_above_threshold(self):
        """BPM difference > 0.5 should flag a conflict."""
        parsed = self._make_parsed(bpm=128.0)
        existing = self._make_track(bpm=127.0)
        conflicts = detect_conflicts(parsed, existing)
        bpm_conflicts = [c for c in conflicts if c.field == "bpm"]
        assert len(bpm_conflicts) == 1
        assert bpm_conflicts[0].rekordbox_value == 128.0
        assert bpm_conflicts[0].rekordbot_value == 127.0
        assert bpm_conflicts[0].recommended == "rekordbox"

    def test_bpm_no_conflict_within_threshold(self):
        """BPM difference <= 0.5 should NOT flag a conflict."""
        parsed = self._make_parsed(bpm=128.0)
        existing = self._make_track(bpm=127.6)
        conflicts = detect_conflicts(parsed, existing)
        bpm_conflicts = [c for c in conflicts if c.field == "bpm"]
        assert len(bpm_conflicts) == 0

    def test_key_conflict(self):
        """Different keys should flag a conflict."""
        parsed = self._make_parsed(key=15)  # A minor
        existing = self._make_track(key=9)  # C minor
        conflicts = detect_conflicts(parsed, existing)
        key_conflicts = [c for c in conflicts if c.field == "key"]
        assert len(key_conflicts) == 1
        assert key_conflicts[0].recommended == "rekordbox"

    def test_key_no_conflict_when_same(self):
        parsed = self._make_parsed(key=15)
        existing = self._make_track(key=15)
        conflicts = detect_conflicts(parsed, existing)
        key_conflicts = [c for c in conflicts if c.field == "key"]
        assert len(key_conflicts) == 0

    def test_genre_conflict_with_ai_tagged(self):
        """Genre difference when rekordbot value is AI-generated should flag."""
        parsed = self._make_parsed(genre="Deep House")
        existing = self._make_track(genre="House", ai_status="tagged")
        conflicts = detect_conflicts(parsed, existing)
        genre_conflicts = [c for c in conflicts if c.field == "genre"]
        assert len(genre_conflicts) == 1
        assert genre_conflicts[0].recommended == "rekordbox"

    def test_genre_no_conflict_when_untagged_and_different(self):
        """Genre difference when rekordbot value is NOT AI-generated should still flag."""
        parsed = self._make_parsed(genre="Deep House")
        existing = self._make_track(genre="House", ai_status="untagged")
        conflicts = detect_conflicts(parsed, existing)
        genre_conflicts = [c for c in conflicts if c.field == "genre"]
        assert len(genre_conflicts) == 1

    def test_rating_conflict(self):
        """Different ratings should flag a conflict."""
        parsed = self._make_parsed(rating=5)
        existing = self._make_track(rating=3)
        conflicts = detect_conflicts(parsed, existing)
        rating_conflicts = [c for c in conflicts if c.field == "rating"]
        assert len(rating_conflicts) == 1
        assert rating_conflicts[0].recommended == "rekordbox"

    def test_title_conflict(self):
        """Different titles should flag a conflict."""
        parsed = self._make_parsed(title="New Title")
        existing = self._make_track(title="Old Title")
        conflicts = detect_conflicts(parsed, existing)
        title_conflicts = [c for c in conflicts if c.field == "title"]
        assert len(title_conflicts) == 1

    def test_artist_conflict(self):
        parsed = self._make_parsed(artist="New Artist")
        existing = self._make_track(artist="Old Artist")
        conflicts = detect_conflicts(parsed, existing)
        artist_conflicts = [c for c in conflicts if c.field == "artist"]
        assert len(artist_conflicts) == 1

    def test_album_conflict(self):
        parsed = self._make_parsed(album="New Album")
        existing = self._make_track(album="Old Album")
        conflicts = detect_conflicts(parsed, existing)
        album_conflicts = [c for c in conflicts if c.field == "album"]
        assert len(album_conflicts) == 1

    def test_comment_conflict_both_nonempty(self):
        """Comments conflict only when both sides are non-empty."""
        parsed = self._make_parsed(comment="XML comment")
        existing = self._make_track(comment="DB comment")
        conflicts = detect_conflicts(parsed, existing)
        comment_conflicts = [c for c in conflicts if c.field == "comment"]
        assert len(comment_conflicts) == 1

    def test_comment_no_conflict_one_side_empty(self):
        """No conflict when only one side has a comment — auto-merge."""
        parsed = self._make_parsed(comment="XML comment")
        existing = self._make_track(comment=None)
        conflicts = detect_conflicts(parsed, existing)
        comment_conflicts = [c for c in conflicts if c.field == "comment"]
        assert len(comment_conflicts) == 0

    def test_both_none_no_conflict(self):
        """Both sides None should NOT produce a conflict."""
        parsed = self._make_parsed(bpm=None, key=None, genre=None)
        existing = self._make_track(bpm=None, key=None, genre=None)
        conflicts = detect_conflicts(parsed, existing)
        assert conflicts == []

    def test_one_side_has_value_no_conflict(self):
        """When only one side has a value, auto-merge — no conflict."""
        parsed = self._make_parsed(bpm=128.0, key=15)
        existing = self._make_track(bpm=None, key=None)
        conflicts = detect_conflicts(parsed, existing)
        assert conflicts == []

    def test_one_side_existing_has_value_no_conflict(self):
        """When only existing has a value, no conflict."""
        parsed = self._make_parsed(bpm=None, key=None)
        existing = self._make_track(bpm=128.0, key=15)
        conflicts = detect_conflicts(parsed, existing)
        assert conflicts == []

    def test_multiple_conflicts(self):
        """Multiple fields can have conflicts simultaneously."""
        parsed = self._make_parsed(title="New", artist="New Artist", bpm=140.0, key=9, rating=5)
        existing = self._make_track(title="Old", artist="Old Artist", bpm=128.0, key=15, rating=3)
        conflicts = detect_conflicts(parsed, existing)
        fields = {c.field for c in conflicts}
        assert "title" in fields
        assert "artist" in fields
        assert "bpm" in fields
        assert "key" in fields
        assert "rating" in fields


# --- find_path_match() tests ---


class TestFindPathMatch:
    """Test path-based track matching."""

    def test_exact_path_match(self, db_session):
        """Should find a track with matching file_path."""
        track = Track(file_path="/Users/daleb/Music/track.aiff")
        db_session.add(track)
        db_session.flush()

        result = find_path_match("/Users/daleb/Music/track.aiff", db_session)
        assert result is not None
        assert result.id == track.id

    def test_no_match(self, db_session):
        """Should return None when no path matches."""
        track = Track(file_path="/Users/daleb/Music/other.aiff")
        db_session.add(track)
        db_session.flush()

        result = find_path_match("/Users/daleb/Music/track.aiff", db_session)
        assert result is None


# --- find_hash_match() tests ---


class TestFindHashMatch:
    """Test hash-based track matching."""

    def test_hash_match(self, db_session, tmp_path):
        """Should find a track with matching file hash."""
        # Create a test file
        test_file = tmp_path / "track.aiff"
        test_file.write_bytes(b"test audio content")

        # Compute hash of the file
        from backend.services.converter import compute_file_hash

        file_hash = compute_file_hash(test_file)

        # Create track with that hash
        track = Track(file_path="/original/path.aiff", file_hash=file_hash)
        db_session.add(track)
        db_session.flush()

        result = find_hash_match(str(test_file), db_session)
        assert result is not None
        assert result.id == track.id

    def test_no_hash_match(self, db_session, tmp_path):
        """Should return None when no hash matches."""
        test_file = tmp_path / "track.aiff"
        test_file.write_bytes(b"different content")

        track = Track(file_path="/test/track.aiff", file_hash="abcdef1234567890")
        db_session.add(track)
        db_session.flush()

        result = find_hash_match(str(test_file), db_session)
        assert result is None

    def test_file_not_found_returns_none(self, db_session):
        """Should return None when the file doesn't exist."""
        result = find_hash_match("/nonexistent/path.aiff", db_session)
        assert result is None


# --- find_match() tests ---


class TestFindMatch:
    """Test the full match strategy."""

    def test_path_match_preferred(self, db_session):
        """Path match should be preferred over hash match."""
        track = Track(file_path="/Users/daleb/Music/track.aiff")
        db_session.add(track)
        db_session.flush()

        parsed = ParsedTrack(location="/Users/daleb/Music/track.aiff")
        result = find_match(parsed, db_session)
        assert result.match_type == "path"
        assert result.existing_track is not None
        assert result.existing_track.id == track.id

    def test_new_track_when_no_match(self, db_session):
        """Should return 'new' match type when nothing matches."""
        parsed = ParsedTrack(location="/nonexistent/path.aiff")
        result = find_match(parsed, db_session)
        assert result.match_type == "new"
        assert result.existing_track is None

    def test_hash_match_when_path_differs(self, db_session, tmp_path):
        """Should fall back to hash match when path doesn't match."""
        test_file = tmp_path / "track.aiff"
        test_file.write_bytes(b"matching audio content")

        from backend.services.converter import compute_file_hash

        file_hash = compute_file_hash(test_file)

        track = Track(file_path="/original/different/path.aiff", file_hash=file_hash)
        db_session.add(track)
        db_session.flush()

        parsed = ParsedTrack(location=str(test_file))
        result = find_match(parsed, db_session)
        assert result.match_type == "hash"
        assert result.existing_track is not None
