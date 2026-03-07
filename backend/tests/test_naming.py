"""Tests for output path generation — written first (TDD)."""

from pathlib import Path

from backend.services.naming import generate_output_path


class TestGenerateOutputPath:
    """Tests for generate_output_path()."""

    def test_basic_flac_to_aiff(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "library"
        result = generate_output_path(
            source_path=Path("/music/song.flac"),
            output_dir=output_dir,
            output_format="aiff",
        )
        assert result.name == "song.aiff"
        assert "imports" in str(result)
        assert result.parent.parent.parent == output_dir

    def test_wav_to_aiff(self, tmp_path: Path) -> None:
        result = generate_output_path(
            source_path=Path("/music/track.wav"),
            output_dir=tmp_path,
            output_format="aiff",
        )
        assert result.name == "track.aiff"

    def test_m4a_alac_to_aiff(self, tmp_path: Path) -> None:
        result = generate_output_path(
            source_path=Path("/music/song.m4a"),
            output_dir=tmp_path,
            output_format="aiff",
        )
        assert result.name == "song.aiff"

    def test_m4a_aac_to_mp3(self, tmp_path: Path) -> None:
        result = generate_output_path(
            source_path=Path("/music/song.m4a"),
            output_dir=tmp_path,
            output_format="mp3",
        )
        assert result.name == "song.mp3"

    def test_m4a_aac_copy(self, tmp_path: Path) -> None:
        result = generate_output_path(
            source_path=Path("/music/song.m4a"),
            output_dir=tmp_path,
            output_format="m4a",
        )
        assert result.name == "song.m4a"

    def test_mp3_copy(self, tmp_path: Path) -> None:
        result = generate_output_path(
            source_path=Path("/music/track.mp3"),
            output_dir=tmp_path,
            output_format="mp3",
        )
        assert result.name == "track.mp3"

    def test_aiff_copy(self, tmp_path: Path) -> None:
        result = generate_output_path(
            source_path=Path("/music/track.aiff"),
            output_dir=tmp_path,
            output_format="aiff",
        )
        assert result.name == "track.aiff"

    def test_collision_handling(self, tmp_path: Path) -> None:
        """If output file exists, append _1, _2, etc."""
        result1 = generate_output_path(
            source_path=Path("/music/song.flac"),
            output_dir=tmp_path,
            output_format="aiff",
        )
        # Create the first file so the next one collides
        result1.parent.mkdir(parents=True, exist_ok=True)
        result1.touch()

        result2 = generate_output_path(
            source_path=Path("/music/song.flac"),
            output_dir=tmp_path,
            output_format="aiff",
        )
        assert result2.name == "song_1.aiff"

        # Create that one too
        result2.touch()

        result3 = generate_output_path(
            source_path=Path("/music/song.flac"),
            output_dir=tmp_path,
            output_format="aiff",
        )
        assert result3.name == "song_2.aiff"

    def test_path_with_spaces(self, tmp_path: Path) -> None:
        result = generate_output_path(
            source_path=Path("/music/my cool track.flac"),
            output_dir=tmp_path,
            output_format="aiff",
        )
        assert result.name == "my cool track.aiff"

    def test_path_with_unicode(self, tmp_path: Path) -> None:
        result = generate_output_path(
            source_path=Path("/music/café électronique.wav"),
            output_dir=tmp_path,
            output_format="aiff",
        )
        assert result.name == "café électronique.aiff"

    def test_date_in_path(self, tmp_path: Path) -> None:
        """Output path includes imports/YYYY-MM-DD/ structure."""
        result = generate_output_path(
            source_path=Path("/music/song.flac"),
            output_dir=tmp_path,
            output_format="aiff",
        )
        parts = result.relative_to(tmp_path).parts
        assert parts[0] == "imports"
        # Date part should look like YYYY-MM-DD
        assert len(parts[1]) == 10
        assert parts[1].count("-") == 2

    def test_output_dir_created(self, tmp_path: Path) -> None:
        """Output directory is created if it doesn't exist."""
        output_dir = tmp_path / "nonexistent" / "deep" / "path"
        result = generate_output_path(
            source_path=Path("/music/song.flac"),
            output_dir=output_dir,
            output_format="aiff",
        )
        assert result.parent.exists()
