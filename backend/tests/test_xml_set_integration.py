"""Tests for XML export integration with set playlists."""

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

from backend.services.xml_builder import build_playlists, build_set_playlists


def _make_set_plan(name: str) -> MagicMock:
    """Create a mock set plan with a name."""
    plan = MagicMock()
    plan.name = name
    return plan


class TestBuildSetPlaylists:
    """Tests for build_set_playlists()."""

    def test_adds_set_nodes(self):
        """Set playlists are added as Type=1 NODEs."""
        parent = ET.Element("NODE")
        plan = _make_set_plan("Friday Warm-Up")
        track_id_map = {1: 100, 2: 200, 3: 300}

        build_set_playlists([(plan, [1, 2, 3])], track_id_map, parent)

        nodes = list(parent)
        assert len(nodes) == 1
        assert nodes[0].get("Name") == "Friday Warm-Up"
        assert nodes[0].get("Type") == "1"
        assert nodes[0].get("Entries") == "3"

    def test_preserves_track_order(self):
        """Track order in the XML matches the input order (position order)."""
        parent = ET.Element("NODE")
        plan = _make_set_plan("Test Set")
        track_id_map = {1: 100, 2: 200, 3: 300}

        # Order: track 3, track 1, track 2
        build_set_playlists([(plan, [3, 1, 2])], track_id_map, parent)

        track_refs = list(list(parent)[0])
        keys = [ref.get("Key") for ref in track_refs]
        assert keys == ["300", "100", "200"]

    def test_sorted_alphabetically(self):
        """Set playlists are sorted by name."""
        parent = ET.Element("NODE")
        plan_z = _make_set_plan("Zzz Set")
        plan_a = _make_set_plan("Aaa Set")
        track_id_map = {1: 100}

        build_set_playlists(
            [(plan_z, [1]), (plan_a, [1])],
            track_id_map,
            parent,
        )

        nodes = list(parent)
        assert nodes[0].get("Name") == "Aaa Set"
        assert nodes[1].get("Name") == "Zzz Set"

    def test_invalid_track_ids_skipped(self):
        """Track IDs not in track_id_map are skipped."""
        parent = ET.Element("NODE")
        plan = _make_set_plan("Test")
        track_id_map = {1: 100}

        build_set_playlists([(plan, [1, 999])], track_id_map, parent)

        node = list(parent)[0]
        assert node.get("Entries") == "1"

    def test_empty_set(self):
        """Set with no matching tracks still gets a node."""
        parent = ET.Element("NODE")
        plan = _make_set_plan("Empty")
        track_id_map: dict[int, int] = {}

        build_set_playlists([(plan, [999])], track_id_map, parent)

        node = list(parent)[0]
        assert node.get("Entries") == "0"


class TestBuildPlaylistsWithSets:
    """Tests for build_playlists() with set integration."""

    def test_sets_appear_alongside_other_playlists(self):
        """Set playlists coexist with folder-based and crate playlists."""
        track = MagicMock()
        track.id = 1
        track.file_path = "/output/Artist/track.aiff"
        track_id_map = {1: 100}

        crate = MagicMock()
        crate.name = "Deep Crate"
        plan = _make_set_plan("Friday Set")

        playlists = build_playlists(
            tracks=[track],
            track_id_map=track_id_map,
            output_directory="/output",
            crates=[(crate, [1])],
            sets=[(plan, [1])],
        )

        playlist_names = []
        for node in playlists.iter("NODE"):
            if node.get("Type") == "1":
                playlist_names.append(node.get("Name"))

        assert "All Tracks" in playlist_names
        assert "Deep Crate" in playlist_names
        assert "Friday Set" in playlist_names

    def test_no_sets(self):
        """Without sets, output is unchanged."""
        track = MagicMock()
        track.id = 1
        track.file_path = "/output/track.aiff"
        track_id_map = {1: 100}

        playlists_with = build_playlists(
            tracks=[track],
            track_id_map=track_id_map,
            output_directory="/output",
            sets=None,
        )
        playlists_without = build_playlists(
            tracks=[track],
            track_id_map=track_id_map,
            output_directory="/output",
        )

        assert ET.tostring(playlists_with) == ET.tostring(playlists_without)

    def test_set_count_included_in_rekordbot_node(self):
        """Rekordbot node Count includes set playlists."""
        track = MagicMock()
        track.id = 1
        track.file_path = "/output/track.aiff"
        track_id_map = {1: 100}

        plan1 = _make_set_plan("Set 1")
        plan2 = _make_set_plan("Set 2")

        playlists = build_playlists(
            tracks=[track],
            track_id_map=track_id_map,
            output_directory="/output",
            sets=[(plan1, [1]), (plan2, [1])],
        )

        root_node = playlists.find("NODE")
        assert root_node is not None
        rekordbot_node = root_node.find("NODE")
        assert rekordbot_node is not None
        assert rekordbot_node.get("Name") == "rekordbot"

        # Count should be All Tracks + 2 sets = 3
        count = int(rekordbot_node.get("Count", "0"))
        assert count >= 3
