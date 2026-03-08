"""Tests for key notation mapping — Camelot, Open Key, and classical conversions."""

import pytest

from backend.services.key_notation import (
    camelot_to_classical,
    classical_to_camelot,
    key_to_camelot_str,
    key_to_display,
    key_to_open_key_str,
    parse_key_tag,
)

# Complete truth table for all 24 keys
FULL_KEY_TABLE = [
    # (internal_int, camelot_str, open_key_str, classical_name)
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


class TestCamelotToClassical:
    """Test camelot_to_classical() for all 24 keys."""

    @pytest.mark.parametrize(
        "key_int, _camelot, _open_key, classical",
        FULL_KEY_TABLE,
        ids=[f"key_{k[0]}" for k in FULL_KEY_TABLE],
    )
    def test_all_keys(self, key_int, _camelot, _open_key, classical):
        assert camelot_to_classical(key_int) == classical

    def test_invalid_key_zero(self):
        with pytest.raises(ValueError, match="out of range"):
            camelot_to_classical(0)

    def test_invalid_key_25(self):
        with pytest.raises(ValueError, match="out of range"):
            camelot_to_classical(25)


class TestKeyToCamelotStr:
    """Test key_to_camelot_str() for all 24 keys."""

    @pytest.mark.parametrize(
        "key_int, camelot, _open_key, _classical",
        FULL_KEY_TABLE,
        ids=[f"key_{k[0]}" for k in FULL_KEY_TABLE],
    )
    def test_all_keys(self, key_int, camelot, _open_key, _classical):
        assert key_to_camelot_str(key_int) == camelot


class TestKeyToOpenKeyStr:
    """Test key_to_open_key_str() for all 24 keys."""

    @pytest.mark.parametrize(
        "key_int, _camelot, open_key, _classical",
        FULL_KEY_TABLE,
        ids=[f"key_{k[0]}" for k in FULL_KEY_TABLE],
    )
    def test_all_keys(self, key_int, _camelot, open_key, _classical):
        assert key_to_open_key_str(key_int) == open_key


class TestClassicalToCamelot:
    """Test classical_to_camelot() with various input formats."""

    @pytest.mark.parametrize(
        "key_int, _camelot, _open_key, classical",
        FULL_KEY_TABLE,
        ids=[f"key_{k[0]}" for k in FULL_KEY_TABLE],
    )
    def test_standard_names(self, key_int, _camelot, _open_key, classical):
        assert classical_to_camelot(classical) == key_int

    # Sharp/flat aliases
    @pytest.mark.parametrize(
        "alias, expected",
        [
            ("G# minor", 1),  # G♯ minor = A♭ minor
            ("Ab minor", 1),
            ("Abm", 1),
            ("G#m", 1),
            ("Eb minor", 3),
            ("D# minor", 3),
            ("D#m", 3),
            ("F# major", 4),
            ("Gb major", 4),
            ("Bb minor", 5),
            ("A# minor", 5),
            ("A#m", 5),
            ("Db major", 6),
            ("C# major", 6),
            ("Ab major", 8),
            ("G# major", 8),
            ("Eb major", 10),
            ("D# major", 10),
            ("Bb major", 12),
            ("A# major", 12),
            ("F# minor", 21),
            ("Gb minor", 21),
            ("Gbm", 21),
            ("Db minor", 23),
            ("C# minor", 23),
            ("C#m", 23),
        ],
    )
    def test_sharp_flat_aliases(self, alias, expected):
        assert classical_to_camelot(alias) == expected

    # Abbreviated forms
    @pytest.mark.parametrize(
        "abbrev, expected",
        [
            ("C", 16),  # C major (no qualifier = major)
            ("Cm", 9),  # C minor
            ("Am", 15),
            ("A", 22),
            ("Em", 17),
            ("E", 24),
            ("G", 18),
            ("Gm", 11),
            ("D", 20),
            ("Dm", 13),
            ("F", 14),
            ("Fm", 7),
            ("B", 2),
            ("Bm", 19),
        ],
    )
    def test_abbreviated_forms(self, abbrev, expected):
        assert classical_to_camelot(abbrev) == expected

    def test_unknown_key_returns_none(self):
        assert classical_to_camelot("XYZ") is None

    def test_empty_string_returns_none(self):
        assert classical_to_camelot("") is None


class TestParseKeyTag:
    """Test parse_key_tag() with various tag formats."""

    # Camelot notation
    @pytest.mark.parametrize(
        "tag, expected",
        [
            ("1A", 1),
            ("1B", 2),
            ("8B", 16),
            ("12B", 24),
            ("12A", 23),
            ("1a", 1),  # case insensitive
            ("8b", 16),
        ],
    )
    def test_camelot_notation(self, tag, expected):
        assert parse_key_tag(tag) == expected

    # Open Key notation
    @pytest.mark.parametrize(
        "tag, expected",
        [
            ("6m", 1),
            ("6d", 2),
            ("1m", 15),
            ("1d", 16),
            ("5d", 24),
            ("1M", 15),  # case insensitive
            ("1D", 16),
        ],
    )
    def test_open_key_notation(self, tag, expected):
        assert parse_key_tag(tag) == expected

    # Classical notation
    @pytest.mark.parametrize(
        "tag, expected",
        [
            ("C major", 16),
            ("A minor", 15),
            ("Cm", 9),
            ("Am", 15),
            ("C", 16),
            ("Abm", 1),
            ("F#m", 21),
        ],
    )
    def test_classical_notation(self, tag, expected):
        assert parse_key_tag(tag) == expected

    # Edge cases
    def test_none_returns_none(self):
        assert parse_key_tag(None) is None  # type: ignore[arg-type]

    def test_empty_string_returns_none(self):
        assert parse_key_tag("") is None

    def test_garbage_returns_none(self):
        assert parse_key_tag("not_a_key") is None

    def test_numeric_string_returns_none(self):
        assert parse_key_tag("42") is None

    def test_whitespace_handling(self):
        assert parse_key_tag("  8B  ") == 16
        assert parse_key_tag(" C minor ") == 9


class TestKeyToDisplay:
    """Test key_to_display() with all three notation preferences."""

    def test_camelot_notation(self):
        assert key_to_display(1, "camelot") == "1A"
        assert key_to_display(16, "camelot") == "8B"

    def test_open_key_notation(self):
        assert key_to_display(1, "open_key") == "6m"
        assert key_to_display(16, "open_key") == "1d"

    def test_classical_notation(self):
        assert key_to_display(1, "classical") == "A♭ minor"
        assert key_to_display(16, "classical") == "C major"

    def test_none_key_returns_empty(self):
        assert key_to_display(None, "camelot") == ""  # type: ignore[arg-type]

    def test_unknown_notation_defaults_to_camelot(self):
        assert key_to_display(1, "unknown") == "1A"
