"""File mover — executes approved file moves and updates DB records.

This is the only component that physically moves files on the filesystem.
All file operations use shutil.move wrapped in asyncio.to_thread() for
non-blocking I/O.
"""

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.exceptions import OrganisationError

logger = logging.getLogger(__name__)


@dataclass
class MoveResult:
    """Result of a single file move operation.

    Attributes:
        track_id: Database ID of the track.
        status: "moved" or "failed".
        old_path: Original file path.
        new_path: Destination file path.
        error: Error message if failed.
    """

    track_id: int
    status: str  # "moved" or "failed"
    old_path: Path
    new_path: Path
    error: str | None = None


@dataclass
class BatchMoveResult:
    """Result of a batch file move operation.

    Attributes:
        total: Total number of files in the batch.
        moved: Number of successfully moved files.
        failed: Number of failed moves.
        results: Individual move results.
        dirs_cleaned: Number of empty directories removed.
    """

    total: int = 0
    moved: int = 0
    failed: int = 0
    results: list[MoveResult] = field(default_factory=list)
    dirs_cleaned: int = 0


def _resolve_collision(destination: Path) -> Path:
    """Apply collision suffix if destination already exists.

    Args:
        destination: Desired destination path.

    Returns:
        Path with _1, _2, etc. suffix if needed.
    """
    if not destination.exists():
        return destination

    stem = destination.stem
    ext = destination.suffix
    parent = destination.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


async def move_file(
    track: Any,
    destination: Path,
    db_session: Session,
) -> MoveResult:
    """Move a single file from its current output_path to the destination.

    Updates the Track record with the new path and previous path.

    Args:
        track: Track model instance (must have file_path, id attributes).
        destination: Target path for the file.
        db_session: SQLAlchemy session for DB updates.

    Returns:
        MoveResult indicating success or failure.
    """
    old_path = Path(track.file_path)
    track_id: int = track.id
    # Verify source exists
    if not old_path.exists():
        error_msg = f"Source file does not exist: {old_path}"
        logger.error("Move failed for track %s: %s", track_id, error_msg)
        return MoveResult(
            track_id=track_id,
            status="failed",
            old_path=old_path,
            new_path=destination,
            error=error_msg,
        )

    # Resolve collision
    final_destination = _resolve_collision(destination)

    try:
        # Create parent directories
        final_destination.parent.mkdir(parents=True, exist_ok=True)

        # Move file (non-blocking)
        await asyncio.to_thread(shutil.move, str(old_path), str(final_destination))

        # Verify move
        if not final_destination.exists():
            raise OrganisationError(
                f"File not found at destination after move: {final_destination}"
            )

        # Verify size matches
        source_size = old_path.stat().st_size if old_path.exists() else None
        dest_size = final_destination.stat().st_size
        if source_size is not None and source_size != dest_size:
            logger.warning(
                "Size mismatch after move for track %s: %d vs %d",
                track_id,
                source_size,
                dest_size,
            )

        # Update DB
        track.previous_output_path = str(old_path)
        track.file_path = str(final_destination)
        track.organisation_status = "organised"
        track.proposed_path = None
        db_session.flush()

        logger.info("Moved track %s: %s → %s", track_id, old_path, final_destination)
        return MoveResult(
            track_id=track_id,
            status="moved",
            old_path=old_path,
            new_path=final_destination,
        )

    except Exception as e:
        error_msg = str(e)
        logger.exception("Move failed for track %s", track_id)
        return MoveResult(
            track_id=track_id,
            status="failed",
            old_path=old_path,
            new_path=final_destination,
            error=error_msg,
        )


async def move_files_batch(
    moves: list[tuple[Any, Path]],
    db_session: Session,
    base_dir: Path | None = None,
) -> BatchMoveResult:
    """Move a batch of files with per-file error isolation.

    Args:
        moves: List of (Track, destination_path) tuples.
        db_session: SQLAlchemy session for DB updates.
        base_dir: Base directory for cleanup (optional).

    Returns:
        BatchMoveResult with individual results and summary.
    """
    result = BatchMoveResult(total=len(moves))

    for track, destination in moves:
        move_result = await move_file(track, destination, db_session)
        result.results.append(move_result)
        if move_result.status == "moved":
            result.moved += 1
        else:
            result.failed += 1

    # Commit all DB changes
    db_session.commit()

    # Clean up empty directories
    if base_dir:
        result.dirs_cleaned = await asyncio.to_thread(cleanup_empty_dirs, base_dir)

    return result


def cleanup_empty_dirs(base_dir: Path) -> int:
    """Recursively remove empty directories within the base directory.

    Safety: Only removes directories that are children of base_dir.
    Never traverses above the base directory.

    Args:
        base_dir: Root directory to clean within.

    Returns:
        Number of directories removed.
    """
    if not base_dir.exists():
        return 0

    removed = 0
    # Walk bottom-up so we remove deepest empty dirs first
    for dirpath in sorted(base_dir.rglob("*"), reverse=True):
        if not dirpath.is_dir():
            continue

        # Safety check: must be a child of base_dir
        try:
            dirpath.relative_to(base_dir)
        except ValueError:
            continue

        # Don't remove base_dir itself
        if dirpath == base_dir:
            continue

        # Remove if empty
        if not any(dirpath.iterdir()):
            try:
                dirpath.rmdir()
                removed += 1
                logger.debug("Removed empty directory: %s", dirpath)
            except OSError:
                logger.warning("Could not remove directory: %s", dirpath)

    return removed
