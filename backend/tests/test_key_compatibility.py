"""Tests for key compatibility module — TDD.

Tests written before implementation. Covers Camelot wheel compatibility
rules: same key, adjacent, relative major/minor, energy boost/drop,
wrap-around, and invalid inputs.
"""

import pytest

from backend.services.key_compatibility import (
    are_keys_compatible,
    get_compatibility_type,
    get_compatible_keys,
)


class TestAreKeysCompatible:
    """Tests for are_keys_compatible()."""

    def test_same_key(self):
        """Same key is always compatible."""
        assert are_keys_compatible(1, 1) is True
        assert are_keys_compatible(15, 15) is True
        assert are_keys_compatible(24, 24) is True

    def test_adjacent_same_letter_up(self):
        """Adjacent +1 on the wheel, same letter (A→A or B→B)."""
        # 1A (int 1) → 2A (int 3) — adjacent minor keys
        assert are_keys_compatible(1, 3) is True
        # 8A (int 15) → 9A (int 17) — adjacent minor keys
        assert are_keys_compatible(15, 17) is True
        # 1B (int 2) → 2B (int 4) — adjacent major keys
        assert are_keys_compatible(2, 4) is True

    def test_adjacent_same_letter_down(self):
        """Adjacent -1 on the wheel, same letter."""
        # 2A (int 3) → 1A (int 1)
        assert are_keys_compatible(3, 1) is True
        # 9A (int 17) → 8A (int 15)
        assert are_keys_compatible(17, 15) is True

    def test_relative_major_minor(self):
        """Same number, different letter (A↔B)."""
        # 1A (int 1) ↔ 1B (int 2)
        assert are_keys_compatible(1, 2) is True
        assert are_keys_compatible(2, 1) is True
        # 8A (int 15) ↔ 8B (int 16)
        assert are_keys_compatible(15, 16) is True
        assert are_keys_compatible(16, 15) is True
        # 12A (int 23) ↔ 12B (int 24)
        assert are_keys_compatible(23, 24) is True

    def test_energy_boost(self):
        """Energy boost: +1 number and switch letter."""
        # 8A (int 15) → 9B (int 18)
        assert are_keys_compatible(15, 18) is True
        # 8B (int 16) → 9A (int 17)
        assert are_keys_compatible(16, 17) is True

    def test_energy_drop(self):
        """Energy drop: -1 number and switch letter."""
        # 8A (int 15) → 7B (int 14)
        assert are_keys_compatible(15, 14) is True
        # 8B (int 16) → 7A (int 13)
        assert are_keys_compatible(16, 13) is True

    def test_wrap_around_12_to_1(self):
        """Wheel wraps: 12 → 1 is adjacent."""
        # 12A (int 23) → 1A (int 1)
        assert are_keys_compatible(23, 1) is True
        # 1A (int 1) → 12A (int 23)
        assert are_keys_compatible(1, 23) is True
        # 12B (int 24) → 1B (int 2)
        assert are_keys_compatible(24, 2) is True
        # 1B (int 2) → 12B (int 24)
        assert are_keys_compatible(2, 24) is True

    def test_wrap_around_energy_boost(self):
        """Energy boost wraps: 12A → 1B, 12B → 1A."""
        # 12A (int 23) → 1B (int 2) — energy boost
        assert are_keys_compatible(23, 2) is True
        # 12B (int 24) → 1A (int 1) — energy boost
        assert are_keys_compatible(24, 1) is True

    def test_wrap_around_energy_drop(self):
        """Energy drop wraps: 1A → 12B, 1B → 12A."""
        # 1A (int 1) → 12B (int 24) — energy drop
        assert are_keys_compatible(1, 24) is True
        # 1B (int 2) → 12A (int 23) — energy drop
        assert are_keys_compatible(2, 23) is True

    def test_not_compatible(self):
        """Keys that are not harmonically compatible."""
        # 1A (int 1) → 3A (int 5) — two steps apart
        assert are_keys_compatible(1, 5) is False
        # 1A (int 1) → 6B (int 12) — distant
        assert are_keys_compatible(1, 12) is False
        # 8A (int 15) → 4B (int 8) — distant
        assert are_keys_compatible(15, 8) is False

    def test_invalid_key_raises(self):
        """Invalid key values raise ValueError."""
        with pytest.raises(ValueError):
            are_keys_compatible(0, 1)
        with pytest.raises(ValueError):
            are_keys_compatible(1, 25)
        with pytest.raises(ValueError):
            are_keys_compatible(-1, 5)


