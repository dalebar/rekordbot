"""Tests for converter service — build_ffmpeg_command, compute_file_hash, orphan handling."""

import hashlib
from pathlib import Path

from backend.config import Settings
from backend.models.crate import Crate, CrateTrack
from backend.models.set_plan import SetPlan, SetTrack
from backend.models.track import Track
from backend.services.conversion import ConversionAction
from backend.services.converter import build_ffmpeg_command, compute_file_hash, convert_file
from backend.services.format_inspector import FileInfo

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


def _make_file_info(
    codec: str = "pcm_s16le",
    bit_depth: int | None = 16,
    container: str = "wav",
    is_lossless: bool = True,
) -> FileInfo:
    """Helper to create FileInfo for testing."""
    return FileInfo(
        path=Path("/test/song.wav"),
        container=container,
        codec=codec,
        sample_rate=44100,
        bit_depth=bit_depth,
        bitrate=1411,
        duration=180.0,
        channels=2,
        is_lossless=is_lossless,
    )


class TestBuildFFmpegCommand:
    """Tests for build_ffmpeg_command()."""

    def test_16bit_lossless_to_aiff(self) -> None:
        action = ConversionAction(
            action="convert_to_aiff",
            reason="test",
            output_format="aiff",
            output_bit_depth=16,
            quality_warning=False,
            warning_detail="",
        )
        info = _make_file_info(codec="pcm_s16le", bit_depth=16)
        cmd = build_ffmpeg_command(Path("/in/song.wav"), Path("/out/song.aiff"), action, info)
        assert cmd == [
            "ffmpeg",
            "-y",
            "-i",
            "/in/song.wav",
            "-c:a",
            "pcm_s16be",
            "-f",
            "aiff",
            "-write_id3v2",
            "1",
            "/out/song.aiff",
        ]

    def test_24bit_lossless_to_aiff(self) -> None:
        action = ConversionAction(
            action="convert_to_aiff",
            reason="test",
            output_format="aiff",
            output_bit_depth=24,
            quality_warning=False,
            warning_detail="",
        )
        info = _make_file_info(codec="pcm_s24le", bit_depth=24)
        cmd = build_ffmpeg_command(Path("/in/song.wav"), Path("/out/song.aiff"), action, info)
        assert cmd == [
            "ffmpeg",
            "-y",
            "-i",
            "/in/song.wav",
            "-c:a",
            "pcm_s24be",
            "-f",
            "aiff",
            "-write_id3v2",
            "1",
            "/out/song.aiff",
        ]

    def test_32bit_float_to_aiff_capped(self) -> None:
        action = ConversionAction(
            action="convert_to_aiff",
            reason="test",
            output_format="aiff",
            output_bit_depth=24,  # Already capped by decision engine
            quality_warning=False,
            warning_detail="",
        )
        info = _make_file_info(codec="pcm_f32le", bit_depth=32)
        cmd = build_ffmpeg_command(Path("/in/song.wav"), Path("/out/song.aiff"), action, info)
        assert cmd == [
            "ffmpeg",
            "-y",
            "-i",
            "/in/song.wav",
            "-c:a",
            "pcm_s24be",
            "-f",
            "aiff",
            "-write_id3v2",
            "1",
            "/out/song.aiff",
        ]

    def test_aac_to_mp3(self) -> None:
        action = ConversionAction(
            action="convert_to_mp3",
            reason="test",
            output_format="mp3",
            output_bit_depth=None,
            quality_warning=False,
            warning_detail="",
        )
        info = _make_file_info(codec="aac", bit_depth=None, is_lossless=False)
        cmd = build_ffmpeg_command(Path("/in/song.m4a"), Path("/out/song.mp3"), action, info)
        assert cmd == [
            "ffmpeg",
            "-y",
            "-i",
            "/in/song.m4a",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "0",
            "/out/song.mp3",
        ]

    def test_flac_to_aiff_16bit(self) -> None:
        action = ConversionAction(
            action="convert_to_aiff",
            reason="test",
            output_format="aiff",
            output_bit_depth=16,
            quality_warning=False,
            warning_detail="",
        )
        info = _make_file_info(codec="flac", bit_depth=16, container="flac")
        cmd = build_ffmpeg_command(Path("/in/song.flac"), Path("/out/song.aiff"), action, info)
        assert cmd == [
            "ffmpeg",
            "-y",
            "-i",
            "/in/song.flac",
            "-c:a",
            "pcm_s16be",
            "-f",
            "aiff",
            "-write_id3v2",
            "1",
            "/out/song.aiff",
        ]

    def test_aiff_conversion_includes_write_id3v2_flag(self) -> None:
        """AIFF conversion must include -write_id3v2 1 to preserve metadata tags."""
        action = ConversionAction(
            action="convert_to_aiff",
            reason="test",
            output_format="aiff",
            output_bit_depth=16,
            quality_warning=False,
            warning_detail="",
        )
        info = _make_file_info(codec="pcm_s16le", bit_depth=16)
        cmd = build_ffmpeg_command(Path("/in/song.wav"), Path("/out/song.aiff"), action, info)
        id3v2_idx = cmd.index("-write_id3v2")
        assert cmd[id3v2_idx + 1] == "1"
        # Flag must appear before the output path (last element)
        assert id3v2_idx < len(cmd) - 1


