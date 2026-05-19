# Post-Scope-Reduction — Panorama Bar Playlist 04 — Josey Rebelle

**Phase:** 6d.1 (Scope Reduction), Step 6 (Re-baseline)
**Run date:** 2026-05-19 (19:26:20 to 19:29:42 BST — 3m 22s operator span, 2m 3s pipeline-time span)
**Build commit:** `2826625` (`feature/scope-reduction` HEAD at run time — Commit 5 of Phase 6d.1)
**Mode:** Packaged. `/Applications/rekordbot.app` launched via direct binary invocation:
`REKORDBOT_PERF_RECORD=1 /Applications/rekordbot.app/Contents/MacOS/rekordbot`
**Hardware:** Apple Silicon Mac (arm64), macOS 26.4.1
**Source drive:** `/Volumes/collection/` (external, USB-C). Drive cold-cache state at run start (no recent reads of the Josey Rebelle folder this session).

## Purpose

This run is the empirical confirmation point for Phase 6d.1. The Phase 6d Decision Point predicted that removing key detection from the analysis pipeline would deliver a ~25× speedup on analysis-per-track wall-clock by eliminating the dominant stage (`analysis_detect_key`, which was 94–96% of analysis time in the Lakuti and Martyn baselines). This run measures the actual delta against the post-Phase-6d.1 codebase to confirm the prediction held.

Companion file: `delta.md` documents the before/after narrative against the Martyn N=52 baseline.

## Corpus

