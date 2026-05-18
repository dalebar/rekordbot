"""Reporting helpers for rekordbot performance profiling.

Reads JSONL records produced by :mod:`backend.services.perf` and produces
typed report dataclasses plus a markdown renderer. All functions in this
module are pure transforms except :func:`load_records`, which reads a
file from disk.

The CLI entry point at ``scripts/perf-report.py`` is a thin wrapper that
parses argv and writes the rendered markdown to a file.
"""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from backend.services.perf import PerfRecord

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# Pipelines that have a single outer stage wrapping each "unit of work".
# Used by the share-of-outer-mean calculation. xml_export and xml_import
# do not appear here — their outer stage IS the whole pipeline, recorded
# once per run rather than per unit.
OUTER_STAGE_FOR_PIPELINE: dict[str, str] = {
    "ingestion": "ingestion_file",
    "analysis": "analysis_track",
    "ai_tagging": "ai_tag_batch",
}

# Inner stages used by compute_rate_limit_wait to detect untimed gaps
# inside an ai_tag_batch context.
_AI_TAG_INNER_STAGES: frozenset[str] = frozenset(
    {
        "ai_tag_build_message",
        "ai_tag_api_call",
        "ai_tag_parse_response",
        "ai_tag_db_update",
    }
)

# Count threshold below which percentile calculation is omitted as not
# meaningful enough to publish.
_PERCENTILE_MIN_COUNT = 10


@dataclass
class StageStats:
    """Aggregate statistics for one stage's duration samples."""

    count: int
    total_s: float
    mean_s: float
    min_s: float
    max_s: float
    p50_s: float | None
    p95_s: float | None


@dataclass
class PipelineReport:
    """Per-pipeline rollup."""

    pipeline_name: str
    stage_stats: dict[str, StageStats]
    stage_shares: dict[str, float] | None
    total_records: int


@dataclass
class FullReport:
    """Top-level report over an entire JSONL file."""

    source_path: str
    session_ids: list[str]
    total_records: int
    run_start: float | None
    run_end: float | None
    wall_clock_span_s: float | None
    pipeline_reports: list[PipelineReport]
    rate_limit_waits: dict[tuple[str, int], float]
    errors: list[PerfRecord] = field(default_factory=list)


def load_records(path: Path) -> list[PerfRecord]:
    """Load and parse PerfRecord entries from a JSONL file.

    Args:
        path: Path to the JSONL file.

    Returns:
        List of parsed :class:`PerfRecord` instances. Malformed lines are
        skipped with a warning to stderr.

    Raises:
        FileNotFoundError: If ``path`` does not exist.
    """
    if not path.exists():
        raise FileNotFoundError(path)

    records: list[PerfRecord] = []
    with path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                records.append(PerfRecord(**data))
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Skipping malformed line %d in %s: %s", lineno, path, e)
    return records


def group_by_pipeline(records: list[PerfRecord]) -> dict[str, list[PerfRecord]]:
    """Group records by their pipeline field, preserving first-appearance order."""
    groups: dict[str, list[PerfRecord]] = {}
    for r in records:
        groups.setdefault(r.pipeline, []).append(r)
    return groups


def group_by_stage(records: list[PerfRecord]) -> dict[str, list[PerfRecord]]:
    """Group records by their stage field, preserving first-appearance order."""
    groups: dict[str, list[PerfRecord]] = {}
    for r in records:
        groups.setdefault(r.stage, []).append(r)
    return groups


def compute_stage_stats(durations: list[float]) -> StageStats:
    """Aggregate stats over a stage's duration samples.

    Percentiles are computed only when there are at least
    :data:`_PERCENTILE_MIN_COUNT` (10) samples, otherwise None.

    Args:
        durations: Duration samples in seconds. Must be non-empty.

    Returns:
        A :class:`StageStats` instance.

    Raises:
        ValueError: If ``durations`` is empty.
    """
    if not durations:
        raise ValueError("Cannot compute stage stats over empty durations list")
    count = len(durations)
    total = sum(durations)
    mean = total / count
    mn = min(durations)
    mx = max(durations)
    if count >= _PERCENTILE_MIN_COUNT:
        cuts = statistics.quantiles(durations, n=100, method="inclusive")
        p50: float | None = cuts[49]
        p95: float | None = cuts[94]
    else:
        p50 = None
        p95 = None
    return StageStats(
        count=count,
        total_s=total,
        mean_s=mean,
        min_s=mn,
        max_s=mx,
        p50_s=p50,
        p95_s=p95,
    )


