# rekordbot — performance report

**Source:** /fixtures/sample-run-small.jsonl
**Session ID(s):** 11111111111111111111111111111111
**Records:** 7
**Run start:** 2026-05-18T00:45:00Z
**Run end:** 2026-05-18T00:45:13Z
**Wall-clock span:** 13.50s

## Pipeline: ingestion

**Total records:** 5

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| ingestion_inspect | 2 | 0.1100 | 0.0550 | — | — | 0.0500 | 0.0600 | 26.2% |
| ingestion_hash | 1 | 0.0400 | 0.0400 | — | — | 0.0400 | 0.0400 | 19.0% |
| ingestion_file | 2 | 0.4200 | 0.2100 | — | — | 0.2000 | 0.2200 | — |

_Percentiles omitted for stages with count < 10._

## Pipeline: analysis

**Total records:** 2

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| analysis_detect_bpm | 1 | 5.0000 | 5.0000 | — | — | 5.0000 | 5.0000 | 38.5% |
| analysis_track | 1 | 13.0000 | 13.0000 | — | — | 13.0000 | 13.0000 | — |

_Percentiles omitted for stages with count < 10._

## Errors

No errors recorded.
