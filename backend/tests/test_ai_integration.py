"""Integration tests for AI tagging pipeline — end-to-end with mocked Claude API."""

from unittest.mock import MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.models.database import SessionLocal, init_db
from backend.models.track import Track


@pytest_asyncio.fixture
async def client():
    """Async HTTP client with a fresh database."""
    from backend.main import app

    init_db()

    db = SessionLocal()
    db.query(Track).delete()
    db.commit()
    db.close()

    import backend.routes.ai_tagging as ai_tagging_module
    import backend.routes.ingest as ingest_module
    import backend.routes.tagging as tagging_module

    ingest_module._queue = None
    tagging_module._analysis_queue = None
    ai_tagging_module._ai_tagger = None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _create_track(
    file_path: str,
    title: str,
    artist: str,
    genre: str | None = None,
    ai_status: str = "untagged",
) -> int:
    """Insert a track and return its ID."""
    db = SessionLocal()
    track = Track(
        file_path=file_path,
        title=title,
        artist=artist,
        genre=genre,
        ai_status=ai_status,
    )
    db.add(track)
    db.commit()
    track_id = track.id
    db.close()
    return track_id


class TestAiTagIntegration:
    """End-to-end AI tagging flow with mocked Claude API."""

    async def test_ai_tag_and_verify_db(self, client):
        """AI tag tracks and verify results are saved to database."""
        track_id = _create_track(
            "/music/integration-1.aiff",
            "Integration Test",
            "Test Artist",
            genre="Electronic",
        )

        with (
            patch("backend.routes.ai_tagging.settings") as mock_settings,
            patch("backend.routes.ai_tagging.AiTagger") as mock_tagger_cls,
            patch("backend.routes.ai_tagging.asyncio") as mock_asyncio,
        ):
            mock_settings.anthropic_api_key = "sk-test"
            mock_settings.ai_model = "claude-sonnet-4-20250514"
            mock_settings.ai_batch_size = 20
            mock_settings.model_copy.return_value = mock_settings

            mock_tagger = MagicMock()
            mock_tagger.is_processing = False
            mock_tagger_cls.return_value = mock_tagger
            mock_asyncio.create_task = MagicMock()

            response = await client.post("/api/tracks/ai-tag", json={})
            assert response.status_code == 200
            data = response.json()
            assert data["total_tracks"] == 1

        # Simulate what the pipeline would have done — update track in DB
        db = SessionLocal()
        track = db.query(Track).filter(Track.id == track_id).first()
        assert track is not None
        track.genre = "Melodic Techno"
        track.subgenre = "Progressive Techno"
        track.mood = "Hypnotic"
        track.energy = 7
        track.ai_confidence = "high"
        track.ai_reasoning = "Known artist and label in melodic techno."
        track.source_genre = "Electronic"
        track.ai_status = "ai_tagged"
        db.commit()
        db.close()

        # Verify via API
        response = await client.get("/api/tracks")
        assert response.status_code == 200
        tracks = response.json()["tracks"]
        assert len(tracks) == 1
        t = tracks[0]
        assert t["genre"] == "Melodic Techno"
        assert t["subgenre"] == "Progressive Techno"
        assert t["mood"] == "Hypnotic"
        assert t["energy"] == 7
        assert t["ai_confidence"] == "high"
        assert t["source_genre"] == "Electronic"
        assert t["ai_status"] == "ai_tagged"


