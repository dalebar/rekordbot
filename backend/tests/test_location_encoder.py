"""Tests for Rekordbox location encoder — TDD, written before implementation."""

from backend.services.location_encoder import encode_location, encode_path_component


class TestEncodePathComponent:
    """Tests for encoding a single path component."""

    def test_simple_name(self) -> None:
        assert encode_path_component("Calibre") == "Calibre"

    def test_spaces(self) -> None:
        assert encode_path_component("Falls to You") == "Falls%20to%20You"

    def test_hash(self) -> None:
        assert encode_path_component("Track #1") == "Track%20%231"

    def test_ampersand(self) -> None:
        assert encode_path_component("Above & Beyond") == "Above%20%26%20Beyond"

    def test_unicode_accent(self) -> None:
        assert encode_path_component("Âme") == "%C3%82me"

    def test_unicode_umlaut(self) -> None:
        assert encode_path_component("Böhm") == "B%C3%B6hm"

    def test_safe_chars_preserved(self) -> None:
        """Unreserved RFC 3986 characters should not be encoded."""
        assert encode_path_component("track-01_mix.aiff") == "track-01_mix.aiff"

    def test_dots_preserved(self) -> None:
        assert encode_path_component("file.aiff") == "file.aiff"

    def test_tilde_preserved(self) -> None:
        assert encode_path_component("~user") == "~user"

    def test_empty_string(self) -> None:
        assert encode_path_component("") == ""

    def test_parentheses(self) -> None:
        assert encode_path_component("Track (Original Mix)") == "Track%20%28Original%20Mix%29"

    def test_single_quote(self) -> None:
        assert encode_path_component("Don't Stop") == "Don%27t%20Stop"

    def test_plus_sign(self) -> None:
        assert encode_path_component("A+B") == "A%2BB"

    def test_equals_sign(self) -> None:
        assert encode_path_component("x=1") == "x%3D1"

    def test_at_sign(self) -> None:
        assert encode_path_component("user@host") == "user%40host"

    def test_exclamation_mark(self) -> None:
        """Exclamation mark is unreserved in RFC 3986 but Rekordbox encodes it."""
        # urllib.parse.quote with safe="" encodes ! — this is fine
        result = encode_path_component("Wow!")
        assert "Wow" in result


class TestEncodeLocation:
    """Tests for full path to Rekordbox Location URI conversion."""

    def test_simple_path(self) -> None:
        result = encode_location("/Users/daleb/rekordbot/library/Calibre/Rej.aiff")
        assert result == "file://localhost/Users/daleb/rekordbot/library/Calibre/Rej.aiff"

    def test_path_with_spaces(self) -> None:
        result = encode_location(
            "/Users/daleb/rekordbot/library/Calibre/Shelflife 6/Falls to You.aiff"
        )
        assert result == (
            "file://localhost/Users/daleb/rekordbot/library/Calibre/"
            "Shelflife%206/Falls%20to%20You.aiff"
        )

    def test_path_with_unicode(self) -> None:
        result = encode_location("/Users/daleb/rekordbot/library/Âme/Rej.aiff")
        assert result == "file://localhost/Users/daleb/rekordbot/library/%C3%82me/Rej.aiff"

    def test_path_with_special_chars(self) -> None:
        result = encode_location("/Users/daleb/library/Above & Beyond/Track #1.mp3")
        assert result == (
            "file://localhost/Users/daleb/library/Above%20%26%20Beyond/Track%20%231.mp3"
        )

    def test_slashes_not_encoded(self) -> None:
        result = encode_location("/a/b/c.aiff")
        assert result == "file://localhost/a/b/c.aiff"
        assert "%2F" not in result

    def test_leading_slash_not_doubled(self) -> None:
        result = encode_location("/Users/daleb/test.aiff")
        assert result.startswith("file://localhost/Users")
        assert "file://localhost//Users" not in result

    def test_round_trip_decodable(self) -> None:
        """Encoded URI should decode back to the original path."""
        from urllib.parse import unquote

        original = "/Users/daleb/library/Âme/Track #1 (Original Mix).aiff"
        encoded = encode_location(original)
        # Strip prefix and decode
        decoded = unquote(encoded.replace("file://localhost", ""))
        assert decoded == original

    def test_mp3_extension(self) -> None:
        result = encode_location("/library/Artist/track.mp3")
        assert result.endswith("track.mp3")

    def test_deeply_nested_path(self) -> None:
        result = encode_location("/a/b/c/d/e/f.aiff")
        assert result == "file://localhost/a/b/c/d/e/f.aiff"
