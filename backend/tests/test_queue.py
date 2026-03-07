"""Tests for processing queue — concurrency, error handling, cancellation."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

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
def mock_session():
    """Mock SQLAlchemy session."""
    from unittest.mock import MagicMock

    return MagicMock()


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
        mock_session,
    ) -> None:
        queue = ProcessingQueue(queue_settings)
        paths = [Path("/test/a.wav"), Path("/test/b.flac"), Path("/test/c.mp3")]

        with patch(
            "backend.services.queue.convert_file",
            new_callable=AsyncMock,
            side_effect=[
                _success_result("/test/a.wav"),
                _success_result("/test/b.flac"),
                _success_result("/test/c.mp3"),
            ],
        ):
            result = await queue.process_batch(paths, mock_session)

        assert result.total == 3
        assert result.succeeded == 3
        assert result.failed == 0

    @pytest.mark.asyncio
    async def test_batch_handles_failures(
        self,
        queue_settings: Settings,
        mock_session,
    ) -> None:
        queue = ProcessingQueue(queue_settings)
        paths = [Path("/test/a.wav"), Path("/test/b.flac")]

        with patch(
            "backend.services.queue.convert_file",
            new_callable=AsyncMock,
            side_effect=[
                _success_result("/test/a.wav"),
                _failure_result("/test/b.flac"),
            ],
        ):
            result = await queue.process_batch(paths, mock_session)

        assert result.succeeded == 1
        assert result.failed == 1

    @pytest.mark.asyncio
    async def test_batch_counts_duplicates(
        self,
        queue_settings: Settings,
        mock_session,
    ) -> None:
        queue = ProcessingQueue(queue_settings)
        paths = [Path("/test/a.wav"), Path("/test/b.wav")]

        with patch(
            "backend.services.queue.convert_file",
            new_callable=AsyncMock,
            side_effect=[
                _success_result("/test/a.wav"),
                _duplicate_result("/test/b.wav"),
            ],
        ):
            result = await queue.process_batch(paths, mock_session)

        assert result.succeeded == 1
        assert result.duplicates == 1

    @pytest.mark.asyncio
    async def test_cancellation(
        self,
        queue_settings: Settings,
        mock_session,
    ) -> None:
        """Cancellation prevents remaining files from processing."""
        queue = ProcessingQueue(queue_settings)
        queue_settings.max_concurrent_conversions = 1
        queue._semaphore = __import__("asyncio").Semaphore(1)

        paths = [Path(f"/test/{i}.wav") for i in range(5)]

        call_count = 0

        async def mock_convert(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                queue.cancel()
            return _success_result(str(args[0]))

        with patch("backend.services.queue.convert_file", side_effect=mock_convert):
            result = await queue.process_batch(paths, mock_session)

        # At least some files should be cancelled
        cancelled = [r for r in result.results if r.action == "cancelled"]
        assert len(cancelled) > 0

    @pytest.mark.asyncio
    async def test_event_generation(
        self,
        queue_settings: Settings,
        mock_session,
    ) -> None:
        """SSE events are emitted for queued, processing, complete, and batch_complete."""
        queue = ProcessingQueue(queue_settings)
        paths = [Path("/test/a.wav")]

        with patch(
            "backend.services.queue.convert_file",
            new_callable=AsyncMock,
            return_value=_success_result("/test/a.wav"),
        ):
            # Start processing in background
            import asyncio

            batch_task = asyncio.create_task(queue.process_batch(paths, mock_session))

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
        mock_session,
    ) -> None:
        queue = ProcessingQueue(queue_settings)
        assert queue.is_processing is False

        with patch(
            "backend.services.queue.convert_file",
            new_callable=AsyncMock,
            return_value=_success_result("/test/a.wav"),
        ):
            await queue.process_batch([Path("/test/a.wav")], mock_session)

        assert queue.is_processing is False
