"""Confidence scorer — evaluates track readiness for automatic file organisation.

Pure logic module with no I/O and no database access. Scores tracks based on
metadata completeness, template resolution quality, VA compilation detection,
bootleg indicators, AI confidence, and preference rule matches.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.services.template_engine import ResolvedPath

logger = logging.getLogger(__name__)

# Bootleg/edit indicator patterns — matched as whole words (case-insensitive)
_BOOTLEG_PATTERNS = [
    r"\bbootleg\b",
    r"\bedit\b",
    r"\bmashup\b",
    r"\bmash[\s-]?up\b",
    r"\bvs\.?\b",
    r"\bvip\b",
    r"\bb2b\b",
]

# VA artist name patterns (case-insensitive, must be exact match or standalone word)
_VA_NAMES = {"various artists", "various", "va", "v/a"}


@dataclass
class ConfidenceResult:
    """Result of confidence scoring for a track's organisation proposal.

    Attributes:
        score: Confidence score from 0.0 to 1.0.
        auto_approve: Whether the score meets or exceeds the threshold.
        reasons: Human-readable list of factors that affected the score.
        flags: Machine-readable flag codes for UI/API use.
    """

    score: float
    auto_approve: bool
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def detect_va_compilation(track: Any) -> bool:
    """Detect whether a track is part of a VA (Various Artists) compilation.

    Checks:
        - album_artist is set and differs from artist
        - artist name matches known VA patterns (case-insensitive)

    Args:
        track: Track model instance.

    Returns:
        True if the track appears to be from a VA compilation.
    """
    artist = getattr(track, "artist", None) or ""
    album_artist = getattr(track, "album_artist", None)

    # Check if artist matches VA patterns
    if artist.strip().lower() in _VA_NAMES:
        return True

    # Check if album_artist is set and differs from artist
    return album_artist is not None and album_artist.strip().lower() != artist.strip().lower()


def detect_bootleg_indicators(track: Any) -> list[str]:
    """Detect bootleg, edit, mashup, and other ambiguous attribution indicators.

    Checks the track title and source filename for known patterns.
    'remix' alone is NOT flagged — remixes have clear attribution.

    Args:
        track: Track model instance.

    Returns:
        List of matched indicator strings (empty if none found).
    """
    indicators: list[str] = []
    title = getattr(track, "title", None) or ""
    source_path = getattr(track, "source_path", None) or ""
    filename = Path(source_path).stem if source_path else ""

    search_text = f"{title} {filename}"

    for pattern in _BOOTLEG_PATTERNS:
        match = re.search(pattern, search_text, re.IGNORECASE)
        if match:
            indicators.append(match.group())

    return indicators


def score_track(
    track: Any,
    resolved_path: ResolvedPath,
    preference_rules: list[Any],
    threshold: float = 0.7,
) -> ConfidenceResult:
    """Score a track's confidence for automatic organisation.

    Starts at a base score of 0.5 and applies deltas for various criteria.
    The final score is clamped to [0.0, 1.0].

    Args:
        track: Track model instance.
        resolved_path: Result of template resolution for this track.
        preference_rules: List of applicable PreferenceRule instances.
        threshold: Score at or above which auto_approve is True.

    Returns:
        ConfidenceResult with score, auto_approve flag, reasons, and flags.
    """
    score = 0.5
    reasons: list[str] = []
    flags: list[str] = []

    # All template variables resolved directly → +0.3
    if not resolved_path.fallbacks_used and not resolved_path.unresolved:
        score += 0.3
        reasons.append("All template variables resolved directly")

    # Single fallback used → neutral (0.0)
    if len(resolved_path.fallbacks_used) == 1:
        reasons.append(f"Single fallback used for '{resolved_path.fallbacks_used[0]}'")

    # Multiple fallbacks (≥2) → -0.3
    if len(resolved_path.fallbacks_used) >= 2:
        score -= 0.3
        reasons.append(f"Multiple fallbacks used ({len(resolved_path.fallbacks_used)} variables)")
        flags.append("multiple_fallbacks")

    # Unresolved variable → -0.5
    if resolved_path.unresolved:
        score -= 0.5
        reasons.append(f"Unresolved variable(s): {', '.join(resolved_path.unresolved)}")
        flags.append("unresolved_variable")

    # AI confidence effects
    ai_confidence = getattr(track, "ai_confidence", None)
    if ai_confidence == "high":
        score += 0.2
        reasons.append("High AI confidence")
    elif ai_confidence == "low":
        score -= 0.2
        reasons.append("Low AI confidence")
        flags.append("low_ai_confidence")

    # VA compilation detection
    if detect_va_compilation(track):
        score -= 0.2
        reasons.append("VA compilation detected")
        flags.append("va_detected")

    # Bootleg/edit indicators
    bootleg_indicators = detect_bootleg_indicators(track)
    if bootleg_indicators:
        score -= 0.2
        reasons.append(f"Bootleg/edit indicators: {', '.join(bootleg_indicators)}")
        flags.append("bootleg_indicators")

    # Preference rule match → +0.3
    artist = getattr(track, "artist", None) or ""
    artist_key = artist.strip().lower()
    has_preference_match = False
    for rule in preference_rules:
        if rule.rule_type == "artist_folder" and rule.key == artist_key:
            has_preference_match = True
            break
        if rule.rule_type == "custom_path" and rule.key == str(track.id):
            has_preference_match = True
            break

    if has_preference_match:
        score += 0.3
        reasons.append("Preference rule exists for this track/artist")
        flags.append("preference_rule_match")

    # Missing genre after AI tagging → -0.2
    genre = getattr(track, "genre", None)
    if not genre and ai_confidence is not None:
        score -= 0.2
        reasons.append("Missing genre after AI tagging")
        flags.append("missing_genre_post_ai")

    # Clamp to [0.0, 1.0]
    score = max(0.0, min(1.0, score))

    return ConfidenceResult(
        score=round(score, 2),
        auto_approve=score >= threshold,
        reasons=reasons,
        flags=flags,
    )