class TestGenreRevertFlow:
    """Genre revert integration tests."""

    async def test_revert_genre_after_ai_tag(self, client):
        """Genre reverts to source_genre after AI tagging."""
        db = SessionLocal()
        track = Track(
            file_path="/music/revert-flow.aiff",
            title="Revert Flow",
            artist="Artist",
            genre="Melodic House",
            source_genre="Electronic",
            ai_status="ai_tagged",
        )
        db.add(track)
        db.commit()
        track_id = track.id
        db.close()

        response = await client.put(f"/api/tracks/{track_id}/revert/genre")
        assert response.status_code == 200
        data = response.json()
        assert data["genre"] == "Electronic"

        # Verify persisted
        response = await client.get("/api/tracks")
        tracks = response.json()["tracks"]
        assert tracks[0]["genre"] == "Electronic"

    async def test_revert_genre_preserves_other_ai_fields(self, client):
        """Reverting genre does not affect other AI fields."""
        db = SessionLocal()
        track = Track(
            file_path="/music/revert-preserve.aiff",
            title="Preserve Fields",
            artist="Artist",
            genre="Melodic House",
            source_genre="Dance",
            subgenre="Deep House",
            mood="Warm",
            energy=6,
            ai_confidence="medium",
            ai_reasoning="Based on tempo and style.",
            ai_status="ai_tagged",
        )
        db.add(track)
        db.commit()
        track_id = track.id
        db.close()

        response = await client.put(f"/api/tracks/{track_id}/revert/genre")
        assert response.status_code == 200
        data = response.json()
        assert data["genre"] == "Dance"
        assert data["subgenre"] == "Deep House"
        assert data["mood"] == "Warm"
        assert data["energy"] == 6
        assert data["ai_confidence"] == "medium"


class TestRetagFlow:
    """Re-tagging tests."""

    async def test_retag_already_tagged(self, client):
        """Can submit already-tagged tracks for re-tagging."""
        track_id = _create_track(
            "/music/retag.aiff",
            "Retag Test",
            "Artist",
            genre="Old Genre",
            ai_status="ai_tagged",
        )

        with (
            patch("backend.routes.ai_tagging.settings") as mock_settings,
            patch("backend.routes.ai_tagging.AiTagger") as mock_tagger_cls,
            patch("backend.routes.ai_tagging.asyncio") as mock_asyncio,
        ):
            mock_settings.anthropic_api_key = "sk-test"
            mock_settings.ai_model = "claude-sonnet-4-20250514"
            mock_settings.ai_batch_size = 20
            mock_settings.model_copy.return_value = mock_settings

            mock_tagger = MagicMock()
            mock_tagger.is_processing = False
            mock_tagger_cls.return_value = mock_tagger
            mock_asyncio.create_task = MagicMock()

            # Explicit track_ids bypasses the "untagged" default filter
            response = await client.post(
                "/api/tracks/ai-tag",
                json={"track_ids": [track_id], "options": {"skip_if_tagged": False}},
            )
            assert response.status_code == 200
            assert response.json()["total_tracks"] == 1


class TestMissingApiKey:
    """Missing API key error handling."""

    async def test_ai_tag_without_key(self, client):
        """Returns 400 when no API key is configured."""
        _create_track("/music/no-key.aiff", "No Key", "Artist")

        with patch("backend.routes.ai_tagging.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            response = await client.post("/api/tracks/ai-tag", json={})
            assert response.status_code == 400
            data = response.json()
            assert data["error"] == "ai_tag_failed"
            assert "API key" in data["detail"]

    async def test_validate_key_without_key(self, client):
        """Validate key returns valid=false when no key configured."""
        with patch("backend.routes.ai_tagging.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            response = await client.post("/api/tracks/ai-tag/validate-key")
            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is False


class TestWriteTagsAiStatus:
    """Write tags updates ai_status for AI-tagged tracks."""

    async def test_write_tags_updates_ai_status(self, client):
        """Writing tags transitions ai_status from ai_tagged to ai_tags_written."""
        db = SessionLocal()
        track = Track(
            file_path="/music/write-ai-status.aiff",
            title="Write Status",
            artist="Artist",
            genre="Techno",
            ai_status="ai_tagged",
        )
        db.add(track)
        db.commit()
        track_id = track.id
        db.close()

        with patch("backend.routes.tagging.write_tags_batch") as mock_write:
            mock_result = MagicMock()
            mock_result.success = True
            mock_write.return_value = [mock_result]

            response = await client.post(
                "/api/tracks/write-tags",
                json={"track_ids": [track_id]},
            )
            assert response.status_code == 200
            assert response.json()["succeeded"] == 1

        # Verify status updated
        response = await client.get("/api/tracks")
        tracks = response.json()["tracks"]
        assert tracks[0]["ai_status"] == "ai_tags_written"
