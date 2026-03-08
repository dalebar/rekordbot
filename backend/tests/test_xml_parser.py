"""Tests for Rekordbox XML parser — written FIRST (TDD)."""

import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from backend.services.xml_parser import (
    ParsedLibrary,
    decode_location,
    parse_bpm,
    parse_playlists,
    parse_rating,
    parse_rekordbox_xml,
    parse_tonality,
    parse_track_element,
    validate_xml_structure,
)

# --- decode_location() tests ---


class TestDecodeLocation:
    """Test Location URI decoding (inverse of location_encoder.py)."""

    def test_simple_path(self):
        uri = "file://localhost/Users/daleb/Music/track.aiff"
        assert decode_location(uri) == "/Users/daleb/Music/track.aiff"

    def test_percent_encoded_spaces(self):
        uri = "file://localhost/Users/daleb/My%20Music/My%20Track.aiff"
        assert decode_location(uri) == "/Users/daleb/My Music/My Track.aiff"

    def test_percent_encoded_special_chars(self):
        uri = "file://localhost/Users/daleb/Music/%23Special%26Track.mp3"
        assert decode_location(uri) == "/Users/daleb/Music/#Special&Track.mp3"

    def test_unicode_characters(self):
        uri = "file://localhost/Users/daleb/Music/Caf%C3%A9.aiff"
        assert decode_location(uri) == "/Users/daleb/Music/Café.aiff"

    def test_deeply_nested_path(self):
        uri = "file://localhost/Volumes/External/DJ/Library/Artist%20Name/Album/01%20Track.aiff"
        assert (
            decode_location(uri) == "/Volumes/External/DJ/Library/Artist Name/Album/01 Track.aiff"
        )

    def test_empty_string_returns_none(self):
        assert decode_location("") is None

    def test_none_returns_none(self):
        assert decode_location(None) is None  # type: ignore[arg-type]

    def test_invalid_prefix_returns_none(self):
        assert decode_location("http://localhost/test.aiff") is None

    def test_no_prefix_returns_none(self):
        assert decode_location("/Users/daleb/Music/track.aiff") is None

    def test_round_trip_with_encoder(self):
        """decode_location(encode_location(path)) should equal path."""
        from backend.services.location_encoder import encode_location

        paths = [
            "/Users/daleb/Music/track.aiff",
            "/Users/daleb/My Music/My Track.aiff",
            "/Volumes/DJ/Library/#1 Hit.mp3",
            "/Users/daleb/Music/Café Vibes.aiff",
        ]
        for path in paths:
            encoded = encode_location(path)
            decoded = decode_location(encoded)
            assert decoded == path, f"Round-trip failed for {path}"


# --- parse_bpm() tests ---


class TestParseBpm:
    """Test BPM string parsing."""

    def test_normal_bpm(self):
        assert parse_bpm("128.00") == 128.0

    def test_decimal_bpm(self):
        assert parse_bpm("174.50") == 174.5

    def test_integer_bpm(self):
        assert parse_bpm("140") == 140.0

    def test_zero_bpm_returns_none(self):
        assert parse_bpm("0.00") is None

    def test_none_returns_none(self):
        assert parse_bpm(None) is None

    def test_empty_string_returns_none(self):
        assert parse_bpm("") is None

    def test_invalid_string_returns_none(self):
        assert parse_bpm("abc") is None

    def test_negative_returns_none(self):
        assert parse_bpm("-128.00") is None


# --- parse_rating() tests ---


class TestParseRating:
    """Test rating scale conversion (non-linear to 0-5)."""

    def test_zero_rating(self):
        assert parse_rating("0") == 0

    def test_one_star(self):
        assert parse_rating("51") == 1

    def test_two_stars(self):
        assert parse_rating("102") == 2

    def test_three_stars(self):
        assert parse_rating("153") == 3

    def test_four_stars(self):
        assert parse_rating("204") == 4

    def test_five_stars(self):
        assert parse_rating("255") == 5

    def test_none_returns_none(self):
        assert parse_rating(None) is None

    def test_empty_returns_none(self):
        assert parse_rating("") is None

    def test_invalid_returns_none(self):
        assert parse_rating("abc") is None

    def test_unrecognised_value_returns_none(self):
        """Values not in the non-linear scale should return None."""
        assert parse_rating("100") is None


# --- parse_tonality() tests ---


