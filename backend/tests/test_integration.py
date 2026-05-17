"""Integration tests — end-to-end file processing pipeline."""

from pathlib import Path

from backend.services.converter import convert_file
from backend.services.format_inspector import inspect_file

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


def _fixture(name: str) -> Path:
    """Get path to a test fixture file."""
    path = FIXTURES_DIR / name
    assert path.exists(), f"Fixture not found: {path}"
    return path


# --- Format inspector integration tests (real ffprobe) ---


class TestInspectRealFiles:
    """Test inspect_file with actual audio fixtures."""

    async def test_inspect_wav_16bit(self) -> None:
        info = inspect_file(_fixture("silence_16bit.wav"))
        assert info.codec == "pcm_s16le"
        assert info.bit_depth == 16
        assert info.is_lossless is True
        assert info.sample_rate == 44100
        assert info.channels == 2

    async def test_inspect_wav_24bit(self) -> None:
        info = inspect_file(_fixture("silence_24bit.wav"))
        assert info.codec == "pcm_s24le"
        assert info.bit_depth == 24
        assert info.is_lossless is True

    async def test_inspect_flac(self) -> None:
        info = inspect_file(_fixture("silence_16bit.flac"))
        assert info.codec == "flac"
        assert info.bit_depth == 16
        assert info.is_lossless is True

    async def test_inspect_aiff(self) -> None:
        info = inspect_file(_fixture("silence_16bit.aiff"))
        assert info.codec == "pcm_s16be"
        assert info.bit_depth == 16
        assert info.is_lossless is True

    async def test_inspect_mp3_320k(self) -> None:
        info = inspect_file(_fixture("silence_320k.mp3"))
        assert info.codec == "mp3"
        assert info.is_lossless is False
        assert info.bit_depth is None

    async def test_inspect_mp3_128k(self) -> None:
        info = inspect_file(_fixture("silence_128k.mp3"))
        assert info.codec == "mp3"
        assert info.is_lossless is False

    async def test_inspect_alac(self) -> None:
        info = inspect_file(_fixture("silence_alac.m4a"))
        assert info.codec == "alac"
        assert info.is_lossless is True
        assert info.bit_depth == 16

    async def test_inspect_aac(self) -> None:
        info = inspect_file(_fixture("silence_aac.m4a"))
        assert info.codec == "aac"
        assert info.is_lossless is False


# --- Full conversion pipeline integration tests ---


class TestConvertRealFiles:
    """Test convert_file with actual audio fixtures through the full pipeline."""

    async def test_convert_wav_to_aiff(self, db_session, tmp_path) -> None:
        from backend.config import Settings

        settings = Settings(
            output_directory=str(tmp_path / "output"),
            db_url="sqlite://",
        )
        result = convert_file(_fixture("silence_16bit.wav"), db_session, settings)

        assert result.success is True
        assert result.track is not None
        assert result.action == "convert_to_aiff"
        assert result.track.source_codec == "pcm_s16le"
        assert result.track.output_format == "aiff"
        assert Path(result.track.file_path).exists()
        assert Path(result.track.file_path).suffix == ".aiff"

    async def test_convert_flac_to_aiff(self, db_session, tmp_path) -> None:
        from backend.config import Settings

        settings = Settings(
            output_directory=str(tmp_path / "output"),
            db_url="sqlite://",
        )
        result = convert_file(_fixture("silence_16bit.flac"), db_session, settings)

        assert result.success is True
        assert result.track is not None
        assert result.action == "convert_to_aiff"
        assert result.track.output_format == "aiff"

    async def test_copy_aiff_as_is(self, db_session, tmp_path) -> None:
        from backend.config import Settings

        settings = Settings(
            output_directory=str(tmp_path / "output"),
            db_url="sqlite://",
        )
        result = convert_file(_fixture("silence_16bit.aiff"), db_session, settings)

        assert result.success is True
        assert result.action == "copy_as_is"
        assert result.track is not None
        assert result.track.output_format == "aiff"

    async def test_copy_mp3_as_is(self, db_session, tmp_path) -> None:
        from backend.config import Settings

        settings = Settings(
            output_directory=str(tmp_path / "output"),
            db_url="sqlite://",
        )
        result = convert_file(_fixture("silence_320k.mp3"), db_session, settings)

        assert result.success is True
        assert result.action == "copy_as_is"
        assert result.track is not None
        assert result.track.output_format == "mp3"

    async def test_mp3_low_bitrate_quality_warning(self, db_session, tmp_path) -> None:
        from backend.config import Settings

        settings = Settings(
            output_directory=str(tmp_path / "output"),
            db_url="sqlite://",
        )
        result = convert_file(_fixture("silence_128k.mp3"), db_session, settings)

        assert result.success is True
        assert result.track is not None
        assert result.track.quality_warning is True

    async def test_convert_alac_to_aiff(self, db_session, tmp_path) -> None:
        from backend.config import Settings

        settings = Settings(
            output_directory=str(tmp_path / "output"),
            db_url="sqlite://",
        )
        result = convert_file(_fixture("silence_alac.m4a"), db_session, settings)

        assert result.success is True
        assert result.action == "convert_to_aiff"
        assert result.track is not None
        assert result.track.output_format == "aiff"

    async def test_aac_copy_default(self, db_session, tmp_path) -> None:
        from backend.config import Settings

        settings = Settings(
            output_directory=str(tmp_path / "output"),
            convert_aac_to_mp3=False,
            db_url="sqlite://",
        )
        result = convert_file(_fixture("silence_aac.m4a"), db_session, settings)

        assert result.success is True
        assert result.action == "copy_as_is"
        assert result.track is not None
        assert result.track.output_format == "m4a"

    async def test_aac_convert_to_mp3(self, db_session, tmp_path) -> None:
        from backend.config import Settings

        settings = Settings(
            output_directory=str(tmp_path / "output"),
            convert_aac_to_mp3=True,
            db_url="sqlite://",
        )
        result = convert_file(_fixture("silence_aac.m4a"), db_session, settings)

        assert result.success is True
        assert result.action == "convert_to_mp3"
        assert result.track is not None
        assert result.track.output_format == "mp3"

    async def test_duplicate_detection(self, db_session, tmp_path) -> None:
        from backend.config import Settings

        settings = Settings(
            output_directory=str(tmp_path / "output"),
            db_url="sqlite://",
        )

        # First ingest succeeds
        result1 = convert_file(_fixture("silence_16bit.wav"), db_session, settings)
        assert result1.success is True

        # Second ingest of same file is detected as duplicate
        result2 = convert_file(_fixture("silence_16bit.wav"), db_session, settings)
        assert result2.success is False
        assert result2.duplicate is True
