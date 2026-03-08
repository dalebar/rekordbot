"""Tests for set prompt builder — TDD (write tests first, then implement)."""

from unittest.mock import MagicMock

from backend.services.set_prompt_builder import (
    build_initial_prompt,
    build_reorder_prompt,
    build_replace_prompt,
    parse_initial_result,
    parse_reorder_result,
    parse_replace_result,
)


def _make_track(track_id, title="Track", artist="Artist", bpm=128.0, key=None, **kwargs):
    """Create a mock track object."""
    track = MagicMock()
    track.id = track_id
    track.title = f"{title} {track_id}"
    track.artist = artist
    track.bpm = bpm
    track.key = key
    track.album = None
    track.label = None
    track.year = None
    track.genre = "Techno"
    track.comment = None
    track.source_path = None
    track.file_path = f"/music/{title.lower()}_{track_id}.aiff"
    track.mood = kwargs.get("mood")
    track.energy = kwargs.get("energy")
    track.subgenre = kwargs.get("subgenre")
    return track


class TestBuildInitialPrompt:
    """Tests for build_initial_prompt()."""

    def test_all_params(self):
        """Prompt includes all parameters when provided."""
        tracks = [_make_track(1), _make_track(2), _make_track(3)]
        system, user, tool = build_initial_prompt(
            description="Deep warm-up set",
            tracks=tracks,
            sequence_length=2,
            candidate_count=3,
            duration_minutes=60,
            target_bpm_start=120.0,
            target_bpm_end=128.0,
            energy_arc="slow build",
            harmonic_mixing=True,
            key_notation="camelot",
        )

        assert "set planner" in system.lower() or "DJ set" in system
        assert "Deep warm-up set" in user
        assert "60" in user  # duration
        assert "120" in user  # bpm start
        assert "128" in user  # bpm end
        assert "slow build" in user
        assert "harmonic" in user.lower() or "key" in user.lower()
        assert "Track 1" in user
        assert tool["name"] == "plan_set"

    def test_optional_params_missing(self):
        """Prompt works without optional parameters."""
        tracks = [_make_track(1), _make_track(2)]
        system, user, tool = build_initial_prompt(
            description="Quick set",
            tracks=tracks,
            sequence_length=2,
            candidate_count=4,
        )

        assert "Quick set" in user
        assert tool["name"] == "plan_set"
        # Should not crash or include None values

    def test_track_summaries_included(self):
        """All track summaries appear in the prompt."""
        tracks = [_make_track(i, artist=f"Artist {i}") for i in range(1, 6)]
        _, user, _ = build_initial_prompt(
            description="Test",
            tracks=tracks,
            sequence_length=3,
            candidate_count=5,
        )

        for i in range(1, 6):
            assert f"Track {i}" in user or f"#{i}" in user
            assert f"Artist {i}" in user


