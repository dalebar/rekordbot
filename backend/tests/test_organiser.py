"""Tests for organisation pipeline — proposal and execution with mocked dependencies."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.organiser import OrganisationProposal, Organiser


def _make_settings(**overrides):
    """Create a mock Settings object."""
    settings = MagicMock()
    settings.output_directory = "/tmp/test_library"
    settings.folder_template = "{artist}/{album}/{title}"
    settings.organise_confidence_threshold = 0.7
    settings.organise_unknown_fallback = "Unsorted"
    settings.anthropic_api_key = ""
    settings.ai_model = "claude-sonnet-4-20250514"
    settings.ai_max_requests_per_minute = 10
    for k, v in overrides.items():
        setattr(settings, k, v)
    return settings


def _make_track(tmp_path: Path, **kwargs):
    """Create a Track-like mock with file on disk."""
    filename = kwargs.pop("filename", "test.aiff")
    file_path = tmp_path / "imports" / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(b"fake audio")

    track = MagicMock()
    track.id = kwargs.get("id", 1)
    track.title = kwargs.get("title", "Test Track")
    track.artist = kwargs.get("artist", "Test Artist")
    track.album = kwargs.get("album", "Test Album")
    track.album_artist = kwargs.get("album_artist")
    track.genre = kwargs.get("genre", "House")
    track.subgenre = kwargs.get("subgenre")
    track.year = kwargs.get("year", 2024)
    track.label = kwargs.get("label")
    track.ai_confidence = kwargs.get("ai_confidence")
    track.output_format = kwargs.get("output_format", "aiff")
    track.source_path = kwargs.get("source_path")
    track.file_path = str(file_path)
    track.proposed_path = None
    track.previous_output_path = None
    track.organisation_status = "unorganised"
    track.organisation_confidence = None
    track.organisation_reasoning = None
    return track


class TestProposeOrganisation:
    """Test the proposal phase of the organisation pipeline."""

    @pytest.mark.asyncio
    async def test_propose_with_full_metadata(self, tmp_path):
        """Track with full metadata gets auto-approved."""
        settings = _make_settings(output_directory=str(tmp_path))
        organiser = Organiser(settings)
        track = _make_track(tmp_path)
        db_session = MagicMock()

        with patch("backend.services.organiser.get_rules_for_track", return_value=[]):
            result = await organiser.propose_organisation([track], db_session)

        assert isinstance(result, OrganisationProposal)
        assert result.total_tracks == 1
        assert result.auto_approved == 1
        assert track.proposed_path is not None
        assert track.organisation_status == "proposed"

    @pytest.mark.asyncio
    async def test_propose_sparse_metadata_needs_review(self, tmp_path):
        """Track with sparse metadata needs review."""
        settings = _make_settings(output_directory=str(tmp_path))
        organiser = Organiser(settings)
        track = _make_track(
            tmp_path,
            artist=None,
            album=None,
            genre=None,
            title="untitled",
        )
        db_session = MagicMock()

        with patch("backend.services.organiser.get_rules_for_track", return_value=[]):
            result = await organiser.propose_organisation([track], db_session)

        assert result.needs_review >= 1
        assert track.organisation_status == "review_needed"

    @pytest.mark.asyncio
    async def test_propose_multiple_tracks(self, tmp_path):
        """Multiple tracks are processed."""
        settings = _make_settings(output_directory=str(tmp_path))
        organiser = Organiser(settings)
        tracks = [
            _make_track(tmp_path, id=1, filename="t1.aiff", artist="A", album="B", title="C"),
            _make_track(tmp_path, id=2, filename="t2.aiff", artist="D", album="E", title="F"),
        ]
        db_session = MagicMock()

        with patch("backend.services.organiser.get_rules_for_track", return_value=[]):
            result = await organiser.propose_organisation(tracks, db_session)

        assert result.total_tracks == 2
        assert result.auto_approved == 2

    @pytest.mark.asyncio
    async def test_propose_cancellation(self, tmp_path):
        """Cancellation stops processing."""
        settings = _make_settings(output_directory=str(tmp_path))
        organiser = Organiser(settings)
        tracks = [_make_track(tmp_path, id=i, filename=f"t{i}.aiff") for i in range(10)]
        db_session = MagicMock()

        # Set cancel event directly on internal event (bypasses clear in propose)
        call_count = 0

        def cancel_after_first(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                organiser._cancel_event.set()
            return []

        with patch(
            "backend.services.organiser.get_rules_for_track",
            side_effect=cancel_after_first,
        ):
            result = await organiser.propose_organisation(tracks, db_session)

        # Should have processed fewer than all 10 tracks
        assert result.auto_approved + result.needs_review + result.failed < 10


class TestExecuteOrganisation:
    """Test the execution phase of the organisation pipeline."""

    @pytest.mark.asyncio
    async def test_execute_moves_files(self, tmp_path):
        """Approved tracks are moved to proposed paths."""
        settings = _make_settings(output_directory=str(tmp_path))
        organiser = Organiser(settings)

        track = _make_track(tmp_path)
        proposed = tmp_path / "Test Artist" / "Test Album" / "Test Track.aiff"
        track.proposed_path = str(proposed)

        db_session = MagicMock()

        result = await organiser.execute_organisation([track], db_session)

        assert result.total_moved == 1
        assert result.failed == 0
        assert proposed.exists()

    @pytest.mark.asyncio
    async def test_execute_no_proposed_path(self, tmp_path):
        """Tracks without proposed_path are skipped."""
        settings = _make_settings(output_directory=str(tmp_path))
        organiser = Organiser(settings)

        track = _make_track(tmp_path)
        track.proposed_path = None

        result = await organiser.execute_organisation([track], MagicMock())

        assert result.total_moved == 0
