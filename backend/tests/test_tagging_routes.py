"""Tests for tagging API routes."""

import shutil
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.models.database import SessionLocal, init_db
from backend.models.track import Track

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client with a fresh database."""
    from backend.main import app

    init_db()

    # Clean tracks table for test isolation
    db = SessionLocal()
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
