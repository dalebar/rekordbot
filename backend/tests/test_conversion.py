"""Tests for conversion decision engine — written first (TDD)."""

from pathlib import Path

from backend.services.conversion import decide_conversion
from backend.services.format_inspector import FileInfo


def _make_file_info(
    codec: str,
    is_lossless: bool,
    container: str = "wav",
    bit_depth: int | None = 16,
    bitrate: int = 1411,
) -> FileInfo:
    """Helper to create FileInfo for testing."""
    return FileInfo(
        path=Path("/test/song.wav"),
        container=container,
        codec=codec,
        sample_rate=44100,
        bit_depth=bit_depth,
        bitrate=bitrate,
        duration=180.0,
        channels=2,
        is_lossless=is_lossless,
    )


class TestDecideConversion:
    """Tests for decide_conversion() — every row of the decision table."""

    # --- Lossless → AIFF conversions ---

    def test_wav_16bit_to_aiff(self) -> None:
        info = _make_file_info("pcm_s16le", is_lossless=True, container="wav", bit_depth=16)
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "convert_to_aiff"
        assert action.output_format == "aiff"
        assert action.output_bit_depth == 16
        assert action.quality_warning is False

    def test_wav_24bit_to_aiff(self) -> None:
        info = _make_file_info("pcm_s24le", is_lossless=True, container="wav", bit_depth=24)
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "convert_to_aiff"
        assert action.output_format == "aiff"
        assert action.output_bit_depth == 24

    def test_wav_32bit_float_to_aiff_capped_at_24(self) -> None:
        info = _make_file_info("pcm_f32le", is_lossless=True, container="wav", bit_depth=32)
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "convert_to_aiff"
        assert action.output_format == "aiff"
        assert action.output_bit_depth == 24  # Capped

    def test_wav_32bit_int_to_aiff_capped_at_24(self) -> None:
        info = _make_file_info("pcm_s32le", is_lossless=True, container="wav", bit_depth=32)
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "convert_to_aiff"
        assert action.output_bit_depth == 24

    def test_flac_16bit_to_aiff(self) -> None:
        info = _make_file_info("flac", is_lossless=True, container="flac", bit_depth=16)
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "convert_to_aiff"
        assert action.output_format == "aiff"
        assert action.output_bit_depth == 16

    def test_flac_24bit_to_aiff(self) -> None:
        info = _make_file_info("flac", is_lossless=True, container="flac", bit_depth=24)
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "convert_to_aiff"
        assert action.output_bit_depth == 24

    def test_alac_16bit_to_aiff(self) -> None:
        info = _make_file_info(
            "alac",
            is_lossless=True,
            container="mov,mp4,m4a,3gp,3g2,mj2",
            bit_depth=16,
        )
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "convert_to_aiff"
        assert action.output_format == "aiff"
        assert action.output_bit_depth == 16

    def test_alac_24bit_to_aiff(self) -> None:
        info = _make_file_info(
            "alac",
            is_lossless=True,
            container="mov,mp4,m4a,3gp,3g2,mj2",
            bit_depth=24,
        )
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.output_bit_depth == 24

    # --- AIFF → copy as-is ---

    def test_aiff_16bit_copy(self) -> None:
        info = _make_file_info("pcm_s16be", is_lossless=True, container="aiff", bit_depth=16)
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "copy_as_is"
        assert action.output_format == "aiff"
        assert action.output_bit_depth is None

    def test_aiff_24bit_copy(self) -> None:
        info = _make_file_info("pcm_s24be", is_lossless=True, container="aiff", bit_depth=24)
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "copy_as_is"
        assert action.output_format == "aiff"

    # --- MP3 → copy as-is ---

    def test_mp3_copy(self) -> None:
        info = _make_file_info(
            "mp3",
            is_lossless=False,
            container="mp3",
            bit_depth=None,
            bitrate=320,
        )
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "copy_as_is"
        assert action.output_format == "mp3"
        assert action.quality_warning is False

    def test_mp3_low_bitrate_quality_warning(self) -> None:
        info = _make_file_info(
            "mp3",
            is_lossless=False,
            container="mp3",
            bit_depth=None,
            bitrate=128,
        )
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "copy_as_is"
        assert action.quality_warning is True
        assert "128" in action.warning_detail

    # --- AAC → copy as-is (default) ---

    def test_aac_copy_default(self) -> None:
        info = _make_file_info(
            "aac",
            is_lossless=False,
            container="mov,mp4,m4a,3gp,3g2,mj2",
            bit_depth=None,
            bitrate=256,
        )
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "copy_as_is"
        assert action.output_format == "m4a"
        assert action.quality_warning is False

    # --- AAC → convert to MP3 (opt-in) ---

    def test_aac_convert_to_mp3(self) -> None:
        info = _make_file_info(
            "aac",
            is_lossless=False,
            container="mov,mp4,m4a,3gp,3g2,mj2",
            bit_depth=None,
            bitrate=256,
        )
        action = decide_conversion(info, convert_aac_to_mp3=True)

        assert action.action == "convert_to_mp3"
        assert action.output_format == "mp3"
        assert action.output_bit_depth is None

    def test_aac_low_bitrate_with_convert(self) -> None:
        info = _make_file_info(
            "aac",
            is_lossless=False,
            container="mov,mp4,m4a,3gp,3g2,mj2",
            bit_depth=None,
            bitrate=128,
        )
        action = decide_conversion(info, convert_aac_to_mp3=True)

        assert action.action == "convert_to_mp3"
        assert action.quality_warning is True

    def test_aac_low_bitrate_copy_default(self) -> None:
        info = _make_file_info(
            "aac",
            is_lossless=False,
            container="mov,mp4,m4a,3gp,3g2,mj2",
            bit_depth=None,
            bitrate=128,
        )
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.action == "copy_as_is"
        assert action.quality_warning is True

    # --- Quality warning propagation ---

    def test_lossless_never_gets_quality_warning(self) -> None:
        info = _make_file_info(
            "flac", is_lossless=True, container="flac", bit_depth=16, bitrate=100
        )
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert action.quality_warning is False
        assert action.warning_detail == ""

    # --- Reason is always populated ---

    def test_action_has_reason(self) -> None:
        info = _make_file_info("pcm_s16le", is_lossless=True, container="wav", bit_depth=16)
        action = decide_conversion(info, convert_aac_to_mp3=False)

        assert isinstance(action.reason, str)
        assert len(action.reason) > 0
