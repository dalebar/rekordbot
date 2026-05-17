"""Tests for analysis pipeline — orchestration, batch processing, and tag writing."""

import shutil
from pathlib import Path

import pytest

from backend.config import Settings
from backend.models.track import Track
from backend.services.analysis import (
    AnalysisQueue,
    analyse_track,
    write_tags_batch,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


@pytest.fixture
def test_settings():
    """Settings with defaults suitable for testing."""
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


class TestAnalyseTrack:
    """Test single-track analysis."""

    async def test_analyse_mp3(self, db_session, test_settings, tmp_audio_dir):
        """Analyse an MP3 file — should populate BPM, key, and analysis_status."""
        track = Track(
            file_path=str(tmp_audio_dir / "silence_320k.mp3"),
            analysis_status="unanalysed",
        )
        db_session.add(track)
        db_session.flush()

        result = await analyse_track(track, db_session, test_settings)

        assert result.status == "success"
        assert result.bpm_result is not None
        assert result.key_result is not None
        assert track.analysis_status == "analysed"
        assert track.bpm is not None
        assert track.key is not None
        assert track.bpm_confidence is not None
        assert track.key_confidence is not None

    async def test_analyse_aiff(self, db_session, test_settings, tmp_audio_dir):
        """Analyse an AIFF file."""
        track = Track(
            file_path=str(tmp_audio_dir / "silence_16bit.aiff"),
            analysis_status="unanalysed",
        )
        db_session.add(track)
        db_session.flush()

        result = await analyse_track(track, db_session, test_settings)
        assert result.status == "success"
        assert track.analysis_status == "analysed"

    async def test_analyse_nonexistent_file(self, db_session, test_settings):
        """Analysing a nonexistent file should fail gracefully."""
        track = Track(
            file_path="/does/not/exist.mp3",
            analysis_status="unanalysed",
        )
        db_session.add(track)
        db_session.flush()

        result = await analyse_track(track, db_session, test_settings)
        assert result.status == "failed"
        assert result.error is not None
        assert track.analysis_status == "failed"

    async def test_analyse_populates_duration(self, db_session, test_settings, tmp_audio_dir):
        """Analysis should populate the duration field."""
        track = Track(
            file_path=str(tmp_audio_dir / "silence_320k.mp3"),
            analysis_status="unanalysed",
        )
        db_session.add(track)
        db_session.flush()

        await analyse_track(track, db_session, test_settings)
        assert track.duration is not None
        assert track.duration > 0


class TestAnalysisQueue:
    """Test batch analysis with concurrency control."""

    async def test_batch_analysis(self, db_session, test_settings, tmp_audio_dir):
        """Batch analysis should process multiple tracks."""
        tracks = []
        for name in ["silence_320k.mp3", "silence_16bit.aiff"]:
            track = Track(
                file_path=str(tmp_audio_dir / name),
                analysis_status="unanalysed",
            )
            db_session.add(track)
            tracks.append(track)
        db_session.flush()

        queue = AnalysisQueue(test_settings)
        result = await queue.analyse_batch(tracks, db_session)

        assert result.total == 2
        assert result.succeeded == 2
        assert result.failed == 0

    async def test_batch_error_isolation(self, db_session, test_settings, tmp_audio_dir):
        """One failed track should not stop the batch."""
        good_track = Track(
            file_path=str(tmp_audio_dir / "silence_320k.mp3"),
            analysis_status="unanalysed",
        )
        bad_track = Track(
            file_path="/does/not/exist.mp3",
            analysis_status="unanalysed",
        )
        db_session.add(good_track)
        db_session.add(bad_track)
        db_session.flush()

        queue = AnalysisQueue(test_settings)
        result = await queue.analyse_batch([good_track, bad_track], db_session)

        assert result.total == 2
        assert result.succeeded == 1
        assert result.failed == 1


class TestWriteTagsBatch:
    """Test batch tag writing."""

    async def test_write_tags_updates_status(self, db_session, test_settings, tmp_audio_dir):
        """Writing tags should update analysis_status to 'tags_written'."""
        track = Track(
            file_path=str(tmp_audio_dir / "silence_320k.mp3"),
            title="Test Song",
            artist="Test Artist",
            bpm=128.0,
            key=16,
            analysis_status="analysed",
        )
        db_session.add(track)
        db_session.flush()

        results = await write_tags_batch([track], db_session)

        assert len(results) == 1
        assert results[0].success
        assert track.analysis_status == "tags_written"
