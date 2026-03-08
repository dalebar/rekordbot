"""Tests for the configuration system."""

import os

from backend.config import Settings


def test_default_settings(monkeypatch):
    """Settings loads with correct defaults when no env vars are set."""
    # Clear any env vars set by config_manager or .env file at import time
    for key in list(k for k in os.environ if k.startswith("REKORDBOT_")):
        monkeypatch.delenv(key, raising=False)
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.port == 8420
    assert s.db_url == "sqlite:///rekordbot_dev.db"
    assert s.log_level == "INFO"
    assert s.ffmpeg_path == "ffmpeg"
    assert s.anthropic_api_key == ""


def test_settings_respects_env_vars(monkeypatch):
    """Settings reads from REKORDBOT_-prefixed env vars."""
    monkeypatch.setenv("REKORDBOT_PORT", "9999")
    monkeypatch.setenv("REKORDBOT_LOG_LEVEL", "DEBUG")
    s = Settings()
    assert s.port == 9999
    assert s.log_level == "DEBUG"
