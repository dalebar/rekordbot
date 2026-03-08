"""Key compatibility — Camelot wheel harmonic mixing rules.

Pure logic module. No I/O, no database access. Uses the internal key
integer representation (1–24) from key_notation.py.

Internal representation:
    Odd integers (1, 3, 5, ..., 23) = minor keys (A column): 1A–12A
    Even integers (2, 4, 6, ..., 24) = major keys (B column): 1B–12B
    Camelot number = (int_key + 1) // 2
    Letter: A if odd, B if even
"""


def _validate(key: int) -> None:
    """Validate key is in range 1–24."""
    if key < 1 or key > 24:
        raise ValueError(f"Key integer {key} out of range (must be 1–24)")


def _camelot_number(key: int) -> int:
    """Extract the Camelot wheel number (1–12) from internal int."""
    return (key + 1) // 2


def _is_minor(key: int) -> bool:
    """True if key is minor (A column) — odd integers."""
    return key % 2 == 1


def _from_camelot(number: int, minor: bool) -> int:
    """Convert Camelot number + minor flag back to internal int."""
    return number * 2 - 1 if minor else number * 2


def _wrap(number: int) -> int:
    """Wrap Camelot number to 1–12 range."""
    return ((number - 1) % 12) + 1


def are_keys_compatible(key_a: int, key_b: int) -> bool:
    """Check if two keys are harmonically compatible on the Camelot wheel.

    Compatible transitions:
        - Same key
        - Adjacent (±1 on wheel, same letter)
        - Relative major/minor (same number, different letter)
        - Energy boost (+1 number, switch letter)
        - Energy drop (-1 number, switch letter)

    Args:
        key_a: Internal key integer (1–24).
        key_b: Internal key integer (1–24).

    Returns:
        True if the keys are compatible for harmonic mixing.

    Raises:
        ValueError: If either key is out of range.
    """
    _validate(key_a)
    _validate(key_b)
    return get_compatibility_type(key_a, key_b) is not None


def get_compatible_keys(key: int) -> list[int]:
    """Return all compatible keys for a given key (excluding itself).

    Args:
        key: Internal key integer (1–24).

    Returns:
        List of 5 compatible key integers.

    Raises:
        ValueError: If key is out of range.
    """
    _validate(key)

    num = _camelot_number(key)
    minor = _is_minor(key)

    results = [
        # Adjacent down
        _from_camelot(_wrap(num - 1), minor),
        # Adjacent up
        _from_camelot(_wrap(num + 1), minor),
        # Relative major/minor (same number, opposite letter)
        _from_camelot(num, not minor),
        # Energy boost (+1, switch letter)
        _from_camelot(_wrap(num + 1), not minor),
        # Energy drop (-1, switch letter)
        _from_camelot(_wrap(num - 1), not minor),
    ]

    return results


def get_compatibility_type(key_a: int, key_b: int) -> str | None:
    """Determine the type of harmonic compatibility between two keys.

    Args:
        key_a: Internal key integer (1–24).
        key_b: Internal key integer (1–24).

    Returns:
        Compatibility type string, or None if not compatible.
        Types: "same", "adjacent", "relative_major_minor",
               "energy_boost", "energy_drop"

    Raises:
        ValueError: If either key is out of range.
    """
    _validate(key_a)
    _validate(key_b)

    if key_a == key_b:
        return "same"

    num_a = _camelot_number(key_a)
    num_b = _camelot_number(key_b)
    minor_a = _is_minor(key_a)
    minor_b = _is_minor(key_b)

    # Check if numbers are adjacent on the wheel (with wrap)
    num_diff = (num_b - num_a) % 12

    if minor_a == minor_b:
        # Same letter
        if num_a == num_b:
            # Same number — but key_a != key_b already checked, so unreachable
            return None  # pragma: no cover
        if num_diff == 1 or num_diff == 11:
            return "adjacent"
    else:
        # Different letter
        if num_a == num_b:
            return "relative_major_minor"
        if num_diff == 1:
            return "energy_boost"
        if num_diff == 11:  # -1 mod 12
            return "energy_drop"

    return None
