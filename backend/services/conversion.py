"""Conversion decision engine — pure logic, no I/O."""

import logging
from dataclasses import dataclass
from typing import Literal

from backend.services.format_inspector import FileInfo, get_quality_warning

logger = logging.getLogger(__name__)

# AIFF container codecs — files already in AIFF format
AIFF_CODECS = frozenset({"pcm_s16be", "pcm_s24be", "pcm_s32be"})

# Output bit depth for AIFF — always 16-bit for universal CDJ compatibility
OUTPUT_BIT_DEPTH = 16


@dataclass(frozen=True)
class ConversionAction:
    """Describes what conversion action to take for a file."""

    action: Literal["convert_to_aiff", "convert_to_mp3", "copy_as_is"]
    reason: str
    output_format: str
    output_bit_depth: int | None
    quality_warning: bool
    warning_detail: str


def decide_conversion(file_info: FileInfo, convert_aac_to_mp3: bool) -> ConversionAction:
    """Decide what conversion action to take for a given file.

    Args:
        file_info: Parsed audio file information.
        convert_aac_to_mp3: Whether to convert AAC files to MP3.

    Returns:
        ConversionAction describing what to do.
    """
    has_warning, warning_detail = get_quality_warning(file_info.bitrate, file_info.is_lossless)

    # AIFF — already target format, copy as-is
    if file_info.is_lossless and file_info.container == "aiff":
        return ConversionAction(
            action="copy_as_is",
            reason="Already in AIFF format",
            output_format="aiff",
            output_bit_depth=None,
            quality_warning=has_warning,
            warning_detail=warning_detail,
        )

    # Lossless (WAV, FLAC, ALAC) → convert to AIFF
    if file_info.is_lossless:
        return ConversionAction(
            action="convert_to_aiff",
            reason=f"Lossless {file_info.codec} → AIFF (16-bit)",
            output_format="aiff",
            output_bit_depth=OUTPUT_BIT_DEPTH,
            quality_warning=has_warning,
            warning_detail=warning_detail,
        )

    # AAC — optional convert to MP3
    if file_info.codec == "aac":
        if convert_aac_to_mp3:
            return ConversionAction(
                action="convert_to_mp3",
                reason="AAC → MP3 (user preference)",
                output_format="mp3",
                output_bit_depth=None,
                quality_warning=has_warning,
                warning_detail=warning_detail,
            )
        return ConversionAction(
            action="copy_as_is",
            reason="AAC — copied as-is (convert_aac_to_mp3 disabled)",
            output_format="m4a",
            output_bit_depth=None,
            quality_warning=has_warning,
            warning_detail=warning_detail,
        )

    # MP3 and other lossy — copy as-is
    return ConversionAction(
        action="copy_as_is",
        reason=f"{file_info.codec} — copied as-is",
        output_format=file_info.codec if file_info.codec == "mp3" else file_info.container,
        output_bit_depth=None,
        quality_warning=has_warning,
        warning_detail=warning_detail,
    )
