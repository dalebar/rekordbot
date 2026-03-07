"""Format inspector — wraps ffprobe to determine true audio format and codec."""

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

# Codecs known to be lossless
LOSSLESS_CODECS = frozenset({"flac", "alac"})
LOSSLESS_CODEC_PREFIXES = ("pcm_",)

QUALITY_WARNING_THRESHOLD_KBPS = 192


@dataclass(frozen=True)
class FileInfo:
    """Parsed audio file information from ffprobe."""

    path: Path
    container: str
    codec: str
    sample_rate: int
    bit_depth: int | None
    bitrate: int
    duration: float
    channels: int
    is_lossless: bool


def determine_lossless(codec: str) -> bool:
    """Determine whether a codec is lossless.

    Args:
        codec: The codec name from ffprobe (e.g. "pcm_s16le", "flac", "aac").

    Returns:
        True if the codec is lossless, False otherwise.
    """
    if codec in LOSSLESS_CODECS:
        return True
    return any(codec.startswith(prefix) for prefix in LOSSLESS_CODEC_PREFIXES)


def get_quality_warning(bitrate: int, is_lossless: bool) -> tuple[bool, str]:
    """Check if a file should be flagged with a quality warning.

    Args:
        bitrate: File bitrate in kbps.
        is_lossless: Whether the file uses a lossless codec.

    Returns:
        Tuple of (has_warning, warning_message). Empty string if no warning.
    """
    if is_lossless:
        return False, ""
    if bitrate < QUALITY_WARNING_THRESHOLD_KBPS:
        return (
            True,
            f"{bitrate} kbps — below quality threshold of {QUALITY_WARNING_THRESHOLD_KBPS} kbps",
        )
    return False, ""


def parse_ffprobe_output(json_output: dict, path: Path) -> FileInfo:
    """Parse ffprobe JSON output into a FileInfo dataclass.

    Args:
        json_output: Parsed JSON from ffprobe -print_format json -show_format -show_streams.
        path: The file path being inspected.

    Returns:
        FileInfo with parsed audio properties.

    Raises:
        ValueError: If no audio stream is found.
    """
    # Find first audio stream
    streams = json_output.get("streams", [])
    audio_stream = None
    for stream in streams:
        if stream.get("codec_type") == "audio":
            audio_stream = stream
            break

    if audio_stream is None:
        raise ValueError(f"No audio stream found in {path}")

    format_info = json_output.get("format", {})
    codec = audio_stream["codec_name"]
    is_lossless = determine_lossless(codec)

    # Extract bit depth from bits_per_raw_sample (present for PCM and lossless)
    bit_depth_raw = audio_stream.get("bits_per_raw_sample")
    bit_depth = int(bit_depth_raw) if bit_depth_raw is not None else None

    # Extract bitrate: prefer format-level, fall back to stream-level
    format_bitrate = format_info.get("bit_rate", "0")
    try:
        bitrate_bps = int(format_bitrate)
    except (ValueError, TypeError):
        bitrate_bps = 0

    if bitrate_bps == 0:
        stream_bitrate = audio_stream.get("bit_rate", "0")
        try:
            bitrate_bps = int(stream_bitrate)
        except (ValueError, TypeError):
            bitrate_bps = 0

    bitrate_kbps = bitrate_bps // 1000

    # Extract duration
    duration_str = format_info.get("duration", "0")
    try:
        duration = float(duration_str)
    except (ValueError, TypeError):
        duration = 0.0

    return FileInfo(
        path=path,
        container=format_info.get("format_name", ""),
        codec=codec,
        sample_rate=int(audio_stream.get("sample_rate", 0)),
        bit_depth=bit_depth,
        bitrate=bitrate_kbps,
        duration=duration,
        channels=int(audio_stream.get("channels", 0)),
        is_lossless=is_lossless,
    )


async def inspect_file(path: Path) -> FileInfo:
    """Run ffprobe on a file and return parsed FileInfo.

    Args:
        path: Path to the audio file.

    Returns:
        FileInfo with parsed audio properties.

    Raises:
        ValueError: If ffprobe fails or file has no audio stream.
    """
    cmd = [
        settings.ffprobe_path,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    logger.debug("Running ffprobe: %s", " ".join(cmd))

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unknown error"
        raise ValueError(f"ffprobe failed for {path}: {error_msg}")

    try:
        json_output = json.loads(stdout.decode())
    except json.JSONDecodeError as e:
        raise ValueError(f"ffprobe returned invalid JSON for {path}: {e}") from e

    logger.debug("ffprobe output for %s: %s", path.name, json_output)
    return parse_ffprobe_output(json_output, path)