class TestParseTonality:
    """Test tonality/key string parsing to internal integer."""

    def test_camelot_notation(self):
        assert parse_tonality("8A") == 15  # A minor

    def test_open_key_notation(self):
        assert parse_tonality("1m") == 15  # A minor

    def test_classical_notation(self):
        assert parse_tonality("A minor") == 15

    def test_classical_abbreviated(self):
        assert parse_tonality("Am") == 15

    def test_major_key(self):
        assert parse_tonality("C major") == 16  # 8B

    def test_flat_key(self):
        assert parse_tonality("Bb major") == 12  # 6B

    def test_sharp_key(self):
        assert parse_tonality("F#m") == 21  # 11A

    def test_none_returns_none(self):
        assert parse_tonality(None) is None

    def test_empty_returns_none(self):
        assert parse_tonality("") is None

    def test_invalid_returns_none(self):
        assert parse_tonality("XYZ") is None


# --- parse_track_element() tests ---


class TestParseTrackElement:
    """Test parsing a single TRACK XML element."""

    def _make_track_element(self, **attrs):
        """Helper to create a TRACK element with given attributes."""
        elem = ET.Element("TRACK")
        for key, value in attrs.items():
            elem.set(key, str(value))
        return elem

    def test_full_track(self):
        """Parse a track with all common attributes."""
        elem = self._make_track_element(
            TrackID="1",
            Name="Test Track",
            Artist="Test Artist",
            Album="Test Album",
            Genre="House",
            AverageBpm="128.00",
            Tonality="8A",
            Rating="204",
            TotalTime="300",
            BitRate="320",
            SampleRate="44100",
            Comments="Great track",
            Label="Test Label",
            Remixer="Test Remixer",
            Composer="Test Composer",
            Grouping="Test Group",
            Year="2024",
            TrackNumber="5",
            DiscNumber="1",
            DateAdded="2024-01-15",
            Mix="Original Mix",
            Colour="0",
            Size="12345678",
            Kind="AIFF File",
            Location="file://localhost/Users/daleb/Music/test.aiff",
        )
        result = parse_track_element(elem)
        assert result is not None
        assert result.location == "/Users/daleb/Music/test.aiff"
        assert result.title == "Test Track"
        assert result.artist == "Test Artist"
        assert result.album == "Test Album"
        assert result.genre == "House"
        assert result.bpm == 128.0
        assert result.key == 15  # 8A = A minor = 15
        assert result.rating == 4  # 204 = 4 stars
        assert result.duration == 300
        assert result.bitrate == 320
        assert result.sample_rate == 44100
        assert result.comment == "Great track"
        assert result.label == "Test Label"
        assert result.remixer == "Test Remixer"
        assert result.composer == "Test Composer"
        assert result.grouping == "Test Group"
        assert result.year == 2024
        assert result.track_number == 5
        assert result.disc_number == 1
        assert result.date_added == "2024-01-15"
        assert result.mix_name == "Original Mix"
        assert result.colour == "0"
        assert result.size == 12345678
        assert result.kind == "AIFF File"

    def test_minimal_track(self):
        """Parse a track with only Location (minimum required)."""
        elem = self._make_track_element(
            TrackID="1",
            Location="file://localhost/Users/daleb/Music/minimal.mp3",
        )
        result = parse_track_element(elem)
        assert result is not None
        assert result.location == "/Users/daleb/Music/minimal.mp3"
        assert result.title is None
        assert result.artist is None
        assert result.bpm is None
        assert result.key is None

    def test_missing_location_returns_none(self):
        """Track without Location should return None."""
        elem = self._make_track_element(
            TrackID="1",
            Name="No Location",
        )
        result = parse_track_element(elem)
        assert result is None

    def test_invalid_location_returns_none(self):
        """Track with unparseable Location should return None."""
        elem = self._make_track_element(
            TrackID="1",
            Location="invalid://path",
        )
        result = parse_track_element(elem)
        assert result is None

    def test_empty_optional_fields(self):
        """Empty optional string fields should be None, not empty strings."""
        elem = self._make_track_element(
            TrackID="1",
            Location="file://localhost/Users/daleb/Music/track.aiff",
            Name="",
            Artist="",
            Genre="",
            Comments="",
        )
        result = parse_track_element(elem)
        assert result is not None
        assert result.title is None
        assert result.artist is None
        assert result.genre is None
        assert result.comment is None

    def test_zero_numeric_fields(self):
        """Zero values for numeric fields should be None."""
        elem = self._make_track_element(
            TrackID="1",
            Location="file://localhost/Users/daleb/Music/track.aiff",
            AverageBpm="0.00",
            Rating="0",
            TotalTime="0",
            Year="0",
            TrackNumber="0",
            DiscNumber="0",
        )
        result = parse_track_element(elem)
        assert result is not None
        assert result.bpm is None
        assert result.rating == 0  # 0 is valid (no rating)
        assert result.duration is None
        assert result.year is None
        assert result.track_number is None
        assert result.disc_number is None

    def test_album_artist_parsed(self):
        """AlbumArtist attribute should be parsed."""
        elem = self._make_track_element(
            TrackID="1",
            Location="file://localhost/Users/daleb/Music/track.aiff",
            AlbumArtist="Various Artists",
        )
        result = parse_track_element(elem)
        assert result is not None
        assert result.album_artist == "Various Artists"


