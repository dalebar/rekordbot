# rekordbot — Performance Documentation

This directory contains performance measurement reports and methodology for rekordbot. It exists because Phase 6d — Performance Optimisation — committed to a profile-first principle: every optimisation must trace to a measurement, not to intuition.

## Purpose

`docs/perf/` is the durable record of performance investigations. It captures:

- Methodology and reproduction instructions for the profiling harness
- Baseline measurements before optimisation work
- Post-optimisation measurements when optimisation work has been done
- Decision points where measurement informed scope or design changes

The audience is future-Dale and future-Claude: anyone trying to understand "why was this optimisation done?" or "what did we know when we made decision X?" should be able to find their answer here without re-running the baselines.

## Methodology

Phase 6d (Performance Optimisation) was structured as **measure-then-decide**, not measure-then-optimise. The brief committed to an explicit decision point after the baseline pass: either name a bottleneck and scope optimisation work (Path A), or document that no meaningful bottleneck exists and close the phase (Path B). A third path emerged from the actual data — scope reduction — and was added retroactively to the decision-point output.

The principles in force throughout:

- **Profile-first.** No optimisation work without a measurement showing it's needed.
- **Real data.** Baselines run against real DJ corpora (curated playlists), not synthetic fixtures.
- **Packaged mode.** Measurements taken in the bundled `.app`, not dev mode. Phase 6c proved that dev-vs-packaged discrepancies matter (stdout pipe deadlock, ffprobe path resolution).
- **Two independent baselines minimum.** A single corpus can mislead. Two baselines with different starting states, different corpus characteristics, and different operator pacing surface what's reproducible vs. what's incidental.

## The profiling harness

The harness is a thin instrumentation layer over the existing pipelines. It does not change pipeline behaviour. When enabled, each pipeline emits structured timing records to a JSONL sink; when disabled, instrumentation is a no-op.

**Enabling the harness:**

```bash
REKORDBOT_PERF_RECORD=1 /Applications/rekordbot.app/Contents/MacOS/rekordbot
```

When `REKORDBOT_PERF_RECORD` is unset (the default in normal operation), the harness is a strict no-op — no I/O, no allocations beyond `contextlib.nullcontext()`. The same code path runs in production without overhead.

**Output location:**

```
~/Library/Application Support/rekordbot/perf/run-<timestamp>.jsonl
```

One JSON object per line, one line per timed event. Records include pipeline stage, track ID or file path, wall-clock duration, and an optional payload (file size, BPM result, ffprobe duration, librosa parameters used).

**Stages instrumented:**

| Pipeline | Stages |
|----------|--------|
| Ingestion | `ingestion_inspect`, `ingestion_decide`, `ingestion_hash`, `ingestion_dup_check`, `ingestion_convert_ffmpeg`, `ingestion_copy`, `ingestion_db_insert`, `ingestion_file` (outer) |
| Analysis | `analysis_read_tags`, `analysis_librosa_load`, `analysis_detect_bpm`, `analysis_detect_key`, `analysis_db_update`, `analysis_track` (outer) |
| AI tagging | `ai_tag_build_message`, `ai_tag_api_call`, `ai_tag_parse_response`, `ai_tag_db_update`, `ai_tag_batch` (outer) |
| XML export | `xml_export_load_tracks`, `xml_export_load_crates`, `xml_export_load_sets`, `xml_export_build`, `xml_export_write`, `xml_export` (outer) |
| XML import | `xml_import_parse`, `xml_import_tracks`, `xml_import_playlists`, `xml_import_commit`, `xml_import` (outer) |

Crate Builder and Set Planner are NOT instrumented. They were excluded from Phase 6d scope as pre-validation-stage features. (Subsequently retired in the scope-reduction phase — see Decision Point below.)

**Source:** `backend/services/perf.py`. Stage constants are `backend/services/perf.py::Stage`. Tests live in `backend/tests/test_perf.py`.

## The reporter

The reporter reads a JSONL file and produces a markdown summary suitable for committing alongside the JSONL.

**Invocation:**

```bash
cd /Users/daleb/Documents/projects/rekordbot
uv run scripts/perf-report.py \
   --input ~/Library/Application\ Support/rekordbot/perf/run-<TIMESTAMP>.jsonl \
   --output /tmp/report.md
```

**Report contents:**

- Per-pipeline aggregate (total wall-clock, per-stage count/total/mean/p50/p95/min/max)
- "Share of outer mean" for inner stages within a pipeline that has a wrapping outer stage (e.g. `analysis_track` wraps `analysis_detect_key`)
- AI tagging rate-limit wait derivation (`AI_TAG_BATCH duration − sum of inner stage durations`)
- Errors table (any records emitted with error payloads)

**Percentile rule:** p50/p95 are computed only when `count >= 10` per stage. Below that they render as "—" with a footnote.

**Source:** `scripts/perf-report.py` (CLI shim) and `backend/services/perf_report.py` (pure logic). Golden-file tests live in `backend/tests/test_perf_report.py` and are regenerable via `pytest --update-golden`.

## Test corpus

Four DJ-curated playlists on `/Volumes/collection/`, sourced from Soulseek:

1. `Panorama_Bar_Playlist_02_Lakuti/` — Lakuti (26 FLAC, 2 corrupt at source)
2. `Panorama_Bar_Playlist_03_Martyn/` — Martyn (51 FLAC + 1 AIFF)
3. `Panorama_Bar_Playlist_04_Josey_Rebelle/` — Josey Rebelle (held for post-scope-reduction measurement)
4. `Panorama_Bar_Playlist_05_Nick_Höppner/` — Nick Höppner (held for reserve / direct A/B if needed)

