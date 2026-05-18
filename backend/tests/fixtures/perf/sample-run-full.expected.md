# rekordbot — performance report

**Source:** /fixtures/sample-run-full.jsonl
**Session ID(s):** 22222222222222222222222222222222
**Records:** 77
**Run start:** 2026-05-18T00:43:20Z
**Run end:** 2026-05-18T00:51:41Z
**Wall-clock span:** 8m 21s

## Pipeline: ingestion

**Total records:** 30

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| ingestion_inspect | 10 | 0.5900 | 0.0590 | 0.0600 | 0.0700 | 0.0500 | 0.0700 | 28.1% |
| ingestion_hash | 10 | 0.4400 | 0.0440 | 0.0400 | 0.0500 | 0.0400 | 0.0500 | 21.0% |
| ingestion_file | 10 | 2.1000 | 0.2100 | 0.2100 | 0.2355 | 0.1800 | 0.2400 | — |

## Pipeline: analysis

**Total records:** 30

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| analysis_librosa_load | 10 | 31.4000 | 3.1400 | 3.1500 | 3.4550 | 2.8000 | 3.5000 | 24.9% |
| analysis_detect_bpm | 10 | 51.4000 | 5.1400 | 5.1500 | 5.4550 | 4.8000 | 5.5000 | 40.7% |
| analysis_track | 10 | 126.3000 | 12.6300 | 12.6000 | 13.4550 | 11.8000 | 13.5000 | — |

## Pipeline: ai_tagging

**Total records:** 15

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| ai_tag_build_message | 3 | 0.3000 | 0.1000 | — | — | 0.1000 | 0.1000 | 0.5% |
| ai_tag_api_call | 3 | 51.5000 | 17.1667 | — | — | 4.5000 | 25.0000 | 81.7% |
| ai_tag_parse_response | 3 | 0.6000 | 0.2000 | — | — | 0.2000 | 0.2000 | 1.0% |
| ai_tag_db_update | 3 | 1.7000 | 0.5667 | — | — | 0.5000 | 0.7000 | 2.7% |
| ai_tag_batch | 3 | 63.0000 | 21.0000 | — | — | 5.0000 | 30.0000 | — |

_Percentiles omitted for stages with count < 10._

## Pipeline: xml_export

**Total records:** 1

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| xml_export | 1 | 0.5000 | 0.5000 | — | — | 0.5000 | 0.5000 | — |

_Percentiles omitted for stages with count < 10._

## Pipeline: xml_import

**Total records:** 1

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| xml_import | 1 | 1.2000 | 1.2000 | — | — | 1.2000 | 1.2000 | — |

_Percentiles omitted for stages with count < 10._

## AI tagging — rate-limit wait per batch

| Session | Batch | Wait (s) |
|---------|------:|---------:|
| 22222222 | 1 | 4.2000 |
| 22222222 | 2 | 5.2000 |
| 22222222 | 3 | 0.0000 |

_Wait = AI_TAG_BATCH duration − sum of inner stage durations. Represents time spent in the rate limiter or untimed gaps._

## Errors

No errors recorded.
