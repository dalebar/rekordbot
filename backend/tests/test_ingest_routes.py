"""Tests for ingestion API routes."""


class TestIngestEndpoint:
    """Tests for POST /api/ingest."""

    async def test_ingest_no_files(self, client) -> None:
        """Empty paths returns no files message."""
        response = await client.post("/api/ingest", json={"paths": []})
        assert response.status_code == 200
        data = response.json()
        assert data["total_files"] == 0
        assert "No supported audio files" in data["message"]

    async def test_ingest_nonexistent_path(self, client) -> None:
        """Non-existent path is filtered out."""
        response = await client.post("/api/ingest", json={"paths": ["/nonexistent/path/song.wav"]})
        assert response.status_code == 200
        data = response.json()
        assert data["total_files"] == 0

    async def test_ingest_unsupported_extension(self, client, tmp_path) -> None:
        """Unsupported file extension is filtered out."""
        ogg_file = tmp_path / "song.ogg"
        ogg_file.touch()
        response = await client.post("/api/ingest", json={"paths": [str(ogg_file)]})
        assert response.status_code == 200
        data = response.json()
        assert data["total_files"] == 0

    async def test_ingest_valid_file_starts_batch(self, client, tmp_path) -> None:
        """Valid audio file starts a batch."""
        wav_file = tmp_path / "song.wav"
        wav_file.write_bytes(b"\x00" * 100)  # Dummy content
        response = await client.post("/api/ingest", json={"paths": [str(wav_file)]})
        assert response.status_code == 200
        data = response.json()
        assert data["total_files"] == 1
        assert data["batch_id"] != ""
        assert data["message"] == "Processing started"

    async def test_ingest_expands_directory(self, client, tmp_path) -> None:
        """Directory is expanded recursively for supported files."""
        sub_dir = tmp_path / "music"
        sub_dir.mkdir()
        (sub_dir / "a.wav").write_bytes(b"\x00" * 100)
        (sub_dir / "b.flac").write_bytes(b"\x00" * 100)
        (sub_dir / "c.txt").write_bytes(b"not audio")

        response = await client.post("/api/ingest", json={"paths": [str(sub_dir)]})
        data = response.json()
        assert data["total_files"] == 2


class TestCancelEndpoint:
    """Tests for POST /api/ingest/cancel."""

    async def test_cancel_no_active_batch(self, client) -> None:
        response = await client.post("/api/ingest/cancel")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "no_active_batch"


class TestTracksEndpoint:
    """Tests for GET /api/tracks."""

    async def test_list_tracks_empty(self, client) -> None:
        response = await client.get("/api/tracks")
        assert response.status_code == 200
        data = response.json()
        assert data["tracks"] == []
        assert data["total"] == 0

    async def test_list_tracks_pagination(self, client) -> None:
        response = await client.get("/api/tracks?limit=10&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 10
        assert data["offset"] == 0
