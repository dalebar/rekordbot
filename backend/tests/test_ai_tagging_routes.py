"""Tests for AI tagging API routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.models.database import SessionLocal, init_db
from backend.models.track import Track


@pytest_asyncio.fixture
async def client():
    """Async HTTP client with a fresh database."""
    from backend.main import app

    init_db()

    # Clean tracks table for test isolation
    db = SessionLocal()
    db.query(Track).delete()
    db.commit()
    db.close()

    # Reset module-level state
    import backend.routes.ai_tagging as ai_tagging_module
    import backend.routes.ingest as ingest_module
    import backend.routes.tagging as tagging_module

    ingest_module._queue = None
    tagging_module._analysis_queue = None
    ai_tagging_module._ai_tagger = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAiTagEndpoint:
    """Tests for POST /api/tracks/ai-tag."""

    async def test_no_api_key(self, client):
        """Returns 400 when API key is not configured."""
        with patch("backend.routes.ai_tagging.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            response = await client.post("/api/tracks/ai-tag", json={})
            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "ai_tag_failed"

    async def test_no_tracks_to_tag(self, client):
        """Returns message when no tracks match."""
        with patch("backend.routes.ai_tagging.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-test"
            response = await client.post("/api/tracks/ai-tag", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["total_tracks"] == 0
            assert "No tracks" in data["message"]

    async def test_start_tagging(self, client):
        """Starts AI tagging for untagged tracks."""
        db = SessionLocal()
        track = Track(
            file_path="/music/ai-route-test.aiff",
            title="Route Test",
            artist="Artist",
        )
        db.add(track)
        db.commit()
        db.close()

        with (
            patch("backend.routes.ai_tagging.settings") as mock_settings,
            patch("backend.routes.ai_tagging.AiTagger") as mock_tagger_cls,
            patch("backend.routes.ai_tagging.asyncio") as mock_asyncio,
        ):
            mock_settings.anthropic_api_key = "sk-test"
            mock_settings.ai_model = "claude-sonnet-4-20250514"
            mock_settings.ai_batch_size = 20
            mock_settings.ai_max_requests_per_minute = 10
            mock_settings.model_copy.return_value = mock_settings

            mock_tagger = MagicMock()
            mock_tagger.is_processing = False
            mock_tagger_cls.return_value = mock_tagger

            mock_asyncio.create_task = MagicMock()

            response = await client.post("/api/tracks/ai-tag", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["total_tracks"] == 1
            assert "started" in data["message"].lower()


class TestAiTagCancel:
    """Tests for POST /api/tracks/ai-tag/cancel."""

    async def test_no_active_batch(self, client):
        """Returns message when no batch is running."""
        response = await client.post("/api/tracks/ai-tag/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "no_active_batch"


class TestAiTagStatus:
    """Tests for GET /api/tracks/ai-tag/status."""

    async def test_idle_status(self, client):
        """Returns idle when no pipeline is running."""
        response = await client.get("/api/tracks/ai-tag/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "idle"


class TestValidateKey:
    """Tests for POST /api/tracks/ai-tag/validate-key."""

    async def test_no_key_configured(self, client):
        """Returns valid=false when no key is configured."""
        with patch("backend.routes.ai_tagging.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            response = await client.post("/api/tracks/ai-tag/validate-key")
            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is False
            assert "No API key" in data["error"]

    async def test_valid_key(self, client):
        """Returns valid=true for a valid key."""
        with (
            patch("backend.routes.ai_tagging.settings") as mock_settings,
            patch("backend.routes.ai_tagging.ClaudeClient") as mock_cls,
        ):
            mock_settings.anthropic_api_key = "sk-valid"
            mock_settings.ai_model = "claude-sonnet-4-20250514"
            mock_client = MagicMock()
            mock_client.validate_api_key = AsyncMock(return_value=True)
            mock_cls.return_value = mock_client

            response = await client.post("/api/tracks/ai-tag/validate-key")
            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is True
            assert data["model"] == "claude-sonnet-4-20250514"


class TestGenreRevert:
    """Tests for PUT /api/tracks/{id}/revert/genre."""

    async def test_revert_genre(self, client):
        """Genre reverts to source_genre."""
        db = SessionLocal()
        track = Track(
            file_path="/music/revert-genre.aiff",
            title="Revert Test",
            genre="AI Genre",
            source_genre="Original Genre",
        )
        db.add(track)
        db.commit()
        track_id = track.id
        db.close()

        response = await client.put(f"/api/tracks/{track_id}/revert/genre")
        assert response.status_code == 200
        data = response.json()
        assert data["genre"] == "Original Genre"

    async def test_revert_genre_no_source(self, client):
        """Returns 404 when no source genre to revert to."""
        db = SessionLocal()
        track = Track(
            file_path="/music/revert-no-source.aiff",
            title="No Source",
            genre="Some Genre",
        )
        db.add(track)
        db.commit()
        track_id = track.id
        db.close()

        response = await client.put(f"/api/tracks/{track_id}/revert/genre")
        assert response.status_code == 404


class TestTrackUpdateExtended:
    """Tests for PUT /api/tracks/{id} with new AI fields."""

    async def test_update_subgenre_mood_energy(self, client):
        """Can update subgenre, mood, and energy."""
        db = SessionLocal()
        track = Track(
            file_path="/music/update-ai.aiff",
            title="Update Test",
        )
        db.add(track)
        db.commit()
        track_id = track.id
        db.close()

        response = await client.put(
            f"/api/tracks/{track_id}",
            json={
                "subgenre": "Liquid DnB",
                "mood": "Euphoric",
                "energy": 7,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["subgenre"] == "Liquid DnB"
        assert data["mood"] == "Euphoric"
        assert data["energy"] == 7


class TestTracksListAiFields:
    """Tests for GET /api/tracks including AI fields."""

    async def test_ai_fields_in_response(self, client):
        """Track list includes AI tagging fields."""
        db = SessionLocal()
        track = Track(
            file_path="/music/ai-list.aiff",
            title="AI List Test",
            genre="Melodic Techno",
            subgenre="Progressive Techno",
            mood="Hypnotic",
            energy=8,
            ai_confidence="high",
            ai_reasoning="Recognised artist and label.",
            source_genre="Electronic",
            ai_status="ai_tagged",
        )
        db.add(track)
        db.commit()
        db.close()

        response = await client.get("/api/tracks")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tracks"]) == 1
        t = data["tracks"][0]
        assert t["subgenre"] == "Progressive Techno"
        assert t["mood"] == "Hypnotic"
        assert t["energy"] == 8
        assert t["ai_confidence"] == "high"
        assert t["ai_reasoning"] == "Recognised artist and label."
        assert t["source_genre"] == "Electronic"
        assert t["ai_status"] == "ai_tagged"
