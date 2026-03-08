"""Tests for XML schema mapper — TDD, written before implementation."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from backend.services.xml_schema_mapper import (
    TrackXmlResult,
    format_bpm,
    format_date,
    format_kind,
    format_rating,
    get_file_size,
    track_to_xml_attrs,
)


class TestFormatBpm:
    """Tests for BPM formatting."""

    def test_normal_bpm(self) -> None:
        assert format_bpm(128.0) == "128.00"

    def test_fractional_bpm(self) -> None:
        assert format_bpm(174.53) == "174.53"

    def test_none_bpm(self) -> None:
        assert format_bpm(None) == "0.00"

    def test_zero_bpm(self) -> None:
        assert format_bpm(0.0) == "0.00"

    def test_high_precision_bpm(self) -> None:
        assert format_bpm(128.456789) == "128.46"

    def test_integer_bpm(self) -> None:
        assert format_bpm(140.0) == "140.00"


class TestFormatRating:
    """Tests for rating conversion to Rekordbox non-linear scale."""

    def test_rating_0(self) -> None:
        assert format_rating(0) == "0"

    def test_rating_1(self) -> None:
        assert format_rating(1) == "51"

    def test_rating_2(self) -> None:
        assert format_rating(2) == "102"

    def test_rating_3(self) -> None:
        assert format_rating(3) == "153"

    def test_rating_4(self) -> None:
        assert format_rating(4) == "204"

    def test_rating_5(self) -> None:
        assert format_rating(5) == "255"

    def test_rating_none(self) -> None:
        assert format_rating(None) == "0"

    def test_rating_out_of_range(self) -> None:
        assert format_rating(7) == "0"

    def test_rating_negative(self) -> None:
        assert format_rating(-1) == "0"


class TestFormatKind:
    """Tests for file kind derivation from extension."""

    def test_aiff(self) -> None:
        assert format_kind("/path/to/track.aiff") == "AIFF File"

    def test_aif(self) -> None:
        assert format_kind("/path/to/track.aif") == "AIFF File"

    def test_mp3(self) -> None:
        assert format_kind("/path/to/track.mp3") == "MP3 File"

    def test_m4a(self) -> None:
        assert format_kind("/path/to/track.m4a") == "M4A File"

    def test_wav(self) -> None:
        assert format_kind("/path/to/track.wav") == "WAV File"

    def test_flac(self) -> None:
        assert format_kind("/path/to/track.flac") == "FLAC File"

    def test_unknown(self) -> None:
        assert format_kind("/path/to/track.ogg") == "Audio File"

    def test_case_insensitive(self) -> None:
        assert format_kind("/path/to/track.AIFF") == "AIFF File"
        assert format_kind("/path/to/track.Mp3") == "MP3 File"


class TestFormatDate:
    """Tests for date formatting."""

    def test_normal_datetime(self) -> None:
        dt = datetime(2026, 3, 8, 14, 30, 0)
        assert format_date(dt) == "2026-03-08"

    def test_none(self) -> None:
        assert format_date(None) == ""

    def test_date_string(self) -> None:
        """format_date should handle string dates too."""
        assert format_date("2026-03-08") == "2026-03-08"


class TestGetFileSize:
    """Tests for file size reading."""

    def test_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.aiff"
        f.write_bytes(b"x" * 1024)
        assert get_file_size(str(f)) == 1024

    def test_missing_file(self) -> None:
        assert get_file_size("/nonexistent/path/file.aiff") == 0


class TestTrackToXmlAttrs:
    """Tests for full track-to-XML-attribute mapping."""

    def _make_track(self, **overrides):
        """Create a mock track with defaults."""

        class MockTrack:
            id = 1
            file_path = "/library/Calibre/Shelflife 6/Falls to You.aiff"
            title = "Falls to You"
            artist = "Calibre"
            album = "Shelflife 6"
            album_artist = None
            genre = "Drum & Bass"
            composer = None
            remixer = None
            label = "Signature"
            mix_name = None
            grouping = None
            comment = "Great track"
            year = 2020
            track_number = 3
            disc_number = 1
            bpm = 174.0
            key = 15  # 8A / A minor
            rating = 4
            duration = 342.5
            bit_rate = 2116
            sample_rate = 44100
            imported_at = datetime(2026, 3, 1, 10, 0, 0)

        track = MockTrack()
        for k, v in overrides.items():
            setattr(track, k, v)
        return track

    @patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
    @patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
    def test_full_track(self, mock_mtime, mock_size) -> None:
        """Full metadata track produces all expected attributes."""
        track = self._make_track()
        result = track_to_xml_attrs(track, track_id=1, key_notation="camelot")

        assert isinstance(result, TrackXmlResult)
        assert result.attrs["TrackID"] == "1"
        assert result.attrs["Name"] == "Falls to You"
        assert result.attrs["Artist"] == "Calibre"
        assert result.attrs["Album"] == "Shelflife 6"
        assert result.attrs["Genre"] == "Drum & Bass"
        assert result.attrs["Kind"] == "AIFF File"
        assert result.attrs["Size"] == "50000000"
        assert result.attrs["TotalTime"] == "342"
        assert result.attrs["AverageBpm"] == "174.00"
        assert result.attrs["Tonality"] == "8A"
        assert result.attrs["Rating"] == "204"
        assert result.attrs["BitRate"] == "2116"
        assert result.attrs["SampleRate"] == "44100"
        assert result.attrs["DateAdded"] == "2026-03-01"
        assert result.attrs["Label"] == "Signature"
        assert result.attrs["Comments"] == "Great track"
        assert result.attrs["Year"] == "2020"
        assert result.attrs["TrackNumber"] == "3"
        assert result.attrs["DiscNumber"] == "1"
        assert result.attrs["PlayCount"] == "0"
        assert result.attrs["Colour"] == "0"
        assert "Location" in result.attrs
        assert result.attrs["Location"].startswith("file://localhost/")
        assert len(result.warnings) == 0

    @patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
    @patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
    def test_sparse_track_fallbacks(self, mock_mtime, mock_size) -> None:
        """Track with missing metadata uses fallbacks."""
        track = self._make_track(
            title=None,
            artist=None,
            album=None,
            genre=None,
            comment=None,
            bpm=None,
            key=None,
            rating=0,
            duration=None,
            bit_rate=None,
            sample_rate=None,
            imported_at=None,
            year=None,
            track_number=None,
            disc_number=None,
            label=None,
            file_path="/library/unknown_track.aiff",
        )
        result = track_to_xml_attrs(track, track_id=5, key_notation="camelot")

        # Fallbacks
        assert result.attrs["Name"] == "unknown_track"  # filename stem
        assert result.attrs["Artist"] == "Unknown Artist"
        assert result.attrs["Album"] == ""
        assert result.attrs["Genre"] == ""
        assert result.attrs["Comments"] == ""
        assert result.attrs["AverageBpm"] == "0.00"
        assert result.attrs["Tonality"] == ""
        assert result.attrs["Rating"] == "0"
        assert result.attrs["TotalTime"] == "0"
        assert result.attrs["BitRate"] == "0"
        assert result.attrs["SampleRate"] == "0"
        assert result.attrs["DateAdded"] == ""

    @patch("backend.services.xml_schema_mapper.get_file_size", return_value=0)
    @patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="")
    def test_missing_file_warning(self, mock_mtime, mock_size) -> None:
        """Track with missing file generates a warning."""
        track = self._make_track(file_path="/nonexistent/track.aiff")
        result = track_to_xml_attrs(track, track_id=1, key_notation="camelot")

        assert result.attrs["Size"] == "0"
        assert any(
            "file not found" in w.lower() or "size is 0" in w.lower() for w in result.warnings
        )

    @patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
    @patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
    def test_classical_key_notation(self, mock_mtime, mock_size) -> None:
        """Key notation preference is respected."""
        track = self._make_track(key=15)  # 8A = A minor
        result = track_to_xml_attrs(track, track_id=1, key_notation="classical")
        assert result.attrs["Tonality"] == "A minor"

    @patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
    @patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
    def test_open_key_notation(self, mock_mtime, mock_size) -> None:
        track = self._make_track(key=15)  # 8A = 1m in Open Key
        result = track_to_xml_attrs(track, track_id=1, key_notation="open_key")
        assert result.attrs["Tonality"] == "1m"

    @patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
    @patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
    def test_optional_attrs_omitted_when_none(self, mock_mtime, mock_size) -> None:
        """Optional attributes (Composer, Remixer, etc.) are omitted when None."""
        track = self._make_track(
            composer=None, remixer=None, grouping=None, mix_name=None, album_artist=None
        )
        result = track_to_xml_attrs(track, track_id=1, key_notation="camelot")
        assert "Composer" not in result.attrs
        assert "Remixer" not in result.attrs
        assert "Grouping" not in result.attrs
        assert "Mix" not in result.attrs
        assert "AlbumArtist" not in result.attrs

    @patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
    @patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
    def test_optional_attrs_included_when_set(self, mock_mtime, mock_size) -> None:
        """Optional attributes are included when they have values."""
        track = self._make_track(composer="Test Composer", remixer="DJ Remix")
        result = track_to_xml_attrs(track, track_id=1, key_notation="camelot")
        assert result.attrs["Composer"] == "Test Composer"
        assert result.attrs["Remixer"] == "DJ Remix"
