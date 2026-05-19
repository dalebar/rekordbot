"""Integration tests for Phase 5a Crate Builder.

End-to-end tests covering the full crate lifecycle:
- Create crate → assign tracks → verify
- Overlapping assignment (track in multiple crates)
- Manual add/remove preservation during refresh
- XML export with crates
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.models.crate import CrateTrack
from backend.models.track import Track
from backend.services.crate_assigner import CrateAssigner
from backend.services.crate_manager import (
    add_tracks,
    create_crate,
    delete_crate,
    get_crate,
    list_crates,
    refresh_crate,
    remove_tracks,
)


def _make_track(
    db_session: Session,
    title: str,
    artist: str = "Test Artist",
    genre: str = "House",
    bpm: float = 128.0,
    key: int | None = 1,
    energy: int | None = 7,
    mood: str | None = "Energetic",
) -> Track:
    """Create and persist a test track."""
    track = Track(
        title=title,
        artist=artist,
        genre=genre,
        bpm=bpm,
        key=key,
        energy=energy,
        mood=mood,
        source_path=f"/test/{title.lower().replace(' ', '_')}.aiff",
        file_path=f"/output/{title.lower().replace(' ', '_')}.aiff",
        source_format="aiff",
        source_codec="pcm_s16be",
        file_hash=f"hash_{title.lower().replace(' ', '_')}",
        conversion_action="copy_lossless",
        imported_at=datetime.now(),
    )
    db_session.add(track)
    db_session.commit()
    return track


def _mock_claude_response(matched_ids: list[int]) -> MagicMock:
    """Create a mock Claude API response with assign_tracks tool use."""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = "assign_tracks"
    tool_block.input = {"matching_track_ids": matched_ids}

    usage = MagicMock()
    usage.input_tokens = 100
    usage.output_tokens = 50

    response = MagicMock()
    response.content = [tool_block]
    response.usage = usage
    return response


class TestCrateLifecycle:
    """End-to-end tests for create → assign → verify → refresh."""

    @pytest.mark.asyncio
    async def test_create_assign_verify(self, db_session: Session) -> None:
        """Create a crate, run AI assignment, verify tracks assigned."""
        t1 = _make_track(db_session, "Track One", genre="Deep House")
        t2 = _make_track(db_session, "Track Two", genre="Tech House")
        _make_track(db_session, "Track Three", genre="Techno")

        # Create crate
        crate = create_crate("Deep & Dubby", "Deep minimal house", False, db_session)
        assert crate.id is not None
        crate.parsed_criteria = json.dumps({"mood": "deep", "genres": ["deep house"]})
        db_session.commit()

        # Assign tracks via mocked Claude
        settings = Settings(anthropic_api_key="test-key")
        assigner = CrateAssigner(settings)
        mock_response = _mock_claude_response([t1.id, t2.id])

        mock_client = MagicMock()
        mock_client.model = "test-model"
        mock_client.rate_limiter = AsyncMock()
        mock_client._usage = MagicMock(
            total_input_tokens=0, total_output_tokens=0, total_requests=0
        )

        tracks = db_session.query(Track).all()
        to_thread_patch = "backend.services.crate_assigner.asyncio.to_thread"
        with patch(to_thread_patch, return_value=mock_response):
            result = await assigner.assign_tracks(crate, tracks, db_session, mock_client)

        assert result.matched == 2
        assert result.total_tracks == 3

        # Verify assignments in DB
        detail = get_crate(crate.id, db_session)
        assert set(detail.track_ids) == {t1.id, t2.id}
        assert detail.track_count == 2

    @pytest.mark.asyncio
    async def test_refresh_preserves_manual_adds(self, db_session: Session) -> None:
        """Refresh clears AI assignments but preserves manual ones."""
        t1 = _make_track(db_session, "AI Track")
        t2 = _make_track(db_session, "Manual Track")
        t3 = _make_track(db_session, "New Match")

        crate = create_crate("Test Crate", "test description", False, db_session)
        crate.parsed_criteria = json.dumps({"mood": "test"})
        db_session.commit()

        # Add t1 as AI assignment
        db_session.add(CrateTrack(crate_id=crate.id, track_id=t1.id, assignment_method="ai"))
        # Add t2 as manual assignment
        db_session.add(CrateTrack(crate_id=crate.id, track_id=t2.id, assignment_method="manual"))
        db_session.commit()

        # Refresh — mock Claude now matches t3
        settings = Settings(anthropic_api_key="test-key")
        assigner = CrateAssigner(settings)
        mock_response = _mock_claude_response([t3.id])

        mock_client = MagicMock()
        mock_client.model = "test-model"
        mock_client.rate_limiter = AsyncMock()
        mock_client._usage = MagicMock(
            total_input_tokens=0, total_output_tokens=0, total_requests=0
        )

        to_thread_patch = "backend.services.crate_assigner.asyncio.to_thread"
        with patch(to_thread_patch, return_value=mock_response):
            await refresh_crate(crate.id, db_session, settings, assigner)

        # Verify: t1 AI removed, t2 manual preserved, t3 new AI added
        assignments = db_session.query(CrateTrack).filter(CrateTrack.crate_id == crate.id).all()
        assignment_map = {ct.track_id: ct.assignment_method for ct in assignments}

        assert t1.id not in assignment_map  # AI assignment cleared
        assert assignment_map[t2.id] == "manual"  # Manual preserved
        assert assignment_map[t3.id] == "ai"  # New AI assignment


class TestOverlappingAssignment:
    """Test that a track can be in multiple crates."""

    def test_track_in_multiple_crates(self, db_session: Session) -> None:
        """A single track can be assigned to multiple crates."""
        track = _make_track(db_session, "Shared Track")

        crate_a = create_crate("Crate A", "first crate", False, db_session)
        crate_b = create_crate("Crate B", "second crate", False, db_session)

        add_tracks(crate_a.id, [track.id], db_session)
        add_tracks(crate_b.id, [track.id], db_session)

        detail_a = get_crate(crate_a.id, db_session)
        detail_b = get_crate(crate_b.id, db_session)

        assert track.id in detail_a.track_ids
        assert track.id in detail_b.track_ids

    def test_delete_crate_does_not_affect_other_crates(self, db_session: Session) -> None:
        """Deleting one crate doesn't remove the track from another."""
        track = _make_track(db_session, "Surviving Track")

        crate_a = create_crate("Delete Me", "to be deleted", False, db_session)
        crate_b = create_crate("Keep Me", "to keep", False, db_session)

        add_tracks(crate_a.id, [track.id], db_session)
        add_tracks(crate_b.id, [track.id], db_session)

        # Trigger ORM cascade load
        _ = crate_a.crate_tracks
        delete_crate(crate_a.id, db_session)

        detail_b = get_crate(crate_b.id, db_session)
        assert track.id in detail_b.track_ids

    def test_remove_from_one_crate_keeps_in_another(self, db_session: Session) -> None:
        """Removing a track from one crate doesn't affect other crates."""
        track = _make_track(db_session, "Multi Crate Track")

        crate_a = create_crate("Crate X", "first", False, db_session)
        crate_b = create_crate("Crate Y", "second", False, db_session)

        add_tracks(crate_a.id, [track.id], db_session)
        add_tracks(crate_b.id, [track.id], db_session)

        remove_tracks(crate_a.id, [track.id], db_session)

        detail_a = get_crate(crate_a.id, db_session)
        detail_b = get_crate(crate_b.id, db_session)

        assert track.id not in detail_a.track_ids
        assert track.id in detail_b.track_ids


