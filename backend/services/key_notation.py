"""Key notation mapping — Camelot, Open Key, and classical key conversions.

Internal representation: integer 1–24 following the Camelot wheel.
All conversions go through this internal representation.
"""

import re

# Complete mapping table: (internal_int, camelot_str, open_key_str, classical_name)
_KEY_TABLE: list[tuple[int, str, str, str]] = [
    (1, "1A", "6m", "A♭ minor"),
    (2, "1B", "6d", "B major"),
    (3, "2A", "7m", "E♭ minor"),
    (4, "2B", "7d", "F♯ major"),
    (5, "3A", "8m", "B♭ minor"),
    (6, "3B", "8d", "D♭ major"),
    (7, "4A", "9m", "F minor"),
    (8, "4B", "9d", "A♭ major"),
    (9, "5A", "10m", "C minor"),
    (10, "5B", "10d", "E♭ major"),
    (11, "6A", "11m", "G minor"),
    (12, "6B", "11d", "B♭ major"),
    (13, "7A", "12m", "D minor"),
    (14, "7B", "12d", "F major"),
    (15, "8A", "1m", "A minor"),
    (16, "8B", "1d", "C major"),
    (17, "9A", "2m", "E minor"),
    (18, "9B", "2d", "G major"),
    (19, "10A", "3m", "B minor"),
    (20, "10B", "3d", "D major"),
    (21, "11A", "4m", "F♯ minor"),
    (22, "11B", "4d", "A major"),
    (23, "12A", "5m", "D♭ minor"),
    (24, "12B", "5d", "E major"),
]

# Build lookup dicts
_INT_TO_CAMELOT: dict[int, str] = {row[0]: row[1] for row in _KEY_TABLE}
_INT_TO_OPEN_KEY: dict[int, str] = {row[0]: row[2] for row in _KEY_TABLE}
_INT_TO_CLASSICAL: dict[int, str] = {row[0]: row[3] for row in _KEY_TABLE}

# Reverse lookups (lowercase for case-insensitive matching)
_CAMELOT_TO_INT: dict[str, int] = {row[1].lower(): row[0] for row in _KEY_TABLE}
_OPEN_KEY_TO_INT: dict[str, int] = {row[2].lower(): row[0] for row in _KEY_TABLE}

# Classical name lookup — build from the table plus common aliases
_CLASSICAL_TO_INT: dict[str, int] = {}

# Enharmonic equivalents for building aliases
_ENHARMONIC_MAP: dict[str, list[str]] = {
    "A♭": ["Ab", "G#"],
    "E♭": ["Eb", "D#"],
    "F♯": ["F#", "Gb"],
    "B♭": ["Bb", "A#"],
    "D♭": ["Db", "C#"],
}

# Note name to pitch classes used in classical names (no accidentals)
_PLAIN_NOTES = ["C", "D", "E", "F", "G", "A", "B"]


def _build_classical_lookup() -> None:
    """Build the classical key name to internal int lookup table."""
    for key_int, _, _, classical in _KEY_TABLE:
        # Standard name: "A♭ minor" → key_int
        _CLASSICAL_TO_INT[classical.lower()] = key_int

        # Determine root and quality
        parts = classical.split(" ")
        root = parts[0]
        quality = parts[1]  # "major" or "minor"

        # ASCII aliases for the standard name
        for unicode_char, ascii_variants in _ENHARMONIC_MAP.items():
            if unicode_char in root:
                for variant in ascii_variants:
                    ascii_root = root.replace(unicode_char, variant)
                    # Full form: "Ab minor"
                    _CLASSICAL_TO_INT[f"{ascii_root} {quality}".lower()] = key_int
                    # Abbreviated: "Abm" for minor, "Ab" for major
                    if quality == "minor":
                        _CLASSICAL_TO_INT[f"{ascii_root}m".lower()] = key_int
                    else:
                        _CLASSICAL_TO_INT[ascii_root.lower()] = key_int

        # Abbreviated form of standard name
        if quality == "minor":
            # "A♭m" style — use ASCII version
            ascii_root = root
            for unicode_char, ascii_variants in _ENHARMONIC_MAP.items():
                if unicode_char in root:
                    ascii_root = root.replace(unicode_char, ascii_variants[0])
            _CLASSICAL_TO_INT[f"{ascii_root}m".lower()] = key_int
        else:
            # Plain root for major: "B" = "B major"
            ascii_root = root
            for unicode_char, ascii_variants in _ENHARMONIC_MAP.items():
                if unicode_char in root:
                    ascii_root = root.replace(unicode_char, ascii_variants[0])
            _CLASSICAL_TO_INT[ascii_root.lower()] = key_int

    # Add plain note abbreviations (no accidentals)
    # These map to their natural key: "C" = C major, "Cm" = C minor
    for note in _PLAIN_NOTES:
        # Check if already added (some might have been via the table)
        for key_int, _, _, classical in _KEY_TABLE:
            parts = classical.split(" ")
            root = parts[0]
            quality = parts[1]
            # Match plain notes exactly (no accidentals in root)
            if root == note:
                if quality == "major":
                    _CLASSICAL_TO_INT[note.lower()] = key_int
                elif quality == "minor":
                    _CLASSICAL_TO_INT[f"{note}m".lower()] = key_int


