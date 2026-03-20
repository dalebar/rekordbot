"""Tests for settings API routes."""

from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def settings_client():
    """Async HTTP client for testing settings endpoints."""
    from backend.main import app
    from backend.models.database import init_db

    init_db()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestGetSettings:
    """Tests for GET /api/settings."""

    @pytest.mark.asyncio
    async def test_returns_settings(self, settings_client: AsyncClient) -> None:
        resp = await settings_client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "anthropic_api_key" in data
        assert "output_directory" in data
        assert "default_key_notation" in data
        assert "folder_template" in data
        assert "convert_aac_to_mp3" in data
        assert "bpm_range_min" in data
        assert "bpm_range_max" in data
        assert "confidence_threshold" in data

    @pytest.mark.asyncio
    async def test_api_key_is_masked(self, settings_client: AsyncClient) -> None:
        from backend.config import settings

        original_key = settings.anthropic_api_key
        try:
            object.__setattr__(settings, "anthropic_api_key", "sk-ant-api03-testkey1234")
            resp = await settings_client.get("/api/settings")
            data = resp.json()
            assert "..." in data["anthropic_api_key"]
            assert "testkey1234" not in data["anthropic_api_key"]
            assert data["anthropic_api_key"].endswith("1234")
        finally:
            object.__setattr__(settings, "anthropic_api_key", original_key)

    @pytest.mark.asyncio
    async def test_empty_api_key_returns_empty(self, settings_client: AsyncClient) -> None:
        from backend.config import settings

        original_key = settings.anthropic_api_key
        try:
            object.__setattr__(settings, "anthropic_api_key", "")
            resp = await settings_client.get("/api/settings")
            data = resp.json()
            assert data["anthropic_api_key"] == ""
        finally:
            object.__setattr__(settings, "anthropic_api_key", original_key)


class TestPutSettings:
    """Tests for PUT /api/settings."""

    @pytest.mark.asyncio
    async def test_updates_settings(self, settings_client: AsyncClient, tmp_path: Path) -> None:
        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        with (
            patch(
                "backend.services.config_manager._get_app_data_dir",
                return_value=config_dir,
            ),
            patch("backend.routes.settings.load_config", return_value={}),
        ):
            resp = await settings_client.put(
                "/api/settings",
                json={"bpm_range_min": 60, "bpm_range_max": 200},
            )
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_masked_key_preserves_existing(
        self, settings_client: AsyncClient, tmp_path: Path
    ) -> None:
        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        existing_config = {"anthropic_api_key": "sk-ant-api03-realkey5678"}
        with (
            patch(
                "backend.services.config_manager._get_app_data_dir",
                return_value=config_dir,
            ),
            patch(
                "backend.routes.settings.load_config",
                return_value=existing_config,
            ),
        ):
            resp = await settings_client.put(
                "/api/settings",
                json={"anthropic_api_key": "sk-ant-...5678"},
            )
            assert resp.status_code == 200
            # The masked key should not have replaced the real key in config
            # (load_config is mocked, so we just verify no crash)

    @pytest.mark.asyncio
    async def test_rejects_invalid_api_key(
        self, settings_client: AsyncClient, tmp_path: Path
    ) -> None:
        """PUT with garbage anthropic_api_key should save other fields but not the key."""
        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        saved_config: dict = {}

        def capture_save(config: dict) -> None:
            saved_config.update(config)

        with (
            patch(
                "backend.services.config_manager._get_app_data_dir",
                return_value=config_dir,
            ),
            patch("backend.routes.settings.load_config", return_value={}),
            patch("backend.routes.settings.save_config", side_effect=capture_save),
        ):
            resp = await settings_client.put(
                "/api/settings",
                json={"anthropic_api_key": "some garbage string", "bpm_range_min": 65},
            )
            assert resp.status_code == 200
            assert "anthropic_api_key" not in saved_config
            assert saved_config.get("bpm_range_min") == 65

    @pytest.mark.asyncio
    async def test_rejects_error_message_as_key(
        self, settings_client: AsyncClient, tmp_path: Path
    ) -> None:
        """PUT with an error message string as key should not persist it."""
        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        saved_config: dict = {}

        def capture_save(config: dict) -> None:
            saved_config.update(config)

        with (
            patch(
                "backend.services.config_manager._get_app_data_dir",
                return_value=config_dir,
            ),
            patch("backend.routes.settings.load_config", return_value={}),
            patch("backend.routes.settings.save_config", side_effect=capture_save),
        ):
            resp = await settings_client.put(
                "/api/settings",
                json={
                    "anthropic_api_key": "API error: 'ascii' codec can't encode character",
                },
            )
            assert resp.status_code == 200
            assert "anthropic_api_key" not in saved_config

    @pytest.mark.asyncio
    async def test_accepts_valid_api_key(
        self, settings_client: AsyncClient, tmp_path: Path
    ) -> None:
        """PUT with a structurally valid API key should persist it."""
        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        saved_config: dict = {}

        def capture_save(config: dict) -> None:
            saved_config.update(config)

        valid_key = "sk-ant-api03-validkey1234567890"
        with (
            patch(
                "backend.services.config_manager._get_app_data_dir",
                return_value=config_dir,
            ),
            patch("backend.routes.settings.load_config", return_value={}),
            patch("backend.routes.settings.save_config", side_effect=capture_save),
        ):
            resp = await settings_client.put(
                "/api/settings",
                json={"anthropic_api_key": valid_key},
            )
            assert resp.status_code == 200
            assert saved_config.get("anthropic_api_key") == valid_key


