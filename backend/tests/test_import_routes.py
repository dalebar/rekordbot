"""Tests for Rekordbox XML import API routes."""

import asyncio
import json
from pathlib import Path

from backend.models.track import Track


def _write_xml(tmp_path: Path, tracks_xml: str = "", playlists_xml: str = "") -> Path:
    """Helper to write a test Rekordbox XML file."""
    if not playlists_xml:
        playlists_xml = '<NODE Type="0" Name="ROOT" Count="0"/>'

    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<DJ_PLAYLISTS Version="1.0.0">\n'
        '  <PRODUCT Name="rekordbox" Version="6.7.4" Company="AlphaTheta"/>\n'
        f'  <COLLECTION Entries="0">{tracks_xml}</COLLECTION>\n'
        f"  <PLAYLISTS>{playlists_xml}</PLAYLISTS>\n"
        "</DJ_PLAYLISTS>\n"
    )
    xml_file = tmp_path / "test_library.xml"
    xml_file.write_text(content)
    return xml_file


class TestStartImport:
    """Test POST /api/import/rekordbox."""

    async def test_start_import_success(self, client, tmp_path):
        audio = tmp_path / "track.aiff"
        audio.write_bytes(b"fake audio")

        from backend.services.location_encoder import encode_location

        xml_file = _write_xml(
            tmp_path,
            f'<TRACK TrackID="1" Name="Test" Location="{encode_location(str(audio))}"/>',
        )

        response = await client.post(
            "/api/import/rekordbox",
            json={"file_path": str(xml_file)},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"

        # Wait for import to complete
        await asyncio.sleep(0.5)

    async def test_start_import_file_not_found(self, client):
        response = await client.post(
            "/api/import/rekordbox",
            json={"file_path": "/nonexistent/file.xml"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert "not found" in data["message"].lower()


class TestCancelImport:
    """Test POST /api/import/cancel."""

    async def test_cancel_no_import(self, client):
        response = await client.post("/api/import/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "no_import"


class TestListConflicts:
    """Test GET /api/import/conflicts."""

    async def test_list_conflicts_empty(self, client):
        response = await client.get("/api/import/conflicts")
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_conflicts_with_data(self, client):
        # Create a track with conflicts
        from backend.models.database import SessionLocal

        db = SessionLocal()
        try:
            track = Track(
                file_path="/test/conflict.aiff",
                title="Test Track",
                artist="Test Artist",
                import_conflicts=json.dumps(
                    [
                        {
                            "field": "bpm",
                            "rekordbox_value": 128.0,
                            "rekordbot_value": 127.0,
                            "recommended": "rekordbox",
                        }
                    ]
                ),
            )
            db.add(track)
            db.commit()
            track_id = track.id
        finally:
            db.close()

        response = await client.get("/api/import/conflicts")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["track_id"] == track_id
        assert len(data[0]["conflicts"]) == 1
        assert data[0]["conflicts"][0]["field"] == "bpm"


class TestResolveConflict:
    """Test POST /api/import/conflicts/{track_id}/resolve."""

    async def test_resolve_single_track(self, client):
        from backend.models.database import SessionLocal

        db = SessionLocal()
        try:
            track = Track(
                file_path="/test/resolve.aiff",
                bpm=127.0,
                import_conflicts=json.dumps(
                    [
                        {
                            "field": "bpm",
                            "rekordbox_value": 128.0,
                            "rekordbot_value": 127.0,
                            "recommended": "rekordbox",
                        }
                    ]
                ),
            )
            db.add(track)
            db.commit()
            track_id = track.id
        finally:
            db.close()

        response = await client.post(
            f"/api/import/conflicts/{track_id}/resolve",
            json={"resolutions": {"bpm": "rekordbox"}},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"

        # Verify the conflict was cleared
        db = SessionLocal()
        try:
            updated = db.query(Track).filter(Track.id == track_id).first()
            assert updated is not None
            assert updated.bpm == 128.0
            assert updated.import_conflicts is None
        finally:
            db.close()


class TestResolveAll:
    """Test POST /api/import/conflicts/resolve-all."""

    async def test_resolve_all_rekordbox(self, client):
        from backend.models.database import SessionLocal

        db = SessionLocal()
        try:
            track = Track(
                file_path="/test/bulk.aiff",
                bpm=127.0,
                genre="Techno",
                import_conflicts=json.dumps(
                    [
                        {
                            "field": "bpm",
                            "rekordbox_value": 128.0,
                            "rekordbot_value": 127.0,
                            "recommended": "rekordbox",
                        },
                        {
                            "field": "genre",
                            "rekordbox_value": "House",
                            "rekordbot_value": "Techno",
                            "recommended": "rekordbox",
                        },
                    ]
                ),
            )
            db.add(track)
            db.commit()
        finally:
            db.close()

        response = await client.post(
            "/api/import/conflicts/resolve-all",
            json={"strategy": "rekordbox"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"
        assert data["count"] == 1

    async def test_resolve_all_rekordbot(self, client):
        from backend.models.database import SessionLocal

        db = SessionLocal()
        try:
            track = Track(
                file_path="/test/keep.aiff",
                bpm=127.0,
                import_conflicts=json.dumps(
                    [
                        {
                            "field": "bpm",
                            "rekordbox_value": 128.0,
                            "rekordbot_value": 127.0,
                            "recommended": "rekordbox",
                        }
                    ]
                ),
            )
            db.add(track)
            db.commit()
        finally:
            db.close()

        response = await client.post(
            "/api/import/conflicts/resolve-all",
            json={"strategy": "rekordbot"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"

    async def test_resolve_all_invalid_strategy(self, client):
        response = await client.post(
            "/api/import/conflicts/resolve-all",
            json={"strategy": "invalid"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
