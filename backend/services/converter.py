"""Converter service — orchestrates inspection, decision, ffmpeg execution, and DB storage."""

import asyncio
import hashlib
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.exceptions import ConversionError, DuplicateTrackError
from backend.models.crate import CrateTrack
from backend.models.set_plan import SetTrack
from backend.models.track import Track
from backend.services.conversion import ConversionAction, decide_conversion
from backend.services.format_inspector import FileInfo, inspect_file
from backend.services.naming import generate_output_path

logger = logging.getLogger(__name__)

# Bit depth to AIFF PCM codec mapping
AIFF_CODEC_MAP = {
    16: "pcm_s16be",
    24: "pcm_s24be",
}


@dataclass
class TrackResult:
    """Result of processing a single file."""

    success: bool
    track: Track | None = None
    error: str | None = None
    duplicate: bool = False
    file_path: str = ""
    action: str = ""


def build_ffmpeg_command(
    input_path: Path,
    output_path: Path,
    action: ConversionAction,
    file_info: FileInfo,
    ffmpeg_path: str = "ffmpeg",
) -> list[str]:
    """Build the ffmpeg command for a conversion.

    Args:
        input_path: Source audio file path.
        output_path: Destination file path.
        action: The conversion action to perform.
        file_info: Parsed info about the source file.
        ffmpeg_path: Path to the ffmpeg binary.

    Returns:
        List of command-line arguments for ffmpeg.
    """
    if action.action == "convert_to_aiff":
        bit_depth = action.output_bit_depth or 16
        codec = AIFF_CODEC_MAP.get(bit_depth, "pcm_s24be")
        return [
            ffmpeg_path,
            "-y",
            "-i",
            str(input_path),
            "-c:a",
            codec,
            "-f",
            "aiff",
            "-write_id3v2",
            "1",
            str(output_path),
        ]

    if action.action == "convert_to_mp3":
        return [
            ffmpeg_path,
            "-y",
            "-i",
            str(input_path),
            "-c:a",
            "libmp3lame",
            "-q:a",
            "0",
            str(output_path),
        ]

    raise ValueError(f"Cannot build ffmpeg command for action: {action.action}")


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file.

    Args:
        path: Path to the file.

    Returns:
        Hex digest of the SHA-256 hash.
    """
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


async def _run_ffmpeg(cmd: list[str]) -> None:
    """Run an ffmpeg command as an async subprocess.

    Args:
        cmd: The ffmpeg command arguments.

    Raises:
        ConversionError: If ffmpeg exits with a non-zero code.
    """
    logger.info("Running ffmpeg: %s", " ".join(cmd))
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode().strip() if stderr else "Unknown ffmpeg error"
        raise ConversionError(f"ffmpeg failed (exit {process.returncode}): {error_msg}")


async def convert_file(
    path: Path,
    db_session: Session,
    settings: Settings,
) -> TrackResult:
    """Process a single audio file through the full ingestion pipeline.

    Pipeline: inspect → decide → hash → check duplicate → execute → store in DB.

    Args:
        path: Path to the source audio file.
        db_session: SQLAlchemy session for database operations.
        settings: Application settings.

    Returns:
        TrackResult with success status and created Track (or error details).
    """
    try:
        # Step 1: Inspect
        file_info = await inspect_file(path)
        logger.info(
            "Inspected %s: %s/%s, %d kbps, %s",
            path.name,
            file_info.container,
            file_info.codec,
            file_info.bitrate,
            "lossless" if file_info.is_lossless else "lossy",
        )

        # Step 2: Decide
        action = decide_conversion(file_info, settings.convert_aac_to_mp3)
        logger.info("Decision for %s: %s — %s", path.name, action.action, action.reason)

        # Step 3: Hash source file for duplicate detection
        logger.info("Hashing source file %s (%d bytes)...", path.name, path.stat().st_size)
        file_hash = compute_file_hash(path)
        logger.info("Hash complete for %s: %s", path.name, file_hash[:12])

        # Step 4: Check for duplicates
        existing = db_session.query(Track).filter_by(file_hash=file_hash).first()
        if existing:
            if Path(existing.file_path).exists():
                logger.info("Duplicate detected for %s (matches track %d)", path.name, existing.id)
                return TrackResult(
                    success=False,
                    duplicate=True,
                    file_path=str(path),
                    action="skip_duplicate",
                    error=f"Duplicate of existing track: {existing.file_path}",
                )
            else:
                # Output file is missing — clean up orphaned record and continue
                logger.warning(
                    "Orphaned track %d (file missing: %s) — cleaning up",
                    existing.id,
                    existing.file_path,
                )
                db_session.query(CrateTrack).filter_by(track_id=existing.id).delete()
                db_session.query(SetTrack).filter_by(track_id=existing.id).delete()
                db_session.delete(existing)
                db_session.commit()

        # Step 5: Generate output path
        logger.info("Generating output path for %s", path.name)
        output_dir = Path(settings.output_directory).expanduser()
        output_path = generate_output_path(path, output_dir, action.output_format)

        # Step 6: Execute conversion or copy
        logger.info("Starting %s for %s", action.action, path.name)
        if action.action in ("convert_to_aiff", "convert_to_mp3"):
            cmd = build_ffmpeg_command(path, output_path, action, file_info, settings.ffmpeg_path)
            await _run_ffmpeg(cmd)
        else:
            # copy_as_is
            shutil.copy2(str(path), str(output_path))

        logger.info("Output written to %s", output_path)

        # Step 7: Get output file size
        output_size = output_path.stat().st_size

        # Step 8: Create Track record
        track = Track(
            file_path=str(output_path),
            file_hash=file_hash,
            source_path=str(path),
            source_format=file_info.container,
            source_codec=file_info.codec,
            source_bitrate=file_info.bitrate,
            source_bit_depth=file_info.bit_depth,
            output_format=action.output_format,
            sample_rate=file_info.sample_rate,
            bit_depth=action.output_bit_depth or file_info.bit_depth,
            duration=file_info.duration,
            file_size=output_size,
            channels=file_info.channels,
            is_lossy=not file_info.is_lossless,
            quality_warning=action.quality_warning,
            conversion_action=action.action,
            conversion_status="complete",
            imported_at=datetime.now(),
        )
        db_session.add(track)
        db_session.commit()

        logger.info("Track %d created for %s", track.id, path.name)
        return TrackResult(
            success=True,
            track=track,
            file_path=str(path),
            action=action.action,
        )

    except DuplicateTrackError:
        raise
    except ConversionError as e:
        logger.error("Conversion failed for %s: %s", path.name, e.detail)
        return TrackResult(
            success=False,
            file_path=str(path),
            error=e.detail,
        )
    except Exception as e:
        logger.exception("Unexpected error processing %s", path.name)
        return TrackResult(
            success=False,
            file_path=str(path),
            error=str(e),
        )
