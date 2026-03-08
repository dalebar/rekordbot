"""Key detector — uses librosa chroma features with Krumhansl-Schmuckler algorithm.

Detects the musical key of an audio file by computing a chromagram,
correlating against major and minor key profiles, and selecting the
best match.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np  # type: ignore[import-not-found]

from backend.services.key_notation import camelot_to_classical

logger = logging.getLogger(__name__)

# Krumhansl-Schmuckler key profiles (perceptual stability weights)
# Starting from the tonic, 12 pitch classes in semitone order
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# Mapping from (pitch_class, quality) to Camelot internal int (1–24)
# pitch_class: 0=C, 1=C#, ..., 11=B
# quality: "major" or "minor"
_PITCH_QUALITY_TO_INT: dict[tuple[int, str], int] = {
    (8, "minor"): 1,  # A♭ minor = 1A
    (11, "major"): 2,  # B major = 1B
    (3, "minor"): 3,  # E♭ minor = 2A
    (6, "major"): 4,  # F♯ major = 2B
    (10, "minor"): 5,  # B♭ minor = 3A
    (1, "major"): 6,  # D♭ major = 3B
    (5, "minor"): 7,  # F minor = 4A
    (8, "major"): 8,  # A♭ major = 4B
    (0, "minor"): 9,  # C minor = 5A
    (3, "major"): 10,  # E♭ major = 5B
    (7, "minor"): 11,  # G minor = 6A
    (10, "major"): 12,  # B♭ major = 6B
    (2, "minor"): 13,  # D minor = 7A
    (5, "major"): 14,  # F major = 7B
    (9, "minor"): 15,  # A minor = 8A
    (0, "major"): 16,  # C major = 8B
    (4, "minor"): 17,  # E minor = 9A
    (7, "major"): 18,  # G major = 9B
    (11, "minor"): 19,  # B minor = 10A
    (2, "major"): 20,  # D major = 10B
    (6, "minor"): 21,  # F♯ minor = 11A
    (9, "major"): 22,  # A major = 11B
    (1, "minor"): 23,  # D♭ minor = 12A
    (4, "major"): 24,  # E major = 12B
}


@dataclass
class KeyResult:
    """Result of key detection for a single track.

    Attributes:
        key: Internal key integer (1–24, Camelot wheel mapping).
        key_name: Classical key name (e.g. "C major", "A♭ minor").
        confidence: Confidence score (0.0–1.0).
        correlation_scores: All 24 key correlations for advanced analysis.
        second_best_key: Runner-up key integer.
        second_best_confidence: Correlation of runner-up key.
    """

    key: int
    key_name: str
    confidence: float
    correlation_scores: dict[int, float] = field(default_factory=dict)
    second_best_key: int = 0
    second_best_confidence: float = 0.0


def compute_key_correlations(chroma: np.ndarray) -> dict[int, float]:
    """Compute Pearson correlation of chroma distribution with all 24 key profiles.

    For each of the 12 pitch classes as tonic, correlates the rotated chroma
    with both major and minor profiles.

    Args:
        chroma: 12-element pitch class distribution vector.

    Returns:
        Dict mapping internal key int (1–24) to correlation coefficient.
    """
    correlations: dict[int, float] = {}

    # Normalize chroma to avoid zero-variance issues
    chroma_std = np.std(chroma)
    if chroma_std == 0:
        return {i: 0.0 for i in range(1, 25)}

    for pitch_class in range(12):
        # Rotate chroma to align with candidate tonic
        rotated = np.roll(chroma, -pitch_class)

        # Correlate with major profile
        major_key = _PITCH_QUALITY_TO_INT.get((pitch_class, "major"))
        if major_key is not None:
            corr = float(np.corrcoef(rotated, MAJOR_PROFILE)[0, 1])
            correlations[major_key] = corr if not np.isnan(corr) else 0.0

        # Correlate with minor profile
        minor_key = _PITCH_QUALITY_TO_INT.get((pitch_class, "minor"))
        if minor_key is not None:
            corr = float(np.corrcoef(rotated, MINOR_PROFILE)[0, 1])
            correlations[minor_key] = corr if not np.isnan(corr) else 0.0

    return correlations


def select_best_key(correlations: dict[int, float]) -> tuple[int, int]:
    """Select the key with highest correlation and the runner-up.

    Args:
        correlations: Dict mapping key int to correlation coefficient.

    Returns:
        Tuple of (best_key, second_best_key) as internal key integers.
    """
    sorted_keys = sorted(correlations.items(), key=lambda x: x[1], reverse=True)
    best_key = sorted_keys[0][0]
    second_key = sorted_keys[1][0] if len(sorted_keys) > 1 else best_key
    return best_key, second_key


def compute_key_confidence(best_corr: float, second_corr: float) -> float:
    """Compute confidence from the gap between top two correlations.

    A large gap indicates a clear winner; a small gap indicates ambiguity.
    Normalised to [0, 1] using a sigmoid-like scaling.

    Args:
        best_corr: Correlation of the best matching key.
        second_corr: Correlation of the second-best key.

    Returns:
        Confidence score between 0.0 and 1.0.
    """
    gap = best_corr - second_corr
    if gap <= 0:
        return 0.0

    # Scale gap to [0, 1] — empirical scaling factor
    # A gap of ~0.15 is "pretty confident", ~0.30+ is "very confident"
    confidence = min(1.0, gap / 0.30)
    return round(confidence, 4)


def detect_key(
    file_path: Path,
    sr: int = 22050,
    y: np.ndarray | None = None,
    loaded_sr: int | None = None,
) -> KeyResult | None:
    """Detect musical key for an audio file using chroma + Krumhansl-Schmuckler.

    Args:
        file_path: Path to the audio file.
        sr: Target sample rate for loading.
        y: Pre-loaded audio signal (if already loaded by analysis pipeline).
        loaded_sr: Sample rate of pre-loaded audio.

    Returns:
        KeyResult with detected key and confidence, or None on error.
    """
    import librosa  # type: ignore[import-not-found]

    try:
        if y is None:
            if not file_path.exists():
                logger.warning("File not found for key detection: %s", file_path)
                return None
            y, loaded_sr = librosa.load(str(file_path), sr=sr, mono=True)
        actual_sr = loaded_sr if loaded_sr is not None else sr

        # Separate harmonic component (remove percussive elements)
        y_harmonic, _ = librosa.effects.hpss(y)

        # Compute constant-Q chromagram
        chromagram = librosa.feature.chroma_cqt(y=y_harmonic, sr=actual_sr)

        # Sum across time to get pitch class distribution
        chroma_sum = np.sum(chromagram, axis=1)

        # Compute correlations with all 24 key profiles
        correlations = compute_key_correlations(chroma_sum)

        if not correlations:
            logger.warning("No key correlations computed for %s", file_path)
            return None

        # Select best key
        best_key, second_key = select_best_key(correlations)

        # Compute confidence
        best_corr = correlations[best_key]
        second_corr = correlations[second_key]
        confidence = compute_key_confidence(best_corr, second_corr)

        return KeyResult(
            key=best_key,
            key_name=camelot_to_classical(best_key),
            confidence=confidence,
            correlation_scores=correlations,
            second_best_key=second_key,
            second_best_confidence=round(second_corr, 4),
        )

    except Exception:
        logger.exception("Key detection failed for %s", file_path)
        return None
