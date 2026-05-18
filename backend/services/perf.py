"""Profiling harness — opt-in performance recorder.

Provides a context-manager-based timing recorder that writes JSONL records
to disk when the ``REKORDBOT_PERF_RECORD`` env var is enabled, and is a
complete no-op otherwise.

The recorder is process-wide (accessed via :func:`get_recorder`). All
records emitted by one recorder instance share the same ``session_id``.

Output path::

    ~/Library/Application Support/rekordbot/perf/run-<timestamp>.jsonl

One JSON object per line. See :class:`PerfRecord` for the schema.
"""

import contextlib
import json
import logging
import os
import threading
import time
import uuid
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, TextIO

logger = logging.getLogger(__name__)


class Stage(StrEnum):
    """Pipeline stage identifiers for timing records."""

    # Ingestion
    INGESTION_FILE = "ingestion_file"
    INGESTION_INSPECT = "ingestion_inspect"
    INGESTION_DECIDE = "ingestion_decide"
    INGESTION_HASH = "ingestion_hash"
    INGESTION_DUP_CHECK = "ingestion_dup_check"
    INGESTION_CONVERT_FFMPEG = "ingestion_convert_ffmpeg"
    INGESTION_COPY = "ingestion_copy"
    INGESTION_DB_INSERT = "ingestion_db_insert"

    # Analysis
    ANALYSIS_TRACK = "analysis_track"
    ANALYSIS_READ_TAGS = "analysis_read_tags"
    ANALYSIS_LIBROSA_LOAD = "analysis_librosa_load"
    ANALYSIS_DETECT_BPM = "analysis_detect_bpm"
    ANALYSIS_DETECT_KEY = "analysis_detect_key"
    ANALYSIS_DB_UPDATE = "analysis_db_update"

    # AI tagging
    AI_TAG_BATCH = "ai_tag_batch"
    AI_TAG_BUILD_MESSAGE = "ai_tag_build_message"
    AI_TAG_API_CALL = "ai_tag_api_call"
    AI_TAG_PARSE_RESPONSE = "ai_tag_parse_response"
    AI_TAG_DB_UPDATE = "ai_tag_db_update"

    # XML export
    XML_EXPORT = "xml_export"
    XML_EXPORT_LOAD_TRACKS = "xml_export_load_tracks"
    XML_EXPORT_LOAD_CRATES = "xml_export_load_crates"
    XML_EXPORT_LOAD_SETS = "xml_export_load_sets"
    XML_EXPORT_BUILD = "xml_export_build"
    XML_EXPORT_WRITE = "xml_export_write"

    # XML import
    XML_IMPORT = "xml_import"
    XML_IMPORT_PARSE = "xml_import_parse"
    XML_IMPORT_TRACKS = "xml_import_tracks"
    XML_IMPORT_PLAYLISTS = "xml_import_playlists"
    XML_IMPORT_COMMIT = "xml_import_commit"


class Pipeline(StrEnum):
    """Top-level pipeline identifiers."""

    INGESTION = "ingestion"
    ANALYSIS = "analysis"
    AI_TAGGING = "ai_tagging"
    XML_EXPORT = "xml_export"
    XML_IMPORT = "xml_import"


STAGE_TO_PIPELINE: dict[Stage, Pipeline] = {
    # Ingestion
    Stage.INGESTION_FILE: Pipeline.INGESTION,
    Stage.INGESTION_INSPECT: Pipeline.INGESTION,
    Stage.INGESTION_DECIDE: Pipeline.INGESTION,
    Stage.INGESTION_HASH: Pipeline.INGESTION,
    Stage.INGESTION_DUP_CHECK: Pipeline.INGESTION,
    Stage.INGESTION_CONVERT_FFMPEG: Pipeline.INGESTION,
    Stage.INGESTION_COPY: Pipeline.INGESTION,
    Stage.INGESTION_DB_INSERT: Pipeline.INGESTION,
    # Analysis
    Stage.ANALYSIS_TRACK: Pipeline.ANALYSIS,
    Stage.ANALYSIS_READ_TAGS: Pipeline.ANALYSIS,
    Stage.ANALYSIS_LIBROSA_LOAD: Pipeline.ANALYSIS,
    Stage.ANALYSIS_DETECT_BPM: Pipeline.ANALYSIS,
    Stage.ANALYSIS_DETECT_KEY: Pipeline.ANALYSIS,
    Stage.ANALYSIS_DB_UPDATE: Pipeline.ANALYSIS,
    # AI tagging
    Stage.AI_TAG_BATCH: Pipeline.AI_TAGGING,
    Stage.AI_TAG_BUILD_MESSAGE: Pipeline.AI_TAGGING,
    Stage.AI_TAG_API_CALL: Pipeline.AI_TAGGING,
    Stage.AI_TAG_PARSE_RESPONSE: Pipeline.AI_TAGGING,
    Stage.AI_TAG_DB_UPDATE: Pipeline.AI_TAGGING,
    # XML export
    Stage.XML_EXPORT: Pipeline.XML_EXPORT,
    Stage.XML_EXPORT_LOAD_TRACKS: Pipeline.XML_EXPORT,
    Stage.XML_EXPORT_LOAD_CRATES: Pipeline.XML_EXPORT,
    Stage.XML_EXPORT_LOAD_SETS: Pipeline.XML_EXPORT,
    Stage.XML_EXPORT_BUILD: Pipeline.XML_EXPORT,
    Stage.XML_EXPORT_WRITE: Pipeline.XML_EXPORT,
    # XML import
    Stage.XML_IMPORT: Pipeline.XML_IMPORT,
    Stage.XML_IMPORT_PARSE: Pipeline.XML_IMPORT,
    Stage.XML_IMPORT_TRACKS: Pipeline.XML_IMPORT,
    Stage.XML_IMPORT_PLAYLISTS: Pipeline.XML_IMPORT,
    Stage.XML_IMPORT_COMMIT: Pipeline.XML_IMPORT,
}


