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
| Analysis | `analysis_read_tags`, `analysis_librosa_load`, `analysis_detect_bpm`, `analysis_detect_key` (retired post-Phase-6d.1), `analysis_db_update`, `analysis_track` (outer) |
| AI tagging | `ai_tag_build_message`, `ai_tag_api_call`, `ai_tag_parse_response`, `ai_tag_db_update`, `ai_tag_batch` (outer) |
| XML export | `xml_export_load_tracks`, `xml_export_load_crates` (retired post-Phase-6d.1), `xml_export_load_sets` (retired post-Phase-6d.1), `xml_export_build`, `xml_export_write`, `xml_export` (outer) |
| XML import | `xml_import_parse`, `xml_import_tracks`, `xml_import_playlists`, `xml_import_commit`, `xml_import` (outer) |

Three stage constants remain in `backend/services/perf.py::Stage` but no longer emit because Phase 6d.1 removed their call sites (key detection, crate loading, set loading). The constants are retained so historical JSONL files emitted before Phase 6d.1 still parse cleanly through the reporter. Post-Phase-6d.1 JSONL files will not contain records for these stages.

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
- "Share of outer mean" for inner stages within a pipeline that has a wrapping outer stage (e.g. `analysis_track` wraps `analysis_detect_bpm`)
- AI tagging rate-limit wait derivation (`AI_TAG_BATCH duration − sum of inner stage durations`)
- Errors table (any records emitted with error payloads)

**Percentile rule:** p50/p95 are computed only when `count >= 10` per stage. Below that they render as "—" with a footnote.

**Source:** `scripts/perf-report.py` (CLI shim) and `backend/services/perf_report.py` (pure logic). Golden-file tests live in `backend/tests/test_perf_report.py` and are regenerable via `pytest --update-golden`.

## Test corpus

Four DJ-curated playlists on `/Volumes/collection/`, sourced from Soulseek:

1. `Panorama_Bar_Playlist_02_Lakuti/` — Lakuti (26 FLAC, 2 corrupt at source). **Consumed:** Baseline 1.
2. `Panorama_Bar_Playlist_03_Martyn/` — Martyn (51 FLAC + 1 AIFF). **Consumed:** Baseline 2.
3. `Panorama_Bar_Playlist_04_Josey_Rebelle/` — Josey Rebelle (40 FLAC). **Consumed:** post-scope-reduction re-baseline. Corpus is smaller than the README originally implied (the Phase 6d.1 brief and the README's earlier "Future runs" wording inferred parity with Martyn's N=52; the folder actually contains 40 audio files).
4. `Panorama_Bar_Playlist_05_Nick_Höppner/` — Nick Höppner (held for reserve / direct A/B if needed).

The corpus was chosen because it reflects real DJ download practice: curated playlists rather than catalogue dumps, lossless source files, real-world tag completeness (often imperfect), occasional source corruption. Synthetic fixtures would not capture the FLAC-decode failures or the source-format-mix characteristics that surfaced in actual baselines.

The three consumed corpora (Lakuti, Martyn, Josey) advanced the real library state as a side effect. This was an intentional trade-off: measurement-against-real-state matters more than measurement-against-pristine-state, given the realistic workflow is "process new folder against existing library."

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

Follow the structure of `baseline-02-lakuti.md`, `baseline-03-martyn.md`, or `post-scope-reduction-04-josey-rebelle.md`. The reporter output is embedded as a section; the surrounding sections (corpus, starting state, pipelines exercised, anomalies, headline findings) provide context the reporter cannot generate.

## Run history

| Run | Date | Corpus | N | Build commit | Report | Notes |
|-----|------|--------|--:|--------------|--------|-------|
| Baseline 1 | 2026-05-18 | Lakuti | 24 (of 26, 2 corrupt) | `45fd218` | [baseline-02-lakuti.md](baseline-02-lakuti.md) | First baseline. AI tagging deferred to Baseline 2. |
| Baseline 2 | 2026-05-18 | Martyn | 52 | `18d74a0` | [baseline-03-martyn.md](baseline-03-martyn.md) | Second baseline. Full pipeline including AI tagging. Established the `analysis_detect_key` 96% share. |
| Post-6d.1 | 2026-05-19 | Josey Rebelle | 40 | `2826625` | [post-scope-reduction-04-josey-rebelle.md](post-scope-reduction-04-josey-rebelle.md) | Re-baseline after Phase 6d.1 scope reduction. Confirmed 19.5× analysis-per-track speedup. Delta narrative: [delta.md](delta.md). |

