"""Tests for config manager — JSON persistence and env var integration.

TDD: tests written before implementation.
"""

import json
import os
from pathlib import Path
from unittest.mock import patch


class TestGetConfigPath:
    """Tests for get_config_path()."""

    def test_returns_path_object(self) -> None:
        from backend.services.config_manager import get_config_path

        result = get_config_path()
        assert isinstance(result, Path)

    def test_path_ends_with_rekordbot(self) -> None:
        from backend.services.config_manager import get_config_path

        result = get_config_path()
        assert result.name == "rekordbot"

    def test_returns_application_support_on_macos(self) -> None:
        from backend.services.config_manager import get_config_path

        with patch("sys.platform", "darwin"):
            result = get_config_path()
            assert "Application Support" in str(result) or "rekordbot" in str(result)

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        from backend.services.config_manager import get_config_path

        config_dir = tmp_path / "rekordbot"
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            result = get_config_path()
            assert result.exists()
            assert result.is_dir()


class TestConfigExists:
    """Tests for config_exists()."""

    def test_returns_false_when_no_config(self, tmp_path: Path) -> None:
        from backend.services.config_manager import config_exists

        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            assert config_exists() is False

    def test_returns_true_when_config_exists(self, tmp_path: Path) -> None:
        from backend.services.config_manager import config_exists

        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        (config_dir / "config.json").write_text("{}")
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            assert config_exists() is True


class TestLoadConfig:
    """Tests for load_config()."""

    def test_returns_empty_dict_when_no_file(self, tmp_path: Path) -> None:
        from backend.services.config_manager import load_config

        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            result = load_config()
            assert result == {}

    def test_returns_parsed_json(self, tmp_path: Path) -> None:
        from backend.services.config_manager import load_config

        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        config_data = {"anthropic_api_key": "sk-test", "output_directory": "/tmp/music"}
        (config_dir / "config.json").write_text(json.dumps(config_data))
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            result = load_config()
            assert result == config_data

    def test_returns_empty_dict_on_invalid_json(self, tmp_path: Path) -> None:
        from backend.services.config_manager import load_config

        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        (config_dir / "config.json").write_text("not valid json{{{")
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            result = load_config()
            assert result == {}

    def test_preserves_all_config_fields(self, tmp_path: Path) -> None:
        from backend.services.config_manager import load_config

        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        config_data = {
            "anthropic_api_key": "sk-ant-key123",
            "output_directory": "/Users/test/Music",
            "default_key_notation": "open_key",
            "folder_template": "{genre}/{artist}/{title}",
            "convert_aac_to_mp3": True,
            "bpm_range_min": 60,
            "bpm_range_max": 200,
            "confidence_threshold": 0.8,
            "set_track_duration_minutes": 5,
            "set_max_tracks": 30,
        }
        (config_dir / "config.json").write_text(json.dumps(config_data))
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            result = load_config()
            assert result == config_data


class TestSaveConfig:
    """Tests for save_config()."""

    def test_writes_json_file(self, tmp_path: Path) -> None:
        from backend.services.config_manager import save_config

        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        config_data = {"output_directory": "/tmp/music"}
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            save_config(config_data)
            written = json.loads((config_dir / "config.json").read_text())
            assert written == config_data

    def test_creates_directory_if_missing(self, tmp_path: Path) -> None:
        from backend.services.config_manager import save_config

        config_dir = tmp_path / "rekordbot"
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            save_config({"output_directory": "/tmp"})
            assert config_dir.exists()
            assert (config_dir / "config.json").exists()

    def test_overwrites_existing_config(self, tmp_path: Path) -> None:
        from backend.services.config_manager import save_config

        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        (config_dir / "config.json").write_text(json.dumps({"output_directory": "/old/path"}))
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            save_config({"output_directory": "/new/path"})
            written = json.loads((config_dir / "config.json").read_text())
            assert written == {"output_directory": "/new/path"}

    def test_writes_pretty_json(self, tmp_path: Path) -> None:
        from backend.services.config_manager import save_config

        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            save_config({"key": "value"})
            content = (config_dir / "config.json").read_text()
            # Pretty-printed JSON has newlines
            assert "\n" in content


