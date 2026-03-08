"""Tests for crate assigner with mocked Claude client."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.crate import Crate, CrateTrack
from backend.models.track import Track
from backend.services.crate_assigner import CrateAssigner


@pytest.fixture
def settings():
    """Test settings."""
    from backend.config import Settings

    return Settings(
        anthropic_api_key="test-key",
        crate_assignment_batch_size=2,
        default_key_notation="camelot",
    )


@pytest.fixture
def mock_claude_response():
    """Create a mock Claude API response."""

    def _make_response(matching_ids: list[int]):
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "assign_tracks"
        tool_block.input = {
            "matching_track_ids": matching_ids,
            "reasoning": "Test match",
        }

        response = MagicMock()
        response.content = [tool_block]
        response.usage = MagicMock()
        response.usage.input_tokens = 100
        response.usage.output_tokens = 50
        response.model = "test-model"
        return response

    return _make_response


@pytest.fixture
def mock_claude_client(mock_claude_response):
    """Create a mocked ClaudeClient."""
    client = MagicMock()
    client.model = "test-model"
    client.rate_limiter = MagicMock()
    client.rate_limiter.acquire = AsyncMock()
    client._usage = MagicMock()
    client._usage.total_input_tokens = 0
    client._usage.total_output_tokens = 0
    client._usage.total_requests = 0
    client.client = MagicMock()
    return client


class TestCrateAssigner:
    """Tests for CrateAssigner."""

    async def test_assign_tracks_basic(
        self, db_session, settings, mock_claude_client, mock_claude_response
    ):
        """Assign matching tracks to a crate."""
        # Create test data
        track1 = Track(file_path="/test/t1.aiff", title="Track 1", artist="Artist A")
        track2 = Track(file_path="/test/t2.aiff", title="Track 2", artist="Artist B")
        track3 = Track(file_path="/test/t3.aiff", title="Track 3", artist="Artist C")
        crate = Crate(
            name="Test",
            description="Dark techno",
            parsed_criteria=json.dumps({"mood": ["dark"], "genres": ["Techno"]}),
        )
        db_session.add_all([track1, track2, track3, crate])
        db_session.flush()

        # Mock Claude to return track1 and track3 in batch 1, nothing in batch 2
        mock_claude_client.client.messages.create = MagicMock(
            side_effect=[
                mock_claude_response([track1.id, track2.id]),  # batch 1
                mock_claude_response([track3.id]),  # batch 2
            ]
        )

        assigner = CrateAssigner(settings)
        result = await assigner.assign_tracks(
            crate, [track1, track2, track3], db_session, mock_claude_client
        )

        assert result.total_tracks == 3
        assert result.matched == 3
        assert result.total_batches == 2

        # Verify DB records
        assignments = db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate.id).all()
        assert len(assignments) == 3
        assert all(ct.assignment_method == "ai" for ct in assignments)

    async def test_assign_empty_tracks(self, db_session, settings, mock_claude_client):
        """No tracks to assign returns empty result."""
        crate = Crate(name="Empty", description="Nothing here")
        db_session.add(crate)
        db_session.flush()

        assigner = CrateAssigner(settings)
        result = await assigner.assign_tracks(crate, [], db_session, mock_claude_client)

        assert result.total_tracks == 0
        assert result.matched == 0

    async def test_clear_ai_assignments_preserves_manual(self, db_session, settings):
        """clear_ai_assignments removes AI but keeps manual assignments."""
        track1 = Track(file_path="/test/clear1.aiff")
        track2 = Track(file_path="/test/clear2.aiff")
        crate = Crate(name="Test", description="Test")
        db_session.add_all([track1, track2, crate])
        db_session.flush()

        # Add AI and manual assignments
        db_session.add(CrateTrack(crate_id=crate.id, track_id=track1.id, assignment_method="ai"))
        db_session.add(
            CrateTrack(crate_id=crate.id, track_id=track2.id, assignment_method="manual")
        )
        db_session.flush()

        assigner = CrateAssigner(settings)
        cleared = assigner.clear_ai_assignments(crate.id, db_session)

        assert cleared == 1
        remaining = db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate.id).all()
        assert len(remaining) == 1
        assert remaining[0].assignment_method == "manual"

    async def test_assign_skips_existing(
        self, db_session, settings, mock_claude_client, mock_claude_response
    ):
        """Tracks already in the crate are not duplicated."""
        track1 = Track(file_path="/test/skip1.aiff", title="T1", artist="A")
        crate = Crate(name="Test", description="Test")
        db_session.add_all([track1, crate])
        db_session.flush()

        # Pre-existing assignment
        db_session.add(
            CrateTrack(crate_id=crate.id, track_id=track1.id, assignment_method="manual")
        )
        db_session.flush()

        mock_claude_client.client.messages.create = MagicMock(
            return_value=mock_claude_response([track1.id])
        )

        assigner = CrateAssigner(settings)
        result = await assigner.assign_tracks(crate, [track1], db_session, mock_claude_client)

        assert result.matched == 0  # Already existed

    async def test_cancellation(
        self, db_session, settings, mock_claude_client, mock_claude_response
    ):
        """Cancellation stops processing at the next batch."""
        tracks = [
            Track(file_path=f"/test/cancel{i}.aiff", title=f"T{i}", artist="A") for i in range(4)
        ]
        crate = Crate(name="Test", description="Test")
        db_session.add_all(tracks + [crate])
        db_session.flush()

        mock_claude_client.client.messages.create = MagicMock(
            return_value=mock_claude_response([tracks[0].id, tracks[1].id])
        )

        assigner = CrateAssigner(settings)

        # Cancel after first batch by using side_effect to set cancel
        def cancel_after_first(*args, **kwargs):
            assigner.cancel()
            return mock_claude_response([tracks[0].id, tracks[1].id])

        mock_claude_client.client.messages.create = MagicMock(side_effect=cancel_after_first)

        await assigner.assign_tracks(crate, tracks, db_session, mock_claude_client)

        # First batch runs, then cancellation stops before second batch
        assert mock_claude_client.client.messages.create.call_count == 1

    async def test_batch_error_isolation(
        self, db_session, settings, mock_claude_client, mock_claude_response
    ):
        """A failed batch doesn't stop the pipeline."""
        tracks = [
            Track(file_path=f"/test/err{i}.aiff", title=f"T{i}", artist="A") for i in range(4)
        ]
        crate = Crate(name="Test", description="Test")
        db_session.add_all(tracks + [crate])
        db_session.flush()

        # First batch fails, second succeeds
        mock_claude_client.client.messages.create = MagicMock(
            side_effect=[
                Exception("API error"),
                mock_claude_response([tracks[2].id, tracks[3].id]),
            ]
        )

        assigner = CrateAssigner(settings)
        result = await assigner.assign_tracks(crate, tracks, db_session, mock_claude_client)

        assert result.matched == 2
        assert len(result.errors) == 1
        assert "API error" in result.errors[0]
