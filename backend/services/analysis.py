"""Analysis pipeline — orchestrates tag reading, BPM/key detection, and tag writing.

Coordinates the full analysis flow for single tracks and batches.
Separate from Phase 1's ingestion pipeline. Uses asyncio.Semaphore
for concurrency control and SSE for progress reporting.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.models.track import Track
from backend.services.bpm_detector import BPMResult, detect_bpm
from backend.services.key_detector import KeyResult, detect_key
from backend.services.key_notation import parse_key_tag
from backend.services.tag_reader import TagData, read_tags
from backend.services.tag_writer import TagValues, TagWriteResult, write_tags

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Result of analysing a single track.

    Attributes:
        track_id: Database ID of the analysed track.
        status: "success" or "failed".
        bpm_result: BPM detection result, if successful.
        key_result: Key detection result, if successful.
        tags_read: Tags read from the file, if successful.
        error: Error message if analysis failed.
    """

    track_id: int
    status: Literal["success", "failed"]
    bpm_result: BPMResult | None = None
    key_result: KeyResult | None = None
    tags_read: TagData | None = None
    error: str | None = None


@dataclass
class BatchAnalysisResult:
    """Result of analysing a batch of tracks.

    Attributes:
        total: Total number of tracks in the batch.
        succeeded: Number of successfully analysed tracks.
        failed: Number of failed analyses.
        results: Per-track results.
    """

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list[AnalysisResult] = field(default_factory=list)


async def analyse_track(
    track: Track,
    db_session: Session,
    settings: Settings,
) -> AnalysisResult:
    """Analyse a single track: read tags, detect BPM and key, update DB.

    Args:
        track: Track model instance to analyse.
        db_session: SQLAlchemy session for database updates.
        settings: Application settings.

    Returns:
        AnalysisResult with detection results.
    """
    file_path = Path(track.file_path)

    if not file_path.exists():
        logger.error("File not found for analysis: %s", file_path)
        track.analysis_status = "failed"
        db_session.commit()
        return AnalysisResult(
            track_id=track.id,
            status="failed",
            error=f"File not found: {file_path}",
        )

    try:
        # Step 1: Read existing tags
        tag_data = await asyncio.to_thread(read_tags, file_path)

        if tag_data is not None:
            # Populate tag fields in DB
            if tag_data.title is not None:
                track.title = tag_data.title
            if tag_data.artist is not None:
                track.artist = tag_data.artist
            if tag_data.album is not None:
                track.album = tag_data.album
            if tag_data.genre is not None:
                track.genre = tag_data.genre
            if tag_data.year is not None:
                track.year = tag_data.year
            if tag_data.track_number is not None:
                track.track_number = tag_data.track_number
            if tag_data.comment is not None:
                track.comment = tag_data.comment
            if tag_data.label is not None:
                track.label = tag_data.label
            if tag_data.rating is not None:
                track.rating = tag_data.rating

            # Store source BPM from existing tags
            if tag_data.bpm is not None:
                track.source_bpm = tag_data.bpm

            # Store source key from existing tags (parse to internal int)
            if tag_data.key is not None:
                parsed_key = parse_key_tag(tag_data.key)
                if parsed_key is not None:
                    track.source_key = parsed_key

            # Duration from tags (fallback — librosa may provide better value)
            if tag_data.duration is not None and track.duration is None:
                track.duration = tag_data.duration

        # Step 2: Load audio with librosa (once, shared between detectors)
        import librosa  # type: ignore[import-not-found]

        y, sr = await asyncio.to_thread(librosa.load, str(file_path), sr=22050, mono=True)

        # Update duration from librosa (more reliable than tag-based)
        track.duration = float(len(y)) / sr

        # Step 3: Detect BPM
        bpm_result = await asyncio.to_thread(
            detect_bpm,
            file_path,
            sr=22050,
            bpm_range_min=settings.bpm_range_min,
            bpm_range_max=settings.bpm_range_max,
            y=y,
            loaded_sr=sr,
        )

        if bpm_result is not None:
            track.bpm = bpm_result.bpm
            track.bpm_confidence = bpm_result.confidence

        # Step 4: Detect key
        key_result = await asyncio.to_thread(
            detect_key,
            file_path,
            y=y,
            loaded_sr=sr,
        )

        if key_result is not None:
            track.key = key_result.key
            track.key_confidence = key_result.confidence

        # Step 5: Update analysis status
        track.analysis_status = "analysed"
        db_session.commit()

        logger.info(
            "Analysis complete for track %d (%s): BPM=%.2f, Key=%s",
            track.id,
            file_path.name,
            track.bpm or 0.0,
            track.key or "unknown",
        )

        return AnalysisResult(
            track_id=track.id,
            status="success",
            bpm_result=bpm_result,
            key_result=key_result,
            tags_read=tag_data,
        )

    except Exception as e:
        logger.exception("Analysis failed for track %d (%s)", track.id, file_path)
        track.analysis_status = "failed"
        db_session.commit()
        return AnalysisResult(
            track_id=track.id,
            status="failed",
            error=str(e),
        )


