"""Tests for BPM detector — correction logic and confidence computation."""

from pathlib import Path

import numpy as np  # type: ignore[import-not-found]

from backend.services.bpm_detector import (
    BPMResult,
    compute_bpm_confidence,
    correct_bpm_range,
    detect_bpm,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


class TestCorrectBpmRange:
    """Test the BPM range auto-correction truth table."""

    # Default range: 70–180

    def test_in_range_no_correction(self):
        """BPM already in range — no correction needed."""
        bpm, factor = correct_bpm_range(128.0, 70, 180)
        assert bpm == 128.0
        assert factor == 1

    def test_at_min_boundary(self):
        """BPM exactly at min boundary — in range."""
        bpm, factor = correct_bpm_range(70.0, 70, 180)
        assert bpm == 70.0
        assert factor == 1

    def test_at_max_boundary(self):
        """BPM exactly at max boundary — in range."""
        bpm, factor = correct_bpm_range(180.0, 70, 180)
        assert bpm == 180.0
        assert factor == 1

    def test_below_min_doubled_in_range(self):
        """BPM below min, doubled lands in range."""
        bpm, factor = correct_bpm_range(64.0, 70, 180)
        assert bpm == 128.0
        assert factor == 2

    def test_above_max_halved_in_range(self):
        """BPM above max, halved lands in range."""
        bpm, factor = correct_bpm_range(256.0, 70, 180)
        assert bpm == 128.0
        assert factor == -2

    def test_below_min_doubled_still_below(self):
        """BPM below min, even doubled is still below — use raw value."""
        bpm, factor = correct_bpm_range(30.0, 70, 180)
        assert bpm == 30.0
        assert factor == 1

    def test_above_max_halved_still_above(self):
        """BPM above max, even halved is still above — use raw value."""
        bpm, factor = correct_bpm_range(400.0, 70, 180)
        assert bpm == 400.0
        assert factor == 1

    def test_below_min_doubled_above_max(self):
        """BPM below min, but doubling goes above max — use raw value."""
        bpm, factor = correct_bpm_range(60.0, 70, 100)
        assert bpm == 60.0
        assert factor == 1

    def test_above_max_halved_below_min(self):
        """BPM above max, but halving goes below min — use raw value."""
        bpm, factor = correct_bpm_range(200.0, 120, 180)
        assert bpm == 200.0
        assert factor == 1

    def test_half_time_detection(self):
        """Common case: librosa detects 65 BPM for a 130 BPM track."""
        bpm, factor = correct_bpm_range(65.0, 70, 180)
        assert bpm == 130.0
        assert factor == 2

    def test_double_time_detection(self):
        """Common case: librosa detects 260 BPM for a 130 BPM track."""
        bpm, factor = correct_bpm_range(260.0, 70, 180)
        assert bpm == 130.0
        assert factor == -2

    def test_custom_range_dnb(self):
        """DnB range: 160–180."""
        bpm, factor = correct_bpm_range(85.0, 160, 180)
        assert bpm == 170.0
        assert factor == 2

    def test_rounding_to_two_decimals(self):
        """Corrected BPM should be rounded to 2 decimal places."""
        bpm, factor = correct_bpm_range(63.333, 70, 180)
        assert bpm == 126.67
        assert factor == 2


class TestComputeBpmConfidence:
    """Test BPM confidence computation from autocorrelation."""

    def test_strong_signal_high_confidence(self):
        """Strong autocorrelation peak → high confidence."""
        # Simulate a strong onset envelope with clear periodicity
        sr = 22050
        hop_length = 512
        bpm = 128.0
        # Create synthetic onset envelope with strong beat pattern
        beat_period = int(60.0 / bpm * sr / hop_length)
        length = beat_period * 16
        onset_env = np.zeros(length)
        for i in range(0, length, beat_period):
            onset_env[i] = 1.0
        confidence = compute_bpm_confidence(onset_env, bpm, sr, hop_length)
        assert 0.0 <= confidence <= 1.0
        assert confidence > 0.5  # should be high for clear beat

    def test_noise_low_confidence(self):
        """Random noise → lower confidence."""
        rng = np.random.default_rng(42)
        onset_env = rng.random(1000)
        confidence = compute_bpm_confidence(onset_env, 128.0, 22050, 512)
        assert 0.0 <= confidence <= 1.0

    def test_empty_signal(self):
        """Empty onset envelope → 0 confidence."""
        onset_env = np.zeros(100)
        confidence = compute_bpm_confidence(onset_env, 128.0, 22050, 512)
        assert confidence == 0.0

    def test_confidence_bounded(self):
        """Confidence is always in [0, 1]."""
        rng = np.random.default_rng(123)
        for _ in range(10):
            onset_env = rng.random(500) * 10
            confidence = compute_bpm_confidence(onset_env, 120.0, 22050, 512)
            assert 0.0 <= confidence <= 1.0


class TestDetectBpmIntegration:
    """Integration test: detect BPM on a test audio fixture."""

    def test_detect_bpm_mp3(self):
        """Detect BPM on an MP3 fixture — should return a valid result."""
        result = detect_bpm(FIXTURES_DIR / "silence_320k.mp3")
        assert isinstance(result, BPMResult)
        assert result.bpm >= 0
        assert 0.0 <= result.confidence <= 1.0

    def test_detect_bpm_aiff(self):
        """Detect BPM on an AIFF fixture."""
        result = detect_bpm(FIXTURES_DIR / "silence_16bit.aiff")
        assert isinstance(result, BPMResult)
        assert result.bpm >= 0

    def test_detect_bpm_nonexistent_file(self):
        """Nonexistent file → None result."""
        result = detect_bpm(FIXTURES_DIR / "does_not_exist.mp3")
        assert result is None
