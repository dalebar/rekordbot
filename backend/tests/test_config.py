"""Tests for the configuration system."""

from backend.config import Settings


def test_default_settings():
    """Settings loads with correct defaults when no env vars are set."""
    s = Settings()
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
