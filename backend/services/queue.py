"""Processing queue — manages batch file processing with concurrency control and SSE."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.services.converter import TrackResult, convert_file

logger = logging.getLogger(__name__)


@dataclass
class BatchProgress:
    """Tracks progress of a batch processing operation."""

    total: int = 0
    completed: int = 0
    failed: int = 0
    duplicates: int = 0


@dataclass
class BatchResult:
    """Final result of batch processing."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    duplicates: int = 0
    results: list[TrackResult] = field(default_factory=list)


class ProcessingQueue:
    """Manages concurrent file processing with SSE progress reporting.

    Attributes:
        settings: Application settings.
        _semaphore: Limits concurrent ffmpeg processes.
        _cancel_event: Set to request cancellation.
        _progress: Current batch progress.
        _event_queue: SSE events are pushed here for consumption.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_conversions)
        self._cancel_event = asyncio.Event()
        self._progress = BatchProgress()
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._processing = False

    @property
    def is_processing(self) -> bool:
        """Whether a batch is currently being processed."""
        return self._processing

    def cancel(self) -> None:
        """Request cancellation of the current batch."""
        self._cancel_event.set()
        logger.info("Batch cancellation requested")

    async def _emit_event(
        self,
        file_path: str,
        status: str,
        action: str = "",
        message: str = "",
        error: str | None = None,
    ) -> None:
        """Push an SSE event to the event queue."""
        event_data = {
            "file_path": file_path,
            "status": status,
            "action": action,
            "message": message,
            "batch_progress": {
                "completed": self._progress.completed,
                "total": self._progress.total,
                "failed": self._progress.failed,
                "duplicates": self._progress.duplicates,
            },
        }
        if error:
            event_data["error"] = error
        await self._event_queue.put({"event": "file_progress", "data": event_data})

    async def _process_one(self, path: Path, db_session: Session) -> TrackResult:
        """Process a single file with semaphore-controlled concurrency."""
        async with self._semaphore:
            if self._cancel_event.is_set():
                return TrackResult(
                    success=False,
                    file_path=str(path),
                    error="Cancelled",
                    action="cancelled",
                )

            await self._emit_event(str(path), "processing", message=f"Processing {path.name}...")

            result = await convert_file(path, db_session, self.settings)

            # Update progress
            if result.duplicate:
                self._progress.duplicates += 1
                self._progress.completed += 1
                await self._emit_event(
                    str(path),
                    "skipped",
                    action="skip_duplicate",
                    message=f"Duplicate: {path.name}",
                )
            elif result.success:
                self._progress.completed += 1
                await self._emit_event(
                    str(path),
                    "complete",
                    action=result.action,
                    message=f"Complete: {path.name}",
                )
            else:
                self._progress.failed += 1
                self._progress.completed += 1
                await self._emit_event(
                    str(path),
                    "failed",
                    message=f"Failed: {path.name}",
                    error=result.error,
                )

            return result

    async def process_batch(
        self,
        paths: list[Path],
        db_session: Session,
    ) -> BatchResult:
        """Process a batch of files concurrently.

        Args:
            paths: List of audio file paths to process.
            db_session: SQLAlchemy session for database operations.

        Returns:
            BatchResult with summary and per-file results.
        """
        self._processing = True
        self._cancel_event.clear()
        self._progress = BatchProgress(total=len(paths))

        # Emit queued events for all files
        for path in paths:
            await self._emit_event(str(path), "queued", message=f"Queued: {path.name}")

        # Process all files concurrently (bounded by semaphore)
        tasks = [self._process_one(path, db_session) for path in paths]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build batch result
        batch_result = BatchResult(total=len(paths))
        for result in results:
            if isinstance(result, Exception):
                logger.exception("Unexpected error in batch processing: %s", result)
                batch_result.failed += 1
            elif isinstance(result, TrackResult):
                batch_result.results.append(result)
                if result.duplicate:
                    batch_result.duplicates += 1
                elif result.success:
                    batch_result.succeeded += 1
                else:
                    batch_result.failed += 1

        # Emit batch complete event
        await self._event_queue.put(
            {
                "event": "batch_complete",
                "data": {
                    "total": batch_result.total,
                    "succeeded": batch_result.succeeded,
                    "failed": batch_result.failed,
                    "duplicates": batch_result.duplicates,
                },
            }
        )

        self._processing = False
        logger.info(
            "Batch complete: %d succeeded, %d failed, %d duplicates out of %d total",
            batch_result.succeeded,
            batch_result.failed,
            batch_result.duplicates,
            batch_result.total,
        )
        return batch_result

    async def event_generator(self):
        """Async generator that yields SSE events.

        Yields:
            Dict with "event" and "data" keys for SSE formatting.
        """
        while True:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=30.0)
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"]),
                }
                # Stop after batch_complete if not processing
                if event["event"] == "batch_complete":
                    break
            except TimeoutError:
                # Send keepalive
                yield {"event": "keepalive", "data": ""}
