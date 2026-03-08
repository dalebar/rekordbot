"""BPM transition scoring — evaluates tempo progressions for DJ set planning.

Pure logic module. No I/O, no database access. Provides scoring functions
for evaluating BPM transitions between adjacent tracks and suggesting
ideal BPM ranges for empty slots in a set sequence.
"""

# Scoring thresholds: (max_delta, score)
# Checked in order — first match wins
_SCORE_TABLE: list[tuple[float, float]] = [
    (0.0, 1.0),  # exact match
    (2.0, 0.95),  # imperceptible
    (5.0, 0.8),  # smooth, common DJ technique
    (10.0, 0.5),  # noticeable, needs mixing skill
    (20.0, 0.2),  # significant jump, transition track territory
]

_DEFAULT_SCORE = 0.0  # >20 BPM: genre change, deliberate break

# Quality labels for transition deltas
_QUALITY_TABLE: list[tuple[float, str]] = [
    (2.0, "smooth"),
    (5.0, "acceptable"),
    (10.0, "noticeable"),
]

_DEFAULT_QUALITY = "jarring"

# Default BPM range when no context is available
_DEFAULT_BPM_MIN = 70.0
_DEFAULT_BPM_MAX = 180.0

# Range width around a target BPM (±5)
_SUGGEST_RANGE = 5.0


def score_bpm_transition(bpm_a: float | None, bpm_b: float | None) -> float:
    """Score the quality of a BPM transition between two tracks.

    Args:
        bpm_a: BPM of the first track, or None/0 if unknown.
        bpm_b: BPM of the second track, or None/0 if unknown.

    Returns:
        Score from 0.0 (jarring) to 1.0 (perfect match).
        Returns 0.0 if either BPM is None or zero.
    """
    if not bpm_a or not bpm_b:
        return 0.0

    delta = abs(bpm_a - bpm_b)

    for max_delta, score in _SCORE_TABLE:
        if delta <= max_delta:
            return score

    return _DEFAULT_SCORE


def get_transition_quality(bpm_a: float | None, bpm_b: float | None) -> str:
    """Get a human-readable quality label for a BPM transition.

    Args:
        bpm_a: BPM of the first track, or None/0 if unknown.
        bpm_b: BPM of the second track, or None/0 if unknown.

    Returns:
        Quality string: "smooth", "acceptable", "noticeable", "jarring",
        or "unknown" if either BPM is None or zero.
    """
    if not bpm_a or not bpm_b:
        return "unknown"

    delta = abs(bpm_a - bpm_b)

    for max_delta, quality in _QUALITY_TABLE:
        if delta <= max_delta:
            return quality

    return _DEFAULT_QUALITY


def suggest_bpm_range(
    sequence_bpms: list[float],
    target_bpm: float | None,
    position: int,
) -> tuple[float, float]:
    """Suggest an ideal BPM range for a slot in a set sequence.

    Uses the target BPM if provided, otherwise interpolates from
    neighboring tracks in the sequence.

    Args:
        sequence_bpms: Current BPMs in the sequence (0.0 for empty slots).
        target_bpm: Overall target BPM for this position, or None.
        position: The slot index to suggest for.

    Returns:
        Tuple of (min_bpm, max_bpm) for the suggested range.
    """
    if target_bpm:
        return (target_bpm - _SUGGEST_RANGE, target_bpm + _SUGGEST_RANGE)

    # Find neighboring BPMs
    reference_bpm = _find_neighbor_bpm(sequence_bpms, position)

    if reference_bpm is None:
        return (_DEFAULT_BPM_MIN, _DEFAULT_BPM_MAX)

    return (reference_bpm - _SUGGEST_RANGE, reference_bpm + _SUGGEST_RANGE)


def _find_neighbor_bpm(sequence_bpms: list[float], position: int) -> float | None:
    """Find a reference BPM from neighboring positions in the sequence.

    Looks at the previous and next non-zero BPMs and returns their
    midpoint, or the single neighbor if only one is available.

    Args:
        sequence_bpms: BPMs in the sequence.
        position: The target position.

    Returns:
        Reference BPM, or None if no neighbors have valid BPMs.
    """
    prev_bpm = None
    next_bpm = None

    # Look backward for previous non-zero BPM
    for i in range(position - 1, -1, -1):
        if i < len(sequence_bpms) and sequence_bpms[i] > 0:
            prev_bpm = sequence_bpms[i]
            break

    # Look forward for next non-zero BPM
    for i in range(position + 1, len(sequence_bpms)):
        if sequence_bpms[i] > 0:
            next_bpm = sequence_bpms[i]
            break

    if prev_bpm and next_bpm:
        return (prev_bpm + next_bpm) / 2
    return prev_bpm or next_bpm
