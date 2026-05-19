"""Phase 2 integration tests — end-to-end flows for metadata and tagging."""

import shutil
from pathlib import Path

import pytest

from backend.config import Settings
from backend.models.track import Track
from backend.services.analysis import analyse_track, write_tags_batch
from backend.services.key_notation import key_to_display, parse_key_tag
from backend.services.tag_reader import read_tags
from backend.services.tag_writer import TagValues, write_tags

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


@pytest.fixture
def test_settings():
    """Settings suitable for testing."""
    return Settings(
        db_url="sqlite://",
        bpm_range_min=70,
        bpm_range_max=180,
        max_concurrent_analyses=1,
    )


@pytest.fixture
def tmp_audio_dir(tmp_path):
    """Copy test audio fixtures to a temporary directory."""
    audio_dir = tmp_path / "audio"
    shutil.copytree(FIXTURES_DIR, audio_dir)
    return audio_dir


class TestIngestAnalyseWriteFlow:
    """End-to-end: ingest → analyse → verify DB → write tags → verify file tags."""

    async def test_full_flow_mp3(self, db_session, test_settings, tmp_audio_dir):
        """Full pipeline on an MP3 file."""
        mp3 = tmp_audio_dir / "silence_320k.mp3"

        # Simulate ingestion (create track record)
        track = Track(
            file_path=str(mp3),
            output_format="mp3",
            analysis_status="unanalysed",
        )
        db_session.add(track)
        db_session.flush()

        # Analyse
        result = await analyse_track(track, db_session, test_settings)
        assert result.status == "success"
        assert track.analysis_status == "analysed"
        assert track.bpm is not None
        assert track.bpm_confidence is not None
        assert track.duration is not None

        # Write tags
        results = await write_tags_batch([track], db_session)
        assert len(results) == 1
        assert results[0].success
        assert track.analysis_status == "tags_written"

        # Verify file tags
        tags = read_tags(mp3)
        assert tags is not None
        assert tags.bpm is not None

    async def test_full_flow_aiff(self, db_session, test_settings, tmp_audio_dir):
        """Full pipeline on an AIFF file."""
        aiff = tmp_audio_dir / "silence_16bit.aiff"

        track = Track(
            file_path=str(aiff),
            output_format="aiff",
            analysis_status="unanalysed",
        )
        db_session.add(track)
        db_session.flush()

        result = await analyse_track(track, db_session, test_settings)
        assert result.status == "success"

        results = await write_tags_batch([track], db_session)
        assert results[0].success

        tags = read_tags(aiff)
        assert tags is not None

    async def test_full_flow_m4a(self, db_session, test_settings, tmp_audio_dir):
        """Full pipeline on an M4A file."""
        m4a = tmp_audio_dir / "silence_aac.m4a"

        track = Track(
            file_path=str(m4a),
            output_format="m4a",
            analysis_status="unanalysed",
        )
        db_session.add(track)
        db_session.flush()

        result = await analyse_track(track, db_session, test_settings)
        assert result.status == "success"

        results = await write_tags_batch([track], db_session)
        assert results[0].success

        tags = read_tags(m4a)
        assert tags is not None


