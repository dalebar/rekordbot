"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """rekordbot application settings.

    All settings can be overridden via environment variables
    prefixed with REKORDBOT_ (e.g. REKORDBOT_PORT=8420).
    """

    model_config = SettingsConfigDict(env_file=".env", env_prefix="REKORDBOT_")

    port: int = 8420
    db_url: str = "sqlite:///rekordbot_dev.db"
    log_level: str = "INFO"
    ffmpeg_path: str = "ffmpeg"
    anthropic_api_key: str = ""


settings = Settings()