class TestParseInitialResult:
    """Tests for parse_initial_result()."""

    def test_valid_result(self):
        """Parses a valid initial result with sequence and candidates."""
        valid_ids = {1, 2, 3, 4, 5}
        tool_input = {
            "sequence": [
                {"track_id": 1, "reasoning": "Great opener"},
                {"track_id": 2, "reasoning": "Builds energy"},
                {"track_id": 3, "reasoning": "Peak moment"},
            ],
            "candidates": [
                {"track_id": 4, "reasoning": "Alternative opener"},
                {"track_id": 5, "reasoning": "Good closer"},
            ],
        }

        seq, cands = parse_initial_result(tool_input, valid_ids)
        assert len(seq) == 3
        assert seq[0] == 1
        assert seq[1] == 2
        assert seq[2] == 3
        assert len(cands) == 2
        assert 4 in cands
        assert 5 in cands

    def test_missing_sequence(self):
        """Returns empty lists if sequence is missing."""
        seq, cands = parse_initial_result({}, {1, 2, 3})
        assert seq == []
        assert cands == []

    def test_dedup_sequence(self):
        """Duplicate track IDs in sequence are removed."""
        valid_ids = {1, 2, 3}
        tool_input = {
            "sequence": [
                {"track_id": 1, "reasoning": "First"},
                {"track_id": 1, "reasoning": "Duplicate"},
                {"track_id": 2, "reasoning": "Second"},
            ],
            "candidates": [],
        }

        seq, _ = parse_initial_result(tool_input, valid_ids)
        assert seq == [1, 2]

    def test_invalid_ids_filtered(self):
        """Track IDs not in valid set are filtered out."""
        valid_ids = {1, 2}
        tool_input = {
            "sequence": [
                {"track_id": 1, "reasoning": "Valid"},
                {"track_id": 999, "reasoning": "Invalid"},
            ],
            "candidates": [
                {"track_id": 2, "reasoning": "Valid"},
                {"track_id": 888, "reasoning": "Invalid"},
            ],
        }

        seq, cands = parse_initial_result(tool_input, valid_ids)
        assert seq == [1]
        assert cands == [2]

    def test_candidates_exclude_sequence_tracks(self):
        """Tracks in the sequence are excluded from candidates."""
        valid_ids = {1, 2, 3}
        tool_input = {
            "sequence": [
                {"track_id": 1, "reasoning": "In sequence"},
            ],
            "candidates": [
                {"track_id": 1, "reasoning": "Also in sequence (should be filtered)"},
                {"track_id": 2, "reasoning": "Valid candidate"},
            ],
        }

        seq, cands = parse_initial_result(tool_input, valid_ids)
        assert seq == [1]
        assert cands == [2]


class TestBuildReplacePrompt:
    """Tests for build_replace_prompt()."""

    def test_locked_tracks_included(self):
        """Locked tracks appear as fixed anchors in the prompt."""
        locked = [(2, _make_track(10, title="Locked"))]
        unlocked_positions = [1, 3]
        available = [_make_track(20), _make_track(21)]
        segments = [
            {"position": 1, "description": "Warm and deep", "start": 1, "end": 2},
            {"position": 2, "description": "Dark and driving", "start": 3, "end": 3},
        ]

        system, user, tool = build_replace_prompt(
            description="Test set",
            locked_tracks=locked,
            unlocked_positions=unlocked_positions,
            available_tracks=available,
            segments=segments,
            total_positions=3,
            harmonic_mixing=False,
            key_notation="camelot",
        )

        assert "Locked" in user or "locked" in user.lower()
        assert "Warm and deep" in user
        assert "Dark and driving" in user
        assert tool["name"] == "replace_tracks"

    def test_segments_in_prompt(self):
        """Segment descriptions appear in the prompt."""
        segments = [
            {"position": 1, "description": "Ambient intro", "start": 1, "end": 3},
        ]

        _, user, _ = build_replace_prompt(
            description="Set",
            locked_tracks=[],
            unlocked_positions=[1, 2, 3],
            available_tracks=[_make_track(1)],
            segments=segments,
            total_positions=3,
        )

        assert "Ambient intro" in user


class TestParseReplaceResult:
    """Tests for parse_replace_result()."""

    def test_valid_replacements(self):
        """Parses valid replacement entries."""
        valid_ids = {10, 20, 30}
        unlocked_positions = {1, 3}
        locked_positions = {2}
        tool_input = {
            "replacements": [
                {"position": 1, "track_id": 20, "reasoning": "Better fit"},
                {"position": 3, "track_id": 30, "reasoning": "Closing track"},
            ],
        }

        result = parse_replace_result(tool_input, valid_ids, unlocked_positions, locked_positions)
        assert len(result) == 2
        assert result[0] == (1, 20)
        assert result[1] == (3, 30)

    def test_locked_position_rejected(self):
        """Replacements at locked positions are rejected."""
        valid_ids = {10, 20}
        unlocked_positions = {1}
        locked_positions = {2}
        tool_input = {
            "replacements": [
                {"position": 2, "track_id": 20, "reasoning": "Replace locked"},
            ],
        }

        result = parse_replace_result(tool_input, valid_ids, unlocked_positions, locked_positions)
        assert len(result) == 0

    def test_out_of_bounds_position(self):
        """Positions beyond the sequence are rejected."""
        valid_ids = {10}
        unlocked_positions = {1, 2}
        locked_positions: set[int] = set()
        tool_input = {
            "replacements": [
                {"position": 99, "track_id": 10, "reasoning": "Bad position"},
            ],
        }

        result = parse_replace_result(tool_input, valid_ids, unlocked_positions, locked_positions)
        assert len(result) == 0

    def test_invalid_track_id(self):
        """Invalid track IDs are filtered."""
        valid_ids = {10}
        unlocked_positions = {1}
        locked_positions: set[int] = set()
        tool_input = {
            "replacements": [
                {"position": 1, "track_id": 999, "reasoning": "Invalid"},
            ],
        }

        result = parse_replace_result(tool_input, valid_ids, unlocked_positions, locked_positions)
        assert len(result) == 0