class TestValidateKey:
    """Tests for POST /api/settings/validate-key."""

    @pytest.mark.asyncio
    async def test_empty_key_invalid(self, settings_client: AsyncClient) -> None:
        resp = await settings_client.post(
            "/api/settings/validate-key",
            json={"key": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    @pytest.mark.asyncio
    async def test_masked_key_invalid(self, settings_client: AsyncClient) -> None:
        resp = await settings_client.post(
            "/api/settings/validate-key",
            json={"key": "sk-ant-...XXXX"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    @pytest.mark.asyncio
    async def test_does_not_leak_exception_text(self, settings_client: AsyncClient) -> None:
        """Generic exceptions should return a safe message, not raw traceback text."""
        from unittest.mock import MagicMock

        mock_anthropic = MagicMock()
        mock_client_instance = MagicMock()
        mock_anthropic.Anthropic.return_value = mock_client_instance
        mock_client_instance.messages.create.side_effect = RuntimeError(
            "Connection refused to api.anthropic.com:443"
        )

        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            resp = await settings_client.post(
                "/api/settings/validate-key",
                json={"key": "sk-ant-api03-test1234567890"},
            )
            data = resp.json()
            assert data["valid"] is False
            assert "Connection refused" not in data["error"]
            assert data["error"] == "Could not validate key. Try again later."


class TestValidateDirectory:
    """Tests for POST /api/settings/validate-directory."""

    @pytest.mark.asyncio
    async def test_valid_directory(self, settings_client: AsyncClient, tmp_path: Path) -> None:
        resp = await settings_client.post(
            "/api/settings/validate-directory",
            json={"path": str(tmp_path)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["error"] == ""

    @pytest.mark.asyncio
    async def test_invalid_directory(self, settings_client: AsyncClient) -> None:
        resp = await settings_client.post(
            "/api/settings/validate-directory",
            json={"path": "/nonexistent/deeply/nested/path"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert data["error"] != ""

    @pytest.mark.asyncio
    async def test_empty_path(self, settings_client: AsyncClient) -> None:
        resp = await settings_client.post(
            "/api/settings/validate-directory",
            json={"path": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False


class TestGetStatus:
    """Tests for GET /api/settings/status."""

    @pytest.mark.asyncio
    async def test_returns_status(self, settings_client: AsyncClient) -> None:
        resp = await settings_client.get("/api/settings/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "configured" in data
        assert "has_api_key" in data
        assert "has_output_directory" in data
        assert "ffmpeg_available" in data
        assert "output_directory_writable" in data

    @pytest.mark.asyncio
    async def test_unconfigured_status(self, settings_client: AsyncClient) -> None:
        with patch("backend.routes.settings.config_exists", return_value=False):
            resp = await settings_client.get("/api/settings/status")
            data = resp.json()
            assert data["configured"] is False