_build_classical_lookup()


def _validate_key_int(key_int: int) -> None:
    """Validate that key_int is in the valid range 1–24.

    Args:
        key_int: Internal key integer.

    Raises:
        ValueError: If key_int is out of range.
    """
    if key_int < 1 or key_int > 24:
        raise ValueError(f"Key integer {key_int} out of range (must be 1–24)")


def camelot_to_classical(key_int: int) -> str:
    """Convert internal key integer to classical key name.

    Args:
        key_int: Internal key integer (1–24).

    Returns:
        Classical key name (e.g. "A♭ minor", "C major").

    Raises:
        ValueError: If key_int is out of range.
    """
    _validate_key_int(key_int)
    return _INT_TO_CLASSICAL[key_int]


def key_to_camelot_str(key_int: int) -> str:
    """Convert internal key integer to Camelot notation string.

    Args:
        key_int: Internal key integer (1–24).

    Returns:
        Camelot notation string (e.g. "1A", "8B").

    Raises:
        ValueError: If key_int is out of range.
    """
    _validate_key_int(key_int)
    return _INT_TO_CAMELOT[key_int]


def key_to_open_key_str(key_int: int) -> str:
    """Convert internal key integer to Open Key notation string.

    Args:
        key_int: Internal key integer (1–24).

    Returns:
        Open Key notation string (e.g. "6m", "1d").

    Raises:
        ValueError: If key_int is out of range.
    """
    _validate_key_int(key_int)
    return _INT_TO_OPEN_KEY[key_int]


def classical_to_camelot(key_name: str) -> int | None:
    """Convert a classical key name to internal key integer.

    Handles standard names ("A♭ minor"), ASCII variants ("Ab minor"),
    and abbreviated forms ("Abm", "C", "Cm").

    Args:
        key_name: Classical key name string.

    Returns:
        Internal key integer (1–24), or None if not recognized.
    """
    if not key_name:
        return None
    return _CLASSICAL_TO_INT.get(key_name.strip().lower())


# Regex patterns for parsing key tags
_CAMELOT_PATTERN = re.compile(r"^(\d{1,2})(a|b)$", re.IGNORECASE)
_OPEN_KEY_PATTERN = re.compile(r"^(\d{1,2})(m|d)$", re.IGNORECASE)


def parse_key_tag(tag_value: str | None) -> int | None:
    """Parse a key tag value from any notation into internal integer.

    Handles Camelot ("8B"), Open Key ("1d"), classical ("C major", "Cm"),
    and ASCII variants. Returns None for unparseable values.

    Args:
        tag_value: Raw key tag string from audio file.

    Returns:
        Internal key integer (1–24), or None if unparseable.
    """
    if tag_value is None:
        return None

    tag_value = tag_value.strip()
    if not tag_value:
        return None

    # Try Camelot notation: "8B", "1A", etc.
    camelot_match = _CAMELOT_PATTERN.match(tag_value)
    if camelot_match:
        result = _CAMELOT_TO_INT.get(tag_value.lower())
        if result is not None:
            return result

    # Try Open Key notation: "6m", "1d", etc.
    open_key_match = _OPEN_KEY_PATTERN.match(tag_value)
    if open_key_match:
        result = _OPEN_KEY_TO_INT.get(tag_value.lower())
        if result is not None:
            return result

    # Try classical notation (full or abbreviated)
    result = classical_to_camelot(tag_value)
    if result is not None:
        return result

    return None


def key_to_display(key_int: int | None, notation: str) -> str:
    """Convert internal key integer to display string in the given notation.

    Args:
        key_int: Internal key integer (1–24), or None.
        notation: Display notation preference: "camelot", "open_key", or "classical".

    Returns:
        Display string, or empty string if key_int is None.
    """
    if key_int is None:
        return ""

    if notation == "open_key":
        return key_to_open_key_str(key_int)
    elif notation == "classical":
        return camelot_to_classical(key_int)
    else:
        return key_to_camelot_str(key_int)
