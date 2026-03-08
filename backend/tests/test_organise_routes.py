"""Tests for organisation API routes."""

import shutil
from pathlib import Path

import pytest
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

    # Clean tables for test isolation
    db = SessionLocal()
    db.query(Track).delete()
    db.query(PreferenceRule).delete()
    db.commit()
    db.close()

    # Reset module-level state
    import backend.routes.organise as organise_module

    organise_module._organiser = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def db_with_track(tmp_path):
    """Insert a track with metadata into the DB."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    src = FIXTURES_DIR / "silence_320k.mp3"
    dst = audio_dir / "test_track.mp3"
    shutil.copy2(src, dst)

    db = SessionLocal()
    try:
        track = Track(
            file_path=str(dst),
            title="Test Track",
            artist="Test Artist",
            album="Test Album",
            genre="House",
            analysis_status="analysed",
            organisation_status="unorganised",
        )
        db.add(track)
        db.commit()
        track_id = track.id
        return track_id, dst
    finally:
        db.close()


@pytest.fixture
def db_with_proposed_track(tmp_path):
    """Insert a track with a proposed path."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    src = FIXTURES_DIR / "silence_320k.mp3"
    dst = audio_dir / "proposed_track.mp3"
    shutil.copy2(src, dst)

    proposed = tmp_path / "library" / "Test Artist" / "Test Album" / "Test Track.mp3"

    db = SessionLocal()
    try:
        track = Track(
            file_path=str(dst),
            title="Test Track",
            artist="Test Artist",
            album="Test Album",
            genre="House",
            analysis_status="analysed",
            organisation_status="proposed",
            proposed_path=str(proposed),
            organisation_confidence=0.9,
        )
        db.add(track)
        db.commit()
        track_id = track.id
        return track_id, dst, proposed
    finally:
        db.close()


@pytest.fixture
def db_with_review_track(tmp_path):
    """Insert a track needing review."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    src = FIXTURES_DIR / "silence_320k.mp3"
    dst = audio_dir / "review_track.mp3"
    shutil.copy2(src, dst)

    proposed = tmp_path / "library" / "Unsorted" / "review_track.mp3"

    db = SessionLocal()
    try:
        track = Track(
            file_path=str(dst),
            title="Unknown",
            organisation_status="review_needed",
            proposed_path=str(proposed),
            organisation_confidence=0.4,
        )
        db.add(track)
        db.commit()
        track_id = track.id
        return track_id, dst, proposed
    finally:
        db.close()


class TestProposeOrganisation:
    """Test POST /api/organise/propose."""

    async def test_propose_no_tracks(self, client):
        """Propose with no unorganised tracks."""
        response = await client.post("/api/organise/propose", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["total_tracks"] == 0
        assert data["message"] == "No tracks to organise."

    async def test_propose_with_tracks(self, client, db_with_track):
        """Propose starts a batch for unorganised tracks."""
        track_id, _ = db_with_track
        response = await client.post(
            "/api/organise/propose",
            json={"track_ids": [track_id]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_tracks"] == 1
        assert data["batch_id"] != ""
        assert data["message"] == "Organisation proposal started"


class TestOrganiseCancel:
    """Test POST /api/organise/cancel."""

    async def test_cancel_no_operation(self, client):
        """Cancel when no operation is running."""
        response = await client.post("/api/organise/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "no_active_operation"


class TestGetProposal:
    """Test GET /api/organise/proposal."""

    async def test_get_proposal_empty(self, client):
        """Get proposal with no proposed tracks."""
        response = await client.get("/api/organise/proposal")
        assert response.status_code == 200
        data = response.json()
        assert data["auto_approved"] == []
        assert data["needs_review"] == []
        assert data["summary"]["total"] == 0

    async def test_get_proposal_with_proposed(self, client, db_with_proposed_track):
        """Get proposal includes auto-approved tracks."""
        response = await client.get("/api/organise/proposal")
        assert response.status_code == 200
        data = response.json()
        assert len(data["auto_approved"]) == 1
        assert data["auto_approved"][0]["title"] == "Test Track"
        assert data["summary"]["auto_approved"] == 1

    async def test_get_proposal_with_review(self, client, db_with_review_track):
        """Get proposal includes tracks needing review."""
        response = await client.get("/api/organise/proposal")
        assert response.status_code == 200
        data = response.json()
        assert len(data["needs_review"]) == 1
        assert data["summary"]["needs_review"] == 1


class TestApproveOrganisation:
    """Test POST /api/organise/approve."""

    async def test_approve_no_tracks(self, client):
        """Approve with no proposed tracks."""
        response = await client.post(
            "/api/organise/approve",
            json={"mode": "auto_approved"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_moved"] == 0
        assert data["message"] == "No tracks to move."

    async def test_approve_auto_approved(self, client, db_with_proposed_track):
        """Approve moves auto-approved files."""
        track_id, src_path, proposed_path = db_with_proposed_track
        response = await client.post(
            "/api/organise/approve",
            json={"mode": "auto_approved"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_moved"] == 1
        assert data["failed"] == 0
        assert proposed_path.exists()

    async def test_approve_specific_tracks(self, client, db_with_proposed_track):
        """Approve specific tracks by ID."""
        track_id, src_path, proposed_path = db_with_proposed_track
        response = await client.post(
            "/api/organise/approve",
            json={"mode": "specific", "track_ids": [track_id]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_moved"] == 1

    async def test_approve_invalid_mode(self, client):
        """Invalid mode returns empty result."""
        response = await client.post(
            "/api/organise/approve",
            json={"mode": "invalid"},
        )
        assert response.status_code == 200
        assert response.json()["total_moved"] == 0


class TestResolveTrack:
    """Test POST /api/organise/resolve/{id}."""

    async def test_resolve_accept(self, client, db_with_review_track):
        """Accept a review track."""
        track_id, _, _ = db_with_review_track
        response = await client.post(
            f"/api/organise/resolve/{track_id}",
            json={"action": "accept"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "resolved"
        assert data["organisation_status"] == "proposed"

    async def test_resolve_skip(self, client, db_with_review_track):
        """Skip a review track."""
        track_id, _, _ = db_with_review_track
        response = await client.post(
            f"/api/organise/resolve/{track_id}",
            json={"action": "skip"},
        )
        assert response.status_code == 200
        assert response.json()["organisation_status"] == "unorganised"

    async def test_resolve_custom_path(self, client, db_with_review_track):
        """Set a custom path for a track."""
        track_id, _, _ = db_with_review_track
        response = await client.post(
            f"/api/organise/resolve/{track_id}",
            json={"action": "custom", "custom_path": "/custom/path/track.mp3"},
        )
        assert response.status_code == 200
        assert response.json()["organisation_status"] == "proposed"

    async def test_resolve_nonexistent_track(self, client):
        """Resolve a track that doesn't exist."""
        response = await client.post(
            "/api/organise/resolve/99999",
            json={"action": "accept"},
        )
        assert response.status_code == 404


