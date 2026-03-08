"""Tests for file mover — file move operations with collision handling and cleanup."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.services.file_mover import (
    BatchMoveResult,
    cleanup_empty_dirs,
    move_file,
    move_files_batch,
)

# --- Helper ---


def _make_track(tmp_path: Path, filename: str = "test.aiff", **kwargs):
    """Create a mock Track with a real file on disk."""
    file_path = tmp_path / "imports" / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"fake audio content for testing")

    track = MagicMock()
    track.id = kwargs.get("id", 1)
    track.file_path = str(file_path)
    track.proposed_path = None
    track.previous_output_path = None
    track.organisation_status = "proposed"
    return track


def _make_db_session():
    """Create a mock DB session."""
    session = MagicMock()
    return session


# --- move_file() ---


class TestMoveFile:
    """Test single file move operations."""

    @pytest.mark.asyncio
    async def test_move_to_new_location(self, tmp_path):
        """File is moved to the new location."""
        track = _make_track(tmp_path)
        old_path = Path(track.file_path)
        dest = tmp_path / "organised" / "Artist" / "Album" / "Track.aiff"

        result = await move_file(track, dest, _make_db_session())

        assert result.status == "moved"
        assert dest.exists()
        assert not old_path.exists()

    @pytest.mark.asyncio
    async def test_collision_handling(self, tmp_path):
        """Collision applies _1 suffix."""
        track = _make_track(tmp_path)
        dest = tmp_path / "organised" / "Track.aiff"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"existing file")

        result = await move_file(track, dest, _make_db_session())

        assert result.status == "moved"
        assert result.new_path == tmp_path / "organised" / "Track_1.aiff"
        assert result.new_path.exists()

    @pytest.mark.asyncio
    async def test_missing_source(self, tmp_path):
        """Missing source file → graceful failure."""
        track = MagicMock()
        track.id = 1
        track.file_path = str(tmp_path / "nonexistent.aiff")

        result = await move_file(
            track,
            tmp_path / "organised" / "Track.aiff",
            _make_db_session(),
        )

        assert result.status == "failed"
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_db_updated_on_move(self, tmp_path):
        """Track record is updated after successful move."""
        track = _make_track(tmp_path)
        old_path = track.file_path
        dest = tmp_path / "organised" / "Track.aiff"
        session = _make_db_session()

        await move_file(track, dest, session)

        assert track.file_path == str(dest)
        assert track.previous_output_path == old_path
        assert track.organisation_status == "organised"
        assert track.proposed_path is None
        session.flush.assert_called()

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, tmp_path):
        """Parent directories are created automatically."""
        track = _make_track(tmp_path)
        dest = tmp_path / "deep" / "nested" / "path" / "Track.aiff"

        result = await move_file(track, dest, _make_db_session())

        assert result.status == "moved"
        assert dest.exists()


# --- move_files_batch() ---


class TestMoveFilesBatch:
    """Test batch file move operations."""

    @pytest.mark.asyncio
    async def test_batch_move(self, tmp_path):
        """Batch moves multiple files."""
        tracks = []
        moves = []
        for i in range(3):
            track = _make_track(tmp_path, f"track_{i}.aiff", id=i + 1)
            dest = tmp_path / "organised" / f"Track_{i}.aiff"
            tracks.append(track)
            moves.append((track, dest))

        result = await move_files_batch(moves, _make_db_session())

        assert isinstance(result, BatchMoveResult)
        assert result.total == 3
        assert result.moved == 3
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_batch_error_isolation(self, tmp_path):
        """One failure doesn't stop the batch."""
        track1 = _make_track(tmp_path, "good.aiff", id=1)
        track2 = MagicMock()
        track2.id = 2
        track2.file_path = str(tmp_path / "nonexistent.aiff")
        track3 = _make_track(tmp_path, "also_good.aiff", id=3)

        moves = [
            (track1, tmp_path / "organised" / "Good.aiff"),
            (track2, tmp_path / "organised" / "Bad.aiff"),
            (track3, tmp_path / "organised" / "AlsoGood.aiff"),
        ]

        result = await move_files_batch(moves, _make_db_session())

        assert result.moved == 2
        assert result.failed == 1


# --- cleanup_empty_dirs() ---


class TestCleanupEmptyDirs:
    """Test empty directory cleanup."""

    def test_removes_empty_dirs(self, tmp_path):
        """Empty directories are removed."""
        empty_dir = tmp_path / "empty" / "nested"
        empty_dir.mkdir(parents=True)

        removed = cleanup_empty_dirs(tmp_path)

        assert removed == 2  # Both "empty" and "nested"
        assert not (tmp_path / "empty").exists()

    def test_preserves_non_empty_dirs(self, tmp_path):
        """Directories with files are preserved."""
        dir_with_file = tmp_path / "has_file"
        dir_with_file.mkdir()
        (dir_with_file / "file.txt").write_text("content")

        removed = cleanup_empty_dirs(tmp_path)

        assert removed == 0
        assert dir_with_file.exists()

    def test_does_not_remove_base_dir(self, tmp_path):
        """Base directory itself is never removed even if empty."""
        cleanup_empty_dirs(tmp_path)
        assert tmp_path.exists()

    def test_nonexistent_base_dir(self, tmp_path):
        """Non-existent base directory returns 0."""
        removed = cleanup_empty_dirs(tmp_path / "nonexistent")
        assert removed == 0

    def test_mixed_empty_and_nonempty(self, tmp_path):
        """Mix of empty and non-empty directories."""
        (tmp_path / "empty1").mkdir()
        (tmp_path / "keep" / "subdir").mkdir(parents=True)
        (tmp_path / "keep" / "file.txt").write_text("keep")

        removed = cleanup_empty_dirs(tmp_path)

        assert removed >= 1  # At least empty1 removed
        assert (tmp_path / "keep").exists()
        assert not (tmp_path / "empty1").exists()
