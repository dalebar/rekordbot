"""Tests for Claude reasoner — AI-powered placement suggestions for ambiguous tracks.

TDD for build_organisation_prompt() and parse_placement_result().
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.claude_reasoner import (
    PlacementSuggestion,
    build_organisation_prompt,
    parse_placement_result,
)
from backend.services.confidence_scorer import ConfidenceResult
from backend.services.template_engine import ResolvedPath

# --- Helper ---


def _make_track(**kwargs):
    """Create a mock Track with the given attributes."""
    track = MagicMock()
    defaults = {
        "id": 1,
        "title": "Test Track",
        "artist": "Test Artist",
        "album": "Test Album",
        "album_artist": None,
        "genre": "House",
        "subgenre": None,
        "year": 2024,
        "label": "Test Label",
        "bpm": 128.0,
        "key": 8,
        "source_path": "/downloads/test.flac",
        "file_path": "/library/test.aiff",
        "output_format": "aiff",
        "ai_confidence": None,
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(track, k, v)
    return track


def _make_resolved_path(
    fallbacks_used: list[str] | None = None,
    unresolved: list[str] | None = None,
) -> ResolvedPath:
    return ResolvedPath(
        path=Path("/library/Test Artist/Test Album/Test Track.aiff"),
        fallbacks_used=fallbacks_used if fallbacks_used is not None else ["album"],
        unresolved=unresolved or [],
        components={"artist": "Test Artist", "album": "Singles", "title": "Test Track"},
    )


def _make_confidence_result(
    score: float = 0.4,
    auto_approve: bool = False,
    reasons: list[str] | None = None,
    flags: list[str] | None = None,
) -> ConfidenceResult:
    return ConfidenceResult(
        score=score,
        auto_approve=auto_approve,
        reasons=reasons if reasons is not None else ["Single fallback used for 'album'"],
        flags=flags or [],
    )


# --- build_organisation_prompt() ---


class TestBuildOrganisationPrompt:
    """Test prompt construction for Claude reasoning."""

    def test_returns_system_and_user_message(self):
        """Returns a tuple of (system_prompt, user_message)."""
        track = _make_track()
        resolved = _make_resolved_path()
        confidence = _make_confidence_result()
        system_prompt, user_message = build_organisation_prompt(
            track, "{artist}/{album}/{title}", resolved, confidence
        )
        assert isinstance(system_prompt, str)
        assert isinstance(user_message, str)
        assert len(system_prompt) > 0
        assert len(user_message) > 0

    def test_includes_template_in_prompt(self):
        """User message includes the folder template."""
        track = _make_track()
        resolved = _make_resolved_path()
        confidence = _make_confidence_result()
        _, user_message = build_organisation_prompt(
            track, "{genre}/{artist}/{title}", resolved, confidence
        )
        assert "{genre}/{artist}/{title}" in user_message

    def test_includes_track_metadata(self):
        """User message includes track metadata."""
        track = _make_track(artist="Calibre", title="Falls to You", genre="DnB")
        resolved = _make_resolved_path()
        confidence = _make_confidence_result()
        _, user_message = build_organisation_prompt(
            track, "{artist}/{album}/{title}", resolved, confidence
        )
        assert "Calibre" in user_message
        assert "Falls to You" in user_message

    def test_includes_confidence_reasons(self):
        """User message includes reasons for low confidence."""
        track = _make_track()
        resolved = _make_resolved_path()
        confidence = _make_confidence_result(
            reasons=["VA compilation detected", "Multiple fallbacks used"]
        )
        _, user_message = build_organisation_prompt(
            track, "{artist}/{album}/{title}", resolved, confidence
        )
        assert "VA compilation detected" in user_message

    def test_includes_flags(self):
        """User message includes flags."""
        track = _make_track()
        resolved = _make_resolved_path()
        confidence = _make_confidence_result(flags=["va_detected", "bootleg_indicators"])
        _, user_message = build_organisation_prompt(
            track, "{artist}/{album}/{title}", resolved, confidence
        )
        assert "va_detected" in user_message


# --- parse_placement_result() ---


class TestParsePlacementResult:
    """Test parsing Claude's tool use response."""

    def test_valid_response(self):
        """Parse a valid tool use response."""
        tool_input = {
            "track_id": 1,
            "suggested_path": "Calibre/Shelflife 6/Falls to You",
            "confidence": "high",
            "reasoning": "Well-known DnB artist on Signature Records.",
        }
        result = parse_placement_result(tool_input, [1])
        assert result is not None
        assert result.track_id == 1
        assert result.suggested_path == "Calibre/Shelflife 6/Falls to You"
        assert result.confidence == "high"
        assert result.reasoning == "Well-known DnB artist on Signature Records."

    def test_missing_required_field(self):
        """Missing required field returns None."""
        tool_input = {
            "track_id": 1,
            "suggested_path": "Calibre/Shelflife 6/Falls to You",
            # Missing confidence and reasoning
        }
        result = parse_placement_result(tool_input, [1])
        assert result is None

    def test_invalid_confidence(self):
        """Invalid confidence is normalised to 'low'."""
        tool_input = {
            "track_id": 1,
            "suggested_path": "Test/Path",
            "confidence": "very_high",
            "reasoning": "Test.",
        }
        result = parse_placement_result(tool_input, [1])
        assert result is not None
        assert result.confidence == "low"

    def test_track_id_not_in_batch(self):
        """track_id not in the expected batch returns None."""
        tool_input = {
            "track_id": 999,
            "suggested_path": "Test/Path",
            "confidence": "high",
            "reasoning": "Test.",
        }
        result = parse_placement_result(tool_input, [1, 2, 3])
        assert result is None

    def test_empty_input(self):
        """Empty dict returns None."""
        result = parse_placement_result({}, [1])
        assert result is None


# --- suggest_placement() with mocked ClaudeClient ---


class TestSuggestPlacement:
    """Test the full suggest_placement flow with mocked API."""

    @pytest.mark.asyncio
    async def test_suggest_placement_calls_claude(self):
        """suggest_placement calls Claude and returns a PlacementSuggestion."""
        from backend.services.claude_reasoner import suggest_placement

        track = _make_track()
        resolved = _make_resolved_path()
        confidence = _make_confidence_result()

        # Mock the ClaudeClient
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.input_tokens = 100
        mock_response.output_tokens = 50

        # Mock tool use response
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.name = "suggest_placement"
        mock_block.input = {
            "track_id": 1,
            "suggested_path": "Test Artist/Singles/Test Track",
            "confidence": "medium",
            "reasoning": "Based on available metadata.",
        }

        mock_raw_response = MagicMock()
        mock_raw_response.content = [mock_block]
        mock_raw_response.usage.input_tokens = 100
        mock_raw_response.usage.output_tokens = 50
        mock_raw_response.stop_reason = "end_turn"

        mock_client.rate_limiter = MagicMock()
        mock_client.rate_limiter.acquire = AsyncMock()
        mock_client.model = "claude-sonnet-4-20250514"

        with patch(
            "backend.services.claude_reasoner._call_claude_for_placement",
            return_value=mock_raw_response,
        ):
            result = await suggest_placement(
                track, "{artist}/{album}/{title}", resolved, confidence, mock_client
            )
            assert result is not None
            assert isinstance(result, PlacementSuggestion)