class TestApplyConfigToEnv:
    """Tests for apply_config_to_env()."""

    def test_sets_env_vars_with_prefix(self) -> None:
        from backend.services.config_manager import apply_config_to_env

        config = {"output_directory": "/tmp/music", "bpm_range_min": 60}
        with patch.dict(os.environ, {}, clear=False):
            apply_config_to_env(config)
            assert os.environ.get("REKORDBOT_OUTPUT_DIRECTORY") == "/tmp/music"
            assert os.environ.get("REKORDBOT_BPM_RANGE_MIN") == "60"

    def test_converts_bool_to_string(self) -> None:
        from backend.services.config_manager import apply_config_to_env

        config = {"convert_aac_to_mp3": True}
        with patch.dict(os.environ, {}, clear=False):
            apply_config_to_env(config)
            assert os.environ.get("REKORDBOT_CONVERT_AAC_TO_MP3") == "True"

    def test_converts_float_to_string(self) -> None:
        from backend.services.config_manager import apply_config_to_env

        config = {"confidence_threshold": 0.8}
        with patch.dict(os.environ, {}, clear=False):
            apply_config_to_env(config)
            assert os.environ.get("REKORDBOT_CONFIDENCE_THRESHOLD") == "0.8"

    def test_does_not_override_existing_env_vars(self) -> None:
        from backend.services.config_manager import apply_config_to_env

        config = {"output_directory": "/from/config"}
        with patch.dict(os.environ, {"REKORDBOT_OUTPUT_DIRECTORY": "/from/env"}, clear=False):
            apply_config_to_env(config)
            # Env var should NOT be overridden — env vars take precedence
            assert os.environ.get("REKORDBOT_OUTPUT_DIRECTORY") == "/from/env"

    def test_empty_config_is_no_op(self) -> None:
        from backend.services.config_manager import apply_config_to_env

        # Should not raise
        apply_config_to_env({})

    def test_only_sets_known_config_fields(self) -> None:
        from backend.services.config_manager import apply_config_to_env

        config = {"unknown_setting": "value", "output_directory": "/tmp"}
        with patch.dict(os.environ, {}, clear=False):
            apply_config_to_env(config)
            assert "REKORDBOT_UNKNOWN_SETTING" not in os.environ
            assert os.environ.get("REKORDBOT_OUTPUT_DIRECTORY") == "/tmp"


class TestValidateOutputDirectory:
    """Tests for validate_output_directory()."""

    def test_valid_existing_directory(self, tmp_path: Path) -> None:
        from backend.services.config_manager import validate_output_directory

        valid, message = validate_output_directory(str(tmp_path))
        assert valid is True
        assert message == ""

    def test_nonexistent_but_parent_exists(self, tmp_path: Path) -> None:
        from backend.services.config_manager import validate_output_directory

        new_dir = tmp_path / "new_dir"
        valid, message = validate_output_directory(str(new_dir))
        assert valid is True

    def test_nonexistent_parent_also_missing(self) -> None:
        from backend.services.config_manager import validate_output_directory

        valid, message = validate_output_directory("/nonexistent/deeply/nested/path")
        assert valid is False
        assert "parent directory" in message.lower() or "does not exist" in message.lower()

    def test_empty_path(self) -> None:
        from backend.services.config_manager import validate_output_directory

        valid, message = validate_output_directory("")
        assert valid is False

    def test_expands_tilde(self, tmp_path: Path) -> None:
        from backend.services.config_manager import validate_output_directory

        # This should at least not crash — ~ expands to home dir
        valid, _ = validate_output_directory("~/rekordbot_test_output")
        # Result depends on whether home dir exists (always true)
        assert isinstance(valid, bool)


class TestGetDbPath:
    """Tests for get_db_path()."""

    def test_returns_db_path_in_config_dir(self, tmp_path: Path) -> None:
        from backend.services.config_manager import get_db_path

        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            result = get_db_path()
            assert result == f"sqlite:///{config_dir}/rekordbot.db"

    def test_db_path_uses_absolute_path(self, tmp_path: Path) -> None:
        from backend.services.config_manager import get_db_path

        config_dir = tmp_path / "rekordbot"
        config_dir.mkdir()
        with patch("backend.services.config_manager._get_app_data_dir", return_value=config_dir):
            result = get_db_path()
            assert ":///" in result


class TestMaskApiKey:
    """Tests for mask_api_key()."""

    def test_masks_full_key(self) -> None:
        from backend.services.config_manager import mask_api_key

        result = mask_api_key("sk-ant-api03-abcdefghijklmnop")
        assert result == "sk-ant-...mnop"

    def test_short_key(self) -> None:
        from backend.services.config_manager import mask_api_key

        result = mask_api_key("abc")
        assert result == "***"

    def test_empty_key(self) -> None:
        from backend.services.config_manager import mask_api_key

        result = mask_api_key("")
        assert result == ""

    def test_key_exactly_8_chars(self) -> None:
        from backend.services.config_manager import mask_api_key

        result = mask_api_key("sk-a1234")
        assert result == "sk-a...1234"


class TestIsKeyMasked:
    """Tests for is_key_masked()."""

    def test_masked_key_detected(self) -> None:
        from backend.services.config_manager import is_key_masked

        assert is_key_masked("sk-ant-...XXXX") is True

    def test_full_key_not_masked(self) -> None:
        from backend.services.config_manager import is_key_masked

        assert is_key_masked("sk-ant-api03-abcdefghijklmnop") is False

    def test_empty_string(self) -> None:
        from backend.services.config_manager import is_key_masked

        assert is_key_masked("") is False
