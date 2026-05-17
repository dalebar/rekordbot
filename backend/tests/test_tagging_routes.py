"""Tests for tagging API routes."""

import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.models.crate import Crate, CrateTrack
from backend.models.database import Base, SessionLocal, init_db
from backend.models.set_plan import SetPlan, SetTrack
from backend.models.track import Track

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client with a fresh database."""
    from backend.main import app
    from backend.models.database import engine as prod_engine

    Base.metadata.drop_all(prod_engine)
    init_db()

    # Clean tables for test isolation
    db = SessionLocal()
    db.query(SetTrack).delete()
    db.query(SetPlan).delete()
    db.query(CrateTrack).delete()
    db.query(Crate).delete()
    db.query(Track).delete()
    db.commit()
    db.close()

    # Reset module-level queue state
    import backend.routes.ingest as ingest_module
    import backend.routes.tagging as tagging_module

    ingest_module._queue = None
    tagging_module._analysis_queue = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def db_with_track(tmp_path):
    """Insert a track into the DB and return its ID + file path."""
    # Copy fixture to tmp dir
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    src = FIXTURES_DIR / "silence_320k.mp3"
    dst = audio_dir / "silence_320k.mp3"
    shutil.copy2(src, dst)

    db = SessionLocal()
    try:
        track = Track(
            file_path=str(dst),
            analysis_status="unanalysed",
        )
        db.add(track)
        db.commit()
        track_id = track.id
        return track_id, dst
    finally:
        db.close()


@pytest.fixture
def db_with_analysed_track(tmp_path):
    """Insert an analysed track into the DB."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    src = FIXTURES_DIR / "silence_320k.mp3"
    dst = audio_dir / "test_analysed.mp3"
    shutil.copy2(src, dst)

    db = SessionLocal()
    try:
        track = Track(
            file_path=str(dst),
            title="Test Track",
            artist="Test Artist",
            bpm=128.0,
            key=16,
            source_bpm=126.0,
            source_key=15,
            bpm_confidence=0.85,
            key_confidence=0.72,
            analysis_status="analysed",
        )
        db.add(track)
        db.commit()
        track_id = track.id
        return track_id, dst
    finally:
        db.close()


class TestTrackListEnhanced:
    """Test enhanced GET /api/tracks."""

    async def test_list_tracks_empty(self, client):
        response = await client.get("/api/tracks")
        assert response.status_code == 200
        data = response.json()
        assert data["tracks"] == []
        assert data["total"] == 0

    async def test_list_tracks_with_analysis_fields(self, client, db_with_analysed_track):
        response = await client.get("/api/tracks")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tracks"]) >= 1

        track = data["tracks"][0]
        assert track["analysis_status"] == "analysed"
        assert track["bpm_confidence"] == 0.85
        assert track["key_confidence"] == 0.72
        assert track["has_bpm_conflict"] is True
        assert track["has_key_conflict"] is True
        assert "key_display" in track