@dataclass
class PerfRecord:
    """A single timing record.

    Field order is the JSONL serialisation order (preserved by
    ``dataclasses.asdict`` and ``json.dumps``).
    """

    session_id: str
    pipeline: str
    stage: str
    start_ts: float
    duration_s: float
    pid: int
    payload: dict[str, Any] | None = None
    error: str | None = None


class _StageContext:
    """Context manager that times a stage block and emits a PerfRecord."""

    def __init__(
        self,
        recorder: "PerfRecorder",
        stage: Stage,
        payload: dict[str, Any] | None,
    ) -> None:
        self._recorder = recorder
        self._stage = stage
        self._payload = payload
        self._start_ts: float = 0.0
        self._start_perf: float = 0.0
        self._pid: int = 0

    def __enter__(self) -> None:
        self._start_ts = time.time()
        self._start_perf = time.perf_counter()
        self._pid = os.getpid()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        duration = time.perf_counter() - self._start_perf
        error_name = exc_type.__name__ if exc_type is not None else None
        record = PerfRecord(
            session_id=self._recorder.session_id,
            pipeline=STAGE_TO_PIPELINE[self._stage].value,
            stage=self._stage.value,
            start_ts=self._start_ts,
            duration_s=duration,
            pid=self._pid,
            payload=self._payload,
            error=error_name,
        )
        self._recorder._write(record)
        return False


class PerfRecorder:
    """Records performance timings to a JSONL file.

    One file per recorder instance, opened in append mode at construction.
    Writes are serialised by an internal lock so the file remains
    well-formed JSONL even under concurrent ``stage()`` calls from many
    threads.
    """

    def __init__(self) -> None:
        """Open the JSONL output file and generate a session id."""
        self.session_id: str = uuid.uuid4().hex
        perf_dir = Path.home() / "Library" / "Application Support" / "rekordbot" / "perf"
        perf_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        self._path: Path = perf_dir / f"run-{timestamp}.jsonl"
        self._lock = threading.Lock()
        # File handle is long-lived for the recorder's lifetime and closed in close().
        self._file: TextIO | None = open(self._path, "a", encoding="utf-8")  # noqa: SIM115
        logger.info("PerfRecorder writing to %s (session %s)", self._path, self.session_id)

    @classmethod
    def from_env(cls) -> "PerfRecorder":
        """Construct a recorder based on the ``REKORDBOT_PERF_RECORD`` env var.

        Returns:
            A real :class:`PerfRecorder` when the env var is ``"1"``,
            ``"true"``, or ``"yes"`` (case-insensitive). Otherwise a
            :class:`NoOpPerfRecorder`.
        """
        value = os.getenv("REKORDBOT_PERF_RECORD", "")
        if value.strip().lower() in {"1", "true", "yes"}:
            return cls()
        return NoOpPerfRecorder()

    def stage(
        self,
        stage: Stage,
        payload: dict[str, Any] | None = None,
    ) -> AbstractContextManager[None]:
        """Time a code block and emit a :class:`PerfRecord` on exit.

        Args:
            stage: The :class:`Stage` being timed.
            payload: Optional dict of extra context to attach to the record.

        Returns:
            A context manager that records the wrapped block's duration.
        """
        return _StageContext(self, stage, payload)

    def _write(self, record: PerfRecord) -> None:
        """Serialise and append a single record to the JSONL file."""
        line = json.dumps(asdict(record)) + "\n"
        with self._lock:
            if self._file is None:
                return
            self._file.write(line)
            self._file.flush()

    def close(self) -> None:
        """Close the JSONL file handle. Idempotent."""
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


class NoOpPerfRecorder(PerfRecorder):
    """No-op recorder. Same public API as :class:`PerfRecorder`, no I/O.

    Returned by :meth:`PerfRecorder.from_env` when the profiling env var
    is unset or falsy. ``stage()`` returns a null context manager;
    ``close()`` does nothing.
    """

    def __init__(self) -> None:
        """Generate a session id without touching the filesystem."""
        # Intentionally does not call ``super().__init__()`` — the no-op
        # recorder must not create directories or open files.
        self.session_id = uuid.uuid4().hex
        self._lock = threading.Lock()
        self._file = None

    def stage(
        self,
        stage: Stage,
        payload: dict[str, Any] | None = None,
    ) -> AbstractContextManager[None]:
        """Return a no-op context manager that performs no I/O."""
        return contextlib.nullcontext()

    def close(self) -> None:
        """No-op."""
        return None


_recorder: PerfRecorder | None = None
_recorder_init_lock = threading.Lock()


def get_recorder() -> PerfRecorder:
    """Return the process-wide :class:`PerfRecorder` singleton.

    Lazily constructed via :meth:`PerfRecorder.from_env` on first call.
    Uses double-checked locking for thread-safe initialisation.
    """
    global _recorder
    if _recorder is None:
        with _recorder_init_lock:
            if _recorder is None:
                _recorder = PerfRecorder.from_env()
    return _recorder


def _reset_for_tests() -> None:
    """Reset the singleton. For tests only."""
    global _recorder
    if _recorder is not None:
        _recorder.close()
    _recorder = None
