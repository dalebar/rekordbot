"""Tests for tag reader — mutagen-based tag extraction from audio files."""

from pathlib import Path

from backend.services.tag_reader import TagData, parse_track_number, parse_year, read_tags

# Path to test audio fixtures from Phase 1
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


class TestParseTrackNumber:
    """Test TRCK tag parsing (handles 'N/M' format)."""

    def test_simple_integer(self):
        assert parse_track_number("3") == 3

    def test_slash_format(self):
        assert parse_track_number("3/12") == 3

    def test_zero(self):
        assert parse_track_number("0") == 0

    def test_none(self):
        assert parse_track_number(None) is None

    def test_empty_string(self):
        assert parse_track_number("") is None

    def test_non_numeric(self):
        assert parse_track_number("abc") is None

    def test_whitespace(self):
        assert parse_track_number(" 5 ") == 5


class TestParseYear:
    """Test year tag parsing (handles TYER and TDRC formats)."""

    def test_four_digit_year(self):
        assert parse_year("2024") == 2024

    def test_full_date_tdrc(self):
        assert parse_year("2024-03-15") == 2024

    def test_timestamp_format(self):
        assert parse_year("2024-03-15T00:00:00") == 2024

    def test_none(self):
        assert parse_year(None) is None

    def test_empty_string(self):
        assert parse_year("") is None

    def test_non_numeric(self):
        assert parse_year("abc") is None

    def test_two_digit_year(self):
        # Should still parse the first numeric part
        assert parse_year("99") == 99


class TestTagDataDefaults:
    """Test TagData dataclass default values."""

    def test_all_none_by_default(self):
        data = TagData()
        assert data.title is None
        assert data.artist is None
        assert data.album is None
        assert data.genre is None
        assert data.year is None
        assert data.track_number is None
        assert data.comment is None
        assert data.label is None
        assert data.bpm is None
        assert data.key is None
        assert data.rating is None
        assert data.duration is None


class TestReadTagsIntegration:
    """Integration tests using Phase 1 test audio fixtures.

    These fixtures are silence files — they may or may not have tags.
    The key assertion is that read_tags() handles all formats without errors.
    """

    def test_read_aiff_tags(self):
        result = read_tags(FIXTURES_DIR / "silence_16bit.aiff")
        assert isinstance(result, TagData)

    def test_read_mp3_tags(self):
        result = read_tags(FIXTURES_DIR / "silence_320k.mp3")
        assert isinstance(result, TagData)

    def test_read_mp3_low_bitrate_tags(self):
        result = read_tags(FIXTURES_DIR / "silence_128k.mp3")
        assert isinstance(result, TagData)

    def test_read_m4a_aac_tags(self):
        result = read_tags(FIXTURES_DIR / "silence_aac.m4a")
        assert isinstance(result, TagData)

    def test_read_m4a_alac_tags(self):
        result = read_tags(FIXTURES_DIR / "silence_alac.m4a")
        assert isinstance(result, TagData)

    def test_nonexistent_file(self):
        result = read_tags(FIXTURES_DIR / "does_not_exist.mp3")
        assert result is None

    def test_unsupported_format(self):
        result = read_tags(FIXTURES_DIR / "silence_16bit.wav")
        # WAV files don't have ID3 tags — should return None or empty TagData
        # depending on whether mutagen can handle it
        assert result is None or isinstance(result, TagData)

    def test_flac_tags(self):
        result = read_tags(FIXTURES_DIR / "silence_16bit.flac")
        # FLAC uses Vorbis comments, not ID3 — we don't read from FLAC
        # since output files are AIFF/MP3/M4A. Should handle gracefully.
        assert result is None or isinstance(result, TagData)

    def test_duration_populated(self):
        """Test that duration is extracted from audio info."""
        result = read_tags(FIXTURES_DIR / "silence_320k.mp3")
        assert result is not None
        # Test fixtures are short silence files, duration should be positive
        assert result.duration is not None
        assert result.duration > 0