class TestManualAddRemove:
    """Test manual track management."""

    def test_manual_add_then_list(self, db_session: Session) -> None:
        """Manually added tracks show up in crate detail."""
        t1 = _make_track(db_session, "Manual One")
        t2 = _make_track(db_session, "Manual Two")

        crate = create_crate("Manual Crate", "manual adds only", False, db_session)
        added = add_tracks(crate.id, [t1.id, t2.id], db_session)
        assert added == 2

        detail = get_crate(crate.id, db_session)
        assert set(detail.track_ids) == {t1.id, t2.id}

    def test_manual_add_duplicate_ignored(self, db_session: Session) -> None:
        """Adding a track that's already in the crate is a no-op."""
        track = _make_track(db_session, "Duplicate Track")
        crate = create_crate("Dup Crate", "test duplicates", False, db_session)

        added_first = add_tracks(crate.id, [track.id], db_session)
        added_second = add_tracks(crate.id, [track.id], db_session)

        assert added_first == 1
        assert added_second == 0

        detail = get_crate(crate.id, db_session)
        assert detail.track_count == 1

    def test_remove_tracks(self, db_session: Session) -> None:
        """Removing tracks decrements the count."""
        t1 = _make_track(db_session, "Remove One")
        t2 = _make_track(db_session, "Remove Two")

        crate = create_crate("Remove Crate", "test removal", False, db_session)
        add_tracks(crate.id, [t1.id, t2.id], db_session)

        removed = remove_tracks(crate.id, [t1.id], db_session)
        assert removed == 1

        detail = get_crate(crate.id, db_session)
        assert detail.track_count == 1
        assert t1.id not in detail.track_ids
        assert t2.id in detail.track_ids


class TestCrateListAndDetail:
    """Test listing and detail views."""

    def test_list_shows_track_counts(self, db_session: Session) -> None:
        """List crates includes accurate track counts."""
        t1 = _make_track(db_session, "Count Track A")
        t2 = _make_track(db_session, "Count Track B")

        crate_a = create_crate("Full Crate", "has two tracks", False, db_session)
        crate_b = create_crate("Empty Crate", "has no tracks", False, db_session)

        add_tracks(crate_a.id, [t1.id, t2.id], db_session)

        summaries = list_crates(db_session)
        by_id = {s.id: s for s in summaries}

        assert by_id[crate_a.id].track_count == 2
        assert by_id[crate_b.id].track_count == 0