# --- parse_playlists() tests ---


class TestParsePlaylists:
    """Test playlist tree parsing."""

    def _build_playlist_xml(self, xml_str: str) -> ET.Element:
        """Parse an XML string into an Element."""
        return ET.fromstring(xml_str)

    def test_single_playlist(self):
        xml = textwrap.dedent("""\
            <NODE Type="0" Name="ROOT" Count="1">
                <NODE Type="0" Name="rekordbox" Count="1">
                    <NODE Name="My Playlist" Type="1" KeyType="0" Entries="2">
                        <TRACK Key="1"/>
                        <TRACK Key="2"/>
                    </NODE>
                </NODE>
            </NODE>
        """)
        root = self._build_playlist_xml(xml)
        playlists = parse_playlists(root)
        assert len(playlists) == 1
        assert playlists[0].name == "My Playlist"

    def test_nested_folder(self):
        """Folder nodes should prefix the playlist name."""
        xml = textwrap.dedent("""\
            <NODE Type="0" Name="ROOT" Count="1">
                <NODE Type="0" Name="rekordbox" Count="1">
                    <NODE Type="0" Name="My Folder" Count="1">
                        <NODE Name="Deep House" Type="1" KeyType="0" Entries="1">
                            <TRACK Key="1"/>
                        </NODE>
                    </NODE>
                </NODE>
            </NODE>
        """)
        root = self._build_playlist_xml(xml)
        playlists = parse_playlists(root)
        assert len(playlists) == 1
        assert playlists[0].name == "My Folder/Deep House"

    def test_deeply_nested_folders(self):
        """Multiple levels of nesting should all be in the prefix."""
        xml = textwrap.dedent("""\
            <NODE Type="0" Name="ROOT" Count="1">
                <NODE Type="0" Name="rekordbox" Count="1">
                    <NODE Type="0" Name="Genre" Count="1">
                        <NODE Type="0" Name="House" Count="1">
                            <NODE Name="Tech House" Type="1" KeyType="0" Entries="1">
                                <TRACK Key="1"/>
                            </NODE>
                        </NODE>
                    </NODE>
                </NODE>
            </NODE>
        """)
        root = self._build_playlist_xml(xml)
        playlists = parse_playlists(root)
        assert len(playlists) == 1
        assert playlists[0].name == "Genre/House/Tech House"

    def test_root_and_product_excluded_from_prefix(self):
        """ROOT and product name nodes should not appear in the playlist name."""
        xml = textwrap.dedent("""\
            <NODE Type="0" Name="ROOT" Count="1">
                <NODE Type="0" Name="rekordbox" Count="1">
                    <NODE Name="Favourites" Type="1" KeyType="0" Entries="1">
                        <TRACK Key="1"/>
                    </NODE>
                </NODE>
            </NODE>
        """)
        root = self._build_playlist_xml(xml)
        playlists = parse_playlists(root)
        assert len(playlists) == 1
        assert playlists[0].name == "Favourites"

    def test_multiple_playlists(self):
        xml = textwrap.dedent("""\
            <NODE Type="0" Name="ROOT" Count="1">
                <NODE Type="0" Name="rekordbox" Count="2">
                    <NODE Name="Playlist A" Type="1" KeyType="0" Entries="1">
                        <TRACK Key="1"/>
                    </NODE>
                    <NODE Name="Playlist B" Type="1" KeyType="0" Entries="1">
                        <TRACK Key="2"/>
                    </NODE>
                </NODE>
            </NODE>
        """)
        root = self._build_playlist_xml(xml)
        playlists = parse_playlists(root)
        assert len(playlists) == 2
        names = {p.name for p in playlists}
        assert names == {"Playlist A", "Playlist B"}

    def test_empty_playlist(self):
        """Empty playlists should be included."""
        xml = textwrap.dedent("""\
            <NODE Type="0" Name="ROOT" Count="1">
                <NODE Type="0" Name="rekordbox" Count="1">
                    <NODE Name="Empty" Type="1" KeyType="0" Entries="0">
                    </NODE>
                </NODE>
            </NODE>
        """)
        root = self._build_playlist_xml(xml)
        playlists = parse_playlists(root)
        assert len(playlists) == 1
        assert playlists[0].name == "Empty"
        assert playlists[0].track_keys == []

    def test_track_keys_collected(self):
        """Track Key attributes should be collected."""
        xml = textwrap.dedent("""\
            <NODE Type="0" Name="ROOT" Count="1">
                <NODE Type="0" Name="rekordbox" Count="1">
                    <NODE Name="Test" Type="1" KeyType="0" Entries="3">
                        <TRACK Key="5"/>
                        <TRACK Key="12"/>
                        <TRACK Key="3"/>
                    </NODE>
                </NODE>
            </NODE>
        """)
        root = self._build_playlist_xml(xml)
        playlists = parse_playlists(root)
        assert playlists[0].track_keys == [5, 12, 3]


