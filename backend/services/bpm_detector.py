"""BPM detector — uses librosa to detect tempo with auto-correction.

Detects BPM from audio files using onset strength analysis and
librosa's tempo estimation. Applies half/double-time auto-correction
based on configurable BPM range settings.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


@dataclass
class BPMResult:
    """Result of BPM detection for a single track.

    Attributes:
        bpm: Detected BPM after auto-correction, rounded to 2 decimal places.
        raw_bpm: BPM before auto-correction.
        confidence: Confidence score (0.0–1.0).
        was_corrected: True if half/double-time correction was applied.
        correction_factor: 1 (no correction), 2 (doubled), or -2 (halved).
    """

    bpm: float
    raw_bpm: float
    confidence: float
    was_corrected: bool
    correction_factor: int


def correct_bpm_range(
    raw_bpm: float,
    bpm_range_min: int,
    bpm_range_max: int,
) -> tuple[float, int]:
    """Apply half/double-time correction to bring BPM into the target range.

    Args:
        raw_bpm: Raw BPM from librosa.
        bpm_range_min: Minimum acceptable BPM.
        bpm_range_max: Maximum acceptable BPM.

    Returns:
        Tuple of (corrected_bpm, correction_factor).
        correction_factor is 1 (no change), 2 (doubled), or -2 (halved).
    """
    # Already in range
    if bpm_range_min <= raw_bpm <= bpm_range_max:
        return round(raw_bpm, 2), 1

    # Too slow — try doubling
    if raw_bpm < bpm_range_min:
        doubled = raw_bpm * 2
        if bpm_range_min <= doubled <= bpm_range_max:
            return round(doubled, 2), 2

    # Too fast — try halving
    if raw_bpm > bpm_range_max:
        halved = raw_bpm / 2
        if bpm_range_min <= halved <= bpm_range_max:
            return round(halved, 2), -2

    # Correction didn't help — return raw value
    return round(raw_bpm, 2), 1


def compute_bpm_confidence(
    onset_env: np.ndarray,
    bpm: float,
    sr: int,
    hop_length: int,
) -> float:
    """Compute confidence score from onset autocorrelation at the detected tempo.

    Args:
        onset_env: Onset strength envelope from librosa.
        bpm: Detected BPM value.
        sr: Sample rate used for audio loading.
        hop_length: Hop length used for onset computation.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    if len(onset_env) == 0 or np.max(onset_env) == 0:
        return 0.0

    # Compute autocorrelation of onset envelope
    onset_normalized = onset_env - np.mean(onset_env)
    autocorr = np.correlate(onset_normalized, onset_normalized, mode="full")
    autocorr = autocorr[len(autocorr) // 2 :]  # keep positive lags only

    if len(autocorr) <= 1 or autocorr[0] == 0:
        return 0.0

    # Normalize by zero-lag value
    autocorr = autocorr / autocorr[0]

    # Find the lag corresponding to the detected BPM
    beat_period_frames = int(60.0 / bpm * sr / hop_length) if bpm > 0 else 0

    if beat_period_frames <= 0 or beat_period_frames >= len(autocorr):
        return 0.0

    # Confidence is the autocorrelation value at the beat period lag
    confidence = float(autocorr[beat_period_frames])

    # Clamp to [0, 1]
    return max(0.0, min(1.0, confidence))


def detect_bpm(
    file_path: Path,
    sr: int = 22050,
    hop_length: int = 512,
    bpm_range_min: int = 70,
    bpm_range_max: int = 180,
    y: np.ndarray | None = None,
    loaded_sr: int | None = None,
) -> BPMResult | None:
    """Detect BPM for an audio file using librosa.

    Args:
        file_path: Path to the audio file.
        sr: Target sample rate for loading.
        hop_length: Hop length for onset computation.
        bpm_range_min: Minimum acceptable BPM for auto-correction.
        bpm_range_max: Maximum acceptable BPM for auto-correction.
        y: Pre-loaded audio signal (if already loaded by analysis pipeline).
        loaded_sr: Sample rate of pre-loaded audio.

    Returns:
        BPMResult with detected BPM and confidence, or None on error.
    """
    import librosa  # type: ignore[import-not-found]

    try:
        if y is None:
            if not file_path.exists():
                logger.warning("File not found for BPM detection: %s", file_path)
                return None
            y, loaded_sr = librosa.load(str(file_path), sr=sr, mono=True)
        actual_sr = loaded_sr if loaded_sr is not None else sr

        # Compute onset strength envelope
        onset_env = librosa.onset.onset_strength(y=y, sr=actual_sr, hop_length=hop_length)

        # Estimate tempo
        tempo = librosa.feature.tempo(
            onset_envelope=onset_env, sr=actual_sr, hop_length=hop_length
        )
        raw_bpm = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)

        # Apply auto-correction
        corrected_bpm, correction_factor = correct_bpm_range(raw_bpm, bpm_range_min, bpm_range_max)

        # Compute confidence
        confidence = compute_bpm_confidence(onset_env, corrected_bpm, actual_sr, hop_length)

        return BPMResult(
            bpm=corrected_bpm,
            raw_bpm=round(raw_bpm, 2),
            confidence=round(confidence, 4),
            was_corrected=correction_factor != 1,
            correction_factor=correction_factor,
        )

    except Exception:
        logger.exception("BPM detection failed for %s", file_path)
        return None
