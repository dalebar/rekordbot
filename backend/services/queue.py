"""Processing queue — manages batch file processing with SSE progress reporting.

Uses a plain background thread for file processing to avoid asyncio event loop
starvation that causes deadlocks after ~40-45 files on macOS.
"""

import asyncio
import json
import logging
import queue
import threading
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
    """Manages file processing in a background thread with SSE progress reporting.

    Processing runs in a plain thread to avoid asyncio event loop starvation.
    SSE events are pushed to the asyncio event queue via call_soon_threadsafe.

    Attributes:
        settings: Application settings.
        _cancel_event: Set to request cancellation (threading.Event).
        _progress: Current batch progress.
        _event_queue: asyncio.Queue for SSE event consumption.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cancel_event = threading.Event()
        self._progress = BatchProgress()
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._processing = False
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_processing(self) -> bool:
        """Whether a batch is currently being processed."""
        return self._processing

    def cancel(self) -> None:
        """Request cancellation of the current batch."""
        self._cancel_event.set()
        logger.info("Batch cancellation requested")

    def _push_event(self, event: dict[str, Any]) -> None:
        """Thread-safe: push an SSE event from the worker thread."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._event_queue.put_nowait, event)

    def _emit(
        self,
        file_path: str,
        status: str,
        action: str = "",
        message: str = "",
        error: str | None = None,
    ) -> None:
        """Emit an SSE event (callable from any thread)."""
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
        self._push_event({"event": "file_progress", "data": event_data})

    def _worker_thread(self, work_queue: queue.Queue[Path | None]) -> list[TrackResult]:
        """Worker thread — processes files sequentially, fully synchronous."""
        results: list[TrackResult] = []

        while True:
            path = work_queue.get()
            if path is None:
                break

            if self._cancel_event.is_set():
                results.append(
                    TrackResult(
                        success=False,
                        file_path=str(path),
                        error="Cancelled",
                        action="cancelled",
                    )
                )
                continue

            self._emit(str(path), "processing", message=f"Processing {path.name}...")

            db_session = SessionLocal()
            try:
                result = convert_file(path, db_session, self.settings)
            except Exception as e:
                logger.exception("Unexpected error processing %s", path.name)
                result = TrackResult(success=False, file_path=str(path), error=str(e))
            finally:
                db_session.close()

            # Update progress and emit events
            if result.duplicate:
                self._progress.duplicates += 1
                self._progress.completed += 1
                self._emit(
                    str(path),
                    "skipped",
                    action="skip_duplicate",
                    message=f"Duplicate: {path.name}",
                )
            elif result.success:
                self._progress.completed += 1
                self._emit(
                    str(path),
                    "complete",
                    action=result.action,
                    message=f"Complete: {path.name}",
                )
            else:
                self._progress.failed += 1
                self._progress.completed += 1
                self._emit(
                    str(path),
                    "failed",
                    message=f"Failed: {path.name}",
                    error=result.error,
                )

            results.append(result)

        return results

    def _run_worker_and_signal(
        self,
        work_queue: queue.Queue[Path | None],
        future: asyncio.Future[list[TrackResult]],
    ) -> None:
        """Run the worker and signal the asyncio Future when done."""
        try:
            results = self._worker_thread(work_queue)
            self._loop.call_soon_threadsafe(future.set_result, results)  # type: ignore[union-attr]
        except Exception as e:
            self._loop.call_soon_threadsafe(future.set_exception, e)  # type: ignore[union-attr]

    async def process_batch(self, paths: list[Path]) -> BatchResult:
        """Process a batch of files in a background thread.

        Args:
            paths: List of audio file paths to process.

        Returns:
            BatchResult with summary and per-file results.
        """
        self._processing = True
        self._cancel_event.clear()
        self._progress = BatchProgress(total=len(paths))
        self._loop = asyncio.get_event_loop()

        # Populate stdlib queue
        work_queue: queue.Queue[Path | None] = queue.Queue()
        for path in paths:
            work_queue.put(path)
        work_queue.put(None)  # sentinel

        # Create Future for getting results back from thread
        worker_future: asyncio.Future[list[TrackResult]] = self._loop.create_future()

        # Run worker in a plain thread
        thread = threading.Thread(
            target=self._run_worker_and_signal,
            args=(work_queue, worker_future),
            name="ingest-worker",
            daemon=True,
        )
        thread.start()

        # Wait for the thread to finish without blocking the event loop
        results = await worker_future

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
        self._push_event(
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
