"""Tests for converter service — build_ffmpeg_command and compute_file_hash (TDD)."""

import hashlib
from pathlib import Path

from backend.services.conversion import ConversionAction
from backend.services.converter import build_ffmpeg_command, compute_file_hash
from backend.services.format_inspector import FileInfo


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
