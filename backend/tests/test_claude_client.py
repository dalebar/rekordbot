"""Tests for Claude client with mocked Anthropic SDK."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.exceptions import AiTagError
from backend.services.claude_client import ClaudeClient, RateLimiter

# --- Helpers ---


def _make_tool_use_response(
    tracks_data: list[dict],
    input_tokens: int = 1000,
    output_tokens: int = 500,
    model: str = "claude-sonnet-4-20250514",
) -> SimpleNamespace:
    """Create a mock Anthropic Message response with tool use."""
    tool_block = SimpleNamespace(
        type="tool_use",
        name="tag_tracks",
        input={"tracks": tracks_data},
    )
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(
        content=[tool_block],
        usage=usage,
        model=model,
        stop_reason="tool_use",
    )


def _make_text_response(
    text: str = "I cannot use the tool.",
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> SimpleNamespace:
    """Create a mock response with only text (no tool use)."""
    text_block = SimpleNamespace(type="text", text=text)
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    return SimpleNamespace(
        content=[text_block],
        usage=usage,
        model="claude-sonnet-4-20250514",
        stop_reason="end_turn",
    )


SAMPLE_TRACKS = [
    {
        "track_id": 1,
        "genre": "Tech House",
        "subgenre": "",
        "mood": "Groovy",
        "energy": 7,
        "confidence": "high",
        "reasoning": "Classic tech house.",
    },
    {
        "track_id": 2,
        "genre": "Melodic Techno",
        "subgenre": "",
        "mood": "Hypnotic",
        "energy": 8,
        "confidence": "medium",
        "reasoning": "BPM suggests techno.",
    },
]


# --- ClaudeClient ---


class TestClaudeClientInit:
    """Tests for ClaudeClient initialisation."""

    def test_missing_api_key_raises(self):
        """Empty API key raises AiTagError."""
        with pytest.raises(AiTagError, match="API key"):
            ClaudeClient(api_key="", model="claude-sonnet-4-20250514")

    @patch("backend.services.claude_client.anthropic.Anthropic")
    def test_valid_init(self, mock_anthropic):
        """Client initialises with valid API key."""
        client = ClaudeClient(
            api_key="sk-test-key",
            model="claude-sonnet-4-20250514",
        )
        assert client.model == "claude-sonnet-4-20250514"
        mock_anthropic.assert_called_once_with(api_key="sk-test-key")


class TestClaudeClientTagBatch:
    """Tests for tag_batch method."""

    @patch("backend.services.claude_client.anthropic.Anthropic")
    async def test_successful_tag_batch(self, mock_anthropic_cls):
        """Successful tool use response is parsed correctly."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_tool_use_response(SAMPLE_TRACKS)

        client = ClaudeClient(
            api_key="sk-test",
            model="claude-sonnet-4-20250514",
        )
        response = await client.tag_batch(
            system_prompt="test prompt",
            user_message="test tracks",
            tool_schema={"name": "tag_tracks", "input_schema": {}},
            batch_track_ids=[1, 2],
        )

        assert len(response.results) == 2
        assert response.results[0].genre == "Tech House"
        assert response.results[1].genre == "Melodic Techno"
        assert response.input_tokens == 1000
        assert response.output_tokens == 500
        assert response.model == "claude-sonnet-4-20250514"
        assert response.request_duration > 0

    @patch("backend.services.claude_client.anthropic.Anthropic")
    async def test_token_usage_accumulates(self, mock_anthropic_cls):
        """Token usage accumulates across multiple calls."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_tool_use_response(
            SAMPLE_TRACKS[:1], input_tokens=500, output_tokens=200
        )

        client = ClaudeClient(
            api_key="sk-test",
            model="claude-sonnet-4-20250514",
        )

        await client.tag_batch(
            system_prompt="p",
            user_message="m",
            tool_schema={"name": "tag_tracks", "input_schema": {}},
            batch_track_ids=[1],
        )
        await client.tag_batch(
            system_prompt="p",
            user_message="m",
            tool_schema={"name": "tag_tracks", "input_schema": {}},
            batch_track_ids=[1],
        )

        usage = client.get_token_usage()
        assert usage.total_input_tokens == 1000
        assert usage.total_output_tokens == 400
        assert usage.total_requests == 2
        assert usage.estimated_cost_usd > 0

    @patch("backend.services.claude_client.anthropic.Anthropic")
    async def test_no_tool_use_returns_empty(self, mock_anthropic_cls):
        """Response without tool use returns empty results."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_text_response()

        client = ClaudeClient(
            api_key="sk-test",
            model="claude-sonnet-4-20250514",
        )
        response = await client.tag_batch(
            system_prompt="p",
            user_message="m",
            tool_schema={"name": "tag_tracks", "input_schema": {}},
            batch_track_ids=[1],
        )
        assert len(response.results) == 0

    @patch("backend.services.claude_client.anthropic.Anthropic")
    async def test_auth_error_raises(self, mock_anthropic_cls):
        """Authentication error raises AiTagError."""
        import anthropic as anthropic_mod  # type: ignore[import-not-found]

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic_mod.AuthenticationError(
            message="invalid key",
            response=MagicMock(status_code=401),
            body={"error": {"message": "invalid key"}},
        )

        client = ClaudeClient(
            api_key="sk-bad",
            model="claude-sonnet-4-20250514",
        )
        with pytest.raises(AiTagError, match="Invalid"):
            await client.tag_batch(
                system_prompt="p",
                user_message="m",
                tool_schema={"name": "tag_tracks", "input_schema": {}},
                batch_track_ids=[1],
            )

    @patch("backend.services.claude_client.anthropic.Anthropic")
    @patch("backend.services.claude_client.asyncio.sleep")
    async def test_rate_limit_retry(self, mock_sleep, mock_anthropic_cls):
        """Rate limit errors trigger retry with backoff."""
        import anthropic as anthropic_mod  # type: ignore[import-not-found]

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        rate_limit_error = anthropic_mod.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body={"error": {"message": "rate limited"}},
        )
        mock_client.messages.create.side_effect = [
            rate_limit_error,
            _make_tool_use_response(SAMPLE_TRACKS[:1]),
        ]

        client = ClaudeClient(
            api_key="sk-test",
            model="claude-sonnet-4-20250514",
        )
        response = await client.tag_batch(
            system_prompt="p",
            user_message="m",
            tool_schema={"name": "tag_tracks", "input_schema": {}},
            batch_track_ids=[1],
        )

        assert len(response.results) == 1
        assert mock_client.messages.create.call_count == 2


