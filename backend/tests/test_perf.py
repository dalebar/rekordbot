"""Tests for the profiling harness (backend/services/perf.py).

TDD: tests written before implementation.
"""

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import pytest


def _patch_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect Path.home() to tmp_path for the duration of the test."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)


def _perf_dir(tmp_path: Path) -> Path:
    return tmp_path / "Library" / "Application Support" / "rekordbot" / "perf"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class TestFromEnvNoOp:
    """from_env returns a NoOpPerfRecorder when the env var is unset or falsy."""

    def test_no_op_when_env_unset(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.services.perf import NoOpPerfRecorder, PerfRecorder, Stage

        monkeypatch.delenv("REKORDBOT_PERF_RECORD", raising=False)
        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder.from_env()
        assert isinstance(recorder, NoOpPerfRecorder)

        with recorder.stage(Stage.ANALYSIS_TRACK):
            pass

        perf_dir = _perf_dir(tmp_path)
        assert not perf_dir.exists() or not list(perf_dir.glob("*.jsonl"))

    @pytest.mark.parametrize("value", ["0", "false", "no", "", "anything-else"])
    def test_no_op_when_env_falsy(
        self, value: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services.perf import NoOpPerfRecorder, PerfRecorder

        monkeypatch.setenv("REKORDBOT_PERF_RECORD", value)
        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder.from_env()
        assert isinstance(recorder, NoOpPerfRecorder)


class TestFromEnvEnabled:
    """from_env returns a real PerfRecorder when the env var is truthy."""

    @pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "Yes"])
    def test_real_recorder_when_enabled(
        self, value: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services.perf import NoOpPerfRecorder, PerfRecorder

        monkeypatch.setenv("REKORDBOT_PERF_RECORD", value)
        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder.from_env()
        try:
            assert isinstance(recorder, PerfRecorder)
            assert not isinstance(recorder, NoOpPerfRecorder)
        finally:
            recorder.close()


class TestFileCreation:
    """The JSONL file is created at the expected path."""

    def test_jsonl_file_created_at_expected_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services.perf import PerfRecorder, Stage

        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder()
        try:
            with recorder.stage(Stage.ANALYSIS_TRACK):
                pass
        finally:
            recorder.close()

        perf_dir = _perf_dir(tmp_path)
        assert perf_dir.exists()
        files = list(perf_dir.glob("run-*.jsonl"))
        assert len(files) == 1


class TestRecordFields:
    """A record contains every expected field with sane values."""

    def test_record_contains_correct_fields(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services.perf import PerfRecorder, Stage

        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder()
        try:
            with recorder.stage(Stage.ANALYSIS_DETECT_BPM, payload={"track_id": 42}):
                time.sleep(0.01)
        finally:
            recorder.close()

        files = list(_perf_dir(tmp_path).glob("run-*.jsonl"))
        records = _read_jsonl(files[0])
        assert len(records) == 1
        rec = records[0]

        assert isinstance(rec["session_id"], str)
        assert re.fullmatch(r"[0-9a-f]{32}", rec["session_id"])
        assert rec["pipeline"] == "analysis"
        assert rec["stage"] == "analysis_detect_bpm"
        assert rec["start_ts"] > 0
        assert rec["duration_s"] >= 0.01
        assert rec["duration_s"] < 0.1
        assert rec["pid"] == os.getpid()
        assert rec["payload"] == {"track_id": 42}
        assert rec["error"] is None


class TestStageMappingCoverage:
    """Every Stage has a Pipeline mapping (belt-and-braces)."""

    def test_every_stage_has_pipeline_mapping(self) -> None:
        from backend.services.perf import STAGE_TO_PIPELINE, Pipeline, Stage

        for stage in Stage:
            assert stage in STAGE_TO_PIPELINE, f"Stage.{stage.name} missing from STAGE_TO_PIPELINE"
            assert isinstance(STAGE_TO_PIPELINE[stage], Pipeline)


class TestNestedStages:
    """Nested stages emit two records, inner finishes first."""

    def test_nested_stages_emit_two_records_inner_first(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services.perf import PerfRecorder, Stage

        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder()
        try:
            with recorder.stage(Stage.INGESTION_FILE):
                time.sleep(0.005)
                with recorder.stage(Stage.INGESTION_INSPECT):
                    time.sleep(0.005)
                time.sleep(0.005)
        finally:
            recorder.close()

        files = list(_perf_dir(tmp_path).glob("run-*.jsonl"))
        records = _read_jsonl(files[0])
        assert len(records) == 2

        inner, outer = records
        assert inner["stage"] == "ingestion_inspect"
        assert outer["stage"] == "ingestion_file"
        assert inner["start_ts"] >= outer["start_ts"]
        assert (
            inner["start_ts"] + inner["duration_s"]
            <= outer["start_ts"] + outer["duration_s"] + 0.01
        )


class TestExceptionInsideStage:
    """An exception inside the stage block propagates and emits an error record."""

    def test_exception_propagates_and_record_emitted(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services.perf import PerfRecorder, Stage

        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder()
        try:
            with (
                pytest.raises(ValueError, match="boom"),
                recorder.stage(Stage.ANALYSIS_DETECT_KEY),
            ):
                time.sleep(0.001)
                raise ValueError("boom")
        finally:
            recorder.close()

        files = list(_perf_dir(tmp_path).glob("run-*.jsonl"))
        records = _read_jsonl(files[0])
        assert len(records) == 1
        rec = records[0]
        assert rec["error"] == "ValueError"
        assert rec["duration_s"] > 0


class TestSessionId:
    """All records emitted by one recorder share a session_id."""

    def test_same_session_id_across_stages(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services.perf import PerfRecorder, Stage

        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder()
        try:
            for stage in (
                Stage.ANALYSIS_TRACK,
                Stage.ANALYSIS_DETECT_BPM,
                Stage.ANALYSIS_DETECT_KEY,
            ):
                with recorder.stage(stage):
                    pass
        finally:
            recorder.close()

        files = list(_perf_dir(tmp_path).glob("run-*.jsonl"))
        records = _read_jsonl(files[0])
        assert len(records) == 3
        session_ids = {r["session_id"] for r in records}
        assert len(session_ids) == 1


class TestThreadSafetyOfWrites:
    """Concurrent writes produce valid JSONL with no corruption."""

    def test_concurrent_writes_produce_valid_jsonl(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services.perf import PerfRecorder, Stage

        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder()

        def worker(idx: int) -> None:
            for j in range(50):
                with recorder.stage(Stage.ANALYSIS_TRACK, payload={"thread": idx, "iter": j}):
                    pass

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            recorder.close()

        files = list(_perf_dir(tmp_path).glob("run-*.jsonl"))
        records = _read_jsonl(files[0])
        assert len(records) == 200

        seen: set[tuple[int, int]] = set()
        for r in records:
            payload = r["payload"]
            key = (payload["thread"], payload["iter"])
            assert key not in seen, f"duplicate {key}"
            seen.add(key)
        assert len(seen) == 200


class TestSingletonThreadSafety:
    """get_recorder() returns the same instance under contention."""

    def test_get_recorder_returns_same_instance_under_contention(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services import perf

        monkeypatch.delenv("REKORDBOT_PERF_RECORD", raising=False)
        _patch_home(monkeypatch, tmp_path)
        perf._reset_for_tests()

        results: list[perf.PerfRecorder] = []
        lock = threading.Lock()

        def call() -> None:
            instance = perf.get_recorder()
            with lock:
                results.append(instance)

        threads = [threading.Thread(target=call) for _ in range(10)]
        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(results) == 10
            first = results[0]
            for r in results[1:]:
                assert r is first
        finally:
            perf._reset_for_tests()


class TestNoOpDoesNotWrite:
    """NoOpPerfRecorder.stage() never writes to disk."""

    def test_no_op_stage_no_disk_writes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services.perf import NoOpPerfRecorder, Stage

        _patch_home(monkeypatch, tmp_path)

        recorder = NoOpPerfRecorder()
        for _ in range(5):
            with recorder.stage(Stage.ANALYSIS_TRACK):
                pass

        perf_dir = _perf_dir(tmp_path)
        assert not perf_dir.exists() or not list(perf_dir.glob("*.jsonl"))


class TestCloseIdempotent:
    """close() can be called repeatedly without error."""

    def test_close_is_idempotent(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from backend.services.perf import PerfRecorder

        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder()
        recorder.close()
        recorder.close()


class TestFilenameFormat:
    """Output filename uses an ISO-ish timestamp."""

    def test_filename_uses_iso_timestamp(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services.perf import PerfRecorder

        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder()
        try:
            files = list(_perf_dir(tmp_path).glob("*.jsonl"))
            assert len(files) == 1
            assert re.fullmatch(r"run-\d{8}T\d{6}\.jsonl", files[0].name)
        finally:
            recorder.close()


class TestPayloadNoneSerialised:
    """payload=None is serialised as null, not omitted."""

    def test_payload_none_serialised_as_null(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.services.perf import PerfRecorder, Stage

        _patch_home(monkeypatch, tmp_path)

        recorder = PerfRecorder()
        try:
            with recorder.stage(Stage.ANALYSIS_TRACK):
                pass
        finally:
            recorder.close()

        files = list(_perf_dir(tmp_path).glob("*.jsonl"))
        line = files[0].read_text().splitlines()[0]
        parsed = json.loads(line)
        assert "payload" in parsed
        assert parsed["payload"] is None
