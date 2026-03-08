"""Preference store — CRUD and rule application for organisation preferences.

Manages user-created preference rules that govern file organisation decisions.
Rules are created from user actions in the review queue and applied
automatically to future tracks.
"""

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.models.preference_rule import PreferenceRule
from backend.services.template_engine import ResolvedPath

logger = logging.getLogger(__name__)


def get_rule(db_session: Session, rule_type: str, key: str) -> PreferenceRule | None:
    """Look up a specific preference rule by type and key.

    Keys are matched case-insensitively (normalised to lowercase).

    Args:
        db_session: SQLAlchemy session.
        rule_type: Rule type to look up.
        key: Rule key (will be normalised to lowercase).

    Returns:
        PreferenceRule if found, else None.
    """
    normalised_key = key.strip().lower()
    return (
        db_session.query(PreferenceRule)
        .filter(
            PreferenceRule.rule_type == rule_type,
            PreferenceRule.key == normalised_key,
        )
        .first()
    )


def get_rules_for_track(db_session: Session, track: Any) -> list[PreferenceRule]:
    """Find all applicable preference rules for a track.

    Checks for artist_folder, va_handling, and custom_path rules.

    Args:
        db_session: SQLAlchemy session.
        track: Track model instance.

    Returns:
        List of matching PreferenceRule instances.
    """
    rules: list[PreferenceRule] = []

    # Check custom_path for this track ID
    custom = get_rule(db_session, "custom_path", str(track.id))
    if custom:
        rules.append(custom)

    # Check artist_folder for this artist
    artist = getattr(track, "artist", None) or ""
    if artist.strip():
        artist_rule = get_rule(db_session, "artist_folder", artist)
        if artist_rule:
            rules.append(artist_rule)

    # Check va_handling for this album
    album = getattr(track, "album", None) or ""
    if album.strip():
        va_rule = get_rule(db_session, "va_handling", album)
        if va_rule:
            rules.append(va_rule)

    return rules


def create_rule(
    db_session: Session,
    rule_type: str,
    key: str,
    value: str,
) -> PreferenceRule:
    """Create a new preference rule.

    The key is normalised to lowercase with whitespace trimmed.

    Args:
        db_session: SQLAlchemy session.
        rule_type: Rule type (artist_folder, va_handling, custom_path).
        key: Rule key (will be normalised).
        value: Rule value.

    Returns:
        The created PreferenceRule.
    """
    normalised_key = key.strip().lower()
    rule = PreferenceRule(
        rule_type=rule_type,
        key=normalised_key,
        value=value,
    )
    db_session.add(rule)
    db_session.flush()
    logger.info("Created preference rule: %s/%s → %s", rule_type, normalised_key, value)
    return rule


def delete_rule(db_session: Session, rule_id: int) -> None:
    """Delete a preference rule by ID.

    Args:
        db_session: SQLAlchemy session.
        rule_id: ID of the rule to delete.
    """
    rule = db_session.query(PreferenceRule).filter(PreferenceRule.id == rule_id).first()
    if rule:
        logger.info("Deleted preference rule: %s/%s", rule.rule_type, rule.key)
        db_session.delete(rule)
        db_session.flush()


def list_rules(
    db_session: Session,
    rule_type: str | None = None,
) -> list[PreferenceRule]:
    """List all preference rules, optionally filtered by type.

    Args:
        db_session: SQLAlchemy session.
        rule_type: Optional filter by rule type.

    Returns:
        List of PreferenceRule instances.
    """
    query = db_session.query(PreferenceRule)
    if rule_type:
        query = query.filter(PreferenceRule.rule_type == rule_type)
    return query.order_by(PreferenceRule.created_at.desc()).all()


def apply_rules(
    track: Any,
    resolved_path: ResolvedPath,
    rules: list[PreferenceRule],
    output_dir: Path,
) -> ResolvedPath:
    """Apply applicable preference rules to modify a resolved path.

    Rule application order (highest priority first):
    1. custom_path — overrides the entire path
    2. artist_folder — replaces the artist component
    3. va_handling — applies VA compilation handling strategy

    Args:
        track: Track model instance.
        resolved_path: The template-resolved path to modify.
        rules: List of PreferenceRule instances to apply.
        output_dir: Base output directory for custom_path resolution.

    Returns:
        Modified ResolvedPath (may be the same object if no rules apply).
    """
    if not rules:
        return resolved_path

    track_id_str = str(track.id)

    # 1. Check for custom_path (highest priority)
    for rule in rules:
        if rule.rule_type == "custom_path" and rule.key == track_id_str:
            resolved_path.path = output_dir / rule.value
            logger.info("Applied custom_path rule for track %s: %s", track.id, rule.value)
            return resolved_path

    # 2. Check for artist_folder
    artist = getattr(track, "artist", None) or ""
    artist_key = artist.strip().lower()
    for rule in rules:
        if rule.rule_type == "artist_folder" and rule.key == artist_key:
            resolved_path = _apply_artist_folder_rule(
                resolved_path, artist, rule.value, output_dir
            )
            break

    # 3. Check for va_handling
    album = getattr(track, "album", None) or ""
    album_key = album.strip().lower()
    album_artist = getattr(track, "album_artist", None)
    for rule in rules:
        if rule.rule_type == "va_handling" and rule.key == album_key:
            resolved_path = _apply_va_handling_rule(
                resolved_path, rule.value, album, album_artist, output_dir
            )
            break

    return resolved_path


def _apply_artist_folder_rule(
    resolved: ResolvedPath,
    old_artist: str,
    new_artist: str,
    output_dir: Path,
) -> ResolvedPath:
    """Replace the artist component in a resolved path.

    Args:
        resolved: Current resolved path.
        old_artist: Original artist name to replace.
        new_artist: Canonical artist folder name.
        output_dir: Base output directory.

    Returns:
        Modified ResolvedPath with the artist component replaced.
    """
    # Rebuild path by replacing the old artist component
    rel_path = resolved.path.relative_to(output_dir)
    parts = list(rel_path.parts)

    # Find and replace the artist component
    for i, part in enumerate(parts):
        if part == old_artist:
            parts[i] = new_artist
            break

    # Also check components dict
    if "artist" in resolved.components:
        resolved.components["artist"] = new_artist

    resolved.path = output_dir / Path(*parts)
    return resolved


def _apply_va_handling_rule(
    resolved: ResolvedPath,
    strategy: str,
    album: str,
    album_artist: str | None,
    output_dir: Path,
) -> ResolvedPath:
    """Apply a VA handling strategy to the resolved path.

    Strategies:
        - use_album_artist: Replace artist component with album_artist.
        - use_album: Replace artist component with album name.
        - use_literal:X: Replace artist component with literal X.

    Args:
        resolved: Current resolved path.
        strategy: VA handling strategy string.
        album: Album name.
        album_artist: Album artist (may be None).
        output_dir: Base output directory.

    Returns:
        Modified ResolvedPath.
    """
    old_artist = resolved.components.get("artist", "")
    new_artist = old_artist  # Default: no change

    if strategy == "use_album_artist" and album_artist:
        new_artist = album_artist
    elif strategy == "use_album" and album:
        new_artist = album
    elif strategy.startswith("use_literal:"):
        new_artist = strategy[len("use_literal:") :]

    if new_artist != old_artist:
        resolved = _apply_artist_folder_rule(resolved, old_artist, new_artist, output_dir)

    return resolved
