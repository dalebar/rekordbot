"""Config manager — JSON persistence and env var integration.

Manages reading and writing the JSON config file at the platform app data
directory. Integrates with pydantic-settings by setting env vars before
Settings instantiation.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Config file name
_CONFIG_FILENAME = "config.json"

# Fields that are user-configurable and stored in the JSON config file.
# Internal settings (port, db_url, log_level, batch sizes, etc.) are excluded.
CONFIGURABLE_FIELDS: set[str] = {
    "anthropic_api_key",
    "output_directory",
    "default_key_notation",
    "folder_template",
    "convert_aac_to_mp3",
    "bpm_range_min",
    "bpm_range_max",
    "confidence_threshold",
    "set_track_duration_minutes",
    "set_max_tracks",
}


def _get_app_data_dir() -> Path:
    """Return the platform-appropriate application data directory.

    Returns:
        Path to ~/Library/Application Support/rekordbot/ on macOS.
    """
    home = Path.home()
    return home / "Library" / "Application Support" / "rekordbot"


def get_config_path() -> Path:
    """Return the config directory path, creating it if needed.

    Returns:
        Path to the config directory.
    """
    config_dir = _get_app_data_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def config_exists() -> bool:
    """Check whether the config file exists.

    Returns:
        True if config.json exists in the config directory.
    """
    config_dir = _get_app_data_dir()
    return (config_dir / _CONFIG_FILENAME).is_file()


def load_config() -> dict:
    """Read the JSON config file and return its contents.

    Returns:
        Parsed config dict, or empty dict if file doesn't exist or is invalid.
    """
    config_file = _get_app_data_dir() / _CONFIG_FILENAME
    if not config_file.is_file():
        logger.debug("No config file found at %s", config_file)
        return {}

    try:
        content = config_file.read_text(encoding="utf-8")
        data: dict = json.loads(content)
        logger.info("Loaded config from %s", config_file)
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read config file %s: %s", config_file, e)
        return {}


def save_config(settings: dict) -> None:
    """Write settings to the JSON config file.

    Only writes fields that are in CONFIGURABLE_FIELDS. Creates the
    config directory if it doesn't exist.

    Args:
        settings: Dict of setting name → value.
    """
    config_dir = _get_app_data_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / _CONFIG_FILENAME

    # Filter to only configurable fields
    filtered = {k: v for k, v in settings.items() if k in CONFIGURABLE_FIELDS}

    config_file.write_text(
        json.dumps(filtered, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Saved config to %s", config_file)


def apply_config_to_env(config: dict) -> None:
    """Set environment variables from config so pydantic-settings picks them up.

    Only sets vars for known configurable fields. Does NOT override
    existing env vars — env vars take precedence over the config file.

    Args:
        config: Dict of setting name → value.
    """
    for key, value in config.items():
        if key not in CONFIGURABLE_FIELDS:
            continue

        env_key = f"REKORDBOT_{key.upper()}"
        if env_key in os.environ:
            logger.debug("Env var %s already set, skipping config value", env_key)
            continue

        os.environ[env_key] = str(value)
        logger.debug("Set %s from config file", env_key)


def validate_output_directory(path: str) -> tuple[bool, str]:
    """Validate that an output directory path is usable.

    Checks that the path is non-empty and that either the directory exists
    or its parent directory exists (so it can be created).

    Args:
        path: Directory path to validate.

    Returns:
        Tuple of (is_valid, error_message). Empty message if valid.
    """
    if not path:
        return False, "Output directory path is required."

    expanded = Path(path).expanduser().resolve()

    if expanded.is_dir():
        # Check writability
        if not os.access(str(expanded), os.W_OK):
            return False, f"Directory is not writable: {expanded}"
        return True, ""

    # Directory doesn't exist — check if parent exists
    parent = expanded.parent
    if parent.is_dir():
        if not os.access(str(parent), os.W_OK):
            return False, f"Parent directory is not writable: {parent}"
        return True, ""

    return False, f"Parent directory does not exist: {parent}"


def get_db_path() -> str:
    """Return the SQLite database URL for the app data directory.

    Returns:
        SQLAlchemy connection string pointing to rekordbot.db in the
        config directory.
    """
    config_dir = _get_app_data_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{config_dir}/rekordbot.db"


def mask_api_key(key: str) -> str:
    """Mask an API key for display, showing only the last 4 characters.

    Args:
        key: Full API key string.

    Returns:
        Masked key like "sk-ant-...XXXX", or empty string if key is empty.
    """
    if not key:
        return ""
    if len(key) <= 7:
        return "***"
    # Preserve the "sk-ant-" prefix if present for readability
    if key.startswith("sk-ant-"):
        return f"sk-ant-...{key[-4:]}"
    return f"{key[:4]}...{key[-4:]}"


def is_key_masked(key: str) -> bool:
    """Check if an API key value is masked (not a real key).

    Args:
        key: Key string to check.

    Returns:
        True if the key contains the mask pattern "...".
    """
    return "..." in key if key else False
