"""Tests for processing queue — concurrency, error handling, cancellation."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.config import Settings
from backend.services.converter import TrackResult
from backend.services.queue import ProcessingQueue


@pytest.fixture
def queue_settings() -> Settings:
    """Settings with low concurrency for testing."""
    return Settings(
        max_concurrent_conversions=2,
        output_directory="/tmp/test-output",
        db_url="sqlite://",
    )


@pytest.fixture
def mock_session_factory():
    """Mock SessionLocal that returns a fresh MagicMock session each call."""
    return MagicMock(side_effect=lambda: MagicMock())


def _success_result(path: str) -> TrackResult:
    return TrackResult(success=True, file_path=path, action="convert_to_aiff")


def _failure_result(path: str) -> TrackResult:
    return TrackResult(success=False, file_path=path, error="Conversion failed")


def _duplicate_result(path: str) -> TrackResult:
    return TrackResult(
        success=False,
        file_path=path,
        duplicate=True,
        action="skip_duplicate",
        error="Duplicate",
    )


class TestProcessingQueue:
    """Tests for ProcessingQueue."""

    @pytest.mark.asyncio
    async def test_batch_processes_all_files(
        self,
        queue_settings: Settings,
        mock_session_factory,
    ) -> None:
        queue = ProcessingQueue(queue_settings)
        paths = [Path("/test/a.wav"), Path("/test/b.flac"), Path("/test/c.mp3")]

        with (
            patch(
                "backend.services.queue.convert_file",
                side_effect=[
                    _success_result("/test/a.wav"),
                    _success_result("/test/b.flac"),
                    _success_result("/test/c.mp3"),
                ],
            ),
            patch("backend.services.queue.SessionLocal", mock_session_factory),
        ):
            result = await queue.process_batch(paths)

        assert result.total == 3
        assert result.succeeded == 3
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_batch_handles_failures(
        self,
        queue_settings: Settings,
        mock_session_factory,
    ) -> None:
        queue = ProcessingQueue(queue_settings)
        paths = [Path("/test/a.wav"), Path("/test/b.flac")]

        with (
            patch(
                "backend.services.queue.convert_file",
                side_effect=[
                    _success_result("/test/a.wav"),
                    _failure_result("/test/b.flac"),
                ],
            ),
            patch("backend.services.queue.SessionLocal", mock_session_factory),
        ):
            result = await queue.process_batch(paths)

        assert result.succeeded == 1
        assert result.failed == 1

    @pytest.mark.asyncio
    async def test_batch_counts_duplicates(
        self,
        queue_settings: Settings,
        mock_session_factory,
    ) -> None:
        queue = ProcessingQueue(queue_settings)
        paths = [Path("/test/a.wav"), Path("/test/b.wav")]

        with (
            patch(
                "backend.services.queue.convert_file",
                side_effect=[
                    _success_result("/test/a.wav"),
                    _duplicate_result("/test/b.wav"),
                ],
            ),
            patch("backend.services.queue.SessionLocal", mock_session_factory),
        ):
            result = await queue.process_batch(paths)

        assert result.succeeded == 1
        assert result.duplicates == 1

    @pytest.mark.asyncio
    async def test_cancellation(
        self,
        mock_session_factory,
    ) -> None:
        """Cancellation prevents remaining files from processing."""
        # Use 1 worker so cancellation is deterministic
        cancel_settings = Settings(
            max_concurrent_conversions=1,
            output_directory="/tmp/test-output",
            db_url="sqlite://",
        )
        queue = ProcessingQueue(cancel_settings)

        paths = [Path(f"/test/{i}.wav") for i in range(5)]

        call_count = 0

        def mock_convert(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                queue.cancel()
            return _success_result(str(args[0]))

        with (
            patch("backend.services.queue.convert_file", side_effect=mock_convert),
            patch("backend.services.queue.SessionLocal", mock_session_factory),
        ):
            result = await queue.process_batch(paths)

        # At least some files should be cancelled
        cancelled = [r for r in result.results if r.action == "cancelled"]
        assert len(cancelled) > 0

    @pytest.mark.asyncio
    async def test_event_generation(
        self,
        queue_settings: Settings,
        mock_session_factory,
    ) -> None:
        """SSE events are emitted for queued, processing, complete, and batch_complete."""
        queue = ProcessingQueue(queue_settings)
        paths = [Path("/test/a.wav")]

        with (
            patch(
                "backend.services.queue.convert_file",
                return_value=_success_result("/test/a.wav"),
            ),
            patch("backend.services.queue.SessionLocal", mock_session_factory),
        ):
            # Start processing in background
            import asyncio

            batch_task = asyncio.create_task(queue.process_batch(paths))

            events = []
            async for event in queue.event_generator():
                events.append(event)

            await batch_task

        event_types = [e["event"] for e in events]
        assert "file_progress" in event_types
        assert "batch_complete" in event_types

    @pytest.mark.asyncio
    async def test_is_processing_flag(
        self,
        queue_settings: Settings,
        mock_session_factory,
    ) -> None:
        queue = ProcessingQueue(queue_settings)
        assert queue.is_processing is False

        with (
            patch(
                "backend.services.queue.convert_file",
                return_value=_success_result("/test/a.wav"),
            ),
            patch("backend.services.queue.SessionLocal", mock_session_factory),
        ):
            await queue.process_batch([Path("/test/a.wav")])

        assert queue.is_processing is False
