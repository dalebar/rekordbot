"""Tests for the performance reporting module (backend/services/perf_report.py).

TDD: tests written before implementation.
"""

import json
import logging
import statistics
from pathlib import Path

import pytest

from backend.services.perf import PerfRecord
from backend.services.perf_report import (
    OUTER_STAGE_FOR_PIPELINE,
    FullReport,
    PipelineReport,
    StageStats,
    build_full_report,
    build_pipeline_report,
    compute_rate_limit_wait,
    compute_stage_shares,
    compute_stage_stats,
    group_by_pipeline,
    group_by_stage,
    load_records,
    render_markdown,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "perf"


def _rec(
    *,
    stage: str,
    pipeline: str,
    duration_s: float,
    start_ts: float = 1779065000.0,
    session_id: str = "0" * 32,
    pid: int = 12345,
    payload: dict[str, object] | None = None,
    error: str | None = None,
) -> PerfRecord:
    """Helper to build a PerfRecord with sensible defaults."""
    return PerfRecord(
        session_id=session_id,
        pipeline=pipeline,
        stage=stage,
        start_ts=start_ts,
        duration_s=duration_s,
        pid=pid,
        payload=payload,
        error=error,
    )


# --- A. compute_stage_stats ---


class TestComputeStageStats:
    """Aggregate stats over duration samples."""

    def test_percentiles_populated_when_count_ten(self) -> None:
        durations = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        result = compute_stage_stats(durations)
        assert result.count == 10
        assert result.p50_s is not None
        assert result.p95_s is not None

    def test_percentiles_none_when_count_below_ten(self) -> None:
        durations = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        result = compute_stage_stats(durations)
        assert result.count == 9
        assert result.p50_s is None
        assert result.p95_s is None

    def test_single_sample_stats(self) -> None:
        result = compute_stage_stats([0.42])
        assert result.count == 1
        assert result.total_s == pytest.approx(0.42)
        assert result.mean_s == pytest.approx(0.42)
        assert result.min_s == pytest.approx(0.42)
        assert result.max_s == pytest.approx(0.42)
        assert result.p50_s is None
        assert result.p95_s is None

    def test_empty_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            compute_stage_stats([])

    def test_hand_calculable_input(self) -> None:
        durations = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        result = compute_stage_stats(durations)
        assert result.total_s == pytest.approx(5.5)
        assert result.mean_s == pytest.approx(0.55)
        assert result.min_s == pytest.approx(0.1)
        assert result.max_s == pytest.approx(1.0)
        # Match the exact statistics.quantiles output the implementation uses.
        cuts = statistics.quantiles(durations, n=100, method="inclusive")
        assert result.p50_s == pytest.approx(cuts[49])
        assert result.p95_s == pytest.approx(cuts[94])


# --- B. group_by_pipeline / group_by_stage ---


class TestGroupByPipeline:
    """Group records by pipeline."""

    def test_empty_input_empty_dict(self) -> None:
        assert group_by_pipeline([]) == {}

    def test_single_pipeline_one_key(self) -> None:
        records = [_rec(stage="ingestion_file", pipeline="ingestion", duration_s=0.1)]
        groups = group_by_pipeline(records)
        assert list(groups.keys()) == ["ingestion"]
        assert len(groups["ingestion"]) == 1

    def test_multiple_pipelines_preserve_first_appearance_order(self) -> None:
        records = [
            _rec(stage="ingestion_file", pipeline="ingestion", duration_s=0.1),
            _rec(stage="analysis_track", pipeline="analysis", duration_s=10.0),
            _rec(stage="xml_export", pipeline="xml_export", duration_s=0.5),
            _rec(stage="ingestion_inspect", pipeline="ingestion", duration_s=0.05),
        ]
        groups = group_by_pipeline(records)
        assert list(groups.keys()) == ["ingestion", "analysis", "xml_export"]
        assert len(groups["ingestion"]) == 2


class TestGroupByStage:
    """Group records by stage."""

    def test_empty_input_empty_dict(self) -> None:
        assert group_by_stage([]) == {}

    def test_same_stage_across_pipelines_merged(self) -> None:
        records = [
            _rec(stage="foo", pipeline="alpha", duration_s=0.1),
            _rec(stage="foo", pipeline="beta", duration_s=0.2),
        ]
        groups = group_by_stage(records)
        assert list(groups.keys()) == ["foo"]
        assert len(groups["foo"]) == 2


# --- C. compute_stage_shares ---


class TestComputeStageShares:
    """Inner-stage mean as a share of outer-stage mean."""

    def test_ingestion_share_simple(self) -> None:
        records = [
            _rec(stage="ingestion_file", pipeline="ingestion", duration_s=1.0) for _ in range(10)
        ] + [
            _rec(stage="ingestion_inspect", pipeline="ingestion", duration_s=0.1)
            for _ in range(10)
        ]
        shares = compute_stage_shares(records, "ingestion")
        assert shares is not None
        assert shares["ingestion_inspect"] == pytest.approx(0.1)
        assert "ingestion_file" not in shares

    def test_pipeline_not_in_outer_returns_none(self) -> None:
        records = [_rec(stage="xml_export", pipeline="xml_export", duration_s=0.5)]
        assert compute_stage_shares(records, "xml_export") is None

    def test_outer_stage_zero_records_returns_none(self) -> None:
        records = [
            _rec(stage="ingestion_inspect", pipeline="ingestion", duration_s=0.05),
        ]
        # No ingestion_file outer records → cannot compute shares.
        assert compute_stage_shares(records, "ingestion") is None


# --- D. compute_rate_limit_wait ---


class TestComputeRateLimitWait:
    """Estimate rate-limiter wait time per batch."""

    def test_basic_wait_calculation(self) -> None:
        sid = "abc" * 10 + "ab"  # 32 chars
        batch_start = 1779065000.0
        records = [
            _rec(
                stage="ai_tag_batch",
                pipeline="ai_tagging",
                start_ts=batch_start,
                duration_s=5.0,
                session_id=sid,
                payload={"batch_number": 1, "batch_size": 20},
            ),
            _rec(
                stage="ai_tag_build_message",
                pipeline="ai_tagging",
                start_ts=batch_start + 0.1,
                duration_s=0.5,
                session_id=sid,
            ),
            _rec(
                stage="ai_tag_api_call",
                pipeline="ai_tagging",
                start_ts=batch_start + 0.6,
                duration_s=2.5,
                session_id=sid,
            ),
            _rec(
                stage="ai_tag_db_update",
                pipeline="ai_tagging",
                start_ts=batch_start + 3.1,
                duration_s=0.5,
                session_id=sid,
            ),
        ]
        waits = compute_rate_limit_wait(records)
        assert waits == {(sid, 1): pytest.approx(1.5)}

    def test_inner_outside_window_excluded(self) -> None:
        sid = "f" * 32
        batch_start = 1779065000.0
        records = [
            _rec(
                stage="ai_tag_batch",
                pipeline="ai_tagging",
                start_ts=batch_start,
                duration_s=1.0,
                session_id=sid,
                payload={"batch_number": 7, "batch_size": 20},
            ),
            # Inside window.
            _rec(
                stage="ai_tag_api_call",
                pipeline="ai_tagging",
                start_ts=batch_start + 0.5,
                duration_s=0.4,
                session_id=sid,
            ),
            # Outside window — should be excluded.
            _rec(
                stage="ai_tag_api_call",
                pipeline="ai_tagging",
                start_ts=batch_start + 2.0,
                duration_s=0.4,
                session_id=sid,
            ),
        ]
        waits = compute_rate_limit_wait(records)
        assert waits[(sid, 7)] == pytest.approx(0.6)

    def test_negative_result_clamps_to_zero(self) -> None:
        sid = "e" * 32
        records = [
            _rec(
                stage="ai_tag_batch",
                pipeline="ai_tagging",
                start_ts=1779065000.0,
                duration_s=1.0,
                session_id=sid,
                payload={"batch_number": 1, "batch_size": 20},
            ),
            # Inner stage with duration exceeding the outer's. Measurement noise.
            _rec(
                stage="ai_tag_api_call",
                pipeline="ai_tagging",
                start_ts=1779065000.1,
                duration_s=1.5,
                session_id=sid,
            ),
        ]
        waits = compute_rate_limit_wait(records)
        assert waits[(sid, 1)] == 0.0

    def test_no_batches_returns_empty_dict(self) -> None:
        records = [_rec(stage="ai_tag_api_call", pipeline="ai_tagging", duration_s=1.0)]
        assert compute_rate_limit_wait(records) == {}

    def test_different_session_excluded(self) -> None:
        sid_a = "a" * 32
        sid_b = "b" * 32
        records = [
            _rec(
                stage="ai_tag_batch",
                pipeline="ai_tagging",
                start_ts=1779065000.0,
                duration_s=2.0,
                session_id=sid_a,
                payload={"batch_number": 1, "batch_size": 20},
            ),
            # Inside time window but different session.
            _rec(
                stage="ai_tag_api_call",
                pipeline="ai_tagging",
                start_ts=1779065000.5,
                duration_s=1.0,
                session_id=sid_b,
            ),
        ]
        waits = compute_rate_limit_wait(records)
        # Inner from session B excluded → wait is full 2.0s.
        assert waits[(sid_a, 1)] == pytest.approx(2.0)


# --- E. load_records ---


class TestLoadRecords:
    """JSONL parsing with malformed-line tolerance."""

    def test_valid_jsonl_loads(self, tmp_path: Path) -> None:
        path = tmp_path / "valid.jsonl"
        path.write_text(
            json.dumps(
                {
                    "session_id": "a" * 32,
                    "pipeline": "ingestion",
                    "stage": "ingestion_file",
                    "start_ts": 1.0,
                    "duration_s": 0.5,
                    "pid": 99,
                    "payload": None,
                    "error": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        records = load_records(path)
        assert len(records) == 1
        assert records[0].stage == "ingestion_file"

    def test_empty_file_returns_empty_list(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        assert load_records(path) == []

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_records(tmp_path / "does-not-exist.jsonl")

    def test_malformed_line_skipped_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "mixed.jsonl"
        path.write_text(
            json.dumps(
                {
                    "session_id": "a" * 32,
                    "pipeline": "ingestion",
                    "stage": "ingestion_file",
                    "start_ts": 1.0,
                    "duration_s": 0.5,
                    "pid": 99,
                    "payload": None,
                    "error": None,
                }
            )
            + "\n"
            + "this is not JSON\n"
            + json.dumps(
                {
                    "session_id": "b" * 32,
                    "pipeline": "analysis",
                    "stage": "analysis_track",
                    "start_ts": 2.0,
                    "duration_s": 1.5,
                    "pid": 99,
                    "payload": None,
                    "error": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        with caplog.at_level(logging.WARNING, logger="backend.services.perf_report"):
            records = load_records(path)
        assert len(records) == 2
        assert records[0].stage == "ingestion_file"
        assert records[1].stage == "analysis_track"
        assert any("malformed line" in msg.lower() for msg in caplog.messages)


# --- F. build_full_report ---


class TestBuildFullReport:
    """Top-level report assembly."""

    def test_empty_records(self) -> None:
        report = build_full_report([], Path("/dev/null"))
        assert report.total_records == 0
        assert report.session_ids == []
        assert report.run_start is None
        assert report.run_end is None
        assert report.wall_clock_span_s is None
        assert report.pipeline_reports == []
        assert report.rate_limit_waits == {}
        assert report.errors == []

    def test_single_ingestion_record(self) -> None:
        records = [
            _rec(stage="ingestion_file", pipeline="ingestion", duration_s=0.5, start_ts=100.0)
        ]
        report = build_full_report(records, Path("/dev/null"))
        assert report.total_records == 1
        assert report.run_start == pytest.approx(100.0)
        assert report.run_end == pytest.approx(100.5)
        assert report.wall_clock_span_s == pytest.approx(0.5)
        assert len(report.pipeline_reports) == 1
        pr = report.pipeline_reports[0]
        assert pr.pipeline_name == "ingestion"
        assert "ingestion_file" in pr.stage_stats

    def test_records_with_errors_populates_errors_field(self) -> None:
        records = [
            _rec(stage="ingestion_file", pipeline="ingestion", duration_s=0.5),
            _rec(
                stage="ingestion_inspect",
                pipeline="ingestion",
                duration_s=0.05,
                error="RuntimeError",
            ),
        ]
        report = build_full_report(records, Path("/dev/null"))
        assert len(report.errors) == 1
        assert report.errors[0].error == "RuntimeError"


# --- G. render_markdown — golden file tests ---


def _golden_test(fixture_name: str, *, update_golden: bool, synthetic_path: str) -> None:
    """Shared body for both golden-file tests."""
    jsonl_path = FIXTURE_DIR / f"{fixture_name}.jsonl"
    golden_path = FIXTURE_DIR / f"{fixture_name}.expected.md"

    records = load_records(jsonl_path)
    report = build_full_report(records, Path(synthetic_path))
    actual = render_markdown(report)

    if update_golden:
        golden_path.write_text(actual, encoding="utf-8")
        return

    expected = golden_path.read_text(encoding="utf-8")
    # Compare line-by-line for better diff output on failure.
    assert actual.splitlines() == expected.splitlines()


class TestRenderMarkdownGolden:
    """Markdown rendering against committed golden files.

    Run ``uv run pytest backend/tests/test_perf_report.py --update-golden``
    to regenerate the golden files after intentional output changes.
    """

    def test_small_run_golden(self, update_golden: bool) -> None:
        _golden_test(
            "sample-run-small",
            update_golden=update_golden,
            synthetic_path="/fixtures/sample-run-small.jsonl",
        )

    def test_full_run_golden(self, update_golden: bool) -> None:
        _golden_test(
            "sample-run-full",
            update_golden=update_golden,
            synthetic_path="/fixtures/sample-run-full.jsonl",
        )


# --- Smoke tests on dataclass identities (defensive against import drift) ---


class TestPublicAPISurface:
    """Belt-and-braces: dataclasses and constants are exported as expected."""

    def test_outer_stage_map_known_pipelines(self) -> None:
        assert OUTER_STAGE_FOR_PIPELINE["ingestion"] == "ingestion_file"
        assert OUTER_STAGE_FOR_PIPELINE["analysis"] == "analysis_track"
        assert OUTER_STAGE_FOR_PIPELINE["ai_tagging"] == "ai_tag_batch"
        assert "xml_export" not in OUTER_STAGE_FOR_PIPELINE
        assert "xml_import" not in OUTER_STAGE_FOR_PIPELINE

    def test_dataclass_field_names(self) -> None:
        # If these break, downstream consumers break — fail loud.
        ss = StageStats(
            count=1,
            total_s=0.0,
            mean_s=0.0,
            min_s=0.0,
            max_s=0.0,
            p50_s=None,
            p95_s=None,
        )
        pr = PipelineReport(pipeline_name="x", stage_stats={}, stage_shares=None, total_records=0)
        fr = FullReport(
            source_path="x",
            session_ids=[],
            total_records=0,
            run_start=None,
            run_end=None,
            wall_clock_span_s=None,
            pipeline_reports=[],
            rate_limit_waits={},
        )
        assert ss.count == 1
        assert pr.pipeline_name == "x"
        assert fr.source_path == "x"

    def test_build_pipeline_report_returns_pipeline_report(self) -> None:
        records = [_rec(stage="xml_export", pipeline="xml_export", duration_s=0.5)]
        pr = build_pipeline_report(records, "xml_export")
        assert isinstance(pr, PipelineReport)
        assert pr.total_records == 1
        assert pr.stage_shares is None