# --- RateLimiter ---


class TestRateLimiter:
    """Tests for the rate limiter."""

    async def test_allows_within_limit(self):
        """Requests within limit pass immediately."""
        limiter = RateLimiter(max_per_minute=5)
        for _ in range(5):
            await limiter.acquire()
        assert len(limiter.timestamps) == 5

    @patch("backend.services.claude_client.asyncio.sleep")
    async def test_sleeps_at_limit(self, mock_sleep):
        """Reaching the limit triggers a sleep."""
        limiter = RateLimiter(max_per_minute=2)
        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()
        # Should have called sleep once when hitting the limit
        assert mock_sleep.called


# --- validate_api_key ---


class TestValidateApiKey:
    """Tests for API key validation."""

    @patch("backend.services.claude_client.anthropic.Anthropic")
    async def test_valid_key(self, mock_anthropic_cls):
        """Valid key returns True."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _make_text_response()

        client = ClaudeClient(
            api_key="sk-valid",
            model="claude-sonnet-4-20250514",
        )
        result = await client.validate_api_key()
        assert result is True

    @patch("backend.services.claude_client.anthropic.Anthropic")
    async def test_invalid_key(self, mock_anthropic_cls):
        """Invalid key raises AiTagError."""
        import anthropic as anthropic_mod  # type: ignore[import-not-found]

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = anthropic_mod.AuthenticationError(
            message="invalid",
            response=MagicMock(status_code=401),
            body={"error": {"message": "invalid"}},
        )

        client = ClaudeClient(
            api_key="sk-bad",
            model="claude-sonnet-4-20250514",
        )
        with pytest.raises(AiTagError, match="Invalid"):
            await client.validate_api_key()
