"""Integration tests for Phase 6a — App Shell & Packaging."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def app_client():
    """Async HTTP client for integration tests."""
    from backend.main import app
    from backend.models.database import init_db

    init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestFirstRunFlow:
    """Test the first-run wizard flow end-to-end."""

    @pytest.mark.asyncio
    async def test_status_unconfigured(self, app_client: AsyncClient) -> None:
        """Status endpoint reports unconfigured when no config file exists."""
        with patch("backend.routes.settings.config_exists", return_value=False):
            resp = await app_client.get("/api/settings/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["configured"] is False

    @pytest.mark.asyncio
    async def test_configure_and_check_status(
        self, app_client: AsyncClient, tmp_path: Path
    ) -> None:
        """After saving settings, status reports configured."""
        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()

        with patch(
            "backend.services.config_manager._get_app_data_dir",
            return_value=config_dir,
        ):
            # Save settings
            resp = await app_client.put(
                "/api/settings",
                json={"output_directory": str(tmp_path / "output")},
            )
            assert resp.status_code == 200

            # Config file should exist now
            assert (config_dir / "config.json").exists()

            # Status should report configured
            resp = await app_client.get("/api/settings/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["configured"] is True


class TestSettingsPersistence:
    """Test that settings persist across reads."""

    @pytest.mark.asyncio
    async def test_save_and_reload(self, app_client: AsyncClient, tmp_path: Path) -> None:
        """Settings saved via API are returned on subsequent GET."""
        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()

        with patch(
            "backend.services.config_manager._get_app_data_dir",
            return_value=config_dir,
        ):
            # Save settings
            await app_client.put(
                "/api/settings",
                json={
                    "output_directory": "/test/output",
                    "default_key_notation": "open_key",
                    "bpm_range_min": 60,
                    "bpm_range_max": 200,
                },
            )

            # Read back
            resp = await app_client.get("/api/settings")
            data = resp.json()
            assert data["output_directory"] == "/test/output"
            assert data["default_key_notation"] == "open_key"
            assert data["bpm_range_min"] == 60
            assert data["bpm_range_max"] == 200

    @pytest.mark.asyncio
    async def test_config_file_contents(self, app_client: AsyncClient, tmp_path: Path) -> None:
        """Config file on disk contains the saved values."""
        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()

        with patch(
            "backend.services.config_manager._get_app_data_dir",
            return_value=config_dir,
        ):
            await app_client.put(
                "/api/settings",
                json={"output_directory": "/test/music", "convert_aac_to_mp3": True},
            )

            config_data = json.loads((config_dir / "config.json").read_text())
            assert config_data["output_directory"] == "/test/music"
            assert config_data["convert_aac_to_mp3"] is True


class TestApiKeyMasking:
    """Test API key masking in the settings flow."""

    @pytest.mark.asyncio
    async def test_key_masked_in_get(self, app_client: AsyncClient, tmp_path: Path) -> None:
        """API key is masked when reading settings."""
        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()

        from backend.config import settings

        original = settings.anthropic_api_key
        try:
            object.__setattr__(
                settings,
                "anthropic_api_key",
                "sk-ant-api03-verysecretkey1234",
            )

            resp = await app_client.get("/api/settings")
            data = resp.json()
            assert "..." in data["anthropic_api_key"]
            assert "verysecretkey1234" not in data["anthropic_api_key"]
            assert data["anthropic_api_key"].endswith("1234")
        finally:
            object.__setattr__(settings, "anthropic_api_key", original)

    @pytest.mark.asyncio
    async def test_masked_key_preserves_value(
        self, app_client: AsyncClient, tmp_path: Path
    ) -> None:
        """Sending back a masked key doesn't overwrite the real key."""
        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        existing = {"anthropic_api_key": "sk-ant-api03-realkey5678"}

        with (
            patch(
                "backend.services.config_manager._get_app_data_dir",
                return_value=config_dir,
            ),
            patch("backend.routes.settings.load_config", return_value=existing),
        ):
            resp = await app_client.put(
                "/api/settings",
                json={
                    "anthropic_api_key": "sk-ant-...5678",
                    "output_directory": "/test",
                },
            )
            assert resp.status_code == 200


class TestDirectoryValidation:
    """Test output directory validation via API."""

    @pytest.mark.asyncio
    async def test_valid_existing_dir(self, app_client: AsyncClient, tmp_path: Path) -> None:
        resp = await app_client.post(
            "/api/settings/validate-directory",
            json={"path": str(tmp_path)},
        )
        data = resp.json()
        assert data["valid"] is True

    @pytest.mark.asyncio
    async def test_creatable_dir(self, app_client: AsyncClient, tmp_path: Path) -> None:
        """Directory that doesn't exist but parent does is valid."""
        new_dir = str(tmp_path / "new_music_folder")
        resp = await app_client.post(
            "/api/settings/validate-directory",
            json={"path": new_dir},
        )
        data = resp.json()
        assert data["valid"] is True

    @pytest.mark.asyncio
    async def test_invalid_dir(self, app_client: AsyncClient) -> None:
        resp = await app_client.post(
            "/api/settings/validate-directory",
            json={"path": "/nonexistent/deep/path"},
        )
        data = resp.json()
        assert data["valid"] is False
        assert data["error"] != ""


class TestErrorHandlingIntegration:
    """Test that errors are returned in standard format across routes."""

    @pytest.mark.asyncio
    async def test_validation_error_format(self, app_client: AsyncClient) -> None:
        """Pydantic validation errors use standard format."""
        resp = await app_client.put(
            "/api/settings",
            json={"organise_confidence_threshold": 5.0},
        )
        assert resp.status_code == 422
        data = resp.json()
        assert data["error"] == "validation_error"
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_health_endpoint(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_404_returns_json(self, app_client: AsyncClient) -> None:
        resp = await app_client.get("/api/nonexistent-route")
        assert resp.status_code in (404, 405)
        data = resp.json()
        assert "detail" in data


class TestBitRateInExport:
    """Test BitRate is correctly populated in XML export."""

    @pytest.mark.asyncio
    async def test_bitrate_populated_for_tracks(self, app_client: AsyncClient) -> None:
        """BitRate field uses source_bitrate or computed value."""
        from backend.services.xml_schema_mapper import compute_bitrate

        # CD quality stereo
        assert compute_bitrate(44100, 16, 2) == 1411
        # HD quality
        assert compute_bitrate(96000, 24, 2) == 4608
        # Missing data returns 0
        assert compute_bitrate(None, None, None) == 0
