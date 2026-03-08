"""Tests for tag writer — write → read back → verify round-trip."""

import shutil
from pathlib import Path

import pytest

from backend.exceptions import TagWriteError
from backend.services.tag_reader import read_tags
from backend.services.tag_writer import TagValues, write_tags

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


@pytest.fixture
def tmp_audio_dir(tmp_path):
    """Copy test audio fixtures to a temporary directory for write testing."""
    audio_dir = tmp_path / "audio"
    shutil.copytree(FIXTURES_DIR, audio_dir)
    return audio_dir


class TestWriteTagsAIFF:
    """Test writing ID3v2.3 tags to AIFF files."""

    def test_write_basic_tags(self, tmp_audio_dir):
        """Write and read back basic text tags."""
        aiff = tmp_audio_dir / "silence_16bit.aiff"
        values = TagValues(
            title="Test Title",
            artist="Test Artist",
            album="Test Album",
            genre="House",
            year=2024,
            bpm=128.00,
            key=16,  # C major → "1d" in Open Key
        )
        result = write_tags(aiff, values)
        assert result.success

        # Read back and verify
        tags = read_tags(aiff)
        assert tags is not None
        assert tags.title == "Test Title"
        assert tags.artist == "Test Artist"
        assert tags.album == "Test Album"
        assert tags.genre == "House"
        assert tags.year == 2024
        assert tags.bpm == 128.00
        assert tags.key == "1d"  # Open Key notation

    def test_write_preserves_existing_tags(self, tmp_audio_dir):
        """Writing new tags should not destroy existing unrelated tags."""
        aiff = tmp_audio_dir / "silence_16bit.aiff"

        # Write initial tags
        write_tags(aiff, TagValues(title="Original Title", artist="Original Artist"))

        # Write only BPM — title and artist should be preserved
        write_tags(aiff, TagValues(bpm=130.00))

        tags = read_tags(aiff)
        assert tags is not None
        assert tags.title == "Original Title"
        assert tags.artist == "Original Artist"
        assert tags.bpm == 130.00

    def test_write_comment(self, tmp_audio_dir):
        """Write and read back comment."""
        aiff = tmp_audio_dir / "silence_16bit.aiff"
        write_tags(aiff, TagValues(comment="Test comment"))
        tags = read_tags(aiff)
        assert tags is not None
        assert tags.comment == "Test comment"

    def test_write_label(self, tmp_audio_dir):
        """Write and read back label (publisher)."""
        aiff = tmp_audio_dir / "silence_16bit.aiff"
        write_tags(aiff, TagValues(label="Test Records"))
        tags = read_tags(aiff)
        assert tags is not None
        assert tags.label == "Test Records"


class TestWriteTagsMP3:
    """Test writing ID3v2.3 tags to MP3 files."""

    def test_write_basic_tags(self, tmp_audio_dir):
        """Write and read back basic text tags."""
        mp3 = tmp_audio_dir / "silence_320k.mp3"
        values = TagValues(
            title="MP3 Test",
            artist="MP3 Artist",
            bpm=140.50,
            key=1,  # A♭ minor → "6m" in Open Key
        )
        result = write_tags(mp3, values)
        assert result.success

        tags = read_tags(mp3)
        assert tags is not None
        assert tags.title == "MP3 Test"
        assert tags.artist == "MP3 Artist"
        assert tags.bpm == 140.50
        assert tags.key == "6m"

    def test_write_track_number(self, tmp_audio_dir):
        """Write and read back track number."""
        mp3 = tmp_audio_dir / "silence_320k.mp3"
        write_tags(mp3, TagValues(track_number=5))
        tags = read_tags(mp3)
        assert tags is not None
        assert tags.track_number == 5


class TestWriteTagsM4A:
    """Test writing MP4 atoms to M4A files."""

    def test_write_basic_tags(self, tmp_audio_dir):
        """Write and read back basic MP4 tags."""
        m4a = tmp_audio_dir / "silence_aac.m4a"
        values = TagValues(
            title="M4A Test",
            artist="M4A Artist",
            album="M4A Album",
            bpm=126.00,
            key=11,  # G minor → "11m" in Open Key
        )
        result = write_tags(m4a, values)
        assert result.success

        tags = read_tags(m4a)
        assert tags is not None
        assert tags.title == "M4A Test"
        assert tags.artist == "M4A Artist"
        assert tags.album == "M4A Album"
        # M4A BPM is integer-only
        assert tags.bpm == 126.0
        assert tags.key == "11m"

    def test_m4a_bpm_rounds_to_integer(self, tmp_audio_dir):
        """M4A tmpo atom is integer — BPM should be rounded."""
        m4a = tmp_audio_dir / "silence_aac.m4a"
        write_tags(m4a, TagValues(bpm=127.8))
        tags = read_tags(m4a)
        assert tags is not None
        assert tags.bpm == 128.0  # Rounded to nearest integer

    def test_write_year_and_comment(self, tmp_audio_dir):
        """Write and read back year and comment."""
        m4a = tmp_audio_dir / "silence_aac.m4a"
        write_tags(m4a, TagValues(year=2023, comment="Test M4A comment"))
        tags = read_tags(m4a)
        assert tags is not None
        assert tags.year == 2023
        assert tags.comment == "Test M4A comment"


class TestWriteTagsEdgeCases:
    """Test edge cases and error handling."""

    def test_nonexistent_file_raises(self):
        """Writing to a nonexistent file should raise TagWriteError."""
        with pytest.raises(TagWriteError):
            write_tags(Path("/does/not/exist.mp3"), TagValues(title="Test"))

    def test_unsupported_format_raises(self, tmp_audio_dir):
        """Writing to unsupported format should raise TagWriteError."""
        wav = tmp_audio_dir / "silence_16bit.wav"
        with pytest.raises(TagWriteError):
            write_tags(wav, TagValues(title="Test"))

    def test_empty_values_no_op(self, tmp_audio_dir):
        """Writing with all None values should succeed without changes."""
        mp3 = tmp_audio_dir / "silence_320k.mp3"
        result = write_tags(mp3, TagValues())
        assert result.success
