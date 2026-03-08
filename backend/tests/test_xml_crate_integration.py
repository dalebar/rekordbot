"""Tests for XML export integration with crate playlists."""

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock

from backend.services.xml_builder import build_crate_playlists, build_playlists


def _make_crate(name: str) -> MagicMock:
    """Create a mock crate with a name."""
    crate = MagicMock()
    crate.name = name
    return crate


class TestBuildCratePlaylists:
    """Tests for build_crate_playlists()."""

    def test_adds_crate_nodes(self):
        """Crate playlists are added as Type=1 NODEs."""
        parent = ET.Element("NODE")
        crate = _make_crate("Deep Dubby")
        track_id_map = {1: 100, 2: 200, 3: 300}
        crate_track_ids = [1, 3]

        build_crate_playlists([(crate, crate_track_ids)], track_id_map, parent)

        nodes = list(parent)
        assert len(nodes) == 1
        assert nodes[0].get("Name") == "Deep Dubby"
        assert nodes[0].get("Type") == "1"
        assert nodes[0].get("Entries") == "2"

        track_refs = list(nodes[0])
        assert len(track_refs) == 2
        assert track_refs[0].get("Key") == "100"
        assert track_refs[1].get("Key") == "300"

    def test_sorted_alphabetically(self):
        """Crate playlists are sorted by name."""
        parent = ET.Element("NODE")
        crate_z = _make_crate("Zzz Crate")
        crate_a = _make_crate("Aaa Crate")
        track_id_map = {1: 100}

        build_crate_playlists(
            [(crate_z, [1]), (crate_a, [1])],
            track_id_map,
            parent,
        )

        nodes = list(parent)
        assert nodes[0].get("Name") == "Aaa Crate"
        assert nodes[1].get("Name") == "Zzz Crate"

    def test_invalid_track_ids_skipped(self):
        """Track IDs not in track_id_map are skipped."""
        parent = ET.Element("NODE")
        crate = _make_crate("Test")
        track_id_map = {1: 100}

        build_crate_playlists([(crate, [1, 999])], track_id_map, parent)

        node = list(parent)[0]
        assert node.get("Entries") == "1"

    def test_empty_crate(self):
        """Crate with no matching tracks still gets a node."""
        parent = ET.Element("NODE")
        crate = _make_crate("Empty")
        track_id_map: dict[int, int] = {}

        build_crate_playlists([(crate, [999])], track_id_map, parent)

        node = list(parent)[0]
        assert node.get("Entries") == "0"


class TestBuildPlaylistsWithCrates:
    """Tests for build_playlists() with crate integration."""

    def test_crates_appear_alongside_folder_playlists(self):
        """Crate playlists coexist with folder-based playlists."""
        track = MagicMock()
        track.id = 1
        track.file_path = "/output/Artist/track.aiff"
        track_id_map = {1: 100}

        crate = _make_crate("Peak Time")

        playlists = build_playlists(
            tracks=[track],
            track_id_map=track_id_map,
            output_directory="/output",
            crates=[(crate, [1])],
        )

        # Find all Type=1 nodes (playlists)
        playlist_names = []
        for node in playlists.iter("NODE"):
            if node.get("Type") == "1":
                playlist_names.append(node.get("Name"))

        assert "All Tracks" in playlist_names
        assert "Peak Time" in playlist_names

    def test_no_crates(self):
        """Without crates, output is unchanged from Phase 4."""
        track = MagicMock()
        track.id = 1
        track.file_path = "/output/track.aiff"
        track_id_map = {1: 100}

        playlists_with = build_playlists(
            tracks=[track],
            track_id_map=track_id_map,
            output_directory="/output",
            crates=None,
        )
        playlists_without = build_playlists(
            tracks=[track],
            track_id_map=track_id_map,
            output_directory="/output",
        )

        # Both should have the same structure
        assert ET.tostring(playlists_with) == ET.tostring(playlists_without)

    def test_crate_count_included_in_rekordbot_node(self):
        """Rekordbot node Count includes crate playlists."""
        track = MagicMock()
        track.id = 1
        track.file_path = "/output/track.aiff"
        track_id_map = {1: 100}

        crate1 = _make_crate("Crate 1")
        crate2 = _make_crate("Crate 2")

        playlists = build_playlists(
            tracks=[track],
            track_id_map=track_id_map,
            output_directory="/output",
            crates=[(crate1, [1]), (crate2, [1])],
        )

        # Find the rekordbot folder node
        root_node = playlists.find("NODE")
        assert root_node is not None
        rekordbot_node = root_node.find("NODE")
        assert rekordbot_node is not None
        assert rekordbot_node.get("Name") == "rekordbot"

        # Count should be All Tracks + 2 crates = 3
        count = int(rekordbot_node.get("Count", "0"))
        assert count >= 3