def compute_stage_shares(
    pipeline_records: list[PerfRecord], pipeline_name: str
) -> dict[str, float] | None:
    """Compute inner-stage mean as a share of outer-stage mean.

    Args:
        pipeline_records: All records for one pipeline.
        pipeline_name: The pipeline name (e.g. "ingestion").

    Returns:
        Dict mapping inner stage name to share (0.0–1.0 range). The outer
        stage itself is excluded. Returns None if the pipeline has no
        designated outer stage, or if the outer stage has zero records.
    """
    outer_stage = OUTER_STAGE_FOR_PIPELINE.get(pipeline_name)
    if outer_stage is None:
        return None
    by_stage = group_by_stage(pipeline_records)
    outer_records = by_stage.get(outer_stage)
    if not outer_records:
        return None
    outer_mean = sum(r.duration_s for r in outer_records) / len(outer_records)
    if outer_mean == 0:
        return None
    shares: dict[str, float] = {}
    for stage_name, recs in by_stage.items():
        if stage_name == outer_stage or not recs:
            continue
        inner_mean = sum(r.duration_s for r in recs) / len(recs)
        shares[stage_name] = inner_mean / outer_mean
    return shares


def compute_rate_limit_wait(
    ai_tag_records: list[PerfRecord],
) -> dict[tuple[str, int], float]:
    """Estimate per-batch rate-limit wait time.

    For each ``ai_tag_batch`` record, finds inner-stage records within
    the batch's [start, end] window with matching session_id, sums their
    durations, and returns (batch duration − inner sum). Clamps to 0 to
    absorb measurement noise.

    Args:
        ai_tag_records: All records for the ai_tagging pipeline.

    Returns:
        Dict keyed by (session_id, batch_number) with wait time in
        seconds. Empty when no ``ai_tag_batch`` records are present or
        none carry a ``batch_number`` payload.
    """
    waits: dict[tuple[str, int], float] = {}
    batches = [r for r in ai_tag_records if r.stage == "ai_tag_batch"]
    if not batches:
        return waits

    inner_candidates = [r for r in ai_tag_records if r.stage in _AI_TAG_INNER_STAGES]

    for batch in batches:
        if batch.payload is None or "batch_number" not in batch.payload:
            continue
        batch_num = batch.payload["batch_number"]
        if not isinstance(batch_num, int):
            continue
        window_start = batch.start_ts
        window_end = batch.start_ts + batch.duration_s

        inner_sum = 0.0
        for inner in inner_candidates:
            if inner.session_id != batch.session_id:
                continue
            if window_start <= inner.start_ts <= window_end:
                inner_sum += inner.duration_s

        wait = max(0.0, batch.duration_s - inner_sum)
        waits[(batch.session_id, batch_num)] = wait

    return waits


def build_pipeline_report(
    pipeline_records: list[PerfRecord], pipeline_name: str
) -> PipelineReport:
    """Assemble per-stage stats and inner-share map into a PipelineReport."""
    by_stage = group_by_stage(pipeline_records)
    stage_stats: dict[str, StageStats] = {}
    for stage_name, recs in by_stage.items():
        if not recs:
            continue
        stage_stats[stage_name] = compute_stage_stats([r.duration_s for r in recs])
    shares = compute_stage_shares(pipeline_records, pipeline_name)
    return PipelineReport(
        pipeline_name=pipeline_name,
        stage_stats=stage_stats,
        stage_shares=shares,
        total_records=len(pipeline_records),
    )


def build_full_report(records: list[PerfRecord], source_path: Path) -> FullReport:
    """Roll a flat list of records into a FullReport."""
    if not records:
        return FullReport(
            source_path=str(source_path),
            session_ids=[],
            total_records=0,
            run_start=None,
            run_end=None,
            wall_clock_span_s=None,
            pipeline_reports=[],
            rate_limit_waits={},
            errors=[],
        )

    session_ids: list[str] = []
    seen: set[str] = set()
    for r in records:
        if r.session_id not in seen:
            session_ids.append(r.session_id)
            seen.add(r.session_id)

    run_start = min(r.start_ts for r in records)
    run_end = max(r.start_ts + r.duration_s for r in records)

    pipeline_groups = group_by_pipeline(records)
    pipeline_reports = [
        build_pipeline_report(recs, name) for name, recs in pipeline_groups.items()
    ]

    ai_tag_records = pipeline_groups.get("ai_tagging", [])
    rate_limit_waits = compute_rate_limit_wait(ai_tag_records)

    errors = [r for r in records if r.error is not None]

    return FullReport(
        source_path=str(source_path),
        session_ids=session_ids,
        total_records=len(records),
        run_start=run_start,
        run_end=run_end,
        wall_clock_span_s=run_end - run_start,
        pipeline_reports=pipeline_reports,
        rate_limit_waits=rate_limit_waits,
        errors=errors,
    )


