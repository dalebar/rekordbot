# Baseline 2 — Panorama Bar Playlist 03 — Martyn

**Phase:** 6d (Performance Optimisation), Step 4 (Baseline Measurement)
**Run date:** 2026-05-18 (17:58:55 to 18:18:43 BST — ~19m 48s operator span, 17m 55s pipeline-time span)
**Build commit:** `18d74a0` (`feature/phase-6d-performance` HEAD at session start)
**Mode:** Packaged. `/Applications/rekordbot.app` launched via direct binary invocation:
`REKORDBOT_PERF_RECORD=1 /Applications/rekordbot.app/Contents/MacOS/rekordbot`
**Hardware:** Apple Silicon Mac (arm64), macOS 26.4.1
**Source drive:** `/Volumes/collection/` (external, USB-C). Drive cold-cache state at run start (no recent reads of the Martyn folder this session).

## Corpus

`Panorama_Bar_Playlist_03_Martyn/` — 52 source files. Real DJ-curated playlist (Martyn for Panorama Bar's playlist series). Format mix: 51 FLAC + 1 AIFF (`13 Mixing Room.aiff`).

**Ingestion results:**
- 52/52 ingested successfully (0 failed, 0 duplicates)
- 51 FLAC → AIFF conversion via `ingestion_convert_ffmpeg`
- 1 AIFF passthrough via `ingestion_copy` (lossless source already in target format)
- 0 duplicates of pre-existing DB tracks

All 52 successful tracks proceeded through analysis, AI tagging, and XML export.

This is the first baseline to exercise the `ingestion_copy` passthrough branch. Baseline 1 (Lakuti) was 100% conversion-path because the corpus was 100% FLAC.

## Starting state

- **Pre-run DB tracks:** 54 (the 30 historical tracks plus the 24 successfully-ingested Lakuti tracks from Baseline 1)
- **Post-run DB tracks:** 106 (54 + 52)
- **Pre-run output dir:** `/Volumes/collection/REKORDBOT/rekordbot_library/` carried forward from Baseline 1
- **Pre-run snapshots retained:**
  - `~/Library/Application Support/rekordbot/rekordbot.db.pre-baseline-03`
  - `/tmp/output-dir-pre-baseline-03.txt`
  - `/tmp/imports-dir-pre-baseline-03.txt`

## Pipelines exercised

| Pipeline | Triggered? | Notes |
|----------|------------|-------|
| Ingestion | ✓ | 52 files, 100% success |
| Analysis | ✓ | All 52 tracks analysed |
| AI tagging | ✓ | 83 tracks tagged across 5 batches. Note this includes 31 pre-existing untagged tracks from Baseline 1 alongside the 52 new Martyn tracks — "AI Tag All Untagged" caught up both. Cost: $0.1667. Tokens: 14,855 in / 8,141 out |
| XML export | ✓ | 106 tracks exported to `/Volumes/collection/REKORDBOT/rekordbox.xml` |
| XML import | ✗ | Not part of standard ingest workflow |

The AI tagging coverage is what Baseline 1 deferred. The 83-track figure is mixed-corpus (Lakuti + Martyn) and should not be read as Martyn-per-track; the per-batch and rate-limit-wait numbers are nonetheless valid measurements of the AI tagging pipeline itself.

## Anomalies during run

- No ingestion failures (vs Baseline 1's 2 corrupt FLACs). Clean corpus.
- One `analysis_librosa_load` record at 1.49s (vs median 0.18s, ~8× the median). Smaller magnitude than Baseline 1's 6.24s outlier (which was ~28× its median). Two-run pattern: outliers exist but are inconsistent in magnitude — not a recurring edge case worth chasing.
- One `ingestion_convert_ffmpeg` record at 1.69s (vs median 0.14s). Likely the largest source file in the corpus. Not material to wall-clock.
- One `analysis_detect_key` at 22.43s (vs median 10.53s) — new high-water mark for analysis-per-track. Single outlier.
- One `analysis_detect_key` at 3.53s (vs median 10.53s) — new low. Likely a short track (key detection time correlates roughly with audio duration). Not concerning.

## Headline findings

**`analysis_detect_key` dominates analysis-per-track wall-clock at 96.0% (mean 11.40s of 11.87s).** Two independent baselines now agree:

| Baseline | Corpus | N | `analysis_detect_key` share | `analysis_detect_key` mean |
|----------|--------|---|----------------------------:|---------------------------:|
| 1 | Lakuti | 24 | 94.4% | 13.01s |
| 2 | Martyn | 52 | 96.0% | 11.40s |

The shape is reproducible. The Step 5 Decision Point now has robust data behind it: the bottleneck is concentrated inside `key_detector.py`, not in the librosa decode (1.9%), not in BPM detection (2.0%), not in tag I/O (0.1%). The brief's named candidate (c) — share the librosa decode between BPM and key detection — caps at a ~1.9% improvement to analysis-per-track wall-clock under ideal execution.

**Other analysis-stage inner timings:**

- `analysis_librosa_load`: 1.9% (audio decode — down from Baseline 1's 3.4% as a share, presumably due to the smaller load outlier)
- `analysis_detect_bpm`: 2.0% (was 2.1%)
- `analysis_read_tags`: 0.1% (was 0.1%)
- `analysis_db_update`: 0.0% (rounding)

**Ingestion conversion share rose to 73.7% (from Baseline 1's 65.8%).** Larger average source file size on Martyn. Per-file ingestion mean: 273ms (vs Baseline 1's 257ms). Concurrent conversion re-enable (brief's secondary deliverable) would parallelise this — modest absolute savings (~10s on 52 tracks at 4× speedup), architectural fix matters more than the wall-clock gain.

**AI tagging: 5 batches × 22.6s mean = 113s total for 83 tracks.** Per-track cost: $0.1667 / 83 ≈ $0.0020/track. Token usage: 14,855 in / 8,141 out across 83 tracks (~179 input tokens / ~98 output tokens per track on average). Rate-limit wait per batch is sub-millisecond — effectively zero. No optimisation work is in scope for AI tagging in this phase; data captured for record.

**XML export remains sub-30ms whole-pipeline.** 28ms for 106 tracks (vs 23ms for 54). Not a candidate for optimisation.

## Reporter output

_Generated by `scripts/perf-report.py` from `run-20260518T185959.jsonl` (707 records)._

# rekordbot — performance report
**Source:** /Users/daleb/Library/Application Support/rekordbot/perf/run-20260518T185959.jsonl
**Session ID(s):** 3c3eaec02bb44697a65a1954ebe494ad
**Records:** 707
**Run start:** 2026-05-18T17:59:59Z
**Run end:** 2026-05-18T18:17:55Z
**Wall-clock span:** 17m 55s

## Pipeline: ingestion

**Total records:** 364

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| ingestion_inspect | 52 | 1.5071 | 0.0290 | 0.0270 | 0.0379 | 0.0243 | 0.0683 | 10.6% |
| ingestion_decide | 52 | 0.0012 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0% |
| ingestion_hash | 52 | 2.0893 | 0.0402 | 0.0367 | 0.0633 | 0.0143 | 0.0905 | 14.7% |
| ingestion_dup_check | 52 | 0.0662 | 0.0013 | 0.0012 | 0.0016 | 0.0010 | 0.0033 | 0.5% |
| ingestion_convert_ffmpeg | 51 | 10.2740 | 0.2015 | 0.1362 | 0.4261 | 0.0890 | 1.6862 | 73.7% |
| ingestion_db_insert | 52 | 0.0890 | 0.0017 | 0.0016 | 0.0023 | 0.0013 | 0.0042 | 0.6% |
| ingestion_file | 52 | 14.2065 | 0.2732 | 0.2103 | 0.5048 | 0.1413 | 1.7606 | — |
| ingestion_copy | 1 | 0.0866 | 0.0866 | — | — | 0.0866 | 0.0866 | 31.7% |

_Percentiles omitted for stages with count < 10._

## Pipeline: analysis

**Total records:** 312

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| analysis_read_tags | 52 | 0.3417 | 0.0066 | 0.0054 | 0.0101 | 0.0011 | 0.0367 | 0.1% |
| analysis_librosa_load | 52 | 11.4548 | 0.2203 | 0.1754 | 0.3599 | 0.0602 | 1.4932 | 1.9% |
| analysis_detect_bpm | 52 | 12.5657 | 0.2416 | 0.2185 | 0.3991 | 0.0687 | 0.5026 | 2.0% |
| analysis_detect_key | 52 | 592.8621 | 11.4012 | 10.5290 | 17.5335 | 3.5259 | 22.4263 | 96.0% |
| analysis_db_update | 52 | 0.0811 | 0.0016 | 0.0013 | 0.0025 | 0.0011 | 0.0062 | 0.0% |
| analysis_track | 52 | 617.3756 | 11.8726 | 10.9713 | 18.2863 | 3.6623 | 23.3203 | — |

## Pipeline: ai_tagging

**Total records:** 25

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| ai_tag_build_message | 5 | 0.0025 | 0.0005 | — | — | 0.0002 | 0.0007 | 0.0% |
| ai_tag_api_call | 5 | 113.0991 | 22.6198 | — | — | 6.0809 | 28.2420 | 100.0% |
| ai_tag_parse_response | 5 | 0.0005 | 0.0001 | — | — | 0.0000 | 0.0002 | 0.0% |
| ai_tag_db_update | 5 | 0.0341 | 0.0068 | — | — | 0.0050 | 0.0103 | 0.0% |
| ai_tag_batch | 5 | 113.1402 | 22.6280 | — | — | 6.0867 | 28.2490 | — |

_Percentiles omitted for stages with count < 10._

## Pipeline: xml_export

**Total records:** 6

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| xml_export_load_tracks | 1 | 0.0057 | 0.0057 | — | — | 0.0057 | 0.0057 | — |
| xml_export_load_crates | 1 | 0.0003 | 0.0003 | — | — | 0.0003 | 0.0003 | — |
| xml_export_load_sets | 1 | 0.0010 | 0.0010 | — | — | 0.0010 | 0.0010 | — |
| xml_export_build | 1 | 0.0107 | 0.0107 | — | — | 0.0107 | 0.0107 | — |
| xml_export_write | 1 | 0.0095 | 0.0095 | — | — | 0.0095 | 0.0095 | — |
| xml_export | 1 | 0.0281 | 0.0281 | — | — | 0.0281 | 0.0281 | — |

_Percentiles omitted for stages with count < 10._

## AI tagging — rate-limit wait per batch

| Session | Batch | Wait (s) |
|---------|------:|---------:|
| 3c3eaec0 | 1 | 0.0012 |
| 3c3eaec0 | 2 | 0.0007 |
| 3c3eaec0 | 3 | 0.0007 |
| 3c3eaec0 | 4 | 0.0007 |
| 3c3eaec0 | 5 | 0.0006 |

_Wait = AI_TAG_BATCH duration − sum of inner stage durations. Represents time spent in the rate limiter or untimed gaps._

## Errors

No errors recorded.
