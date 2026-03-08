"""Tests for BPM transition scoring — TDD (write tests first, then implement)."""

import pytest

from backend.services.bpm_transition import (
    get_transition_quality,
    score_bpm_transition,
    suggest_bpm_range,
)


class TestScoreBpmTransition:
    """Tests for score_bpm_transition()."""

    def test_exact_match(self):
        """Same BPM scores 1.0."""
        assert score_bpm_transition(128.0, 128.0) == 1.0

    def test_small_delta_1bpm(self):
        """±1 BPM scores 0.95."""
        assert score_bpm_transition(128.0, 129.0) == 0.95
        assert score_bpm_transition(129.0, 128.0) == 0.95

    def test_small_delta_2bpm(self):
        """±2 BPM scores 0.95."""
        assert score_bpm_transition(128.0, 130.0) == 0.95

    def test_medium_delta_3bpm(self):
        """±3 BPM scores 0.8."""
        assert score_bpm_transition(128.0, 131.0) == 0.8

    def test_medium_delta_5bpm(self):
        """±5 BPM scores 0.8."""
        assert score_bpm_transition(128.0, 123.0) == 0.8

    def test_noticeable_delta_6bpm(self):
        """±6 BPM scores 0.5."""
        assert score_bpm_transition(128.0, 134.0) == 0.5

    def test_noticeable_delta_10bpm(self):
        """±10 BPM scores 0.5."""
        assert score_bpm_transition(128.0, 138.0) == 0.5

    def test_large_delta_11bpm(self):
        """±11 BPM scores 0.2."""
        assert score_bpm_transition(128.0, 139.0) == 0.2

    def test_large_delta_20bpm(self):
        """±20 BPM scores 0.2."""
        assert score_bpm_transition(128.0, 148.0) == 0.2

    def test_very_large_delta_21bpm(self):
        """>20 BPM scores 0.0."""
        assert score_bpm_transition(128.0, 149.0) == 0.0

    def test_very_large_delta_50bpm(self):
        """>20 BPM scores 0.0."""
        assert score_bpm_transition(128.0, 178.0) == 0.0

    def test_zero_bpm_a(self):
        """Zero BPM returns 0.0."""
        assert score_bpm_transition(0.0, 128.0) == 0.0

    def test_zero_bpm_b(self):
        """Zero BPM returns 0.0."""
        assert score_bpm_transition(128.0, 0.0) == 0.0

    def test_none_bpm_a(self):
        """None BPM returns 0.0."""
        assert score_bpm_transition(None, 128.0) == 0.0

    def test_none_bpm_b(self):
        """None BPM returns 0.0."""
        assert score_bpm_transition(128.0, None) == 0.0

    def test_both_none(self):
        """Both None returns 0.0."""
        assert score_bpm_transition(None, None) == 0.0

    def test_fractional_bpm(self):
        """Fractional BPM values work correctly."""
        # 128.50 to 130.00 = 1.5 BPM delta → 0.95
        assert score_bpm_transition(128.5, 130.0) == 0.95


class TestGetTransitionQuality:
    """Tests for get_transition_quality()."""

    def test_smooth(self):
        """0–2 BPM delta is 'smooth'."""
        assert get_transition_quality(128.0, 128.0) == "smooth"
        assert get_transition_quality(128.0, 129.0) == "smooth"
        assert get_transition_quality(128.0, 130.0) == "smooth"

    def test_acceptable(self):
        """3–5 BPM delta is 'acceptable'."""
        assert get_transition_quality(128.0, 131.0) == "acceptable"
        assert get_transition_quality(128.0, 133.0) == "acceptable"

    def test_noticeable(self):
        """6–10 BPM delta is 'noticeable'."""
        assert get_transition_quality(128.0, 134.0) == "noticeable"
        assert get_transition_quality(128.0, 138.0) == "noticeable"

    def test_jarring(self):
        """11+ BPM delta is 'jarring'."""
        assert get_transition_quality(128.0, 139.0) == "jarring"
        assert get_transition_quality(128.0, 178.0) == "jarring"

    def test_none_bpm(self):
        """None BPM returns 'unknown'."""
        assert get_transition_quality(None, 128.0) == "unknown"
        assert get_transition_quality(128.0, None) == "unknown"

    def test_zero_bpm(self):
        """Zero BPM returns 'unknown'."""
        assert get_transition_quality(0.0, 128.0) == "unknown"


class TestSuggestBpmRange:
    """Tests for suggest_bpm_range()."""

    def test_with_target_bpm(self):
        """With a target BPM, suggest range around it."""
        low, high = suggest_bpm_range([], target_bpm=128.0, position=0)
        assert low <= 128.0 <= high
        # Range should be ±5 around target
        assert low == pytest.approx(123.0)
        assert high == pytest.approx(133.0)

    def test_without_target_uses_neighbors(self):
        """Without target, uses neighboring BPMs in sequence."""
        bpms = [120.0, 124.0, 0.0, 130.0]
        low, high = suggest_bpm_range(bpms, target_bpm=None, position=2)
        # Should interpolate from neighbors (124 and 130), midpoint ~127
        assert low <= 127.0 <= high

    def test_at_start_of_sequence(self):
        """At start, uses next track BPM as reference."""
        bpms = [0.0, 125.0, 128.0]
        low, high = suggest_bpm_range(bpms, target_bpm=None, position=0)
        assert low <= 125.0 <= high

    def test_at_end_of_sequence(self):
        """At end, uses previous track BPM as reference."""
        bpms = [120.0, 124.0, 0.0]
        low, high = suggest_bpm_range(bpms, target_bpm=None, position=2)
        assert low <= 124.0 <= high

    def test_empty_sequence_no_target(self):
        """Empty sequence with no target returns wide range."""
        low, high = suggest_bpm_range([], target_bpm=None, position=0)
        assert low == 70.0
        assert high == 180.0

    def test_all_zero_bpms(self):
        """All zero BPMs with no target returns wide range."""
        low, high = suggest_bpm_range([0.0, 0.0, 0.0], target_bpm=None, position=1)
        assert low == 70.0
        assert high == 180.0
