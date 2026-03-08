"""Tests for the AI tagger pipeline with mocked Claude client."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.config import Settings
from backend.models.track import Track
from backend.services.ai_tagger import AiTagger
from backend.services.claude_client import ClaudeResponse
from backend.services.prompt_builder import AiTagResult


def _make_settings(**overrides: object) -> Settings:
    """Create a Settings instance with test defaults."""
    defaults = {
        "anthropic_api_key": "sk-test-key",
        "ai_model": "claude-sonnet-4-20250514",
        "ai_batch_size": 20,
        "ai_max_requests_per_minute": 10,
        "default_key_notation": "camelot",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _make_claude_response(
    results: list[AiTagResult],
    input_tokens: int = 1000,
    output_tokens: int = 500,
) -> ClaudeResponse:
    """Create a ClaudeResponse for testing."""
    return ClaudeResponse(
        results=results,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model="claude-sonnet-4-20250514",
        request_duration=0.5,
    )


class TestAiTaggerPipeline:
    """Tests for the AiTagger pipeline orchestration."""

    @patch("backend.services.ai_tagger.ClaudeClient")
    async def test_basic_pipeline(self, mock_client_cls, db_session):
        """Pipeline tags tracks and updates DB."""
        # Set up tracks
        track1 = Track(
            file_path="/music/track1.aiff",
            title="Track One",
            artist="Artist A",
            genre="Electronic",
        )
        track2 = Track(
            file_path="/music/track2.aiff",
            title="Track Two",
            artist="Artist B",
        )
        db_session.add_all([track1, track2])
        db_session.flush()

        # Mock Claude client
        mock_client = MagicMock()
        mock_client.tag_batch = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.tag_batch.return_value = _make_claude_response(
            [
                AiTagResult(
                    track_id=track1.id,
                    genre="Tech House",
                    subgenre="",
                    mood="Groovy",
                    energy=7,
                    confidence="high",
                    reasoning="Classic tech house.",
                ),
                AiTagResult(
                    track_id=track2.id,
                    genre="Melodic Techno",
                    subgenre="Progressive Techno",
                    mood="Hypnotic",
                    energy=8,
                    confidence="medium",
                    reasoning="BPM suggests techno.",
                ),
            ]
        )
        mock_client.get_token_usage.return_value = SimpleNamespace(estimated_cost_usd=0.01)

        # Run pipeline
        settings = _make_settings()
        tagger = AiTagger(settings)
        result = await tagger.tag_tracks([track1, track2], db_session)

        assert result.succeeded == 2
        assert result.failed == 0
        assert result.total_tracks == 2

        # Verify DB updates
        assert track1.genre == "Tech House"
        assert track1.mood == "Groovy"
        assert track1.energy == 7
        assert track1.ai_confidence == "high"
        assert track1.ai_status == "ai_tagged"

        assert track2.genre == "Melodic Techno"
        assert track2.subgenre == "Progressive Techno"
        assert track2.ai_status == "ai_tagged"

    @patch("backend.services.ai_tagger.ClaudeClient")
    async def test_source_genre_preservation(self, mock_client_cls, db_session):
        """Existing genre is preserved in source_genre."""
        track = Track(
            file_path="/music/preserve.aiff",
            title="Preserve Test",
            artist="Artist",
            genre="Drum & Bass",
        )
        db_session.add(track)
        db_session.flush()

        mock_client = MagicMock()
        mock_client.tag_batch = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.tag_batch.return_value = _make_claude_response(
            [
                AiTagResult(
                    track_id=track.id,
                    genre="Liquid DnB",
                    subgenre="",
                    mood="Euphoric",
                    energy=7,
                    confidence="high",
                    reasoning="Liquid style.",
                ),
            ]
        )
        mock_client.get_token_usage.return_value = SimpleNamespace(estimated_cost_usd=0.01)

        tagger = AiTagger(_make_settings())
        await tagger.tag_tracks([track], db_session)

        assert track.source_genre == "Drum & Bass"
        assert track.genre == "Liquid DnB"

    @patch("backend.services.ai_tagger.ClaudeClient")
    async def test_no_source_genre_when_none(self, mock_client_cls, db_session):
        """source_genre stays None when there was no existing genre."""
        track = Track(
            file_path="/music/no-genre.aiff",
            title="No Genre",
            artist="Artist",
        )
        db_session.add(track)
        db_session.flush()

        mock_client = MagicMock()
        mock_client.tag_batch = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.tag_batch.return_value = _make_claude_response(
            [
                AiTagResult(
                    track_id=track.id,
                    genre="House",
                    subgenre="",
                    mood="Warm",
                    energy=5,
                    confidence="low",
                    reasoning="Guess.",
                ),
            ]
        )
        mock_client.get_token_usage.return_value = SimpleNamespace(estimated_cost_usd=0.01)

        tagger = AiTagger(_make_settings())
        await tagger.tag_tracks([track], db_session)

        assert track.source_genre is None
        assert track.genre == "House"

    @patch("backend.services.ai_tagger.ClaudeClient")
    async def test_source_genre_not_overwritten_on_retag(self, mock_client_cls, db_session):
        """Re-tagging doesn't overwrite source_genre."""
        track = Track(
            file_path="/music/retag.aiff",
            title="Retag Test",
            artist="Artist",
            genre="Original Genre",
            source_genre="Original Genre",
            ai_status="ai_tagged",
        )
        db_session.add(track)
        db_session.flush()

        mock_client = MagicMock()
        mock_client.tag_batch = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.tag_batch.return_value = _make_claude_response(
            [
                AiTagResult(
                    track_id=track.id,
                    genre="New Genre",
                    subgenre="",
                    mood="Dark",
                    energy=8,
                    confidence="high",
                    reasoning="Re-tagged.",
                ),
            ]
        )
        mock_client.get_token_usage.return_value = SimpleNamespace(estimated_cost_usd=0.01)

        tagger = AiTagger(_make_settings())
        await tagger.tag_tracks([track], db_session)

        assert track.source_genre == "Original Genre"
        assert track.genre == "New Genre"

    @patch("backend.services.ai_tagger.ClaudeClient")
    async def test_batch_error_isolation(self, mock_client_cls, db_session):
        """One batch failing doesn't stop the pipeline."""
        tracks = [
            Track(
                file_path=f"/music/batch-err-{i}.aiff",
                title=f"Track {i}",
                artist="Artist",
            )
            for i in range(3)
        ]
        db_session.add_all(tracks)
        db_session.flush()

        mock_client = MagicMock()
        mock_client.tag_batch = AsyncMock()
        mock_client_cls.return_value = mock_client

        # First call fails, second succeeds
        mock_client.tag_batch.side_effect = [
            Exception("API error"),
            _make_claude_response(
                [
                    AiTagResult(
                        track_id=tracks[2].id,
                        genre="House",
                        subgenre="",
                        mood="Warm",
                        energy=5,
                        confidence="high",
                        reasoning="Good.",
                    ),
                ]
            ),
        ]
        mock_client.get_token_usage.return_value = SimpleNamespace(estimated_cost_usd=0.01)

        tagger = AiTagger(_make_settings(ai_batch_size=2))
        result = await tagger.tag_tracks(tracks, db_session)

        # First batch (2 tracks) failed, second batch (1 track) succeeded
        assert result.succeeded == 1
        assert result.failed == 2
        assert len(result.errors) == 1

    @patch("backend.services.ai_tagger.ClaudeClient")
    async def test_cancellation(self, mock_client_cls, db_session):
        """Pipeline stops when cancellation is requested during processing."""
        tracks = [
            Track(
                file_path=f"/music/cancel-{i}.aiff",
                title=f"Track {i}",
                artist="Artist",
            )
            for i in range(5)
        ]
        db_session.add_all(tracks)
        db_session.flush()

        mock_client = MagicMock()
        mock_client.tag_batch = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_token_usage.return_value = SimpleNamespace(estimated_cost_usd=0.0)

        tagger = AiTagger(_make_settings(ai_batch_size=2))

        # Cancel after first batch completes
        async def cancel_after_first(*args, **kwargs):
            tagger.cancel()
            return _make_claude_response(
                [
                    AiTagResult(
                        track_id=tracks[0].id,
                        genre="House",
                        subgenre="",
                        mood="Warm",
                        energy=5,
                        confidence="high",
                        reasoning="Test.",
                    ),
                    AiTagResult(
                        track_id=tracks[1].id,
                        genre="House",
                        subgenre="",
                        mood="Warm",
                        energy=5,
                        confidence="high",
                        reasoning="Test.",
                    ),
                ]
            )

        mock_client.tag_batch.side_effect = cancel_after_first
        result = await tagger.tag_tracks(tracks, db_session)

        # Only the first batch should have been processed
        assert mock_client.tag_batch.call_count == 1
        assert result.succeeded == 2

    @patch("backend.services.ai_tagger.ClaudeClient")
    async def test_ai_status_transition(self, mock_client_cls, db_session):
        """Track ai_status transitions from untagged to ai_tagged."""
        track = Track(
            file_path="/music/status.aiff",
            title="Status Test",
            artist="Artist",
        )
        db_session.add(track)
        db_session.flush()
        assert track.ai_status == "untagged"

        mock_client = MagicMock()
        mock_client.tag_batch = AsyncMock()
        mock_client_cls.return_value = mock_client
        mock_client.tag_batch.return_value = _make_claude_response(
            [
                AiTagResult(
                    track_id=track.id,
                    genre="House",
                    subgenre="",
                    mood="Warm",
                    energy=5,
                    confidence="high",
                    reasoning="Test.",
                ),
            ]
        )
        mock_client.get_token_usage.return_value = SimpleNamespace(estimated_cost_usd=0.01)

        tagger = AiTagger(_make_settings())
        await tagger.tag_tracks([track], db_session)

        assert track.ai_status == "ai_tagged"

    @patch("backend.services.ai_tagger.ClaudeClient")
    async def test_multiple_batches(self, mock_client_cls, db_session):
        """Tracks are split into correct number of batches."""
        tracks = [
            Track(
                file_path=f"/music/multi-{i}.aiff",
                title=f"Track {i}",
                artist="Artist",
            )
            for i in range(5)
        ]
        db_session.add_all(tracks)
        db_session.flush()

        mock_client = MagicMock()
        mock_client.tag_batch = AsyncMock()
        mock_client_cls.return_value = mock_client

        def make_response(*args, **kwargs):
            batch_ids = kwargs.get("batch_track_ids", [])
            return _make_claude_response(
                [
                    AiTagResult(
                        track_id=tid,
                        genre="House",
                        subgenre="",
                        mood="Warm",
                        energy=5,
                        confidence="high",
                        reasoning="Test.",
                    )
                    for tid in batch_ids
                ]
            )

        mock_client.tag_batch.side_effect = make_response
        mock_client.get_token_usage.return_value = SimpleNamespace(estimated_cost_usd=0.02)

        tagger = AiTagger(_make_settings(ai_batch_size=2))
        result = await tagger.tag_tracks(tracks, db_session)

        assert result.total_batches == 3
        assert result.succeeded == 5
        assert mock_client.tag_batch.call_count == 3