## Decision point (Phase 6d Step 5)

**Outcome: scope reduction.** Path A (in-scope optimisation of `key_detector.py`) was the expected outcome given the baseline shape. The actual decision is a third path that the brief did not contemplate: retire the consumers of key data and remove key detection from the analysis pipeline entirely. This brings the analysis stage from ~11.9s/track to ~0.5s/track — a 25x speedup on the dominant phase — and removes two features (Crate Builder, Set Planner) whose downstream value the user empirically does not consume.

**Outcome confirmed empirically:** the post-scope-reduction re-baseline (Josey Rebelle, 2026-05-19, build `2826625`) measured a 19.5× per-track speedup on `analysis_track` mean — slightly below the 25× prediction, with the shortfall attributable to cold-cache I/O on external storage now being the new ceiling rather than computation. See [delta.md](delta.md) for the full before/after narrative.

### Data

Two independent baselines, 76 tracks across two real DJ corpora, agreed pre-scope-reduction:

| Baseline | Corpus | N | `analysis_detect_key` share | `analysis_detect_key` mean |
|----------|--------|---|----------------------------:|---------------------------:|
| 1 | Lakuti | 24 | 94.4% | 13.01s |
| 2 | Martyn | 52 | 96.0% | 11.40s |

Key detection dominates analysis-per-track wall-clock. All other inner stages of analysis are negligible: librosa decode is 1.9–3.4%, BPM detection is 2.0–2.1%, tag reading is 0.1%, DB update is rounding error. The brief's named optimisation candidate (c) "share the librosa decode between BPM and key detection" caps at a ~2–3% improvement under ideal execution.

### Reasoning

The Path A → Path-A-with-algorithmic-changes-inside-key_detector route was viable. Concurrent analysis workers (brief candidate b) could have delivered a further 4–6x on top via a worker pool. But the bottleneck-as-stated assumes the work needs doing at all.

Key data inside rekordbot is consumed by:

1. **Crate Builder** (Phase 5a) — Camelot-wheel-based harmonic mixing for crate assignment.
2. **Set Planner** (Phase 5b) — key-aware transition scoring and segment planning.
3. **The track table UI** — displays key as a column.
4. **The Rekordbox XML export** — writes the `Tonality` attribute.

The Phase 5a/5b features were empirically tested in real interaction during this session. The Crate Builder run was abandoned by the user after several minutes with no output produced, and the architectural mismatch was identified: the AI-clustered crate-building model assumes a comprehensive analysed library to mine, while the realistic workflow involves a few hundred new tracks against a much larger Rekordbox-managed library already known to the DJ through listening. The features solve a problem the user does not have.

The (3) and (4) consumers are surface-level only. Key data in the track table and the XML export has informational value but is not load-bearing for the workflow the user describes as central: ingest → analyse → AI-tag → organise → import to Rekordbox.

Rekordbox performs its own key analysis on import. The user does not use harmonic-mixing or Camelot-wheel-based selection in practice. The rekordbot value proposition is the work Rekordbox does *not* do well — fast ingestion, quality conversion, AI-augmented tagging, intelligent organisation — and key detection is not part of that work.

BPM detection (~2% of analysis time, ~0.24s/track) is kept. BPM is consumed by the AI tagging prompt as input for genre/mood/energy inference, displayed and sorted in the track table, and written to the TBPM tag that Rekordbox uses as a hint for its own beat-grid analysis. The cost-vs-value ratio for BPM is excellent; for key it is not.

### Consequences

**In scope for the scope-reduction phase (Phase 6d.1, completed in Session 35):**

