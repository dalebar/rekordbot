"""Tests for format inspector — written first (TDD)."""

from pathlib import Path

import pytest

from backend.services.format_inspector import (
    determine_lossless,
    get_quality_warning,
    parse_ffprobe_output,
)

# --- Sample ffprobe JSON outputs for each format ---


def _make_ffprobe_output(
    format_name: str,
    codec_name: str,
    sample_rate: str = "44100",
    bits_per_raw_sample: str | None = None,
    bit_rate: str = "1411000",
    duration: str = "180.5",
    channels: int = 2,
    stream_bit_rate: str | None = None,
) -> dict:
    """Helper to build a realistic ffprobe JSON structure."""
    stream: dict = {
        "codec_type": "audio",
        "codec_name": codec_name,
        "sample_rate": sample_rate,
        "channels": channels,
    }
    if bits_per_raw_sample is not None:
        stream["bits_per_raw_sample"] = bits_per_raw_sample
    if stream_bit_rate is not None:
        stream["bit_rate"] = stream_bit_rate

    return {
        "format": {
            "format_name": format_name,
            "duration": duration,
            "bit_rate": bit_rate,
        },
        "streams": [stream],
    }


# --- parse_ffprobe_output tests ---


class TestParseFFprobeOutput:
    """Tests for parse_ffprobe_output()."""

    def test_wav_16bit(self) -> None:
        data = _make_ffprobe_output("wav", "pcm_s16le", bits_per_raw_sample="16")
        info = parse_ffprobe_output(data, Path("/test/song.wav"))

        assert info.container == "wav"
        assert info.codec == "pcm_s16le"
        assert info.sample_rate == 44100
        assert info.bit_depth == 16
        assert info.bitrate == 1411
        assert info.duration == 180.5
        assert info.channels == 2
        assert info.is_lossless is True

    def test_wav_24bit(self) -> None:
        data = _make_ffprobe_output(
            "wav", "pcm_s24le", bits_per_raw_sample="24", bit_rate="2116800"
        )
        info = parse_ffprobe_output(data, Path("/test/song.wav"))

        assert info.bit_depth == 24
        assert info.codec == "pcm_s24le"
        assert info.is_lossless is True

    def test_flac_16bit(self) -> None:
        data = _make_ffprobe_output("flac", "flac", bits_per_raw_sample="16", bit_rate="900000")
        info = parse_ffprobe_output(data, Path("/test/song.flac"))

        assert info.container == "flac"
        assert info.codec == "flac"
        assert info.bit_depth == 16
        assert info.is_lossless is True

    def test_flac_24bit(self) -> None:
        data = _make_ffprobe_output("flac", "flac", bits_per_raw_sample="24", bit_rate="1800000")
        info = parse_ffprobe_output(data, Path("/test/song.flac"))

        assert info.bit_depth == 24
        assert info.is_lossless is True

    def test_alac_in_m4a(self) -> None:
        data = _make_ffprobe_output(
            "mov,mp4,m4a,3gp,3g2,mj2", "alac", bits_per_raw_sample="16", bit_rate="900000"
        )
        info = parse_ffprobe_output(data, Path("/test/song.m4a"))

        assert info.container == "mov,mp4,m4a,3gp,3g2,mj2"
        assert info.codec == "alac"
        assert info.bit_depth == 16
        assert info.is_lossless is True

    def test_aac_in_m4a(self) -> None:
        data = _make_ffprobe_output("mov,mp4,m4a,3gp,3g2,mj2", "aac", bit_rate="256000")
        info = parse_ffprobe_output(data, Path("/test/song.m4a"))

        assert info.codec == "aac"
        assert info.bit_depth is None
        assert info.bitrate == 256
        assert info.is_lossless is False

    def test_mp3(self) -> None:
        data = _make_ffprobe_output("mp3", "mp3", bit_rate="320000")
        info = parse_ffprobe_output(data, Path("/test/song.mp3"))

        assert info.container == "mp3"
        assert info.codec == "mp3"
        assert info.bitrate == 320
        assert info.bit_depth is None
        assert info.is_lossless is False

    def test_aiff_16bit(self) -> None:
        data = _make_ffprobe_output("aiff", "pcm_s16be", bits_per_raw_sample="16")
        info = parse_ffprobe_output(data, Path("/test/song.aiff"))

        assert info.container == "aiff"
        assert info.codec == "pcm_s16be"
        assert info.bit_depth == 16
        assert info.is_lossless is True

    def test_aiff_24bit(self) -> None:
        data = _make_ffprobe_output(
            "aiff", "pcm_s24be", bits_per_raw_sample="24", bit_rate="2116800"
        )
        info = parse_ffprobe_output(data, Path("/test/song.aiff"))

        assert info.bit_depth == 24
        assert info.codec == "pcm_s24be"
        assert info.is_lossless is True

    def test_no_audio_stream(self) -> None:
        data = {
            "format": {"format_name": "mp4", "duration": "60.0", "bit_rate": "500000"},
            "streams": [{"codec_type": "video", "codec_name": "h264"}],
        }
        with pytest.raises(ValueError, match="No audio stream"):
            parse_ffprobe_output(data, Path("/test/video.mp4"))

    def test_no_streams(self) -> None:
        data = {
            "format": {"format_name": "unknown", "duration": "0", "bit_rate": "0"},
            "streams": [],
        }
        with pytest.raises(ValueError, match="No audio stream"):
            parse_ffprobe_output(data, Path("/test/corrupt.bin"))

    def test_multi_stream_takes_first_audio(self) -> None:
        """When multiple streams exist, take the first audio stream."""
        data = {
            "format": {"format_name": "mp4", "duration": "180.0", "bit_rate": "1500000"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264"},
                {
                    "codec_type": "audio",
                    "codec_name": "aac",
                    "sample_rate": "48000",
                    "channels": 2,
                    "bit_rate": "256000",
                },
                {
                    "codec_type": "audio",
                    "codec_name": "ac3",
                    "sample_rate": "44100",
                    "channels": 6,
                    "bit_rate": "640000",
                },
            ],
        }
        info = parse_ffprobe_output(data, Path("/test/movie.mp4"))

        assert info.codec == "aac"
        assert info.sample_rate == 48000
        assert info.channels == 2

    def test_bitrate_from_stream_when_format_missing(self) -> None:
        """Fall back to stream-level bit_rate when format-level is missing."""
        data = _make_ffprobe_output(
            "flac",
            "flac",
            bits_per_raw_sample="16",
            bit_rate="0",
            stream_bit_rate="900000",
        )
        info = parse_ffprobe_output(data, Path("/test/song.flac"))
        assert info.bitrate == 900

    def test_bitrate_from_stream_when_format_is_n_a(self) -> None:
        """Fall back to stream-level bit_rate when format-level is 'N/A'."""
        stream: dict = {
            "codec_type": "audio",
            "codec_name": "flac",
            "sample_rate": "44100",
            "channels": 2,
            "bits_per_raw_sample": "16",
            "bit_rate": "900000",
        }
        data = {
            "format": {"format_name": "flac", "duration": "180.0", "bit_rate": "N/A"},
            "streams": [stream],
        }
        info = parse_ffprobe_output(data, Path("/test/song.flac"))
        assert info.bitrate == 900


