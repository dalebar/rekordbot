"""Tests for preference store — rule storage and application logic.

TDD for apply_rules(). CRUD operations tested after implementation.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.models.preference_rule import PreferenceRule
from backend.services.preference_store import apply_rules
from backend.services.template_engine import ResolvedPath

# --- Helper ---


def _make_track(**kwargs):
    """Create a mock Track with the given attributes."""
    track = MagicMock()
    defaults = {
        "id": 1,
        "title": "Test Track",
        "artist": "Test Artist",
        "album": "Test Album",
        "album_artist": None,
        "output_format": "aiff",
        "file_path": "/library/imports/2026-03-08/test.aiff",
    }
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(track, k, v)
    return track


def _make_resolved_path(
    path: str = "/library/Test Artist/Test Album/Test Track.aiff",
    components: dict[str, str] | None = None,
    fallbacks_used: list[str] | None = None,
    unresolved: list[str] | None = None,
):
    """Create a ResolvedPath."""
    return ResolvedPath(
        path=Path(path),
        fallbacks_used=fallbacks_used or [],
        unresolved=unresolved or [],
        components=components
        or {"artist": "Test Artist", "album": "Test Album", "title": "Test Track"},
    )


def _make_rule(rule_type: str, key: str, value: str) -> PreferenceRule:
    """Create a PreferenceRule without DB persistence."""
    rule = PreferenceRule()
    rule.id = 1
    rule.rule_type = rule_type
    rule.key = key
    rule.value = value
    return rule


# --- apply_rules() tests (TDD) ---


class TestApplyRules:
    """Test preference rule application to resolved paths."""

    def test_no_rules(self):
        """No rules → path unchanged."""
        track = _make_track()
        resolved = _make_resolved_path()
        result = apply_rules(track, resolved, [], Path("/library"))
        assert result.path == resolved.path

    def test_custom_path_overrides_everything(self):
        """custom_path rule overrides the entire resolved path."""
        track = _make_track(id=42)
        resolved = _make_resolved_path()
        rule = _make_rule("custom_path", "42", "Specials/That One Track.aiff")
        result = apply_rules(track, resolved, [rule], Path("/library"))
        assert result.path == Path("/library/Specials/That One Track.aiff")

    def test_artist_folder_replaces_artist(self):
        """artist_folder rule replaces the artist component in the path."""
        track = _make_track(artist="aphex twin")
        resolved = _make_resolved_path(
            path="/library/aphex twin/Test Album/Test Track.aiff",
            components={"artist": "aphex twin", "album": "Test Album", "title": "Test Track"},
        )
        rule = _make_rule("artist_folder", "aphex twin", "Aphex Twin")
        result = apply_rules(track, resolved, [rule], Path("/library"))
        assert "Aphex Twin" in str(result.path)
        assert "aphex twin" not in str(result.path)

    def test_va_handling_use_album_artist(self):
        """va_handling with 'use_album_artist' replaces artist with album_artist."""
        track = _make_track(
            artist="Various Artists",
            album="Fabric 99",
            album_artist="Shanti Celeste",
        )
        resolved = _make_resolved_path(
            path="/library/Various Artists/Fabric 99/Test Track.aiff",
            components={
                "artist": "Various Artists",
                "album": "Fabric 99",
                "title": "Test Track",
            },
        )
        rule = _make_rule("va_handling", "fabric 99", "use_album_artist")
        result = apply_rules(track, resolved, [rule], Path("/library"))
        assert "Shanti Celeste" in str(result.path)

    def test_va_handling_use_album(self):
        """va_handling with 'use_album' replaces artist with album name."""
        track = _make_track(
            artist="Various Artists",
            album="Fabric 99",
        )
        resolved = _make_resolved_path(
            path="/library/Various Artists/Fabric 99/Test Track.aiff",
            components={
                "artist": "Various Artists",
                "album": "Fabric 99",
                "title": "Test Track",
            },
        )
        rule = _make_rule("va_handling", "fabric 99", "use_album")
        result = apply_rules(track, resolved, [rule], Path("/library"))
        assert "Fabric 99" in str(result.path)
        assert "Various Artists" not in str(result.path)

    def test_va_handling_use_literal(self):
        """va_handling with 'use_literal:X' uses X as the artist folder."""
        track = _make_track(artist="Various Artists", album="Fabric 99")
        resolved = _make_resolved_path(
            path="/library/Various Artists/Fabric 99/Test Track.aiff",
            components={
                "artist": "Various Artists",
                "album": "Fabric 99",
                "title": "Test Track",
            },
        )
        rule = _make_rule("va_handling", "fabric 99", "use_literal:Compilations")
        result = apply_rules(track, resolved, [rule], Path("/library"))
        assert "Compilations" in str(result.path)

    def test_custom_path_takes_priority_over_artist_folder(self):
        """custom_path rule takes priority over artist_folder."""
        track = _make_track(id=42, artist="Test Artist")
        resolved = _make_resolved_path()
        rules = [
            _make_rule("artist_folder", "test artist", "DJ Test"),
            _make_rule("custom_path", "42", "Specials/Track.aiff"),
        ]
        result = apply_rules(track, resolved, rules, Path("/library"))
        assert result.path == Path("/library/Specials/Track.aiff")

    def test_normalised_key_matching(self):
        """Rule keys are matched case-insensitively."""
        track = _make_track(artist="Aphex Twin")
        resolved = _make_resolved_path(
            path="/library/Aphex Twin/Test Album/Test Track.aiff",
            components={"artist": "Aphex Twin", "album": "Test Album", "title": "Test Track"},
        )
        rule = _make_rule("artist_folder", "aphex twin", "AFX")
        result = apply_rules(track, resolved, [rule], Path("/library"))
        assert "AFX" in str(result.path)


# --- CRUD tests (written after implementation) ---


class TestPreferenceStoreCRUD:
    """Test preference store CRUD operations with DB."""

    def test_create_rule(self, db_session):
        """Create a preference rule."""
        from backend.services.preference_store import create_rule

        rule = create_rule(db_session, "artist_folder", "Aphex Twin", "Aphex Twin")
        assert rule.id is not None
        assert rule.rule_type == "artist_folder"
        assert rule.key == "aphex twin"  # Normalised to lowercase
        assert rule.value == "Aphex Twin"

    def test_get_rule(self, db_session):
        """Get a specific rule by type and key."""
        from backend.services.preference_store import create_rule, get_rule

        create_rule(db_session, "artist_folder", "Calibre", "Calibre")
        result = get_rule(db_session, "artist_folder", "calibre")
        assert result is not None
        assert result.value == "Calibre"

    def test_get_rule_not_found(self, db_session):
        """Get returns None when rule doesn't exist."""
        from backend.services.preference_store import get_rule

        result = get_rule(db_session, "artist_folder", "nonexistent")
        assert result is None

    def test_list_rules(self, db_session):
        """List all rules."""
        from backend.services.preference_store import create_rule, list_rules

        create_rule(db_session, "artist_folder", "Calibre", "Calibre")
        create_rule(db_session, "va_handling", "fabric 99", "use_album_artist")
        rules = list_rules(db_session)
        assert len(rules) >= 2

    def test_list_rules_by_type(self, db_session):
        """List rules filtered by type."""
        from backend.services.preference_store import create_rule, list_rules

        create_rule(db_session, "artist_folder", "Artist1", "Artist1")
        create_rule(db_session, "va_handling", "album1", "use_album")
        rules = list_rules(db_session, rule_type="artist_folder")
        assert all(r.rule_type == "artist_folder" for r in rules)

    def test_delete_rule(self, db_session):
        """Delete a preference rule."""
        from backend.services.preference_store import create_rule, delete_rule, get_rule

        rule = create_rule(db_session, "artist_folder", "ToDelete", "ToDelete")
        delete_rule(db_session, rule.id)
        assert get_rule(db_session, "artist_folder", "todelete") is None

    def test_get_rules_for_track(self, db_session):
        """Get all rules applicable to a track."""
        from backend.services.preference_store import create_rule, get_rules_for_track

        create_rule(db_session, "artist_folder", "test artist", "Test Artist")
        create_rule(db_session, "custom_path", "1", "Specials/track.aiff")

        track = _make_track(id=1, artist="Test Artist")
        rules = get_rules_for_track(db_session, track)
        assert len(rules) >= 1

    def test_duplicate_rule_raises(self, db_session):
        """Creating a duplicate (same type + key) raises an error."""
        from sqlalchemy.exc import IntegrityError

        from backend.services.preference_store import create_rule

        create_rule(db_session, "artist_folder", "Duplicate", "Value1")
        with pytest.raises(IntegrityError):
            create_rule(db_session, "artist_folder", "Duplicate", "Value2")
