"""Tests for crate prompt builder — TDD.

Tests written before implementation. Covers prompt construction,
criteria parsing, assignment prompts, and result parsing.
"""

from backend.services.crate_prompt_builder import (
    build_assignment_prompt,
    build_criteria_prompt,
    parse_assignment_result,
    parse_criteria_result,
)


class TestBuildCriteriaPrompt:
    """Tests for build_criteria_prompt()."""

    def test_returns_system_and_user(self):
        """Returns a tuple of (system_prompt, user_message, tool_schema)."""
        result = build_criteria_prompt("Deep minimal house, warm and hypnotic")
        assert len(result) == 3
        system, user, tool = result
        assert isinstance(system, str)
        assert isinstance(user, str)
        assert isinstance(tool, dict)

    def test_description_in_user_message(self):
        """User's description appears in the user message."""
        _, user, _ = build_criteria_prompt("Deep minimal house, warm and hypnotic")
        assert "Deep minimal house, warm and hypnotic" in user

    def test_system_prompt_has_instructions(self):
        """System prompt contains relevant instructions."""
        system, _, _ = build_criteria_prompt("Anything")
        assert "mood" in system.lower()
        assert "energy" in system.lower()
        assert "bpm" in system.lower()
        assert "genre" in system.lower()

    def test_tool_schema_structure(self):
        """Tool schema has required fields."""
        _, _, tool = build_criteria_prompt("Anything")
        assert "name" in tool
        assert "input_schema" in tool
        schema = tool["input_schema"]
        assert "properties" in schema


class TestParseCriteriaResult:
    """Tests for parse_criteria_result()."""

    def test_valid_full_criteria(self):
        """Parse a complete criteria result."""
        tool_input = {
            "mood": ["hypnotic", "warm"],
            "energy_min": 3,
            "energy_max": 6,
            "bpm_min": 118,
            "bpm_max": 124,
            "genres": ["Deep House", "Minimal House"],
            "keywords": ["dubby"],
            "exclude_genres": [],
            "notes": "Looking for deep minimal vibes",
        }
        result = parse_criteria_result(tool_input)
        assert result["mood"] == ["hypnotic", "warm"]
        assert result["energy_min"] == 3
        assert result["energy_max"] == 6
        assert result["bpm_min"] == 118
        assert result["bpm_max"] == 124
        assert result["genres"] == ["Deep House", "Minimal House"]

    def test_missing_fields_default_to_none(self):
        """Missing fields are set to None."""
        result = parse_criteria_result({"mood": ["dark"]})
        assert result["mood"] == ["dark"]
        assert result["energy_min"] is None
        assert result["energy_max"] is None
        assert result["bpm_min"] is None
        assert result["bpm_max"] is None
        assert result["genres"] is None

    def test_energy_clamped_1_to_10(self):
        """Energy values are clamped to 1–10 range."""
        result = parse_criteria_result({"energy_min": 0, "energy_max": 15})
        assert result["energy_min"] == 1
        assert result["energy_max"] == 10

    def test_bpm_range_validation(self):
        """BPM values must be positive."""
        result = parse_criteria_result({"bpm_min": -10, "bpm_max": 300})
        assert result["bpm_min"] is None
        assert result["bpm_max"] == 300

    def test_invalid_types_handled(self):
        """Non-list mood, non-int energy handled gracefully."""
        result = parse_criteria_result({"mood": "hypnotic", "energy_min": "high"})
        assert result["mood"] == ["hypnotic"]
        assert result["energy_min"] is None

    def test_empty_input(self):
        """Empty dict returns all-None criteria."""
        result = parse_criteria_result({})
        assert result["mood"] is None
        assert result["genres"] is None


class TestBuildAssignmentPrompt:
    """Tests for build_assignment_prompt()."""

    def test_returns_system_user_tool(self):
        """Returns a tuple of (system_prompt, user_message, tool_schema)."""
        criteria = {"mood": ["dark"], "genres": ["Techno"]}
        tracks_text = "Track #1:\n  Title: Test\n  Artist: Test Artist"
        result = build_assignment_prompt(
            description="Dark techno",
            criteria=criteria,
            track_summaries=tracks_text,
        )
        assert len(result) == 3

    def test_criteria_in_message(self):
        """Criteria and description appear in the user message."""
        criteria = {"mood": ["dark"], "bpm_min": 130, "bpm_max": 140}
        tracks_text = "Track #1:\n  Title: Test"
        _, user, _ = build_assignment_prompt(
            description="Dark techno",
            criteria=criteria,
            track_summaries=tracks_text,
        )
        assert "Dark techno" in user
        assert "dark" in user.lower()
        assert "130" in user
        assert "Track #1" in user

    def test_tool_schema_has_matching_track_ids(self):
        """Tool schema expects matching_track_ids."""
        criteria = {"mood": ["dark"]}
        _, _, tool = build_assignment_prompt(
            description="Dark techno",
            criteria=criteria,
            track_summaries="Track #1",
        )
        props = tool["input_schema"]["properties"]
        assert "matching_track_ids" in props


class TestParseAssignmentResult:
    """Tests for parse_assignment_result()."""

    def test_valid_ids(self):
        """Parse a valid list of track IDs."""
        result = parse_assignment_result(
            {"matching_track_ids": [1, 5, 12], "reasoning": "All match"},
            valid_ids={1, 2, 3, 5, 10, 12},
        )
        assert result == [1, 5, 12]

    def test_duplicates_removed(self):
        """Duplicate IDs are removed."""
        result = parse_assignment_result(
            {"matching_track_ids": [1, 1, 5, 5]},
            valid_ids={1, 5},
        )
        assert sorted(result) == [1, 5]

    def test_invalid_ids_filtered(self):
        """IDs not in valid_ids are filtered out."""
        result = parse_assignment_result(
            {"matching_track_ids": [1, 999, 5]},
            valid_ids={1, 5},
        )
        assert sorted(result) == [1, 5]

    def test_empty_list(self):
        """Empty matching_track_ids returns empty list."""
        result = parse_assignment_result(
            {"matching_track_ids": []},
            valid_ids={1, 5},
        )
        assert result == []

    def test_missing_field(self):
        """Missing matching_track_ids returns empty list."""
        result = parse_assignment_result({}, valid_ids={1, 5})
        assert result == []

    def test_non_list_value(self):
        """Non-list matching_track_ids returns empty list."""
        result = parse_assignment_result(
            {"matching_track_ids": "not a list"},
            valid_ids={1, 5},
        )
        assert result == []