# --- validate_xml_structure() tests ---


class TestValidateXmlStructure:
    """Test XML structure validation."""

    def test_valid_xml(self, tmp_path):
        xml_file = tmp_path / "valid.xml"
        xml_file.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <DJ_PLAYLISTS Version="1.0.0">
                <PRODUCT Name="rekordbox" Version="6.0.0" Company="AlphaTheta"/>
                <COLLECTION Entries="0"/>
                <PLAYLISTS>
                    <NODE Type="0" Name="ROOT" Count="0"/>
                </PLAYLISTS>
            </DJ_PLAYLISTS>
        """)
        )
        valid, msg = validate_xml_structure(xml_file)
        assert valid is True
        assert msg == ""

    def test_missing_root_element(self, tmp_path):
        xml_file = tmp_path / "bad_root.xml"
        xml_file.write_text('<OTHER_ROOT Version="1.0.0"/>')
        valid, msg = validate_xml_structure(xml_file)
        assert valid is False
        assert "DJ_PLAYLISTS" in msg

    def test_missing_collection(self, tmp_path):
        xml_file = tmp_path / "no_collection.xml"
        xml_file.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <DJ_PLAYLISTS Version="1.0.0">
                <PRODUCT Name="rekordbox"/>
                <PLAYLISTS>
                    <NODE Type="0" Name="ROOT" Count="0"/>
                </PLAYLISTS>
            </DJ_PLAYLISTS>
        """)
        )
        valid, msg = validate_xml_structure(xml_file)
        assert valid is False
        assert "COLLECTION" in msg

    def test_missing_playlists(self, tmp_path):
        xml_file = tmp_path / "no_playlists.xml"
        xml_file.write_text(
            textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <DJ_PLAYLISTS Version="1.0.0">
                <PRODUCT Name="rekordbox"/>
                <COLLECTION Entries="0"/>
            </DJ_PLAYLISTS>
        """)
        )
        valid, msg = validate_xml_structure(xml_file)
        assert valid is False
        assert "PLAYLISTS" in msg

    def test_malformed_xml(self, tmp_path):
        xml_file = tmp_path / "malformed.xml"
        xml_file.write_text("this is not xml at all")
        valid, msg = validate_xml_structure(xml_file)
        assert valid is False

    def test_nonexistent_file(self, tmp_path):
        xml_file = tmp_path / "nonexistent.xml"
        valid, msg = validate_xml_structure(xml_file)
        assert valid is False


# --- parse_rekordbox_xml() full integration ---


class TestParseRekordboxXml:
    """Test full XML parsing pipeline."""

    def _write_xml(self, tmp_path: Path, content: str) -> Path:
        xml_file = tmp_path / "library.xml"
        xml_file.write_text(content)
        return xml_file

    def test_full_parse(self, tmp_path):
        """Parse a complete minimal Rekordbox XML."""
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <DJ_PLAYLISTS Version="1.0.0">
                <PRODUCT Name="rekordbox" Version="6.7.4" Company="AlphaTheta"/>
                <COLLECTION Entries="2">
                    <TRACK TrackID="1" Name="Track One" Artist="Artist A"
                           AverageBpm="128.00" Tonality="8A" Rating="204"
                           Location="file://localhost/Users/daleb/Music/one.aiff"
                           TotalTime="300" Genre="House"/>
                    <TRACK TrackID="2" Name="Track Two" Artist="Artist B"
                           AverageBpm="140.00" Tonality="Cm"
                           Location="file://localhost/Users/daleb/Music/two.mp3"
                           TotalTime="240" Genre="Techno"/>
                </COLLECTION>
                <PLAYLISTS>
                    <NODE Type="0" Name="ROOT" Count="1">
                        <NODE Type="0" Name="rekordbox" Count="1">
                            <NODE Name="Test Playlist" Type="1" KeyType="0" Entries="2">
                                <TRACK Key="1"/>
                                <TRACK Key="2"/>
                            </NODE>
                        </NODE>
                    </NODE>
                </PLAYLISTS>
            </DJ_PLAYLISTS>
        """)
        xml_file = self._write_xml(tmp_path, xml_content)
        result = parse_rekordbox_xml(xml_file)

        assert isinstance(result, ParsedLibrary)
        assert result.product_name == "rekordbox"
        assert result.product_version == "6.7.4"
        assert len(result.tracks) == 2
        assert result.tracks[0].title == "Track One"
        assert result.tracks[0].bpm == 128.0
        assert result.tracks[1].title == "Track Two"
        assert len(result.playlists) == 1
        assert result.playlists[0].name == "Test Playlist"

    def test_tracks_without_location_skipped(self, tmp_path):
        """Tracks missing Location should be skipped."""
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <DJ_PLAYLISTS Version="1.0.0">
                <PRODUCT Name="rekordbox" Version="6.0.0"/>
                <COLLECTION Entries="2">
                    <TRACK TrackID="1" Name="Good Track"
                           Location="file://localhost/Users/daleb/Music/good.aiff"/>
                    <TRACK TrackID="2" Name="No Location"/>
                </COLLECTION>
                <PLAYLISTS>
                    <NODE Type="0" Name="ROOT" Count="0"/>
                </PLAYLISTS>
            </DJ_PLAYLISTS>
        """)
        xml_file = self._write_xml(tmp_path, xml_content)
        result = parse_rekordbox_xml(xml_file)
        assert len(result.tracks) == 1
        assert result.tracks[0].title == "Good Track"

    def test_invalid_xml_raises(self, tmp_path):
        """Invalid XML should raise XmlImportError."""
        from backend.exceptions import XmlImportError

        xml_file = self._write_xml(tmp_path, "not valid xml")
        with pytest.raises(XmlImportError):
            parse_rekordbox_xml(xml_file)

    def test_tempo_and_position_mark_ignored(self, tmp_path):
        """TEMPO and POSITION_MARK elements should be silently ignored."""
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <DJ_PLAYLISTS Version="1.0.0">
                <PRODUCT Name="rekordbox" Version="6.0.0"/>
                <COLLECTION Entries="1">
                    <TRACK TrackID="1" Name="With Cues"
                           Location="file://localhost/Users/daleb/Music/cued.aiff">
                        <TEMPO Inizio="0.571" Bpm="128.00" Metro="4/4"/>
                        <POSITION_MARK Name="Cue" Type="0" Start="32.456"/>
                    </TRACK>
                </COLLECTION>
                <PLAYLISTS>
                    <NODE Type="0" Name="ROOT" Count="0"/>
                </PLAYLISTS>
            </DJ_PLAYLISTS>
        """)
        xml_file = self._write_xml(tmp_path, xml_content)
        result = parse_rekordbox_xml(xml_file)
        assert len(result.tracks) == 1
        assert result.tracks[0].title == "With Cues"

    def test_track_id_map_built(self, tmp_path):
        """The parser should build a TrackID → location map for playlist resolution."""
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <DJ_PLAYLISTS Version="1.0.0">
                <PRODUCT Name="rekordbox" Version="6.0.0"/>
                <COLLECTION Entries="2">
                    <TRACK TrackID="42" Name="First"
                           Location="file://localhost/Users/daleb/Music/first.aiff"/>
                    <TRACK TrackID="99" Name="Second"
                           Location="file://localhost/Users/daleb/Music/second.mp3"/>
                </COLLECTION>
                <PLAYLISTS>
                    <NODE Type="0" Name="ROOT" Count="1">
                        <NODE Type="0" Name="rekordbox" Count="1">
                            <NODE Name="Playlist" Type="1" KeyType="0" Entries="2">
                                <TRACK Key="42"/>
                                <TRACK Key="99"/>
                            </NODE>
                        </NODE>
                    </NODE>
                </PLAYLISTS>
            </DJ_PLAYLISTS>
        """)
        xml_file = self._write_xml(tmp_path, xml_content)
        result = parse_rekordbox_xml(xml_file)
        # Playlists should have resolved track_locations from the TrackID map
        assert len(result.playlists) == 1
        assert len(result.playlists[0].track_locations) == 2
        assert "/Users/daleb/Music/first.aiff" in result.playlists[0].track_locations
        assert "/Users/daleb/Music/second.mp3" in result.playlists[0].track_locations
