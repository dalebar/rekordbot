"""Tests for crate API routes."""

from backend.models.crate import Crate, CrateTrack
from backend.models.database import SessionLocal
from backend.models.track import Track


class TestCrateListAndDetail:
    """Tests for GET /api/crates and GET /api/crates/{id}."""

    async def test_list_empty(self, client):
        """List crates when none exist."""
        response = await client.get("/api/crates")
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_with_crates(self, client):
        """List crates with track counts."""
        db = SessionLocal()
        crate = Crate(name="Test", description="Desc")
        track = Track(file_path="/test/route_list.aiff")
        db.add_all([crate, track])
        db.commit()
        db.add(CrateTrack(crate_id=crate.id, track_id=track.id, assignment_method="ai"))
        db.commit()
        db.close()

        response = await client.get("/api/crates")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test"
        assert data[0]["track_count"] == 1

    async def test_get_crate_detail(self, client):
        """Get crate detail with track list."""
        db = SessionLocal()
        crate = Crate(name="Detail", description="Test desc")
        track = Track(file_path="/test/route_detail.aiff")
        db.add_all([crate, track])
        db.commit()
        db.add(CrateTrack(crate_id=crate.id, track_id=track.id, assignment_method="manual"))
        db.commit()
        crate_id = crate.id
        track_id = track.id
        db.close()

        response = await client.get(f"/api/crates/{crate_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Detail"
        assert data["track_ids"] == [track_id]
        assert data["track_count"] == 1

    async def test_get_crate_not_found(self, client):
        """Non-existent crate returns 404."""
        response = await client.get("/api/crates/9999")
        assert response.status_code == 404


class TestCrateDelete:
    """Tests for DELETE /api/crates/{id}."""

    async def test_delete_crate(self, client):
        """Delete a crate."""
        db = SessionLocal()
        crate = Crate(name="Delete", description="Test")
        db.add(crate)
        db.commit()
        crate_id = crate.id
        db.close()

        response = await client.delete(f"/api/crates/{crate_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

    async def test_delete_not_found(self, client):
        """Delete non-existent crate returns 404."""
        response = await client.delete("/api/crates/9999")
        assert response.status_code == 404


class TestCrateUpdate:
    """Tests for PUT /api/crates/{id}."""

    async def test_update_name(self, client):
        """Update crate name only."""
        db = SessionLocal()
        crate = Crate(name="Old Name", description="Desc")
        db.add(crate)
        db.commit()
        crate_id = crate.id
        db.close()

        response = await client.put(
            f"/api/crates/{crate_id}",
            json={"name": "New Name"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"
        assert data["description_changed"] is False

    async def test_update_not_found(self, client):
        """Update non-existent crate returns 404."""
        response = await client.put(
            "/api/crates/9999",
            json={"name": "X"},
        )
        assert response.status_code == 404


class TestCrateTrackManagement:
    """Tests for POST/DELETE /api/crates/{id}/tracks."""

    async def test_add_tracks(self, client):
        """Manually add tracks to a crate."""
        db = SessionLocal()
        crate = Crate(name="Add", description="Test")
        track = Track(file_path="/test/route_add.aiff")
        db.add_all([crate, track])
        db.commit()
        crate_id = crate.id
        track_id = track.id
        db.close()

        response = await client.post(
            f"/api/crates/{crate_id}/tracks",
            json={"track_ids": [track_id]},
        )
        assert response.status_code == 200
        assert response.json()["added"] == 1

    async def test_remove_tracks(self, client):
        """Remove tracks from a crate."""
        db = SessionLocal()
        crate = Crate(name="Remove", description="Test")
        track = Track(file_path="/test/route_rm.aiff")
        db.add_all([crate, track])
        db.commit()
        db.add(CrateTrack(crate_id=crate.id, track_id=track.id, assignment_method="ai"))
        db.commit()
        crate_id = crate.id
        track_id = track.id
        db.close()

        response = await client.request(
            "DELETE",
            f"/api/crates/{crate_id}/tracks",
            json={"track_ids": [track_id]},
        )
        assert response.status_code == 200
        assert response.json()["removed"] == 1


class TestCrateCreate:
    """Tests for POST /api/crates."""

    async def test_create_crate(self, client):
        """Create a crate (pipeline runs in background)."""
        response = await client.post(
            "/api/crates",
            json={
                "name": "Deep Dubby",
                "description": "Deep minimal house, warm and hypnotic",
                "auto_refresh": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Deep Dubby"
        assert data["id"] > 0
        assert "assignment started" in data["message"]