class TestPreferences:
    """Test preference CRUD endpoints."""

    async def test_list_preferences_empty(self, client):
        """List preferences when none exist."""
        response = await client.get("/api/preferences")
        assert response.status_code == 200
        assert response.json() == []

    async def test_create_preference(self, client):
        """Create a preference rule."""
        response = await client.post(
            "/api/preferences",
            json={
                "rule_type": "artist_folder",
                "key": "Test Artist",
                "value": "TestArtist",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["rule_type"] == "artist_folder"
        assert data["key"] == "test artist"  # key is normalised to lowercase
        assert data["value"] == "TestArtist"
        assert data["id"] is not None

    async def test_list_preferences_filtered(self, client):
        """List preferences filtered by rule_type."""
        # Create two rules of different types
        await client.post(
            "/api/preferences",
            json={"rule_type": "artist_folder", "key": "A", "value": "a"},
        )
        await client.post(
            "/api/preferences",
            json={"rule_type": "va_handling", "key": "B", "value": "b"},
        )

        response = await client.get("/api/preferences?rule_type=artist_folder")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["rule_type"] == "artist_folder"

    async def test_delete_preference(self, client):
        """Delete a preference rule."""
        # Create a rule
        create_resp = await client.post(
            "/api/preferences",
            json={"rule_type": "artist_folder", "key": "Del", "value": "del"},
        )
        rule_id = create_resp.json()["id"]

        # Delete it
        response = await client.delete(f"/api/preferences/{rule_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

        # Verify it's gone
        list_resp = await client.get("/api/preferences")
        assert all(r["id"] != rule_id for r in list_resp.json())


class TestTrackListOrganisationFields:
    """Test that GET /api/tracks includes organisation fields."""

    async def test_tracks_include_organisation_fields(self, client, db_with_proposed_track):
        """Track list response includes organisation metadata."""
        response = await client.get("/api/tracks")
        assert response.status_code == 200
        track = response.json()["tracks"][0]
        assert track["organisation_status"] == "proposed"
        assert track["proposed_path"] is not None
        assert track["organisation_confidence"] == 0.9
