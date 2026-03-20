"""Processing queue — manages batch file processing with concurrency control and SSE."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config import Settings
from backend.models.database import SessionLocal
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

    Uses a bounded worker pool (not gather) to avoid coroutine explosion
    when processing large batches.

    Attributes:
        settings: Application settings.
        _cancel_event: Set to request cancellation.
        _progress: Current batch progress.
        _event_queue: SSE events are pushed here for consumption.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
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

    async def process_batch(self, paths: list[Path]) -> BatchResult:
        """Process a batch of files using a bounded worker pool.

        Spawns exactly max_concurrent_conversions workers that pull from an
        asyncio.Queue, avoiding the coroutine explosion that gather causes
        with large batches.

        Args:
            paths: List of audio file paths to process.

        Returns:
            BatchResult with summary and per-file results.
        """
        self._processing = True
        self._cancel_event.clear()
        self._progress = BatchProgress(total=len(paths))

        # Populate work queue (no SSE events — workers emit processing/complete/failed)
        work_queue: asyncio.Queue[Path | None] = asyncio.Queue()
        for path in paths:
            await work_queue.put(path)

        # Add sentinel values to signal workers to stop
        num_workers = self.settings.max_concurrent_conversions
        for _ in range(num_workers):
            await work_queue.put(None)

        results: list[TrackResult] = []
        results_lock = asyncio.Lock()

        async def worker() -> None:
            while True:
                path = await work_queue.get()
                if path is None:
                    break

                if self._cancel_event.is_set():
                    async with results_lock:
                        results.append(
                            TrackResult(
                                success=False,
                                file_path=str(path),
                                error="Cancelled",
                                action="cancelled",
                            )
                        )
                    work_queue.task_done()
                    continue

                logger.debug("Worker processing: %s", path.name)
                await self._emit_event(
                    str(path), "processing", message=f"Processing {path.name}..."
                )

                db_session = SessionLocal()
                try:
                    result = await convert_file(path, db_session, self.settings)
                except Exception as e:
                    logger.exception("Unexpected error processing %s", path.name)
                    result = TrackResult(success=False, file_path=str(path), error=str(e))
                finally:
                    db_session.close()

                # Update progress and emit events
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

                async with results_lock:
                    results.append(result)

                work_queue.task_done()

        # Start exactly max_concurrent_conversions workers
        workers = [asyncio.create_task(worker()) for _ in range(num_workers)]

        # Wait for all workers to finish
        await asyncio.gather(*workers)

        # Build batch result
        batch_result = BatchResult(total=len(paths))
        for result in results:
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