class TestBuildReorderPrompt:
    """Tests for build_reorder_prompt()."""

    def test_current_state_in_prompt(self):
        """Current sequence state appears in the prompt."""
        current_sequence = [
            (1, _make_track(10), False),
            (2, _make_track(20), True),  # locked
            (3, _make_track(30), False),
        ]

        system, user, tool = build_reorder_prompt(
            description="Test",
            current_sequence=current_sequence,
            harmonic_mixing=False,
            key_notation="camelot",
        )

        assert "Track 10" in user or "#10" in user
        assert tool["name"] == "reorder_tracks"

    def test_locked_positions_marked(self):
        """Locked positions are clearly indicated."""
        current_sequence = [
            (1, _make_track(10), False),
            (2, _make_track(20), True),
            (3, _make_track(30), False),
        ]

        _, user, _ = build_reorder_prompt(
            description="Test",
            current_sequence=current_sequence,
        )

        assert "locked" in user.lower() or "LOCKED" in user


class TestParseReorderResult:
    """Tests for parse_reorder_result()."""

    def test_valid_reorder(self):
        """Parses a valid reorder result."""
        locked_positions = {2}
        locked_track_ids = {20: 2}  # track_id → position
        tool_input = {
            "reordered": [
                {"track_id": 30, "new_position": 1, "reasoning": "Better opener"},
                {"track_id": 10, "new_position": 3, "reasoning": "Moved to end"},
            ],
        }

        result = parse_reorder_result(
            tool_input,
            locked_positions=locked_positions,
            locked_track_ids=locked_track_ids,
            total_positions=3,
            all_track_ids={10, 20, 30},
        )
        assert len(result) == 2
        assert result[0] == (30, 1)
        assert result[1] == (10, 3)

    def test_locked_position_unchanged(self):
        """Reorder cannot move tracks to/from locked positions."""
        locked_positions = {2}
        locked_track_ids = {20: 2}
        tool_input = {
            "reordered": [
                {"track_id": 10, "new_position": 2, "reasoning": "Move to locked"},
            ],
        }

        result = parse_reorder_result(
            tool_input,
            locked_positions=locked_positions,
            locked_track_ids=locked_track_ids,
            total_positions=3,
            all_track_ids={10, 20, 30},
        )
        assert len(result) == 0

    def test_locked_track_cannot_move(self):
        """Locked tracks cannot be moved to new positions."""
        locked_positions = {2}
        locked_track_ids = {20: 2}
        tool_input = {
            "reordered": [
                {"track_id": 20, "new_position": 1, "reasoning": "Move locked track"},
            ],
        }

        result = parse_reorder_result(
            tool_input,
            locked_positions=locked_positions,
            locked_track_ids=locked_track_ids,
            total_positions=3,
            all_track_ids={10, 20, 30},
        )
        assert len(result) == 0

    def test_invalid_positions(self):
        """Out of bounds positions are filtered."""
        tool_input = {
            "reordered": [
                {"track_id": 10, "new_position": 99, "reasoning": "Bad position"},
            ],
        }

        result = parse_reorder_result(
            tool_input,
            locked_positions=set(),
            locked_track_ids={},
            total_positions=3,
            all_track_ids={10},
        )
        assert len(result) == 0