class TestGetCompatibleKeys:
    """Tests for get_compatible_keys()."""

    def test_returns_list(self):
        """Returns a list of compatible key integers."""
        result = get_compatible_keys(15)  # 8A
        assert isinstance(result, list)

    def test_count(self):
        """Each key has exactly 5 compatible keys (same, adj+, adj-, relative, boost, drop)."""
        for key in range(1, 25):
            result = get_compatible_keys(key)
            assert len(result) == 5, f"Key {key} has {len(result)} compatible keys, expected 5"

    def test_8a_compatible_keys(self):
        """8A (int 15) compatible with 7A, 9A, 8B, 9B, 7B."""
        result = set(get_compatible_keys(15))
        expected = {
            13,  # 7A — adjacent down
            17,  # 9A — adjacent up
            16,  # 8B — relative major
            18,  # 9B — energy boost
            14,  # 7B — energy drop
        }
        assert result == expected

    def test_1a_compatible_keys_with_wrap(self):
        """1A (int 1) wraps around the wheel."""
        result = set(get_compatible_keys(1))
        expected = {
            23,  # 12A — adjacent down (wrap)
            3,  # 2A — adjacent up
            2,  # 1B — relative major
            4,  # 2B — energy boost
            24,  # 12B — energy drop (wrap)
        }
        assert result == expected

    def test_12b_compatible_keys_with_wrap(self):
        """12B (int 24) wraps around the wheel."""
        result = set(get_compatible_keys(24))
        expected = {
            22,  # 11B — adjacent down
            2,  # 1B — adjacent up (wrap)
            23,  # 12A — relative minor
            1,  # 1A — energy boost (wrap)
            21,  # 11A — energy drop
        }
        assert result == expected

    def test_all_24_keys(self):
        """Every key from 1–24 returns valid results."""
        for key in range(1, 25):
            result = get_compatible_keys(key)
            assert all(1 <= k <= 24 for k in result)

    def test_does_not_include_self(self):
        """The compatible keys list does not include the key itself."""
        for key in range(1, 25):
            result = get_compatible_keys(key)
            assert key not in result

    def test_invalid_key_raises(self):
        """Invalid key raises ValueError."""
        with pytest.raises(ValueError):
            get_compatible_keys(0)
        with pytest.raises(ValueError):
            get_compatible_keys(25)


class TestGetCompatibilityType:
    """Tests for get_compatibility_type()."""

    def test_same_key(self):
        assert get_compatibility_type(15, 15) == "same"

    def test_adjacent(self):
        # 8A → 7A (adjacent down)
        assert get_compatibility_type(15, 13) == "adjacent"
        # 8A → 9A (adjacent up)
        assert get_compatibility_type(15, 17) == "adjacent"

    def test_relative_major_minor(self):
        # 8A ↔ 8B
        assert get_compatibility_type(15, 16) == "relative_major_minor"
        assert get_compatibility_type(16, 15) == "relative_major_minor"

    def test_energy_boost(self):
        # 8A → 9B
        assert get_compatibility_type(15, 18) == "energy_boost"
        # 8B → 9A
        assert get_compatibility_type(16, 17) == "energy_boost"

    def test_energy_drop(self):
        # 8A → 7B
        assert get_compatibility_type(15, 14) == "energy_drop"
        # 8B → 7A
        assert get_compatibility_type(16, 13) == "energy_drop"

    def test_not_compatible_returns_none(self):
        assert get_compatibility_type(1, 5) is None
        assert get_compatibility_type(15, 8) is None

    def test_wrap_around_adjacent(self):
        # 12A → 1A (adjacent wrap)
        assert get_compatibility_type(23, 1) == "adjacent"
        # 1A → 12A
        assert get_compatibility_type(1, 23) == "adjacent"

    def test_wrap_around_energy_boost(self):
        # 12A → 1B (energy boost wrap)
        assert get_compatibility_type(23, 2) == "energy_boost"

    def test_wrap_around_energy_drop(self):
        # 1A → 12B (energy drop wrap)
        assert get_compatibility_type(1, 24) == "energy_drop"

    def test_invalid_key_raises(self):
        with pytest.raises(ValueError):
            get_compatibility_type(0, 1)