# --- Rendering helpers ---


def _format_ts(ts: float) -> str:
    """Format a unix timestamp as ISO 8601 UTC with second precision."""
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_span(seconds: float) -> str:
    """Format a wall-clock span: 'Xm Ys' when >= 60s, else 'Y.YYs'."""
    if seconds >= 60:
        minutes = int(seconds // 60)
        rem = seconds - minutes * 60
        return f"{minutes}m {rem:.0f}s"
    return f"{seconds:.2f}s"


def _format_payload(payload: dict[str, object] | None) -> str:
    """Render a payload dict as a compact JSON cell (or em-dash if None)."""
    if not payload:
        return "—"
    return json.dumps(payload, sort_keys=True)


def render_markdown(report: FullReport) -> str:
    """Render a FullReport as a markdown document."""
    lines: list[str] = []
    lines.append("# rekordbot — performance report")
    lines.append("")
    lines.append(f"**Source:** {report.source_path}")
    sessions_str = ", ".join(report.session_ids) if report.session_ids else "—"
    lines.append(f"**Session ID(s):** {sessions_str}")
    lines.append(f"**Records:** {report.total_records}")
    lines.append(
        "**Run start:** " + (_format_ts(report.run_start) if report.run_start is not None else "—")
    )
    lines.append(
        "**Run end:** " + (_format_ts(report.run_end) if report.run_end is not None else "—")
    )
    if report.wall_clock_span_s is not None:
        span_str = _format_span(report.wall_clock_span_s)
    else:
        span_str = "—"
    lines.append(f"**Wall-clock span:** {span_str}")
    lines.append("")

    if not report.pipeline_reports:
        lines.append("_No pipelines instrumented in this run._")
        lines.append("")
    else:
        for pr in report.pipeline_reports:
            lines.append(f"## Pipeline: {pr.pipeline_name}")
            lines.append("")
            lines.append(f"**Total records:** {pr.total_records}")
            lines.append("")
            lines.append(
                "| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | "
                "Min (s) | Max (s) | Share of outer mean |"
            )
            lines.append(
                "|-------|------:|----------:|---------:|--------:|--------:|"
                "--------:|--------:|--------------------:|"
            )
            outer_stage = OUTER_STAGE_FOR_PIPELINE.get(pr.pipeline_name)
            any_percentiles_omitted = False
            for stage_name, st in pr.stage_stats.items():
                p50_cell = f"{st.p50_s:.4f}" if st.p50_s is not None else "—"
                p95_cell = f"{st.p95_s:.4f}" if st.p95_s is not None else "—"
                if st.p50_s is None or st.p95_s is None:
                    any_percentiles_omitted = True

                if pr.stage_shares is None or stage_name == outer_stage:
                    share_cell = "—"
                elif stage_name in pr.stage_shares:
                    share_cell = f"{pr.stage_shares[stage_name] * 100:.1f}%"
                else:
                    share_cell = "—"

                lines.append(
                    f"| {stage_name} | {st.count} | {st.total_s:.4f} | "
                    f"{st.mean_s:.4f} | {p50_cell} | {p95_cell} | "
                    f"{st.min_s:.4f} | {st.max_s:.4f} | {share_cell} |"
                )
            lines.append("")
            if any_percentiles_omitted:
                lines.append("_Percentiles omitted for stages with count < 10._")
                lines.append("")

    if report.rate_limit_waits:
        lines.append("## AI tagging — rate-limit wait per batch")
        lines.append("")
        lines.append("| Session | Batch | Wait (s) |")
        lines.append("|---------|------:|---------:|")
        for (session_id, batch_num), wait in report.rate_limit_waits.items():
            lines.append(f"| {session_id[:8]} | {batch_num} | {wait:.4f} |")
        lines.append("")
        lines.append(
            "_Wait = AI_TAG_BATCH duration − sum of inner stage durations. "
            "Represents time spent in the rate limiter or untimed gaps._"
        )
        lines.append("")

    lines.append("## Errors")
    lines.append("")
    if not report.errors:
        lines.append("No errors recorded.")
    else:
        lines.append("| Pipeline | Stage | Payload | Error |")
        lines.append("|----------|-------|---------|-------|")
        for r in report.errors:
            payload_cell = _format_payload(r.payload)
            lines.append(f"| {r.pipeline} | {r.stage} | {payload_cell} | {r.error} |")
    lines.append("")

    return "\n".join(lines)
