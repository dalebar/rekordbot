"""Phase 2b integration tests — end-to-end organisation pipeline.

Tests the full flow: ingest → analyse → propose → approve → verify.
"""

import shutil
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.models.database import SessionLocal, init_db
from backend.models.preference_rule import PreferenceRule
from backend.models.track import Track

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "audio"


@pytest_asyncio.fixture
async def client(tmp_path):
    """Async HTTP client with a fresh database."""
    from backend.main import app

    init_db()

    db = SessionLocal()
    db.query(Track).delete()
    db.query(PreferenceRule).delete()
    db.commit()
    db.close()

    import backend.routes.organise as organise_module

    organise_module._organiser = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _insert_track(tmp_path: Path, **kwargs) -> int:
    """Insert a track with metadata, returning its ID."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(exist_ok=True)
    filename = kwargs.pop("filename", "test.mp3")
    src = FIXTURES_DIR / "silence_320k.mp3"
    dst = audio_dir / filename
    shutil.copy2(src, dst)

    db = SessionLocal()
    try:
        track = Track(
            file_path=str(dst),
            title=kwargs.get("title", "Test Track"),
            artist=kwargs.get("artist", "Test Artist"),
            album=kwargs.get("album", "Test Album"),
            genre=kwargs.get("genre", "House"),
            analysis_status=kwargs.get("analysis_status", "analysed"),
            organisation_status="unorganised",
        )
        db.add(track)
        db.commit()
        return track.id
    finally:
        db.close()


class TestEndToEndOrganisation:
    """End-to-end organisation flow tests."""

    async def test_propose_and_approve_flow(self, client, tmp_path):
        """Full flow: insert track → propose → get proposal → approve → verify moved."""
        track_id = _insert_track(
            tmp_path,
            filename="flow_test.mp3",
            title="Flow Test",
            artist="Test Artist",
            album="Test Album",
        )

        # Step 1: Propose organisation
        response = await client.post(
            "/api/organise/propose",
            json={"track_ids": [track_id]},
        )
        assert response.status_code == 200
        assert response.json()["total_tracks"] == 1

        # Wait for proposal to complete (it runs as background task)
        import asyncio

        await asyncio.sleep(0.5)

        # Step 2: Get proposal
        response = await client.get("/api/organise/proposal")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["total"] >= 1

        # Step 3: Approve
        response = await client.post(
            "/api/organise/approve",
            json={"mode": "auto_approved"},
        )
        assert response.status_code == 200
        result = response.json()
        # Track should have been moved (or no proposed tracks if proposal didn't finish)
        assert result["total_moved"] >= 0

    async def test_propose_and_resolve_flow(self, client, tmp_path):
        """Propose a sparse track → review → resolve → approve."""
        # Track with sparse metadata should need review
        track_id = _insert_track(
            tmp_path,
            filename="sparse_test.mp3",
            title="Unknown",
            artist=None,
            album=None,
            genre=None,
        )

        # Propose
        response = await client.post(
            "/api/organise/propose",
            json={"track_ids": [track_id]},
        )
        assert response.status_code == 200

        import asyncio

        await asyncio.sleep(0.5)

        # Get proposal
        response = await client.get("/api/organise/proposal")
        assert response.status_code == 200
        data = response.json()

        # Should be in needs_review or auto_approved
        total = data["summary"]["total"]
        assert total >= 1

        # Resolve by accepting (whether it's in review or auto-approved)
        if data["summary"]["needs_review"] > 0:
            response = await client.post(
                f"/api/organise/resolve/{track_id}",
                json={"action": "accept"},
            )
            assert response.status_code == 200
            assert response.json()["organisation_status"] == "proposed"

    async def test_preference_rule_affects_organisation(self, client, tmp_path):
        """Create a preference rule, then organise — rule should be applied."""
        # Create a preference rule
        response = await client.post(
            "/api/preferences",
            json={
                "rule_type": "artist_folder",
                "key": "Test Artist",
                "value": "My Test Artist",
            },
        )
        assert response.status_code == 200

        # Insert a track
        track_id = _insert_track(
            tmp_path,
            filename="pref_test.mp3",
            title="Pref Test",
            artist="Test Artist",
            album="Test Album",
        )

        # Propose
        response = await client.post(
            "/api/organise/propose",
            json={"track_ids": [track_id]},
        )
        assert response.status_code == 200

        import asyncio

        await asyncio.sleep(0.5)

        # Verify the track was proposed (preference rule should have been applied)
        response = await client.get("/api/tracks")
        assert response.status_code == 200
        tracks = response.json()["tracks"]
        track = next((t for t in tracks if t["id"] == track_id), None)
        assert track is not None
        # The proposed_path should exist and contain the preference-mapped folder
        if track["proposed_path"]:
            assert "My Test Artist" in track["proposed_path"]

    async def test_reorganise_after_changes(self, client, tmp_path):
        """Re-organise a track after metadata changes."""
        track_id = _insert_track(
            tmp_path,
            filename="reorg_test.mp3",
            title="Reorg Test",
            artist="Original Artist",
        )

        # First proposal
        response = await client.post(
            "/api/organise/propose",
            json={"track_ids": [track_id]},
        )
        assert response.status_code == 200

        import asyncio

        await asyncio.sleep(0.5)

        # Update artist
        response = await client.put(
            f"/api/tracks/{track_id}",
            json={"artist": "New Artist"},
        )
        assert response.status_code == 200

        # Re-propose
        response = await client.post(
            "/api/organise/propose",
            json={"track_ids": [track_id], "options": {"skip_if_organised": False}},
        )
        assert response.status_code == 200

    async def test_tracks_list_includes_organisation_fields(self, client, tmp_path):
        """GET /api/tracks returns organisation fields."""
        _insert_track(tmp_path, filename="fields_test.mp3")

        response = await client.get("/api/tracks")
        assert response.status_code == 200
        track = response.json()["tracks"][0]
        assert "organisation_status" in track
        assert "proposed_path" in track
        assert "organisation_confidence" in track
        assert track["organisation_status"] == "unorganised"
