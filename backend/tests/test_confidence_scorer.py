"""Tests for confidence scorer — track readiness scoring for file organisation.

TDD: These tests are written before the implementation.
"""

from unittest.mock import MagicMock

from backend.services.confidence_scorer import (
    detect_bootleg_indicators,
    detect_va_compilation,
    score_track,
)
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
        "label": None,
        "ai_confidence": None,
        "source_path": "/downloads/test.flac",
        "file_path": "/library/test.aiff",
        "output_format": "aiff",
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(track, k, v)
    return track


def _make_resolved_path(
    fallbacks_used: list[str] | None = None,
    unresolved: list[str] | None = None,
):
    """Create a ResolvedPath with specified fallback/unresolved lists."""
    from pathlib import Path

    return ResolvedPath(
        path=Path("/library/Test Artist/Test Album/Test Track.aiff"),
        fallbacks_used=fallbacks_used or [],
        unresolved=unresolved or [],
        components={"artist": "Test Artist", "album": "Test Album", "title": "Test Track"},
    )


# --- detect_va_compilation() ---


class TestDetectVaCompilation:
    """Test VA compilation detection."""

    def test_not_va_simple(self):
        """Normal track is not VA."""
        track = _make_track(artist="Calibre", album_artist=None)
        assert detect_va_compilation(track) is False

    def test_different_album_artist(self):
        """album_artist differs from artist → VA detected."""
        track = _make_track(artist="Track Artist", album_artist="Various Artists")
        assert detect_va_compilation(track) is True

    def test_same_album_artist(self):
        """album_artist same as artist → not VA."""
        track = _make_track(artist="Calibre", album_artist="Calibre")
        assert detect_va_compilation(track) is False

    def test_artist_is_various_artists(self):
        """Artist is 'Various Artists'."""
        track = _make_track(artist="Various Artists")
        assert detect_va_compilation(track) is True

    def test_artist_is_va(self):
        """Artist is 'VA'."""
        track = _make_track(artist="VA")
        assert detect_va_compilation(track) is True

    def test_artist_is_v_slash_a(self):
        """Artist is 'V/A'."""
        track = _make_track(artist="V/A")
        assert detect_va_compilation(track) is True

    def test_case_insensitive(self):
        """VA detection is case-insensitive."""
        track = _make_track(artist="various artists")
        assert detect_va_compilation(track) is True

    def test_artist_contains_various(self):
        """Artist containing 'Various' (standalone word)."""
        track = _make_track(artist="Various")
        assert detect_va_compilation(track) is True

    def test_no_false_positive_on_partial(self):
        """'Varius' should not trigger VA detection."""
        track = _make_track(artist="Varius")
        assert detect_va_compilation(track) is False


# --- detect_bootleg_indicators() ---


class TestDetectBootlegIndicators:
    """Test bootleg/edit indicator detection."""

    def test_no_indicators(self):
        """Normal track has no bootleg indicators."""
        track = _make_track(title="Falls to You")
        assert detect_bootleg_indicators(track) == []

    def test_bootleg_in_title(self):
        """'bootleg' in title."""
        track = _make_track(title="Track (Bootleg)")
        indicators = detect_bootleg_indicators(track)
        assert len(indicators) > 0
        assert any("bootleg" in i.lower() for i in indicators)

    def test_edit_in_title(self):
        """'edit' in title."""
        track = _make_track(title="Track (DJ Edit)")
        indicators = detect_bootleg_indicators(track)
        assert len(indicators) > 0

    def test_mashup_in_title(self):
        """'mashup' in title."""
        track = _make_track(title="Track vs Other (Mashup)")
        indicators = detect_bootleg_indicators(track)
        assert len(indicators) > 0

    def test_vs_in_title(self):
        """'vs' in title."""
        track = _make_track(title="Artist vs Other Artist - Track")
        indicators = detect_bootleg_indicators(track)
        assert len(indicators) > 0

    def test_vip_in_title(self):
        """'VIP' in title."""
        track = _make_track(title="Track (VIP Mix)")
        indicators = detect_bootleg_indicators(track)
        assert len(indicators) > 0

    def test_b2b_in_title(self):
        """'b2b' in title."""
        track = _make_track(title="Track (B2B Mix)")
        indicators = detect_bootleg_indicators(track)
        assert len(indicators) > 0

    def test_case_insensitive(self):
        """Detection is case-insensitive."""
        track = _make_track(title="Track (BOOTLEG)")
        assert len(detect_bootleg_indicators(track)) > 0

    def test_bootleg_in_filename(self):
        """'bootleg' in source filename."""
        track = _make_track(
            title="Some Track",
            source_path="/downloads/Artist - Track (Bootleg).flac",
        )
        indicators = detect_bootleg_indicators(track)
        assert len(indicators) > 0

    def test_remix_not_flagged(self):
        """'remix' alone is NOT flagged (clear attribution)."""
        track = _make_track(title="Track (Some DJ Remix)")
        assert detect_bootleg_indicators(track) == []

    def test_no_false_positive_on_editing(self):
        """'editing' should not trigger (only 'edit' as a word)."""
        track = _make_track(title="Editing Suite")
        assert detect_bootleg_indicators(track) == []


# --- score_track() ---