class AnalysisQueue:
    """Manages batch track analysis with concurrency control and SSE progress.

    Attributes:
        settings: Application settings.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_analyses)
        self._cancel_event = asyncio.Event()
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._processing = False
        self._total = 0
        self._completed = 0
        self._failed = 0

    @property
    def is_processing(self) -> bool:
        """Whether a batch is currently being processed."""
        return self._processing

    def cancel(self) -> None:
        """Request cancellation of the current batch."""
        self._cancel_event.set()
        logger.info("Analysis batch cancellation requested")

    async def _emit_event(
        self,
        track_id: int,
        status: str,
        message: str = "",
        error: str | None = None,
    ) -> None:
        """Push an SSE event to the event queue."""
        event_data: dict[str, Any] = {
            "track_id": track_id,
            "status": status,
            "message": message,
            "batch_progress": {
                "completed": self._completed,
                "total": self._total,
                "failed": self._failed,
            },
        }
        if error:
            event_data["error"] = error
        await self._event_queue.put({"event": f"analysis_{status}", "data": event_data})

    async def _analyse_one(self, track: Track, db_session: Session) -> AnalysisResult:
        """Analyse a single track with semaphore-controlled concurrency."""
        async with self._semaphore:
            if self._cancel_event.is_set():
                return AnalysisResult(
                    track_id=track.id,
                    status="failed",
                    error="Cancelled",
                )

            await self._emit_event(track.id, "processing", f"Analysing {track.file_path}...")

            result = await analyse_track(track, db_session, self.settings)

            if result.status == "success":
                self._completed += 1
                await self._emit_event(
                    track.id, "complete", f"Analysis complete: track {track.id}"
                )
            else:
                self._failed += 1
                self._completed += 1
                await self._emit_event(
                    track.id, "failed", f"Analysis failed: track {track.id}", result.error
                )

            return result

    async def analyse_batch(
        self,
        tracks: list[Track],
        db_session: Session,
    ) -> BatchAnalysisResult:
        """Analyse a batch of tracks with concurrency control and SSE progress.

        Args:
            tracks: List of Track model instances to analyse.
            db_session: SQLAlchemy session for database operations.

        Returns:
            BatchAnalysisResult with summary and per-track results.
        """
        self._processing = True
        self._cancel_event.clear()
        self._total = len(tracks)
        self._completed = 0
        self._failed = 0

        # Emit queued events for all tracks
        for track in tracks:
            await self._emit_event(track.id, "queued", f"Queued: track {track.id}")

        # Process all tracks concurrently (bounded by semaphore)
        tasks = [self._analyse_one(track, db_session) for track in tracks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build batch result
        batch_result = BatchAnalysisResult(total=len(tracks))
        for result in results:
            if isinstance(result, Exception):
                logger.exception("Unexpected error in batch analysis: %s", result)
                batch_result.failed += 1
            elif isinstance(result, AnalysisResult):
                batch_result.results.append(result)
                if result.status == "success":
                    batch_result.succeeded += 1
                else:
                    batch_result.failed += 1

        # Emit batch complete event
        await self._event_queue.put(
            {
                "event": "analysis_batch_complete",
                "data": {
                    "total": batch_result.total,
                    "succeeded": batch_result.succeeded,
                    "failed": batch_result.failed,
                },
            }
        )

        self._processing = False
        logger.info(
            "Analysis batch complete: %d succeeded, %d failed out of %d total",
            batch_result.succeeded,
            batch_result.failed,
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
                if event["event"] == "analysis_batch_complete":
                    break
            except TimeoutError:
                yield {"event": "keepalive", "data": ""}


async def write_tags_batch(
    tracks: list[Track],
    db_session: Session,
) -> list[TagWriteResult]:
    """Write tags to files for a list of tracks.

    Args:
        tracks: List of Track model instances whose tags should be written.
        db_session: SQLAlchemy session for status updates.

    Returns:
        List of TagWriteResult for each track.
    """
    results: list[TagWriteResult] = []

    for track in tracks:
        file_path = Path(track.file_path)
        values = TagValues(
            title=track.title,
            artist=track.artist,
            album=track.album,
            genre=track.genre,
            year=track.year,
            track_number=track.track_number,
            comment=track.comment,
            label=track.label,
            bpm=track.bpm,
            key=track.key,
            rating=track.rating if track.rating and track.rating > 0 else None,
        )

        result = await asyncio.to_thread(write_tags, file_path, values)
        results.append(result)

        if result.success:
            track.analysis_status = "tags_written"
            logger.info("Tags written for track %d", track.id)
        else:
            logger.error("Tag writing failed for track %d: %s", track.id, result.error)

    db_session.commit()
    return results
