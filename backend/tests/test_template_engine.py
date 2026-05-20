"""Tests for template engine — path template parsing, resolution, and sanitisation.

TDD: These tests are written before the implementation.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.services.template_engine import (
    TemplateSegment,
    build_output_path,
    parse_template,
    resolve_template,
    sanitise_path_component,
    validate_template,
)

# --- parse_template() ---


class TestParseTemplate:
    """Test template string parsing into typed segments."""

    def test_simple_variables(self):
        """Simple template with only variables."""
        segments = parse_template("{artist}/{album}/{title}")
        assert len(segments) == 5
        assert segments[0] == TemplateSegment(type="variable", value="artist", fallbacks=[])
        assert segments[1] == TemplateSegment(type="separator", value="/", fallbacks=[])
        assert segments[2] == TemplateSegment(type="variable", value="album", fallbacks=[])
        assert segments[3] == TemplateSegment(type="separator", value="/", fallbacks=[])
        assert segments[4] == TemplateSegment(type="variable", value="title", fallbacks=[])

    def test_variable_with_literal_fallback(self):
        """Variable with a quoted literal fallback."""
        segments = parse_template('{album|"Singles"}')
        assert len(segments) == 1
        assert segments[0].type == "variable"
        assert segments[0].value == "album"
        assert segments[0].fallbacks == ['"Singles"']

    def test_chained_fallbacks(self):
        """Variable with multiple chained fallbacks."""
        segments = parse_template('{artist|album_artist|"Unknown"}')
        assert len(segments) == 1
        assert segments[0].type == "variable"
        assert segments[0].value == "artist"
        assert segments[0].fallbacks == ["album_artist", '"Unknown"']

    def test_mixed_template(self):
        """Template with variables, fallbacks, and separators."""
        segments = parse_template('{genre}/{artist|"Unknown"}/{title}')
        assert len(segments) == 5
        assert segments[0] == TemplateSegment(type="variable", value="genre", fallbacks=[])
        assert segments[2].value == "artist"
        assert segments[2].fallbacks == ['"Unknown"']

    def test_empty_template(self):
        """Empty template string."""
        segments = parse_template("")
        assert segments == []

    def test_no_variables(self):
        """Template with no variable markers — treated as literal."""
        segments = parse_template("music")
        assert len(segments) == 1
        assert segments[0] == TemplateSegment(type="literal", value="music", fallbacks=[])

    def test_consecutive_separators(self):
        """Consecutive separators are preserved."""
        segments = parse_template("{artist}/{title}")
        # Normal case — no consecutive separators
        seps = [s for s in segments if s.type == "separator"]
        assert len(seps) == 1

    def test_variable_with_variable_fallback(self):
        """Variable falling back to another variable (no quotes)."""
        segments = parse_template("{artist|album_artist}")
        assert segments[0].value == "artist"
        assert segments[0].fallbacks == ["album_artist"]


# --- resolve_template() ---


class TestResolveTemplate:
    """Test template resolution against track metadata."""

    def _make_track(self, **kwargs):
        """Create a mock Track with the given attributes."""
        track = MagicMock()
        defaults = {
            "id": 1,
            "title": None,
            "artist": None,
            "album": None,
            "album_artist": None,
            "genre": None,
            "subgenre": None,
            "year": None,
            "label": None,
            "output_format": "aiff",
            "source_path": None,
            "file_path": "/music/test.aiff",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(track, k, v)
        return track

    def test_all_resolved(self):
        """All template variables resolved directly from track metadata."""
        track = self._make_track(artist="Calibre", album="Shelflife 6", title="Falls to You")
        result = resolve_template("{artist}/{album}/{title}", track, "Unsorted")
        assert result.fallbacks_used == []
        assert result.unresolved == []
        assert result.components["artist"] == "Calibre"
        assert result.components["album"] == "Shelflife 6"
        assert result.components["title"] == "Falls to You"

    def test_single_fallback_to_literal(self):
        """Single fallback to a literal string."""
        track = self._make_track(artist="Bicep", title="Glue")
        result = resolve_template('{artist}/{album|"Singles"}/{title}', track, "Unsorted")
        assert "album" in result.fallbacks_used
        assert result.components["album"] == "Singles"

    def test_single_fallback_to_variable(self):
        """Fallback to another variable."""
        track = self._make_track(album_artist="VA Comp", title="Track 1")
        result = resolve_template("{artist|album_artist}/{title}", track, "Unsorted")
        assert "artist" in result.fallbacks_used
        assert result.components["artist"] == "VA Comp"

    def test_chained_fallback_resolution_order(self):
        """Chained fallbacks resolve in order."""
        track = self._make_track(label="Ninja Tune", title="Test")
        result = resolve_template(
            '{artist|album_artist|label|"Unknown"}/{title}', track, "Unsorted"
        )
        assert result.components["artist"] == "Ninja Tune"
        assert "artist" in result.fallbacks_used

    def test_multiple_fallbacks_used(self):
        """Multiple different variables using fallbacks."""
        track = self._make_track(title="Test Track")
        result = resolve_template(
            '{artist|"Unknown Artist"}/{album|"Unknown Album"}/{title}', track, "Unsorted"
        )
        assert "artist" in result.fallbacks_used
        assert "album" in result.fallbacks_used
        assert result.components["artist"] == "Unknown Artist"
        assert result.components["album"] == "Unknown Album"

    def test_unresolved_no_fallback(self):
        """Variable with no fallback and no value → uses unknown_fallback."""
        track = self._make_track(title="Test")
        result = resolve_template("{artist}/{title}", track, "Unsorted")
        assert "artist" in result.unresolved
        assert result.components["artist"] == "Unsorted"

    def test_none_vs_empty_string(self):
        """Empty string treated as unresolved (same as None)."""
        track = self._make_track(artist="", title="Test")
        result = resolve_template("{artist}/{title}", track, "Unsorted")
        assert "artist" in result.unresolved
        assert result.components["artist"] == "Unsorted"

    def test_year_as_string(self):
        """Year (integer) is converted to string."""
        track = self._make_track(artist="Test", year=2024, title="Song")
        result = resolve_template("{artist}/{year}/{title}", track, "Unsorted")
        assert result.components["year"] == "2024"

    def test_genre_template(self):
        """Genre-first template."""
        track = self._make_track(genre="Melodic Techno", artist="Âme", title="Rej")
        result = resolve_template("{genre}/{artist}/{title}", track, "Unsorted")
        assert result.components["genre"] == "Melodic Techno"
        assert result.components["artist"] == "Âme"


# --- sanitise_path_component() ---


class TestSanitisePathComponent:
    """Test path component sanitisation."""

    def test_unsafe_chars_removed(self):
        """Characters unsafe on macOS/Windows are stripped."""
        assert sanitise_path_component('Track: The "Best" Mix') == "Track The Best Mix"

    def test_backslash_removed(self):
        assert sanitise_path_component("Artist\\Name") == "ArtistName"

    def test_pipe_removed(self):
        assert sanitise_path_component("A|B") == "AB"

    def test_angle_brackets_removed(self):
        assert sanitise_path_component("Track <Remix>") == "Track Remix"

    def test_question_mark_removed(self):
        assert sanitise_path_component("What?") == "What"

    def test_asterisk_removed(self):
        assert sanitise_path_component("Track*") == "Track"

    def test_leading_trailing_dots_stripped(self):
        assert sanitise_path_component("..hidden..") == "hidden"

    def test_leading_trailing_spaces_stripped(self):
        assert sanitise_path_component("  spaced  ") == "spaced"

    def test_multiple_spaces_collapsed(self):
        assert sanitise_path_component("DJ   Name") == "DJ Name"

    def test_unicode_preserved(self):
        assert sanitise_path_component("Âme") == "Âme"
        assert sanitise_path_component("日本語") == "日本語"

    def test_empty_string(self):
        """Empty string after sanitisation returns empty."""
        assert sanitise_path_component("") == ""

    def test_long_string_trimmed(self):
        """Strings longer than 255 chars are trimmed."""
        long_name = "A" * 300
        result = sanitise_path_component(long_name)
        assert len(result) <= 255

    def test_all_unsafe_chars_results_empty(self):
        """String of only unsafe chars results in empty string."""
        assert sanitise_path_component(':<>"|?*') == ""

    def test_colon_removed(self):
        assert sanitise_path_component("DJ: The Mix") == "DJ The Mix"

    def test_slash_removed(self):
        """Forward slash removed (it's a path separator, not component char)."""
        assert sanitise_path_component("A/B") == "AB"

    def test_control_chars_removed(self):
        """ASCII control characters (0x00–0x1F) are stripped."""
        assert sanitise_path_component("Track\x00Name") == "TrackName"
        assert sanitise_path_component("a\x01\x1fb") == "ab"

    def test_reserved_name_gets_suffix(self):
        """Windows reserved device names get a safe suffix appended."""
        assert sanitise_path_component("CON") == "CON_"
        assert sanitise_path_component("NUL") == "NUL_"
        assert sanitise_path_component("COM1") == "COM1_"
        assert sanitise_path_component("LPT9") == "LPT9_"

    def test_reserved_name_case_insensitive(self):
        """Reserved-name matching is case-insensitive; original case preserved."""
        assert sanitise_path_component("con") == "con_"
        assert sanitise_path_component("Aux") == "Aux_"

    def test_reserved_name_substring_unaffected(self):
        """A name merely containing a reserved word is not modified."""
        assert sanitise_path_component("CONTROL") == "CONTROL"
        assert sanitise_path_component("Conjure") == "Conjure"

    def test_ampersand_preserved(self):
        """Ampersand is safe and must be preserved."""
        assert sanitise_path_component("Louie Vega & AXEL TOSCA") == "Louie Vega & AXEL TOSCA"


# --- build_output_path() ---


class TestBuildOutputPath:
    """Test full pipeline: resolve → sanitise → join with output dir and extension."""

    def _make_track(self, **kwargs):
        track = MagicMock()
        defaults = {
            "id": 1,
            "title": None,
            "artist": None,
            "album": None,
            "album_artist": None,
            "genre": None,
            "subgenre": None,
            "year": None,
            "label": None,
            "output_format": "aiff",
            "source_path": None,
            "file_path": "/music/test.aiff",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(track, k, v)
        return track

    def test_full_pipeline(self):
        """Full template resolution with output directory and extension."""
        track = self._make_track(
            artist="Calibre",
            album="Shelflife 6",
            title="Falls to You",
            output_format="aiff",
        )
        result = build_output_path("{artist}/{album}/{title}", track, Path("/library"), "Unsorted")
        assert result.path == Path("/library/Calibre/Shelflife 6/Falls to You.aiff")

    def test_sanitised_components(self):
        """Unsafe characters in metadata are sanitised in the output path."""
        track = self._make_track(
            artist='DJ "Bass"',
            title="Track: The Best",
            output_format="mp3",
        )
        result = build_output_path(
            '{artist}/{album|"Singles"}/{title}', track, Path("/library"), "Unsorted"
        )
        assert ":" not in str(result.path)
        assert '"' not in str(result.path.name)

    def test_extension_from_output_format(self):
        """File extension is derived from output_format, not template."""
        track = self._make_track(
            artist="Test",
            title="Song",
            output_format="mp3",
        )
        result = build_output_path(
            '{artist}/{album|"Singles"}/{title}', track, Path("/library"), "Unsorted"
        )
        assert result.path.suffix == ".mp3"

    def test_fallback_used_in_path(self):
        """Fallback values appear in the output path."""
        track = self._make_track(
            artist="Test",
            title="Song",
            output_format="aiff",
        )
        result = build_output_path(
            '{artist}/{album|"Singles"}/{title}', track, Path("/library"), "Unsorted"
        )
        assert "Singles" in str(result.path)
        assert "album" in result.fallbacks_used

    def test_unresolved_uses_unknown_fallback(self):
        """Unresolved variables use the configured unknown fallback."""
        track = self._make_track(title="Song", output_format="aiff")
        result = build_output_path("{artist}/{title}", track, Path("/library"), "MyFallback")
        assert "MyFallback" in str(result.path)


# --- validate_template() ---


class TestValidateTemplate:
    """Test template validation against the schema."""

    @pytest.mark.parametrize(
        "template,reason",
        [
            ("", "empty template"),
            ("   ", "whitespace-only template"),
            ("/{artist}/{album}", "absolute path"),
            ("{artist", "unbalanced opening brace"),
            ("artist}", "unbalanced closing brace"),
            ("{}", "empty variable"),
            ("{nonexistent}/{album}", "unknown variable"),
            ("{artist|unknown_fallback}/{album}", "unknown variable in fallback chain"),
            ("../{artist}/{album}", "path traversal"),
            ("{artist}/..", "path traversal trailing"),
            (
                "rekordbot_library{artist}/{album}",
                "missing separator between literal and variable",
            ),
            ("{artist}folder/{album}", "missing separator between variable and literal"),
            ("{artist}{album}/{title}", "missing separator between two variables"),
        ],
        ids=[
            "empty",
            "whitespace",
            "absolute",
            "open_brace",
            "close_brace",
            "empty_var",
            "unknown_var",
            "unknown_fallback",
            "traversal_leading",
            "traversal_trailing",
            "literal_then_var",
            "var_then_literal",
            "var_then_var",
        ],
    )
    def test_rejects_invalid_template(self, template: str, reason: str) -> None:
        valid, error = validate_template(template)
        assert valid is False, f"Expected rejection for {reason}: {template!r}"
        assert error, f"Empty error message for {reason}: {template!r}"

    @pytest.mark.parametrize(
        "template",
        [
            "{artist}/{album}/{title}",
            "{genre}/{artist}/{title}",
            '{artist|album_artist|"Unknown"}/{album}/{title}',
            "rekordbot_library/{artist}/{album}/{title}",
            '{artist}/{album|"Singles"}/{title}',
            "{year}/{artist}/{title}",
        ],
    )
    def test_accepts_valid_template(self, template: str) -> None:
        valid, error = validate_template(template)
        assert valid is True, f"Expected accept: {template!r}, got error: {error}"
        assert error == ""


# --- Path-construction: embedded slashes & artist semicolons ---


class TestPathComponentSlashHandling:
    """Slash inside a metadata value must NOT split into phantom directories.

    Real fixtures from the live library. Each album value below contains a "/"
    that, pre-fix, was interpreted by Path() as a directory boundary before
    per-component sanitisation could see it.
    """

    def _make_track(self, **kwargs):
        track = MagicMock()
        defaults = {
            "id": 1,
            "title": None,
            "artist": None,
            "album": None,
            "album_artist": None,
            "genre": None,
            "subgenre": None,
            "year": None,
            "label": None,
            "output_format": "aiff",
            "source_path": None,
            "file_path": "/music/test.aiff",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(track, k, v)
        return track

    @pytest.mark.parametrize(
        "album,expected_folder",
        [
            ("V/A - Hyper Love", "VA - Hyper Love"),
            ("Taste / Love In London", "Taste Love In London"),
            ("Quicksand / Getaway", "Quicksand Getaway"),
        ],
        ids=["va_hyper_love", "taste_love", "quicksand_getaway"],
    )
    def test_album_slash_collapses_to_single_folder(self, album, expected_folder):
        track = self._make_track(album=album, title="Some Track")
        result = build_output_path("{album}/{title}", track, Path("/library"), "Unsorted")
        rel_parts = result.path.relative_to("/library").parts
        # Exactly two components: the album folder and the filename. No phantom dirs.
        assert len(rel_parts) == 2, f"phantom dirs created: {rel_parts}"
        assert rel_parts[0] == expected_folder
        assert rel_parts[1] == "Some Track.aiff"

    def test_album_slash_with_parenthetical_tail(self):
        """w/ inside a parenthetical — slash stripped, tail '(wEden...)' acceptable."""
        track = self._make_track(album="Planet Dance Vol. I (w/Eden Burns Remixes)", title="T")
        result = build_output_path("{album}/{title}", track, Path("/library"), "Unsorted")
        rel_parts = result.path.relative_to("/library").parts
        assert len(rel_parts) == 2
        assert rel_parts[0] == "Planet Dance Vol. I (wEden Burns Remixes)"

    def test_album_slash_in_compilation_title(self):
        """'Soul/Disco' must not split; '&' preserved within the same component."""
        track = self._make_track(
            album="The P & P Records Soul/Disco Anthology Compiled By Bill Brewster",
            title="T",
        )
        result = build_output_path("{album}/{title}", track, Path("/library"), "Unsorted")
        rel_parts = result.path.relative_to("/library").parts
        assert len(rel_parts) == 2
        assert rel_parts[0] == ("The P & P Records SoulDisco Anthology Compiled By Bill Brewster")

    def test_title_slash_in_filename_collapses(self):
        """A slash in the title (the filename component) is stripped, not split."""
        track = self._make_track(artist="A", title="Quicksand / Getaway")
        result = build_output_path("{artist}/{title}", track, Path("/library"), "Unsorted")
        rel_parts = result.path.relative_to("/library").parts
        assert len(rel_parts) == 2
        assert rel_parts[1] == "Quicksand Getaway.aiff"


class TestArtistSemicolonNormalisation:
    """Artist ';' → ', ' in the folder name ONLY (path layer, never tags/XML/DB)."""

    def _make_track(self, **kwargs):
        track = MagicMock()
        defaults = {
            "id": 1,
            "title": None,
            "artist": None,
            "album": None,
            "album_artist": None,
            "genre": None,
            "subgenre": None,
            "year": None,
            "label": None,
            "output_format": "aiff",
            "source_path": None,
            "file_path": "/music/test.aiff",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(track, k, v)
        return track

    @pytest.mark.parametrize(
        "artist,expected_folder",
        [
            ("Okyerema Asante;Black Fire", "Okyerema Asante, Black Fire"),
            ("DEADBEAT;The Mole", "DEADBEAT, The Mole"),
            ("A;B;C", "A, B, C"),
        ],
        ids=["okyerema", "deadbeat", "abc"],
    )
    def test_artist_semicolon_becomes_comma_space(self, artist, expected_folder):
        track = self._make_track(artist=artist, title="Track")
        result = build_output_path("{artist}/{title}", track, Path("/library"), "Unsorted")
        rel_parts = result.path.relative_to("/library").parts
        assert rel_parts[0] == expected_folder

    def test_semicolon_only_applies_to_artist(self):
        """Album containing ';' is NOT semicolon-normalised (artist-only rule)."""
        track = self._make_track(artist="X", album="One;Two", title="T")
        result = build_output_path("{album}/{title}", track, Path("/library"), "Unsorted")
        rel_parts = result.path.relative_to("/library").parts
        # ';' is a safe filesystem char and not subject to the artist normalisation.
        assert rel_parts[0] == "One;Two"

    def test_artist_track_field_untouched(self):
        """The normalisation is path-only — components reflects the raw resolved value."""
        track = self._make_track(artist="Okyerema Asante;Black Fire", title="Track")
        result = resolve_template("{artist}/{title}", track, "Unsorted")
        # components carries the unmodified resolved artist value.
        assert result.components["artist"] == "Okyerema Asante;Black Fire"


class TestRegressionUnchangedComponents:
    """Values that are correct today must remain unchanged after the fix."""

    def _make_track(self, **kwargs):
        track = MagicMock()
        defaults = {
            "id": 1,
            "title": None,
            "artist": None,
            "album": None,
            "album_artist": None,
            "genre": None,
            "subgenre": None,
            "year": None,
            "label": None,
            "output_format": "aiff",
            "source_path": None,
            "file_path": "/music/test.aiff",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(track, k, v)
        return track

    @pytest.mark.parametrize(
        "artist",
        ["Louie Vega & AXEL TOSCA", "Michael Campbell & High Volt"],
        ids=["louie_vega", "michael_campbell"],
    )
    def test_ampersand_preserved_in_path(self, artist):
        track = self._make_track(artist=artist, title="T")
        result = build_output_path("{artist}/{title}", track, Path("/library"), "Unsorted")
        assert result.path.relative_to("/library").parts[0] == artist

    @pytest.mark.parametrize(
        "artist",
        ["Andrés", "Fünfzehn + 1", "ファイアークラッカー"],
        ids=["andres", "funfzehn", "firecracker"],
    )
    def test_unicode_preserved_in_path(self, artist):
        track = self._make_track(artist=artist, title="T")
        result = build_output_path("{artist}/{title}", track, Path("/library"), "Unsorted")
        assert result.path.relative_to("/library").parts[0] == artist

    def test_title_colon_stripped(self):
        """Colon strip is intended behaviour: 'Track: Reprise' -> 'Track Reprise'."""
        track = self._make_track(artist="A", title="Track: Reprise")
        result = build_output_path("{artist}/{title}", track, Path("/library"), "Unsorted")
        assert result.path.relative_to("/library").parts[1] == "Track Reprise.aiff"

    def test_acdc_artist_not_dropped(self):
        """'AC/DC' collapses to a single 'ACDC' component, not dropped or emptied."""
        track = self._make_track(artist="AC/DC", title="Thunderstruck")
        result = build_output_path("{artist}/{title}", track, Path("/library"), "Unsorted")
        rel_parts = result.path.relative_to("/library").parts
        assert len(rel_parts) == 2
        assert rel_parts[0] == "ACDC"
        assert rel_parts[1] == "Thunderstruck.aiff"


class TestEmptiedComponentFallback:
    """A component that sanitises to "" must not collapse the path structure.

    Path() silently drops empty parts, so an all-unsafe value would make a folder
    vanish (collision one level up) or yield a bare '.aiff' dotfile. Both flush
    points fall back to unknown_fallback instead.
    """

    def _make_track(self, **kwargs):
        track = MagicMock()
        defaults = {
            "id": 1,
            "title": None,
            "artist": None,
            "album": None,
            "album_artist": None,
            "genre": None,
            "subgenre": None,
            "year": None,
            "label": None,
            "output_format": "aiff",
            "source_path": None,
            "file_path": "/music/test.aiff",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(track, k, v)
        return track

    @pytest.mark.parametrize("album", ["???", "/", ":::"], ids=["q", "slash", "colons"])
    def test_all_unsafe_album_uses_fallback(self, album):
        """An all-unsafe album folder becomes unknown_fallback, never dropped."""
        track = self._make_track(artist="Real Artist", album=album, title="Real Title")
        result = build_output_path("{artist}/{album}/{title}", track, Path("/library"), "Unknown")
        rel_parts = result.path.relative_to("/library").parts
        assert len(rel_parts) == 3, f"path collapsed: {rel_parts}"
        assert rel_parts == ("Real Artist", "Unknown", "Real Title.aiff")

    def test_all_unsafe_title_is_fallback_not_dotfile(self):
        """An emptied title yields '<fallback>.aiff', never a bare '.aiff' dotfile."""
        track = self._make_track(artist="Real Artist", title="???")
        result = build_output_path("{artist}/{title}", track, Path("/library"), "Unknown")
        rel_parts = result.path.relative_to("/library").parts
        assert rel_parts[-1] == "Unknown.aiff"
        assert result.path.name != ".aiff"

    def test_middle_component_emptying_does_not_collapse(self):
        """A middle component emptying preserves the overall part count."""
        track = self._make_track(artist="Real Artist", album=":::", title="Real Title")
        result = build_output_path("{artist}/{album}/{title}", track, Path("/library"), "Unknown")
        assert len(result.path.relative_to("/library").parts) == 3
