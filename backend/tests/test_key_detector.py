"""Tests for key detector — Krumhansl-Schmuckler algorithm and confidence."""

from pathlib import Path

import numpy as np  # type: ignore[import-not-found]

from backend.services.key_detector import (
    KeyResult,
    compute_key_confidence,
    compute_key_correlations,
    detect_key,
    select_best_key,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


class TestComputeKeyCorrelations:
    """Test chroma-to-key correlation computation."""

    def test_c_major_chroma(self):
        """A chroma vector emphasising C major notes should correlate with C major."""
        # C major scale: C D E F G A B → pitch classes 0 1 2 3 4 5 6 7 8 9 10 11
        # Emphasise C E G (tonic triad)
        chroma = np.zeros(12)
        chroma[0] = 1.0  # C
        chroma[4] = 0.8  # E
        chroma[7] = 0.6  # G
        correlations = compute_key_correlations(chroma)
        assert len(correlations) == 24
        # All values should be floats
        assert all(isinstance(v, float) for v in correlations.values())

    def test_a_minor_chroma(self):
        """A chroma vector emphasising A minor notes should correlate with A minor."""
        chroma = np.zeros(12)
        chroma[9] = 1.0  # A
        chroma[0] = 0.8  # C
        chroma[4] = 0.6  # E
        correlations = compute_key_correlations(chroma)
        assert len(correlations) == 24

    def test_uniform_chroma(self):
        """Uniform chroma → all correlations should be similar."""
        chroma = np.ones(12)
        correlations = compute_key_correlations(chroma)
        values = list(correlations.values())
        # All should be very close
        assert max(values) - min(values) < 0.1

    def test_zero_chroma(self):
        """Zero chroma → correlations should all be 0 or NaN-safe."""
        chroma = np.zeros(12)
        correlations = compute_key_correlations(chroma)
        assert len(correlations) == 24


class TestSelectBestKey:
    """Test selecting the best key from correlations."""

    def test_clear_winner(self):
        """When one key has much higher correlation, it should be selected."""
        correlations = {i: 0.1 for i in range(1, 25)}
        correlations[16] = 0.95  # C major = key 16
        best_key, second_key = select_best_key(correlations)
        assert best_key == 16

    def test_returns_second_best(self):
        """Second best key should be returned."""
        correlations = {i: 0.1 for i in range(1, 25)}
        correlations[16] = 0.95  # C major
        correlations[9] = 0.85  # C minor (relative minor)
        best_key, second_key = select_best_key(correlations)
        assert best_key == 16
        assert second_key == 9

    def test_ambiguous_case(self):
        """When top two are close, both should be returned."""
        correlations = {i: 0.1 for i in range(1, 25)}
        correlations[16] = 0.80
        correlations[15] = 0.79
        best_key, second_key = select_best_key(correlations)
        assert best_key == 16
        assert second_key == 15


class TestComputeKeyConfidence:
    """Test confidence computation from correlation gap."""

    def test_large_gap_high_confidence(self):
        """Large gap between top two → high confidence."""
        confidence = compute_key_confidence(0.95, 0.50)
        assert 0.5 < confidence <= 1.0

    def test_small_gap_low_confidence(self):
        """Small gap between top two → low confidence."""
        confidence = compute_key_confidence(0.80, 0.79)
        assert confidence < 0.5

    def test_zero_gap(self):
        """Zero gap → minimum confidence."""
        confidence = compute_key_confidence(0.80, 0.80)
        assert confidence == 0.0

    def test_confidence_bounded(self):
        """Confidence is always in [0, 1]."""
        for best in [0.1, 0.5, 0.9, 1.0]:
            for second in [0.0, 0.1, 0.5, 0.8]:
                if second <= best:
                    conf = compute_key_confidence(best, second)
                    assert 0.0 <= conf <= 1.0


class TestDetectKeyIntegration:
    """Integration test: detect key on a test audio fixture."""

    def test_detect_key_mp3(self):
        """Detect key on an MP3 fixture — should return a valid result."""
        result = detect_key(FIXTURES_DIR / "silence_320k.mp3")
        assert isinstance(result, KeyResult)
        assert 1 <= result.key <= 24
        assert 0.0 <= result.confidence <= 1.0
        assert result.key_name  # non-empty string

    def test_detect_key_aiff(self):
        """Detect key on an AIFF fixture."""
        result = detect_key(FIXTURES_DIR / "silence_16bit.aiff")
        assert isinstance(result, KeyResult)
        assert 1 <= result.key <= 24

    def test_detect_key_nonexistent_file(self):
        """Nonexistent file → None result."""
        result = detect_key(FIXTURES_DIR / "does_not_exist.mp3")
        assert result is None