`Panorama_Bar_Playlist_04_Josey_Rebelle/` — **40 source FLAC files**. Real DJ-curated playlist (Josey Rebelle for Panorama Bar's playlist series).

**Corpus-size correction:** The Phase 6d.1 brief and the perf README implied corpus-size parity with Martyn (N=52). The actual Josey Rebelle folder contains 40 audio files (plus an `_index.csv` metadata file). The brief was inferring parity from the README's "Future runs" section; no failure or silent loss during ingestion — the folder is genuinely smaller. Per-track numbers remain directly comparable to Martyn; per-stage totals scale to N=40 rather than N=52.

Genre characteristics on visual inspection of the AI-tagged output: a mix of deep house, garage, broken beat, jungle, soul, dub, ambient electronica, and disco-adjacent material. Broadly consistent with Josey Rebelle's reputation as a UK-rooted selector working across house, garage, jungle, and adjacent genres.

**Ingestion results:**
- 40/40 ingested successfully (0 failed, 0 duplicates)
- 40 FLAC → AIFF 16-bit conversion via `ingestion_convert_ffmpeg`
- 0 AIFF passthrough (no AIFF sources in this corpus, unlike Martyn's 1)
- 0 duplicates of pre-existing DB tracks

All 40 successful tracks proceeded through analysis, AI tagging, and XML export.

## Starting state

- **Pre-run DB tracks:** 106 (54 from baselines 1+2 plus 52 from Martyn, less any prior-session changes — matches the Martyn post-run total)
- **Post-run DB tracks:** 146 (106 + 40)
- **Pre-run output dir:** `/Volumes/collection/REKORDBOT/rekordbot_library/` carried forward from Baseline 2 (Martyn)
- **Pre-run snapshots retained:**
  - `~/Library/Application Support/rekordbot/rekordbot.db.pre-baseline-04`
  - `/tmp/output-dir-pre-baseline-04.txt`
  - `/tmp/imports-dir-pre-baseline-04.txt`

## Pipelines exercised

| Pipeline | Triggered? | Notes |
|----------|------------|-------|
| Ingestion | ✓ | 40 files, 100% success |
| Analysis | ✓ | All 40 tracks analysed |
| AI tagging | ✓ | 40 tracks tagged in 2 batches. Cost: $0.0803. Tokens: 6,374 in / 4,081 out. AI quality smoke check: no obvious regressions on visual inspection. |
| XML export | ✓ | 146 tracks exported to `/Volumes/collection/REKORDBOT/rekordbox.xml`, 3 playlists |
| XML import | ✗ | Not part of standard ingest workflow |

## Anomalies during run

- No ingestion failures (matches Martyn; differs from Lakuti's 2 corrupt FLACs). Clean corpus.
- One `analysis_librosa_load` record at 6.7754s — strong outlier, ~19× the median of 0.1866s. New high-water mark for librosa_load across all three runs (Baseline 1: 6.24s, Baseline 2: 1.49s, this run: 6.78s). Outlier magnitude is reproducible in kind; the specific track varies. Not concerning at this point — likely a long source file loaded cold from external USB.
- One `ingestion_convert_ffmpeg` record at 1.3872s — largest source file in the corpus. In the same range as Martyn's max (1.69s). Not material to wall-clock.
- AI tagging per-batch wall-clock at 28.6s mean (vs Martyn's 22.6s). Per-batch sample size is only n=2 here, so this is not a meaningful signal — Claude API latency on the day, batch composition, and rate-limit variance all dominate at n=2. Per-track cost is essentially identical to Martyn ($0.00201 vs $0.00200), confirming the prompt change was cost-neutral.

## Headline findings

**`analysis_track` mean wall-clock dropped from 11.8726s (Martyn N=52) to 0.6096s (Josey N=40) — a 19.5× speedup.** The Phase 6d Decision Point predicted ~25×. The shortfall is explained below.

The pipeline shape post-scope-reduction:

| Stage | Mean (s) | Share of `analysis_track` mean |
|-------|---------:|-------------------------------:|
| `analysis_librosa_load` | 0.3564 | 58.5% |
| `analysis_detect_bpm` | 0.2466 | 40.5% |
| `analysis_read_tags` | 0.0044 | 0.7% |
| `analysis_db_update` | 0.0014 | 0.2% |

`analysis_detect_key` is absent — the stage is no longer emitted, confirming the Commit 3 source removal landed in the packaged binary.

**Why the speedup is 19.5× rather than 25×.** Pre-scope-reduction, `analysis_librosa_load` was 1.9% of analysis time and its outliers were absorbed by the dominant key detection. Post-scope-reduction, librosa_load is now 58.5% of analysis time — the same absolute outliers (a 6.78s cold-cache load on one track) now dominate the variance. The post-6d.1 floor is **I/O-bound** rather than compute-bound: librosa's audio decode reads the source file from disk before chroma/onset extraction can begin. On a USB-C external drive with cold cache, that I/O cost is the new ceiling.

Two implications:

1. **On warmer storage (internal SSD), the per-track number would drop further** toward the theoretical floor of ~0.25s (BPM + tag-read + DB-update, with a minimal librosa decode). The 0.61s/track mean here is conservative — a fast-storage measurement would likely show 25–30× rather than 19.5×.
2. **Further optimisation candidates have shifted.** BPM detection is now 40.5% of analysis time, not 2%. The librosa-decode-sharing optimisation that Phase 6d named as candidate (c) — formerly capped at a ~2% improvement — is now potentially worth ~20–30% of the post-6d.1 analysis time, because the decode-load is shared between *no other stage* (vs being shared with key detection pre-6d.1). Whether to pursue this is a Path X / Phase 6e decision; at 0.6s/track, the absolute savings are small in wall-clock terms.

**Total analysis stage wall-clock for the corpus: 24.4s for 40 tracks**, vs Martyn's 617s for 52 tracks. Per-track: 0.61s vs 11.87s. Qualitatively this is the difference between "make a coffee" and "blink and miss it."

**XML export records confirm Commit 2 landed in the packaged binary.** The reporter shows 4 inner-stage record types for `xml_export` rather than 6 — `xml_export_load_crates` and `xml_export_load_sets` are absent, as expected. The stage constants remain in `backend/services/perf.py` for historical JSONL parsing; they just stop being emitted because the exporter no longer reads crates or sets.

**AI tagging cost stayed flat per-track despite the prompt change.** Input tokens per track: 159 (post-6d.1) vs 179 (Martyn pre-6d.1), a -11% reduction. Output tokens per track: 102 (post-6d.1) vs 98 (Martyn), a +4% increase. Net cost per track: $0.00201 vs $0.00200. The prompt slimming saved input cost but Claude wrote marginally more reasoning per track, washing out the savings. Good news in that the Commit 4 prompt change was cost-neutral; the analysis-stage speedup came for free.

**AI tagging quality (visual inspection, not formal evaluation).** The 40 Josey tracks were eyeballed in the track table for obvious misclassification — particularly in the 120–126 BPM band where the removed "minor-key suggests deep/tech house" hint would have disambiguated. No obvious regressions observed. Genres assigned across the corpus reflect the expected mix (deep house, garage, jungle, ambient, soul, broken beat, etc.). Operator confidence: "looks fine at this stage." Formal evaluation against a held-out labelled set is not part of Phase 6d.1 scope; this is a real-world sanity check only.

## Reporter output

_Generated by `scripts/perf-report.py` from `run-20260519T192728.jsonl` (494 records)._

# rekordbot — performance report

**Source:** /Users/daleb/Library/Application Support/rekordbot/perf/run-20260519T192728.jsonl
**Session ID(s):** 02c895d3918b43afac5bab9a3523b33e
**Records:** 494
**Run start:** 2026-05-19T18:27:28Z
**Run end:** 2026-05-19T18:29:31Z
**Wall-clock span:** 2m 3s

## Pipeline: ingestion

**Total records:** 280

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| ingestion_inspect | 40 | 1.1496 | 0.0287 | 0.0265 | 0.0341 | 0.0246 | 0.0820 | 10.7% |
| ingestion_decide | 40 | 0.0005 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0% |
| ingestion_hash | 40 | 1.7066 | 0.0427 | 0.0411 | 0.0662 | 0.0073 | 0.0791 | 15.9% |
| ingestion_dup_check | 40 | 0.0494 | 0.0012 | 0.0011 | 0.0016 | 0.0010 | 0.0030 | 0.5% |
| ingestion_convert_ffmpeg | 40 | 7.6782 | 0.1920 | 0.1424 | 0.4084 | 0.0563 | 1.3872 | 71.6% |
| ingestion_db_insert | 40 | 0.0701 | 0.0018 | 0.0017 | 0.0021 | 0.0013 | 0.0041 | 0.7% |
| ingestion_file | 40 | 10.7226 | 0.2681 | 0.2206 | 0.4837 | 0.0935 | 1.4717 | — |

## Pipeline: analysis

**Total records:** 200

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| analysis_read_tags | 40 | 0.1741 | 0.0044 | 0.0027 | 0.0104 | 0.0010 | 0.0319 | 0.7% |
| analysis_librosa_load | 40 | 14.2579 | 0.3564 | 0.1866 | 0.3670 | 0.0339 | 6.7754 | 58.5% |
| analysis_detect_bpm | 40 | 9.8650 | 0.2466 | 0.2255 | 0.4004 | 0.0321 | 0.8295 | 40.5% |
| analysis_db_update | 40 | 0.0540 | 0.0014 | 0.0013 | 0.0018 | 0.0009 | 0.0023 | 0.2% |
| analysis_track | 40 | 24.3822 | 0.6096 | 0.4301 | 0.7653 | 0.0697 | 7.6431 | — |

## Pipeline: ai_tagging

**Total records:** 10

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| ai_tag_build_message | 2 | 0.0006 | 0.0003 | — | — | 0.0003 | 0.0003 | 0.0% |
| ai_tag_api_call | 2 | 57.2180 | 28.6090 | — | — | 28.4468 | 28.7711 | 100.0% |
| ai_tag_parse_response | 2 | 0.0001 | 0.0001 | — | — | 0.0000 | 0.0001 | 0.0% |
| ai_tag_db_update | 2 | 0.0087 | 0.0044 | — | — | 0.0032 | 0.0056 | 0.0% |
| ai_tag_batch | 2 | 57.2287 | 28.6143 | — | — | 28.4508 | 28.7779 | — |

_Percentiles omitted for stages with count < 10._

## Pipeline: xml_export

**Total records:** 4

| Stage | Count | Total (s) | Mean (s) | p50 (s) | p95 (s) | Min (s) | Max (s) | Share of outer mean |
|-------|------:|----------:|---------:|--------:|--------:|--------:|--------:|--------------------:|
| xml_export_load_tracks | 1 | 0.0058 | 0.0058 | — | — | 0.0058 | 0.0058 | — |
| xml_export_build | 1 | 0.0135 | 0.0135 | — | — | 0.0135 | 0.0135 | — |
| xml_export_write | 1 | 0.0083 | 0.0083 | — | — | 0.0083 | 0.0083 | — |
| xml_export | 1 | 0.0281 | 0.0281 | — | — | 0.0281 | 0.0281 | — |

_Percentiles omitted for stages with count < 10._

## AI tagging — rate-limit wait per batch

| Session | Batch | Wait (s) |
|---------|------:|---------:|
| 02c895d3 | 1 | 0.0008 |
| 02c895d3 | 2 | 0.0005 |

_Wait = AI_TAG_BATCH duration − sum of inner stage durations. Represents time spent in the rate limiter or untimed gaps._

## Errors

No errors recorded.