- ✅ Soft-retire Crate Builder (Phase 5a). UI entry points and routes removed; code, models, tests, and DB tables preserved.
- ✅ Soft-retire Set Planner (Phase 5b). Same treatment.
- ✅ Remove `analysis_detect_key` from the analysis pipeline. The `KeyDetector` service stays in the codebase as dormant code reachable only by direct call.
- ✅ Remove the key column from the track table UI.
- ✅ Remove the `Tonality` attribute from the Rekordbox XML export.
- ✅ Verify the AI tagging prompt does not consume key as input. The prompt did consume key in three places (system prompt hint, `build_track_summary`'s `key_display` row, `ai_tagger.py`'s `key_displays` construction); all three removed in Commit 4.
- ✅ Update CLAUDE.md and the project plan to reflect the new value proposition.
- ✅ Re-baseline against `Panorama_Bar_Playlist_04_Josey_Rebelle/` to confirm the expected ~25× analysis speedup in practice. Result committed as `post-scope-reduction-04-josey-rebelle.md` plus `delta.md`. Empirical speedup: 19.5× (slightly below the 25× prediction; explanation in delta.md).

**Deferred:**

- **Concurrent conversion re-enable** (the brief's secondary deliverable for Phase 6d). On a post-scope-reduction analysis pipeline running at ~0.5s/track, the absolute savings from concurrent conversion are small. The architectural fix may still be worth doing — single-worker is a regression from the pre-Phase-6c capability — but it does not belong in the scope-reduction phase. Will be revisited as its own scoped session after the scope reduction lands.
- **Algorithmic improvements inside `key_detector.py`.** Moot once the consumer is gone. Code preserved for any future revival.

**Not done:**

- Path A optimisation work as originally scoped. The bottleneck identified by the brief is real, but the work would have produced speedups against features the user does not use. Better to remove the work than to optimise it.

### Why this is recorded as a third path rather than Path A or Path B

The brief's Path A assumed feature stability — optimise the bottleneck within the existing scope. Path B was "nothing meaningfully slow, close phase." Neither matched the actual conclusion. The decision is closer to Path B in shape (no in-scope optimisation work performed) but with substantial follow-on work in a separate phase, and with the explicit reasoning that the bottleneck IS real and IS meaningfully slow — just not worth optimising because its output is unused. This is recorded as a deliberate third path so future audits do not misread it as "no bottleneck found."

## Future runs

The post-scope-reduction re-baseline (Josey Rebelle, post-6d.1) has been consumed and the analysis speedup empirically confirmed.

`Panorama_Bar_Playlist_05_Nick_Höppner/` remains held in reserve for:

- A direct A/B against either earlier baseline if needed (e.g. validating any future concurrent-analysis worker pool implementation).
- A future confirmation pass on the real library after any subsequent optimisation work (e.g. if concurrent conversion is re-enabled or if librosa I/O caching is pursued).
- A hard-delete-phase (Path X) confirmation that the dormant Phase 5a/5b code paths haven't accidentally crept back into the live pipelines.

Post-6d.1, the next bottleneck candidates are I/O (librosa_load at 58.5% of post-6d.1 analysis time, dominated by cold-cache external-drive variance) and BPM detection (40.5% of post-6d.1 analysis time, the largest remaining computational cost). Neither is currently in scope; both are real candidates if a future phase justifies the work.

## Known caveats

- **External-drive I/O variance.** `/Volumes/collection/` is a USB-C external. I/O timings vary with drive cache state and concurrent system I/O. Multiple runs of the same corpus would show different absolute numbers; the per-stage *shapes* are reproducible (see the Baseline 1 vs Baseline 2 `analysis_detect_key` share comparison, and the consistent librosa_load max outliers across all three runs).
- **Pipeline-time vs operator-time.** The reporter's wall-clock span measures from first emitted record to last. Operator-driven gaps between clicking "Analyse" → "AI Tag" → "Export XML" are not pipeline cost and are not captured. Both spans are recorded in baseline report preambles.
- **One outer stage may overlap multiple inner stages.** Reporter relies on `start_ts` and the `OUTER_STAGE_FOR_PIPELINE` mapping for nesting awareness, not file order. Records emit in exit-order (inner before outer).
- **Thread origin not yet captured.** `PerfRecord` does not currently include `threading.get_ident()`. The single-worker conversion path means this hasn't mattered yet. If concurrent conversion is re-enabled at any point, this field becomes essential and the harness will need to be updated.
- **Retired stage constants.** `Stage.ANALYSIS_DETECT_KEY`, `Stage.XML_EXPORT_LOAD_CRATES`, and `Stage.XML_EXPORT_LOAD_SETS` remain defined in `backend/services/perf.py` but no longer emit records. Historical JSONL files (Baseline 1, Baseline 2) contain records for these stages and parse correctly; post-Phase-6d.1 runs do not.