class TestComputeFileHash:
    """Tests for compute_file_hash()."""

    def test_hash_known_content(self, tmp_path: Path) -> None:
        """Hash of known content matches expected SHA-256."""
        test_file = tmp_path / "test.bin"
        content = b"hello rekordbot"
        test_file.write_bytes(content)

        expected = hashlib.sha256(content).hexdigest()
        result = compute_file_hash(test_file)
        assert result == expected

    def test_hash_is_stable(self, tmp_path: Path) -> None:
        """Same file produces same hash on repeated calls."""
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"consistent content")

        hash1 = compute_file_hash(test_file)
        hash2 = compute_file_hash(test_file)
        assert hash1 == hash2

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        file1 = tmp_path / "a.bin"
        file2 = tmp_path / "b.bin"
        file1.write_bytes(b"content a")
        file2.write_bytes(b"content b")

        assert compute_file_hash(file1) != compute_file_hash(file2)


class TestDuplicateDetectionOrphanHandling:
    """Tests for duplicate detection with missing file handling in convert_file()."""

    async def test_duplicate_with_existing_file_returns_duplicate(
        self, db_session, tmp_path: Path
    ) -> None:
        """When a duplicate is found and the matched file still exists, return duplicate."""
        fixture = FIXTURES_DIR / "silence_320k.mp3"
        file_hash = compute_file_hash(fixture)

        # Create an existing track with matching hash whose file exists on disk
        output_file = tmp_path / "output" / "existing.mp3"
        output_file.parent.mkdir(parents=True)
        output_file.write_bytes(b"existing track data")

        existing_track = Track(
            file_path=str(output_file),
            file_hash=file_hash,
            conversion_status="complete",
        )
        db_session.add(existing_track)
        db_session.commit()

        settings = Settings(output_directory=str(tmp_path / "new_output"), db_url="sqlite://")
        result = convert_file(fixture, db_session, settings)

        assert result.success is False
        assert result.duplicate is True
        # Original track should still exist in DB
        assert db_session.query(Track).filter_by(file_hash=file_hash).first() is not None

    async def test_duplicate_with_missing_file_cleans_orphan_and_continues(
        self, db_session, tmp_path: Path
    ) -> None:
        """When a duplicate is found but the matched file is missing, clean up and continue."""
        fixture = FIXTURES_DIR / "silence_320k.mp3"
        file_hash = compute_file_hash(fixture)

        # Create an orphaned track — file_path points to a non-existent file
        orphan = Track(
            file_path=str(tmp_path / "deleted" / "gone.mp3"),
            file_hash=file_hash,
            conversion_status="complete",
        )
        orphan_path = str(tmp_path / "deleted" / "gone.mp3")
        db_session.add(orphan)
        db_session.commit()

        settings = Settings(output_directory=str(tmp_path / "output"), db_url="sqlite://")
        result = convert_file(fixture, db_session, settings)

        # Processing should continue and succeed
        assert result.success is True
        assert result.duplicate is False
        assert result.track is not None
        assert result.track.file_hash == file_hash

        # Orphaned record should be gone — only the new track should have this hash
        tracks_with_hash = db_session.query(Track).filter_by(file_hash=file_hash).all()
        assert len(tracks_with_hash) == 1
        assert tracks_with_hash[0].file_path != orphan_path

    async def test_orphan_with_crate_and_set_associations_cascades(
        self, db_session, tmp_path: Path
    ) -> None:
        """When an orphaned track has CrateTrack/SetTrack rows, they are also cleaned up."""
        fixture = FIXTURES_DIR / "silence_320k.mp3"
        file_hash = compute_file_hash(fixture)

        # Create orphaned track
        orphan = Track(
            file_path=str(tmp_path / "deleted" / "gone.mp3"),
            file_hash=file_hash,
            conversion_status="complete",
        )
        db_session.add(orphan)
        db_session.commit()
        orphan_id = orphan.id

        # Create a crate with this track
        crate = Crate(name="Test Crate", description="test")
        db_session.add(crate)
        db_session.commit()
        crate_track = CrateTrack(crate_id=crate.id, track_id=orphan_id, assignment_method="ai")
        db_session.add(crate_track)
        db_session.commit()

        # Create a set with this track
        set_plan = SetPlan(name="Test Set", description="test")
        db_session.add(set_plan)
        db_session.commit()
        set_track = SetTrack(set_id=set_plan.id, track_id=orphan_id, position=1)
        db_session.add(set_track)
        db_session.commit()

        settings = Settings(output_directory=str(tmp_path / "output"), db_url="sqlite://")
        result = convert_file(fixture, db_session, settings)

        # Processing should succeed
        assert result.success is True
        assert result.track is not None

        # Orphan record should be replaced — only the new track should have this hash
        tracks_with_hash = db_session.query(Track).filter_by(file_hash=file_hash).all()
        assert len(tracks_with_hash) == 1
        new_track = tracks_with_hash[0]
        assert new_track.file_path != str(tmp_path / "deleted" / "gone.mp3")

        # CrateTrack/SetTrack rows for the orphan should be cleaned up
        assert db_session.query(CrateTrack).filter_by(track_id=orphan_id).first() is None
        assert db_session.query(SetTrack).filter_by(track_id=orphan_id).first() is None

        # Crate and set themselves should still exist
        assert db_session.query(Crate).filter_by(id=crate.id).first() is not None
        assert db_session.query(SetPlan).filter_by(id=set_plan.id).first() is not None
