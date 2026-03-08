"""Tests for prompt builder — TDD tests written before implementation."""

from backend.services.prompt_builder import (
    AiTagResult,
    build_batch_message,
    build_system_prompt,
    build_track_summary,
    get_tool_schema,
    group_tracks_into_batches,
    parse_tool_result,
)

# --- Helpers ---


class FakeTrack:
    """Minimal Track-like object for testing prompt builder (no DB dependency)."""

    id: int
    title: str | None
    artist: str | None
    album: str | None
    album_artist: str | None
    label: str | None
    year: int | None
    genre: str | None
    comment: str | None
    bpm: float | None
    key: int | None
    source_format: str | None
    source_bitrate: int | None
    source_path: str | None
    file_path: str

    def __init__(self, **kwargs: object) -> None:
        defaults: dict[str, object] = {
            "id": 1,
            "title": None,
            "artist": None,
            "album": None,
            "album_artist": None,
            "label": None,
            "year": None,
            "genre": None,
            "comment": None,
            "bpm": None,
            "key": None,
            "source_format": None,
            "source_bitrate": None,
            "source_path": None,
            "file_path": "/music/test.aiff",
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


# --- build_system_prompt() ---


class TestBuildSystemPrompt:
    """Tests for the system prompt builder."""

    def test_contains_role(self):
        """System prompt contains the music metadata specialist role."""
        prompt = build_system_prompt()
        assert "music metadata specialist" in prompt.lower()

    def test_contains_genre_guidelines(self):
        """System prompt contains genre guidance with specific genres."""
        prompt = build_system_prompt()
        assert "Tech House" in prompt
        assert "Melodic Techno" in prompt
        assert "Liquid DnB" in prompt

    def test_contains_mood_vocabulary(self):
        """System prompt contains mood examples."""
        prompt = build_system_prompt()
        assert "Euphoric" in prompt
        assert "Dark" in prompt
        assert "Groovy" in prompt

    def test_contains_energy_scale(self):
        """System prompt contains the 1-10 energy scale definition."""
        prompt = build_system_prompt()
        assert "1" in prompt and "10" in prompt
        assert "Ambient" in prompt or "ambient" in prompt
        assert "Peak time" in prompt or "peak time" in prompt

    def test_contains_confidence_levels(self):
        """System prompt defines high/medium/low confidence."""
        prompt = build_system_prompt()
        assert "high" in prompt.lower()
        assert "medium" in prompt.lower()
        assert "low" in prompt.lower()

    def test_contains_tool_instructions(self):
        """System prompt mentions the tag_tracks tool."""
        prompt = build_system_prompt()
        assert "tag_tracks" in prompt


# --- build_track_summary() ---


class TestBuildTrackSummary:
    """Tests for track summary generation."""

    def test_full_data(self):
        """Track with all fields populated produces complete summary."""
        track = FakeTrack(
            id=42,
            title="Lost Souls",
            artist="Calibre",
            album="Shelflife 6",
            label="Signature Records",
            year=2022,
            genre="Drum & Bass",
            bpm=174.0,
            key=5,
            comment="Vinyl rip",
            source_path="/downloads/calibre-lost_souls.flac",
        )
        summary = build_track_summary(track, key_display="4A")
        assert "Track #42" in summary
        assert "Lost Souls" in summary
        assert "Calibre" in summary
        assert "Shelflife 6" in summary
        assert "Signature Records" in summary
        assert "2022" in summary
        assert "Drum & Bass" in summary
        assert "174" in summary
        assert "4A" in summary
        assert "Vinyl rip" in summary
        assert "calibre-lost_souls.flac" in summary

    def test_partial_data(self):
        """Track with missing fields omits those lines."""
        track = FakeTrack(
            id=7,
            title="Unknown Track",
            artist="Unknown Artist",
        )
        summary = build_track_summary(track, key_display=None)
        assert "Track #7" in summary
        assert "Unknown Track" in summary
        assert "Unknown Artist" in summary
        # Missing fields should not appear
        assert "Album:" not in summary
        assert "Label:" not in summary
        assert "Year:" not in summary
        assert "BPM:" not in summary
        assert "Key:" not in summary

    def test_none_values_omitted(self):
        """None values don't produce lines in the summary."""
        track = FakeTrack(id=1, title=None, artist=None)
        summary = build_track_summary(track, key_display=None)
        assert "Track #1" in summary
        assert "Title:" not in summary
        assert "Artist:" not in summary

    def test_empty_string_values_omitted(self):
        """Empty string values don't produce lines in the summary."""
        track = FakeTrack(id=1, title="", artist="")
        summary = build_track_summary(track, key_display=None)
        assert "Title:" not in summary
        assert "Artist:" not in summary

    def test_filename_from_source_path(self):
        """Filename is extracted from source_path."""
        track = FakeTrack(id=1, source_path="/long/path/to/file.mp3")
        summary = build_track_summary(track, key_display=None)
        assert "file.mp3" in summary

    def test_filename_from_file_path_fallback(self):
        """Falls back to file_path when source_path is absent."""
        track = FakeTrack(id=1, source_path=None, file_path="/library/track.aiff")
        summary = build_track_summary(track, key_display=None)
        assert "track.aiff" in summary

    def test_unicode_handling(self):
        """Unicode characters in metadata are preserved."""
        track = FakeTrack(id=1, title="Über Alles", artist="Björk")
        summary = build_track_summary(track, key_display=None)
        assert "Über Alles" in summary
        assert "Björk" in summary


# --- build_batch_message() ---


class TestBuildBatchMessage:
    """Tests for batch message construction."""

    def test_multiple_tracks(self):
        """Batch message includes summaries for all tracks."""
        tracks = [
            FakeTrack(id=1, title="Track A", artist="Artist A"),
            FakeTrack(id=2, title="Track B", artist="Artist B"),
            FakeTrack(id=3, title="Track C", artist="Artist C"),
        ]
        message = build_batch_message(tracks)
        assert "Track #1" in message
        assert "Track #2" in message
        assert "Track #3" in message
        assert "Track A" in message
        assert "Track C" in message

    def test_single_track(self):
        """Batch message works with a single track."""
        tracks = [FakeTrack(id=1, title="Solo")]
        message = build_batch_message(tracks)
        assert "Track #1" in message
        assert "Solo" in message


# --- group_tracks_into_batches() ---


class TestGroupTracksIntoBatches:
    """Tests for batch grouping logic."""

    def test_empty_list(self):
        """Empty track list produces no batches."""
        result = group_tracks_into_batches([], batch_size=20)
        assert result == []

    def test_single_batch(self):
        """Tracks within batch_size stay in one batch."""
        tracks = [FakeTrack(id=i) for i in range(5)]
        result = group_tracks_into_batches(tracks, batch_size=20)
        assert len(result) == 1
        assert len(result[0]) == 5

    def test_exact_batch_size(self):
        """Tracks exactly at batch_size produce one batch."""
        tracks = [FakeTrack(id=i) for i in range(20)]
        result = group_tracks_into_batches(tracks, batch_size=20)
        assert len(result) == 1
        assert len(result[0]) == 20

    def test_multiple_batches(self):
        """Tracks exceeding batch_size are split into multiple batches."""
        tracks = [FakeTrack(id=i) for i in range(45)]
        result = group_tracks_into_batches(tracks, batch_size=20)
        assert len(result) == 3
        assert len(result[0]) == 20
        assert len(result[1]) == 20
        assert len(result[2]) == 5

    def test_artist_grouping(self):
        """Tracks by the same artist tend to be in the same batch."""
        tracks = [
            FakeTrack(id=1, artist="Alpha"),
            FakeTrack(id=2, artist="Beta"),
            FakeTrack(id=3, artist="Alpha"),
            FakeTrack(id=4, artist="Alpha"),
            FakeTrack(id=5, artist="Beta"),
        ]
        result = group_tracks_into_batches(tracks, batch_size=20)
        # All should be in one batch since total < batch_size
        assert len(result) == 1
        # Alpha tracks should be grouped together
        ids = [t.id for t in result[0]]
        alpha_indices = [ids.index(t.id) for t in result[0] if t.artist == "Alpha"]
        # All alpha tracks should be consecutive
        assert alpha_indices == list(
            range(alpha_indices[0], alpha_indices[0] + len(alpha_indices))
        )

    def test_artist_overflow_splits(self):
        """Artist with more tracks than batch_size splits across batches."""
        tracks = [FakeTrack(id=i, artist="Same") for i in range(25)]
        result = group_tracks_into_batches(tracks, batch_size=20)
        assert len(result) == 2
        assert len(result[0]) == 20
        assert len(result[1]) == 5

    def test_all_tracks_present(self):
        """All input tracks appear exactly once in the output batches."""
        tracks = [FakeTrack(id=i, artist=f"Artist {i % 3}") for i in range(47)]
        result = group_tracks_into_batches(tracks, batch_size=20)
        output_ids = sorted(t.id for batch in result for t in batch)
        input_ids = sorted(t.id for t in tracks)
        assert output_ids == input_ids


# --- get_tool_schema() ---


class TestGetToolSchema:
    """Tests for the tool schema definition."""

    def test_schema_has_name(self):
        """Schema has the correct tool name."""
        schema = get_tool_schema()
        assert schema["name"] == "tag_tracks"

    def test_schema_has_required_fields(self):
        """Each track item in the schema requires all expected fields."""
        schema = get_tool_schema()
        track_props = schema["input_schema"]["properties"]["tracks"]["items"]["properties"]
        assert "track_id" in track_props
        assert "genre" in track_props
        assert "subgenre" in track_props
        assert "mood" in track_props
        assert "energy" in track_props
        assert "confidence" in track_props
        assert "reasoning" in track_props


# --- parse_tool_result() ---


class TestParseToolResult:
    """Tests for parsing Claude's tool use response. Highest-value TDD target."""

    def test_valid_result(self):
        """Valid tool input produces correct AiTagResult objects."""
        tool_input = {
            "tracks": [
                {
                    "track_id": 1,
                    "genre": "Tech House",
                    "subgenre": "Minimal Tech House",
                    "mood": "Groovy",
                    "energy": 7,
                    "confidence": "high",
                    "reasoning": "Classic tech house BPM and label.",
                },
                {
                    "track_id": 2,
                    "genre": "Melodic Techno",
                    "subgenre": "",
                    "mood": "Hypnotic",
                    "energy": 8,
                    "confidence": "medium",
                    "reasoning": "BPM and key suggest melodic techno.",
                },
            ]
        }
        results = parse_tool_result(tool_input, batch_track_ids=[1, 2])
        assert len(results) == 2
        assert results[0].track_id == 1
        assert results[0].genre == "Tech House"
        assert results[0].subgenre == "Minimal Tech House"
        assert results[0].mood == "Groovy"
        assert results[0].energy == 7
        assert results[0].confidence == "high"
        assert results[0].reasoning == "Classic tech house BPM and label."
        assert results[1].track_id == 2
        assert results[1].subgenre == ""

    def test_energy_clamped_high(self):
        """Energy values above 10 are clamped to 10."""
        tool_input = {
            "tracks": [
                {
                    "track_id": 1,
                    "genre": "Hard Techno",
                    "subgenre": "",
                    "mood": "Aggressive",
                    "energy": 15,
                    "confidence": "high",
                    "reasoning": "Very intense.",
                }
            ]
        }
        results = parse_tool_result(tool_input, batch_track_ids=[1])
        assert results[0].energy == 10

    def test_energy_clamped_low(self):
        """Energy values below 1 are clamped to 1."""
        tool_input = {
            "tracks": [
                {
                    "track_id": 1,
                    "genre": "Ambient",
                    "subgenre": "",
                    "mood": "Ethereal",
                    "energy": -2,
                    "confidence": "low",
                    "reasoning": "Very quiet.",
                }
            ]
        }
        results = parse_tool_result(tool_input, batch_track_ids=[1])
        assert results[0].energy == 1

    def test_invalid_confidence_defaults_to_low(self):
        """Invalid confidence values default to 'low'."""
        tool_input = {
            "tracks": [
                {
                    "track_id": 1,
                    "genre": "House",
                    "subgenre": "",
                    "mood": "Funky",
                    "energy": 6,
                    "confidence": "very_high",
                    "reasoning": "Guess.",
                }
            ]
        }
        results = parse_tool_result(tool_input, batch_track_ids=[1])
        assert results[0].confidence == "low"

    def test_wrong_track_id_filtered(self):
        """Track IDs not in the batch are filtered out with a warning."""
        tool_input = {
            "tracks": [
                {
                    "track_id": 1,
                    "genre": "House",
                    "subgenre": "",
                    "mood": "Warm",
                    "energy": 5,
                    "confidence": "high",
                    "reasoning": "Valid.",
                },
                {
                    "track_id": 999,
                    "genre": "Techno",
                    "subgenre": "",
                    "mood": "Dark",
                    "energy": 7,
                    "confidence": "high",
                    "reasoning": "Wrong ID.",
                },
            ]
        }
        results = parse_tool_result(tool_input, batch_track_ids=[1, 2])
        assert len(results) == 1
        assert results[0].track_id == 1

    def test_missing_required_field_skips_track(self):
        """Track entries missing required fields are skipped."""
        tool_input = {
            "tracks": [
                {
                    "track_id": 1,
                    "genre": "House",
                    # missing subgenre, mood, energy, confidence, reasoning
                },
                {
                    "track_id": 2,
                    "genre": "Techno",
                    "subgenre": "",
                    "mood": "Dark",
                    "energy": 7,
                    "confidence": "high",
                    "reasoning": "Complete.",
                },
            ]
        }
        results = parse_tool_result(tool_input, batch_track_ids=[1, 2])
        assert len(results) == 1
        assert results[0].track_id == 2

    def test_empty_tracks_list(self):
        """Empty tracks list returns empty results."""
        tool_input: dict[str, list[object]] = {"tracks": []}
        results = parse_tool_result(tool_input, batch_track_ids=[1, 2])
        assert results == []

    def test_missing_tracks_key(self):
        """Missing 'tracks' key returns empty results."""
        tool_input: dict[str, list[object]] = {"results": []}
        results = parse_tool_result(tool_input, batch_track_ids=[1, 2])
        assert results == []

    def test_energy_float_converted_to_int(self):
        """Float energy values are converted to int."""
        tool_input = {
            "tracks": [
                {
                    "track_id": 1,
                    "genre": "House",
                    "subgenre": "",
                    "mood": "Warm",
                    "energy": 7.5,
                    "confidence": "high",
                    "reasoning": "Float energy.",
                }
            ]
        }
        results = parse_tool_result(tool_input, batch_track_ids=[1])
        assert results[0].energy == 7
        assert isinstance(results[0].energy, int)

    def test_result_is_aitag_result_type(self):
        """parse_tool_result returns AiTagResult instances."""
        tool_input = {
            "tracks": [
                {
                    "track_id": 1,
                    "genre": "House",
                    "subgenre": "",
                    "mood": "Warm",
                    "energy": 5,
                    "confidence": "high",
                    "reasoning": "Test.",
                }
            ]
        }
        results = parse_tool_result(tool_input, batch_track_ids=[1])
        assert isinstance(results[0], AiTagResult)
