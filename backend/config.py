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
    ffprobe_path: str = "ffprobe"
    output_directory: str = "~/rekordbot/library"
    max_concurrent_conversions: int = 2
    convert_aac_to_mp3: bool = False
    anthropic_api_key: str = ""

    # Phase 3: AI tagging settings
    ai_model: str = "claude-sonnet-4-20250514"
    ai_batch_size: int = 20
    ai_max_requests_per_minute: int = 10

    # Phase 2b: Organisation settings
    folder_template: str = "{artist}/{album}/{title}"
    organise_confidence_threshold: float = 0.7
    organise_unknown_fallback: str = "Unsorted"

    # Phase 2: Analysis settings
    bpm_range_min: int = 70
    bpm_range_max: int = 180
    confidence_threshold: float = 0.6
    max_concurrent_analyses: int = 1
    default_key_notation: str = "camelot"


settings = Settings()