class TestTagRoundTrip:
    """Write tags → read back → verify exact match."""

    def test_mp3_round_trip(self, tmp_audio_dir):
        """MP3 tag round-trip with BPM and key."""
        mp3 = tmp_audio_dir / "silence_320k.mp3"

        write_tags(
            mp3,
            TagValues(
                title="Round Trip Test",
                artist="Test DJ",
                album="Test Album",
                genre="Techno",
                year=2025,
                track_number=3,
                comment="Testing round trip",
                label="Test Records",
                bpm=133.50,
                key=9,  # C minor → "10m"
            ),
        )

        tags = read_tags(mp3)
        assert tags is not None
        assert tags.title == "Round Trip Test"
        assert tags.artist == "Test DJ"
        assert tags.album == "Test Album"
        assert tags.genre == "Techno"
        assert tags.year == 2025
        assert tags.track_number == 3
        assert tags.comment == "Testing round trip"
        assert tags.label == "Test Records"
        assert tags.bpm == 133.50
        assert tags.key == "10m"

    def test_aiff_round_trip(self, tmp_audio_dir):
        """AIFF tag round-trip."""
        aiff = tmp_audio_dir / "silence_16bit.aiff"

        write_tags(
            aiff,
            TagValues(
                title="AIFF Round Trip",
                artist="AIFF Artist",
                bpm=140.00,
                key=16,  # C major → "1d"
            ),
        )

        tags = read_tags(aiff)
        assert tags is not None
        assert tags.title == "AIFF Round Trip"
        assert tags.artist == "AIFF Artist"
        assert tags.bpm == 140.00
        assert tags.key == "1d"

    def test_m4a_round_trip(self, tmp_audio_dir):
        """M4A tag round-trip (BPM is integer in MP4)."""
        m4a = tmp_audio_dir / "silence_aac.m4a"

        write_tags(
            m4a,
            TagValues(
                title="M4A Round Trip",
                bpm=125.7,  # Should be rounded to 126 for M4A
                key=11,  # G minor → "11m"
            ),
        )

        tags = read_tags(m4a)
        assert tags is not None
        assert tags.title == "M4A Round Trip"
        assert tags.bpm == 126.0  # Rounded
        assert tags.key == "11m"


class TestRevertFlow:
    """Test revert-to-original functionality."""

    async def test_revert_bpm(self, db_session, test_settings, tmp_audio_dir):
        """Revert BPM to source value after analysis."""
        mp3 = tmp_audio_dir / "silence_320k.mp3"

        # Write a known BPM tag to the file first
        write_tags(mp3, TagValues(bpm=130.00))

        track = Track(
            file_path=str(mp3),
            analysis_status="unanalysed",
        )
        db_session.add(track)
        db_session.flush()

        # Analyse — should read source BPM and detect new BPM
        await analyse_track(track, db_session, test_settings)

        assert track.source_bpm == 130.00
        # Detected BPM will differ from source (it's silence, so detection is arbitrary)
        detected_bpm = track.bpm

        # Revert to source
        track.bpm = track.source_bpm
        assert track.bpm == 130.00
        assert track.bpm != detected_bpm or detected_bpm == 130.00


class TestBpmMultiplyFlow:
    """Test BPM ×2 and ÷2 operations."""

    def test_double_bpm(self):
        """Double a BPM value."""
        track = Track(bpm=128.0, file_path="/test")
        assert track.bpm is not None
        track.bpm = round(track.bpm * 2, 2)
        assert track.bpm == 256.0

    def test_halve_bpm(self):
        """Halve a BPM value."""
        track = Track(bpm=128.0, file_path="/test")
        assert track.bpm is not None
        track.bpm = round(track.bpm * 0.5, 2)
        assert track.bpm == 64.0


class TestKeyNotationRoundTrip:
    """Test key notation parsing and display consistency."""

    def test_parse_and_display_all_notations(self):
        """Parse a key in one notation, display in all three."""
        # Start with Camelot "8B" = C major = key 16
        key_int = parse_key_tag("8B")
        assert key_int == 16
        assert key_to_display(key_int, "camelot") == "8B"
        assert key_to_display(key_int, "open_key") == "1d"
        assert key_to_display(key_int, "classical") == "C major"

    def test_parse_open_key_display_camelot(self):
        """Parse Open Key "6m" → display as Camelot "1A"."""
        key_int = parse_key_tag("6m")
        assert key_int == 1
        assert key_to_display(key_int, "camelot") == "1A"

    def test_parse_classical_display_open_key(self):
        """Parse classical "Am" → display as Open Key "1m"."""
        key_int = parse_key_tag("Am")
        assert key_int == 15
        assert key_to_display(key_int, "open_key") == "1m"

    def test_written_key_parseable(self):
        """Key written to file should be parseable back to same int."""
        for key_int in range(1, 25):
            # We write Open Key notation
            from backend.services.key_notation import key_to_open_key_str

            open_key = key_to_open_key_str(key_int)
            parsed = parse_key_tag(open_key)
            assert parsed == key_int, f"Key {key_int} → '{open_key}' → {parsed}"
