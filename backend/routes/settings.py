"""Settings API routes — configuration management and first-run status."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.config import Settings, settings
from backend.services.config_manager import (
    CONFIGURABLE_FIELDS,
    config_exists,
    is_key_masked,
    load_config,
    mask_api_key,
    save_config,
    validate_output_directory,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsResponse(BaseModel):
    """Current settings with API key masked."""

    anthropic_api_key: str = ""
    output_directory: str = ""
    default_key_notation: str = "camelot"
    folder_template: str = "{artist}/{album}/{title}"
    convert_aac_to_mp3: bool = False
    bpm_range_min: int = 70
    bpm_range_max: int = 180
    confidence_threshold: float = 0.6
    set_track_duration_minutes: int = 7
    set_max_tracks: int = 50


class SettingsUpdate(BaseModel):
    """Settings update request — all fields optional."""

    anthropic_api_key: str | None = None
    output_directory: str | None = None
    default_key_notation: str | None = None
    folder_template: str | None = None
    convert_aac_to_mp3: bool | None = None
    bpm_range_min: int | None = None
    bpm_range_max: int | None = None
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    set_track_duration_minutes: int | None = Field(default=None, ge=1)
    set_max_tracks: int | None = Field(default=None, ge=1)


class SettingsStatus(BaseModel):
    """First-run status and health check results."""

    configured: bool
    has_api_key: bool
    has_output_directory: bool
    ffmpeg_available: bool = True
    output_directory_writable: bool = True


class ValidateKeyRequest(BaseModel):
    """Request body for API key validation."""

    key: str


class ValidateKeyResponse(BaseModel):
    """API key validation result."""

    valid: bool
    error: str = ""


class ValidateDirectoryRequest(BaseModel):
    """Request body for directory validation."""

    path: str


class ValidateDirectoryResponse(BaseModel):
    """Directory validation result."""

    valid: bool
    error: str = ""


@router.get("")
async def get_settings() -> SettingsResponse:
    """Get current settings with API key masked."""
    return SettingsResponse(
        anthropic_api_key=mask_api_key(settings.anthropic_api_key),
        output_directory=settings.output_directory,
        default_key_notation=settings.default_key_notation,
        folder_template=settings.folder_template,
        convert_aac_to_mp3=settings.convert_aac_to_mp3,
        bpm_range_min=settings.bpm_range_min,
        bpm_range_max=settings.bpm_range_max,
        confidence_threshold=settings.confidence_threshold,
        set_track_duration_minutes=settings.set_track_duration_minutes,
        set_max_tracks=settings.set_max_tracks,
    )


@router.put("")
async def update_settings(update: SettingsUpdate) -> SettingsResponse:
    """Update settings, write to JSON config, and update in-memory Settings."""
    # Build the new config from current + updates
    current_config = load_config()

    update_data = update.model_dump(exclude_none=True)

    # Handle masked API key: if user didn't change it, keep existing
    if "anthropic_api_key" in update_data and is_key_masked(update_data["anthropic_api_key"]):
        update_data.pop("anthropic_api_key")

    # Merge updates into current config
    for key, value in update_data.items():
        if key in CONFIGURABLE_FIELDS:
            current_config[key] = value

    # Save to disk
    save_config(current_config)

    # Update the in-memory settings singleton
    _apply_to_settings(current_config)

    logger.info("Settings updated and saved")
    return await get_settings()


@router.post("/validate-key")
async def validate_key(body: ValidateKeyRequest) -> ValidateKeyResponse:
    """Test whether an API key is valid by making a test API call."""
    if not body.key or is_key_masked(body.key):
        return ValidateKeyResponse(valid=False, error="No API key provided.")

    try:
        import anthropic  # type: ignore[import-not-found]

        client = anthropic.Anthropic(api_key=body.key)
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
        return ValidateKeyResponse(valid=True)
    except Exception as e:
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
            return ValidateKeyResponse(valid=False, error="Invalid API key.")
        return ValidateKeyResponse(valid=False, error=f"API error: {error_msg}")


@router.post("/validate-directory")
async def validate_directory(body: ValidateDirectoryRequest) -> ValidateDirectoryResponse:
    """Test whether an output directory path is valid and writable."""
    valid, error = validate_output_directory(body.path)
    return ValidateDirectoryResponse(valid=valid, error=error)


@router.get("/status")
async def get_status() -> SettingsStatus:
    """Get first-run status and health check results."""
    has_key = bool(settings.anthropic_api_key)
    has_output = (
        bool(settings.output_directory) and settings.output_directory != "~/rekordbot/library"
    )

    # Check output directory writability
    output_writable = True
    if has_output:
        valid, _ = validate_output_directory(settings.output_directory)
        output_writable = valid

    # Check ffmpeg availability
    ffmpeg_ok = _check_ffmpeg()

    return SettingsStatus(
        configured=config_exists(),
        has_api_key=has_key,
        has_output_directory=has_output,
        ffmpeg_available=ffmpeg_ok,
        output_directory_writable=output_writable,
    )


def _apply_to_settings(config: dict) -> None:
    """Update the in-memory Settings singleton from a config dict.

    Args:
        config: Dict of setting name → value.
    """
    for key, value in config.items():
        if key in CONFIGURABLE_FIELDS and hasattr(settings, key):
            # Use object.__setattr__ since pydantic models may be frozen
            object.__setattr__(settings, key, value)


def _check_ffmpeg() -> bool:
    """Check if ffmpeg is available and executable.

    Returns:
        True if ffmpeg can be executed.
    """
    import shutil

    return shutil.which(settings.ffmpeg_path) is not None


# Re-export settings singleton for convenience (used by status endpoint)
def get_settings_singleton() -> Settings:
    """Return the in-memory Settings singleton."""
    return settings
