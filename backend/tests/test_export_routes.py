"""Tests for Rekordbox XML export API routes."""

from typing import Any
from unittest.mock import patch

import pytest

from backend.models.database import SessionLocal
from backend.models.track import Track


def _add_track(title: str = "Test", artist: str = "Artist", file_path: str = "/lib/t.aiff") -> int:
    """Add a track to the dev database and return its ID."""
    db = SessionLocal()
    track = Track(
        file_path=file_path,
        title=title,
        artist=artist,
        album="Album",
        genre="Electronic",
        bpm=128.0,
        key=16,
        rating=0,
        duration=300.0,
        bit_rate=2116,
        sample_rate=44100,
    )
    db.add(track)
    db.commit()
    track_id = track.id
    db.close()
    return track_id


@patch("backend.services.xml_schema_mapper.get_file_size", return_value=50000000)
@patch("backend.services.xml_schema_mapper._get_file_mtime", return_value="2026-03-08")
class TestExportRoutes:
    """Tests for the export API endpoints."""

    @pytest.mark.asyncio
    async def test_export_success(self, mock_mtime: Any, mock_size: Any, client: Any) -> None:
        _add_track(title="Track 1", file_path="/lib/a/t1.aiff")
        _add_track(title="Track 2", file_path="/lib/b/t2.aiff")

        response = await client.post("/api/export/rekordbox", json={})
        assert response.status_code == 200

        data = response.json()
        assert data["tracks_exported"] == 2
        assert data["tracks_skipped"] == 0
        assert "output_path" in data
        assert isinstance(data["warnings"], list)

    @pytest.mark.asyncio
    async def test_export_no_tracks(self, mock_mtime: Any, mock_size: Any, client: Any) -> None:
        response = await client.post("/api/export/rekordbox", json={})
        assert response.status_code == 200

        data = response.json()
        assert data["tracks_exported"] == 0

    @pytest.mark.asyncio
    async def test_export_with_track_ids(
        self, mock_mtime: Any, mock_size: Any, client: Any
    ) -> None:
        id1 = _add_track(title="Track 1", file_path="/lib/a/t1.aiff")
        _add_track(title="Track 2", file_path="/lib/b/t2.aiff")

        response = await client.post(
            "/api/export/rekordbox",
            json={"options": {"track_ids": [id1]}},
        )
        assert response.status_code == 200
        assert response.json()["tracks_exported"] == 1

    @pytest.mark.asyncio
    async def test_status_idle(self, mock_mtime: Any, mock_size: Any, client: Any) -> None:
        response = await client.get("/api/export/rekordbox/status")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "idle"
        assert data["last_export"] is None

    @pytest.mark.asyncio
    async def test_status_after_export(self, mock_mtime: Any, mock_size: Any, client: Any) -> None:
        _add_track(title="Track 1", file_path="/lib/a/t1.aiff")

        await client.post("/api/export/rekordbox", json={})
        response = await client.get("/api/export/rekordbox/status")

        data = response.json()
        assert data["status"] == "idle"
        assert data["last_export"] is not None
        assert data["last_export"]["tracks_exported"] == 1
        assert "timestamp" in data["last_export"]