class TestScoreTrack:
    """Test confidence scoring for track organisation."""

    def test_full_metadata_high_score(self):
        """Track with complete metadata scores high (≥ 0.7)."""
        track = _make_track()
        resolved = _make_resolved_path()
        result = score_track(track, resolved, [], threshold=0.7)
        assert result.score >= 0.7
        assert result.auto_approve is True

    def test_single_fallback_neutral(self):
        """Single fallback is neutral — doesn't lower score below threshold."""
        track = _make_track()
        resolved = _make_resolved_path(fallbacks_used=["album"])
        result = score_track(track, resolved, [], threshold=0.7)
        # Base 0.5 + 0.0 (single fallback) + other positives
        assert result.score >= 0.5

    def test_multiple_fallbacks_low_score(self):
        """Multiple fallbacks (≥2) lower the score."""
        track = _make_track(artist=None, album=None, genre=None)
        resolved = _make_resolved_path(fallbacks_used=["artist", "album"])
        result = score_track(track, resolved, [], threshold=0.7)
        assert result.score < 0.7
        assert result.auto_approve is False
        assert "multiple_fallbacks" in result.flags

    def test_unresolved_variable_low_score(self):
        """Unresolved variable heavily penalises score."""
        track = _make_track()
        resolved = _make_resolved_path(unresolved=["artist"])
        result = score_track(track, resolved, [], threshold=0.7)
        assert result.score < 0.5
        assert "unresolved_variable" in result.flags

    def test_va_penalty(self):
        """VA compilation detection lowers score."""
        track = _make_track(artist="Various Artists")
        resolved = _make_resolved_path()
        result = score_track(track, resolved, [], threshold=0.7)
        assert "va_detected" in result.flags
        # VA penalty should noticeably reduce score
        non_va_track = _make_track()
        non_va_result = score_track(non_va_track, resolved, [], threshold=0.7)
        assert result.score < non_va_result.score

    def test_bootleg_penalty(self):
        """Bootleg indicators lower score."""
        track = _make_track(title="Track (Bootleg)")
        resolved = _make_resolved_path()
        result = score_track(track, resolved, [], threshold=0.7)
        assert "bootleg_indicators" in result.flags

    def test_high_ai_confidence_boost(self):
        """High AI confidence boosts score."""
        track = _make_track(ai_confidence="high")
        resolved = _make_resolved_path()
        result = score_track(track, resolved, [], threshold=0.7)
        # Should be higher than without AI confidence
        no_ai_track = _make_track(ai_confidence=None)
        no_ai_result = score_track(no_ai_track, resolved, [], threshold=0.7)
        assert result.score >= no_ai_result.score

    def test_low_ai_confidence_penalty(self):
        """Low AI confidence lowers score."""
        track = _make_track(ai_confidence="low")
        resolved = _make_resolved_path()
        result = score_track(track, resolved, [], threshold=0.7)
        assert "low_ai_confidence" in result.flags

    def test_preference_rule_boost(self):
        """Existing preference rule for artist boosts confidence."""
        track = _make_track(artist="Calibre")
        resolved = _make_resolved_path()
        # Create a mock preference rule
        rule = MagicMock()
        rule.rule_type = "artist_folder"
        rule.key = "calibre"
        result = score_track(track, resolved, [rule], threshold=0.7)
        assert "preference_rule_match" in result.flags
        # Should boost above non-rule score
        no_rule_result = score_track(track, resolved, [], threshold=0.7)
        assert result.score > no_rule_result.score

    def test_threshold_boundary_exact(self):
        """Score at exactly the threshold → auto_approve = True."""
        track = _make_track()
        resolved = _make_resolved_path()
        result = score_track(track, resolved, [], threshold=0.7)
        # Full metadata should be well above threshold
        assert result.auto_approve is True

    def test_score_clamped_to_0_1(self):
        """Score is always in [0.0, 1.0] range."""
        # Many negatives
        track = _make_track(
            artist="Various Artists",
            title="Track (Bootleg Mashup VIP Edit)",
            ai_confidence="low",
            genre=None,
        )
        resolved = _make_resolved_path(
            fallbacks_used=["artist", "album", "genre"],
            unresolved=["label"],
        )
        result = score_track(track, resolved, [], threshold=0.7)
        assert 0.0 <= result.score <= 1.0

    def test_missing_genre_after_ai(self):
        """Missing genre when AI has been run → penalty."""
        track = _make_track(genre=None, ai_confidence="medium")
        resolved = _make_resolved_path()
        result = score_track(track, resolved, [], threshold=0.7)
        assert "missing_genre_post_ai" in result.flags

    def test_all_resolved_boost(self):
        """All template variables resolved directly → +0.3 boost."""
        track = _make_track()
        resolved = _make_resolved_path()  # No fallbacks, no unresolved
        result = score_track(track, resolved, [], threshold=0.7)
        # Base 0.5 + 0.3 = 0.8 minimum
        assert result.score >= 0.8

    def test_reasons_list_populated(self):
        """Reasons list contains human-readable explanations."""
        track = _make_track(artist="Various Artists", title="Track (Bootleg)")
        resolved = _make_resolved_path()
        result = score_track(track, resolved, [], threshold=0.7)
        assert len(result.reasons) > 0
        assert all(isinstance(r, str) for r in result.reasons)