class TestUpdateTrack:
    """Test PUT /api/tracks/{id}."""

    async def test_update_title(self, client, db_with_analysed_track):
        track_id, _ = db_with_analysed_track
        response = await client.put(
            f"/api/tracks/{track_id}",
            json={"title": "Updated Title"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"
        # Other fields should be unchanged
        assert data["artist"] == "Test Artist"

    async def test_update_bpm(self, client, db_with_analysed_track):
        track_id, _ = db_with_analysed_track
        response = await client.put(
            f"/api/tracks/{track_id}",
            json={"bpm": 130.5},
        )
        assert response.status_code == 200
        assert response.json()["bpm"] == 130.5

    async def test_update_nonexistent_track(self, client):
        response = await client.put("/api/tracks/99999", json={"title": "X"})
        assert response.status_code == 404


class TestRevertField:
    """Test PUT /api/tracks/{id}/revert/{field}."""

    async def test_revert_bpm(self, client, db_with_analysed_track):
        track_id, _ = db_with_analysed_track
        response = await client.put(f"/api/tracks/{track_id}/revert/bpm")
        assert response.status_code == 200
        assert response.json()["bpm"] == 126.0

    async def test_revert_key(self, client, db_with_analysed_track):
        track_id, _ = db_with_analysed_track
        response = await client.put(f"/api/tracks/{track_id}/revert/key")
        assert response.status_code == 200
        assert response.json()["key"] == 15

    async def test_revert_invalid_field(self, client, db_with_analysed_track):
        track_id, _ = db_with_analysed_track
        response = await client.put(f"/api/tracks/{track_id}/revert/title")
        assert response.status_code == 400


class TestBPMMultiply:
    """Test PUT /api/tracks/{id}/bpm-multiply."""

    async def test_double_bpm(self, client, db_with_analysed_track):
        track_id, _ = db_with_analysed_track
        response = await client.put(
            f"/api/tracks/{track_id}/bpm-multiply",
            json={"factor": 2},
        )
        assert response.status_code == 200
        assert response.json()["bpm"] == 256.0

    async def test_halve_bpm(self, client, db_with_analysed_track):
        track_id, _ = db_with_analysed_track
        response = await client.put(
            f"/api/tracks/{track_id}/bpm-multiply",
            json={"factor": 0.5},
        )
        assert response.status_code == 200
        assert response.json()["bpm"] == 64.0

    async def test_invalid_factor(self, client, db_with_analysed_track):
        track_id, _ = db_with_analysed_track
        response = await client.put(
            f"/api/tracks/{track_id}/bpm-multiply",
            json={"factor": 3},
        )
        assert response.status_code == 400


class TestWriteTags:
    """Test POST /api/tracks/write-tags."""

    async def test_write_tags(self, client, db_with_analysed_track):
        track_id, _ = db_with_analysed_track
        response = await client.post(
            "/api/tracks/write-tags",
            json={"track_ids": [track_id]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["succeeded"] == 1

    async def test_write_tags_empty_list(self, client):
        response = await client.post(
            "/api/tracks/write-tags",
            json={"track_ids": []},
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0


class TestAnalyseEndpoints:
    """Test POST /api/tracks/analyse and related endpoints."""

    async def test_analyse_no_tracks(self, client):
        """Analyse with no unanalysed tracks."""
        response = await client.post("/api/tracks/analyse", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["total_tracks"] == 0

    async def test_cancel_no_batch(self, client):
        """Cancel when no batch is running."""
        response = await client.post("/api/tracks/analyse/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "no_active_batch"


class TestDeleteTracks:
    """Test DELETE /api/tracks."""

    async def test_delete_tracks_by_id(self, client, db_with_track):
        """Delete tracks by ID — records removed."""
        track_id, _ = db_with_track
        response = await client.request("DELETE", "/api/tracks", json={"track_ids": [track_id]})
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 1
        assert data["not_found"] == 0
        assert data["file_errors"] == 0

        # Verify track is gone
        get_response = await client.get("/api/tracks")
        assert all(t["id"] != track_id for t in get_response.json()["tracks"])

    async def test_delete_with_file_removal(self, client, db_with_track):
        """Delete with delete_files=true — output file removed from disk."""
        track_id, file_path = db_with_track
        assert file_path.exists()

        response = await client.request(
            "DELETE",
            "/api/tracks",
            json={"track_ids": [track_id], "delete_files": True},
        )
        assert response.status_code == 200
        assert response.json()["deleted"] == 1
        assert not file_path.exists()

    async def test_delete_with_missing_file(self, client, tmp_path):
        """Delete with delete_files=true but file already missing — no error."""
        db = SessionLocal()
        track = Track(file_path=str(tmp_path / "nonexistent.mp3"))
        db.add(track)
        db.commit()
        track_id = track.id
        db.close()

        response = await client.request(
            "DELETE",
            "/api/tracks",
            json={"track_ids": [track_id], "delete_files": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 1
        assert data["file_errors"] == 0

    async def test_delete_tracks_in_crates_and_sets(self, client, db_with_track):
        """Delete tracks that are in crates/sets — associations also removed."""
        track_id, _ = db_with_track

        db = SessionLocal()
        crate = Crate(name="Test", description="test")
        db.add(crate)
        db.commit()
        crate_id = crate.id
        db.add(CrateTrack(crate_id=crate_id, track_id=track_id, assignment_method="ai"))
        db.commit()

        set_plan = SetPlan(name="Test Set", description="test")
        db.add(set_plan)
        db.commit()
        set_plan_id = set_plan.id
        db.add(SetTrack(set_id=set_plan_id, track_id=track_id, position=1))
        db.commit()
        db.close()

        response = await client.request("DELETE", "/api/tracks", json={"track_ids": [track_id]})
        assert response.status_code == 200
        assert response.json()["deleted"] == 1

        # Verify associations are gone
        db = SessionLocal()
        assert db.query(CrateTrack).filter_by(track_id=track_id).first() is None
        assert db.query(SetTrack).filter_by(track_id=track_id).first() is None
        # Crate/set themselves still exist
        assert db.query(Crate).filter_by(id=crate_id).first() is not None
        assert db.query(SetPlan).filter_by(id=set_plan_id).first() is not None
        db.close()

    async def test_delete_empty_track_ids(self, client):
        """Delete with empty track_ids — 200 with deleted=0."""
        response = await client.request("DELETE", "/api/tracks", json={"track_ids": []})
        assert response.status_code == 200
        assert response.json()["deleted"] == 0

    async def test_delete_nonexistent_ids(self, client):
        """Delete with non-existent IDs — not_found incremented."""
        response = await client.request(
            "DELETE", "/api/tracks", json={"track_ids": [99998, 99999]}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] == 0
        assert data["not_found"] == 2