The corpus was chosen because it reflects real DJ download practice: curated playlists rather than catalogue dumps, lossless source files, real-world tag completeness (often imperfect), occasional source corruption. Synthetic fixtures would not capture the FLAC-decode failures or the source-format-mix characteristics that surfaced in actual baselines.

The two baselines (Lakuti, Martyn) advanced the real library state as a side effect. This was an intentional trade-off: measurement-against-real-state matters more than measurement-against-pristine-state, given the realistic workflow is "process new folder against existing library."

## Reproduction

To reproduce a baseline measurement run:

### 1. Verify the install is current

**This is the most important pre-flight check, and the one most easily skipped.** The Session 33 lesson is recorded in CLAUDE.md: `make build-dmg` produces a `.app` and `.dmg` in `target/release/bundle/` but does NOT copy them to `/Applications/`. A stale `/Applications/rekordbot.app` will silently miss any instrumentation added in recent commits, making the harness appear broken when it isn't.

Audit cheaply by comparing the install timestamp against your latest instrumentation commit:

```bash
ls -la /Applications/rekordbot.app/Contents/MacOS/sidecar/rekordbot-server
```

The modification time should be after the commit that introduced or last modified the harness. If it's earlier, reinstall: open the `.dmg` in `target/release/bundle/dmg/` and drag the new `.app` to `/Applications/`.

### 2. Take pre-run snapshots

The harness writes to the real DB and real library. Any baseline against the real state advances that state. Take forensic snapshots before the run so anything that goes wrong can be recovered:

```bash
# DB snapshot
cp ~/Library/Application\ Support/rekordbot/rekordbot.db \
   ~/Library/Application\ Support/rekordbot/rekordbot.db.pre-baseline-NN

# Output dir listing
ls -la /Volumes/collection/REKORDBOT/rekordbot_library/ \
   > /tmp/output-dir-pre-baseline-NN.txt

# Imports dir listing
ls -la /Volumes/collection/REKORDBOT/imports/ \
   > /tmp/imports-dir-pre-baseline-NN.txt 2>&1
```

### 3. Launch with the harness enabled

```bash
REKORDBOT_PERF_RECORD=1 /Applications/rekordbot.app/Contents/MacOS/rekordbot
```

Direct binary invocation is required because macOS `open` and Finder double-click are LaunchServices-intermediated and may not propagate env vars to the child process. Direct invocation passes the env var through Rust's `std::process::Command` default-inheriting environment.

### 4. Drive the pipelines through the UI

For a standard full-pipeline baseline:

1. Drag the corpus folder onto the drop zone (or use "Select Folder…")
2. Click "Analyse All Unanalysed", wait for completion
3. Click "AI Tag All Untagged", wait for completion
4. Click "Export XML"
5. Cmd-Q to quit cleanly (do not force-quit — the watchdog handles sidecar shutdown)

Record the timestamps of each user action for the report preamble.

### 5. Run the reporter

```bash
ls -lat ~/Library/Application\ Support/rekordbot/perf/ | head -5
# identify the new run file by its timestamp

cd /Users/daleb/Documents/projects/rekordbot
uv run scripts/perf-report.py \
   --input ~/Library/Application\ Support/rekordbot/perf/run-<TIMESTAMP>.jsonl \
   --output /tmp/baseline-NN-<corpus>-reporter.md
```

### 6. Write the report

Follow the structure of `baseline-02-lakuti.md` or `baseline-03-martyn.md`. The reporter output is embedded as a section; the surrounding sections (corpus, starting state, pipelines exercised, anomalies, headline findings) provide context the reporter cannot generate.

## Run history

| Run | Date | Corpus | N | Build commit | Report | Notes |
|-----|------|--------|--:|--------------|--------|-------|
| Baseline 1 | 2026-05-18 | Lakuti | 24 (of 26, 2 corrupt) | `45fd218` | [baseline-02-lakuti.md](baseline-02-lakuti.md) | First baseline. AI tagging deferred to Baseline 2. |
| Baseline 2 | 2026-05-18 | Martyn | 52 | `18d74a0` | [baseline-03-martyn.md](baseline-03-martyn.md) | Second baseline. Full pipeline including AI tagging. |

## Decision point (Phase 6d Step 5)

_Pending. To be recorded in a follow-up commit once scope discussion is complete. See README commit history._

## Future runs

Following the scope-reduction phase that closes Phase 6d, a re-measurement pass against `Panorama_Bar_Playlist_04_Josey_Rebelle/` will be committed as `post-scope-reduction-04-josey-rebelle.md`, with an accompanying `delta.md` documenting the before/after wall-clock change.

`Panorama_Bar_Playlist_05_Nick_Höppner/` is held in reserve for: (a) a direct A/B against either earlier baseline if needed, or (b) a final confirmation pass on the real library after optimisation work completes.

## Known caveats

- **External-drive I/O variance.** `/Volumes/collection/` is a USB-C external. I/O timings vary with drive cache state and concurrent system I/O. Multiple runs of the same corpus would show different absolute numbers; the per-stage *shapes* are reproducible (see the Baseline 1 vs Baseline 2 `analysis_detect_key` share comparison).
- **Pipeline-time vs operator-time.** The reporter's wall-clock span measures from first emitted record to last. Operator-driven gaps between clicking "Analyse" → "AI Tag" → "Export XML" are not pipeline cost and are not captured. Both spans are recorded in baseline report preambles.
- **One outer stage may overlap multiple inner stages.** Reporter relies on `start_ts` and the `OUTER_STAGE_FOR_PIPELINE` mapping for nesting awareness, not file order. Records emit in exit-order (inner before outer).
- **Thread origin not yet captured.** `PerfRecord` does not currently include `threading.get_ident()`. The single-worker conversion path means this hasn't mattered yet. If concurrent conversion is re-enabled at any point, this field becomes essential and the harness will need to be updated.
