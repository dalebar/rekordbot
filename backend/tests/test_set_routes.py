"""Tests for set planner API routes."""

import pytest

from backend.models.database import SessionLocal
from backend.models.set_plan import SetPlan, SetTrack
from backend.models.track import Track
from backend.services.set_planner import recalculate_segments

pytestmark = pytest.mark.skip(
    reason="Routes deregistered in Phase 6d.1 — module preserved for future revival"
)

_route_counter = 0


def _create_track(db_session, title="Test", bpm=128.0):
    """Helper to create a track with unique file path."""
    global _route_counter
    _route_counter += 1
    track = Track(
        file_path=f"/test/route_{title.lower()}_{_route_counter}.aiff",
        title=title,
        artist="Artist",
        bpm=bpm,
        genre="Techno",
    )
    db_session.add(track)
    db_session.flush()
    return track


def _create_set_with_tracks(num_tracks=3, name="Test Set"):
    """Helper to create a set with tracks and segments using SessionLocal."""
    db = SessionLocal()
    try:
        plan = SetPlan(
            name=name, description="A test set", source_type="library", status="complete"
        )
        db.add(plan)
        db.flush()

        tracks = []
        for i in range(num_tracks):
            t = _create_track(db, title=f"Track {i + 1}", bpm=120.0 + i * 2)
            tracks.append(t)
            db.add(SetTrack(set_id=plan.id, track_id=t.id, position=i + 1, is_candidate=False))
        db.commit()
        recalculate_segments(plan.id, db)

        # Return IDs (not ORM objects, since session will be closed)
        plan_id = plan.id
        track_ids = [t.id for t in tracks]
        return plan_id, track_ids
    finally:
        db.close()


@pytest.mark.asyncio
async def test_list_sets(client):
    """GET /api/sets returns all sets."""
    _create_set_with_tracks(3, "Set A")

    response = await client.get("/api/sets")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    names = [s["name"] for s in data]
    assert "Set A" in names


@pytest.mark.asyncio
async def test_get_set(client):
    """GET /api/sets/{id} returns set detail."""
    plan_id, _ = _create_set_with_tracks(3)

    response = await client.get(f"/api/sets/{plan_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Set"
    assert len(data["tracks"]) == 3
    assert len(data["segments"]) >= 1


@pytest.mark.asyncio
async def test_get_set_not_found(client):
    """GET /api/sets/{id} returns 404 for missing set."""
    response = await client.get("/api/sets/999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_set(client):
    """PUT /api/sets/{id} updates metadata."""
    plan_id, _ = _create_set_with_tracks(2)

    response = await client.put(f"/api/sets/{plan_id}", json={"name": "Updated Name"})
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_delete_set(client):
    """DELETE /api/sets/{id} deletes the set."""
    plan_id, _ = _create_set_with_tracks(2)

    response = await client.delete(f"/api/sets/{plan_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_lock_unlock_track(client):
    """POST lock/unlock toggles track lock state."""
    plan_id, _ = _create_set_with_tracks(3)

    # Lock
    response = await client.post(f"/api/sets/{plan_id}/lock/2")
    assert response.status_code == 200
    assert response.json()["status"] == "locked"

    # Verify
    detail = await client.get(f"/api/sets/{plan_id}")
    tracks = detail.json()["tracks"]
    pos2 = next(t for t in tracks if t["position"] == 2)
    assert pos2["is_locked"] is True

    # Unlock
    response = await client.post(f"/api/sets/{plan_id}/unlock/2")
    assert response.status_code == 200
    assert response.json()["status"] == "unlocked"


@pytest.mark.asyncio
async def test_update_segment(client):
    """PUT /api/sets/{id}/segments/{seg_id} updates description."""
    plan_id, _ = _create_set_with_tracks(3)

    # Get segments
    detail = await client.get(f"/api/sets/{plan_id}")
    segments = detail.json()["segments"]
    seg_id = segments[0]["id"]

    response = await client.put(
        f"/api/sets/{plan_id}/segments/{seg_id}",
        json={"description": "Dark and moody"},
    )
    assert response.status_code == 200
    assert response.json()["description"] == "Dark and moody"


@pytest.mark.asyncio
async def test_add_track(client):
    """POST /api/sets/{id}/tracks adds a track."""
    plan_id, _ = _create_set_with_tracks(3)

    # Create a new track
    db = SessionLocal()
    try:
        new_track = _create_track(db, "New Track")
        db.commit()
        new_track_id = new_track.id
    finally:
        db.close()

    response = await client.post(
        f"/api/sets/{plan_id}/tracks",
        json={"track_id": new_track_id, "position": 2},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "added"

    # Verify track count increased
    detail = await client.get(f"/api/sets/{plan_id}")
    assert len(detail.json()["tracks"]) == 4


@pytest.mark.asyncio
async def test_remove_track(client):
    """DELETE /api/sets/{id}/tracks/{position} removes a track."""
    plan_id, _ = _create_set_with_tracks(3)

    response = await client.delete(f"/api/sets/{plan_id}/tracks/2")
    assert response.status_code == 200
    assert response.json()["status"] == "removed"

    # Verify track count decreased
    detail = await client.get(f"/api/sets/{plan_id}")
    assert len(detail.json()["tracks"]) == 2


@pytest.mark.asyncio
async def test_move_track(client):
    """POST /api/sets/{id}/tracks/move moves a track."""
    plan_id, _ = _create_set_with_tracks(4)

    response = await client.post(
        f"/api/sets/{plan_id}/tracks/move",
        json={"from_position": 1, "to_position": 3},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "moved"


@pytest.mark.asyncio
async def test_get_candidates(client):
    """GET /api/sets/{id}/candidates returns the candidate pool."""
    plan_id, _ = _create_set_with_tracks(3)

    db = SessionLocal()
    try:
        cand = _create_track(db, "Candidate")
        db.add(SetTrack(set_id=plan_id, track_id=cand.id, position=0, is_candidate=True))
        db.commit()
        cand_id = cand.id
    finally:
        db.close()

    response = await client.get(f"/api/sets/{plan_id}/candidates")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["track_id"] == cand_id


@pytest.mark.asyncio
async def test_export_set(client, tmp_path):
    """POST /api/sets/{id}/export generates XML with set playlist."""
    plan_id, _ = _create_set_with_tracks(3)

    # Override output path to tmp dir
    import backend.config as config_module

    original_xml_path = config_module.settings.rekordbox_xml_path
    config_module.settings.rekordbox_xml_path = str(tmp_path / "rekordbox.xml")
    try:
        response = await client.post(f"/api/sets/{plan_id}/export")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "exported"
        assert data["tracks_in_set"] == 3
    finally:
        config_module.settings.rekordbox_xml_path = original_xml_path