# --- determine_lossless tests ---


class TestDetermineLossless:
    """Tests for determine_lossless()."""

    @pytest.mark.parametrize(
        "codec",
        [
            "pcm_s16le",
            "pcm_s24le",
            "pcm_s32le",
            "pcm_s16be",
            "pcm_s24be",
            "pcm_s32be",
            "pcm_f32le",
            "pcm_f32be",
            "pcm_f64le",
            "flac",
            "alac",
        ],
    )
    def test_lossless_codecs(self, codec: str) -> None:
        assert determine_lossless(codec) is True

    @pytest.mark.parametrize("codec", ["mp3", "aac", "vorbis", "opus", "ac3", "wma"])
    def test_lossy_codecs(self, codec: str) -> None:
        assert determine_lossless(codec) is False

    def test_unknown_codec_is_lossy(self) -> None:
        assert determine_lossless("unknown_codec") is False


# --- get_quality_warning tests ---


class TestGetQualityWarning:
    """Tests for get_quality_warning()."""

    def test_lossy_below_threshold_warns(self) -> None:
        has_warning, message = get_quality_warning(191, is_lossless=False)
        assert has_warning is True
        assert "191" in message

    def test_lossy_at_threshold_no_warning(self) -> None:
        has_warning, message = get_quality_warning(192, is_lossless=False)
        assert has_warning is False
        assert message == ""

    def test_lossy_above_threshold_no_warning(self) -> None:
        has_warning, message = get_quality_warning(320, is_lossless=False)
        assert has_warning is False
        assert message == ""

    def test_lossless_low_bitrate_no_warning(self) -> None:
        """Lossless files never get quality warnings regardless of bitrate."""
        has_warning, message = get_quality_warning(100, is_lossless=True)
        assert has_warning is False
        assert message == ""

    def test_lossless_zero_bitrate_no_warning(self) -> None:
        has_warning, message = get_quality_warning(0, is_lossless=True)
        assert has_warning is False
        assert message == ""
