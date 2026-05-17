# Feature: Performance Optimisation
**Branch:** `feature/phase-6d-performance`
**Status:** Brief written. Implementation not yet started.
**Phase:** 6d
**Depends on:** Phase 6c (complete, merged at `b7dc4f4`, tagged `phase-6c-complete`)

---

## What this phase does

This is a measurement-then-decide phase, not a feature delivery. The goal is to find out where time actually goes when rekordbot processes a real folder of music against the corpus you'd realistically throw at it, and to act only on what the data shows is slow.

**Primary target for optimisation work: the analysis stage** (BPM + key detection via librosa). Dale's experience with large folders points at analysis as the bottleneck. The profiling pass either confirms that or redirects the work — but the optimisation budget for this phase lives there.

A secondary deliverable in this phase: re-enable concurrent conversion in the ingestion pipeline. Concurrent conversion was disabled in Phase 6c during the stdout-pipe deadlock investigation (CLAUDE.md line 475). Now that the root cause is understood and the StreamHandler-in-packaged-mode mitigation is in place, the disable can be lifted. Dale notes that current single-worker conversion speed is tolerable — so this work is "restore the prior capability and confirm nothing regresses" rather than "expected to deliver a big win."

Everything else — AI tagging, XML export, XML import — is profiled for the record but explicitly not in scope for optimisation in this phase. Crate Builder and Set Planner are excluded from the harness entirely (see "Out of scope" below).

---

## Profile-first principle

Every optimisation in this phase must trace to a measurement. The brief commits to the measurement step; specific optimisation work is scoped only after the baseline is in. This is not a phase for "common optimisation patterns applied speculatively" — caching, virtualisation, lazy loading, parallelisation, etc. are all candidates if and only if measurement points at them.

The phase has an explicit early-close path: if the baseline shows nothing meaningfully slow in the analysis stage, the brief commits to closing the phase with the baseline report as the deliverable, rather than inventing optimisation work to justify the phase existing.

---

## Out of scope

Explicitly NOT part of Phase 6d:

- **Crate Builder and Set Planner profiling or optimisation.** These modules (Phases 5a and 5b) have never been exercised against a real library end-to-end. They're in a pre-validation state, not a pre-optimisation state. Profiling them risks surfacing functional bugs that need a dedicated dogfooding session (captured as `feature/dogfood-crates-and-sets`). You can't meaningfully measure a system you haven't proven works.

- **AI tagging optimisation.** The current 20-track batches against Anthropic are sufficient for now. Any change here (batch size tuning, parallel API calls, prompt token efficiency) gets its own scoped session. AI tagging IS profiled in 6d for the record — we capture wall-clock, token usage, and per-track cost — but no code changes for performance.

- **UI responsiveness profiling.** Frame-time, paint cost, render-blocking JS are a different toolset (browser dev tools, Lighthouse, React Profiler) and a different conversation. Deferred to Phase 6e (UI Polish & Design) where the toolset already lives.

- **Optimisations driven by intuition or "common patterns" rather than measurement.** Any optimisation must name the bottleneck it addresses and predict the expected gain before implementation.

- **Refactoring for performance reasons alone without a measurement.**

---

## Test corpus

**Source folders** (in order, on the external collection drive):

1. `/Volumes/collection/music/downloads/soulseek/complete/Panorama_Bar_Playlist_02_Lakuti/`
2. `/Volumes/collection/music/downloads/soulseek/complete/Panorama_Bar_Playlist_03_Martyn/`
3. `/Volumes/collection/music/downloads/soulseek/complete/Panorama_Bar_Playlist_04_Josey_Rebelle/`
4. `/Volumes/collection/music/downloads/soulseek/complete/Panorama_Bar_Playlist_05_Nick_Höppner/`

**Pre-existing state at session start:**

- DB contains ~30 tracks from Session 28's confidence-threshold verification.
- `rekordbot_library/` (at `/Volumes/collection/REKORDBOT/rekordbot_library/`) contains the organised output for `Panorama_Bar_Playlist_01_Tama_Sumo/`, not yet imported to Rekordbox.

This is a realistic starting state, not a fresh DB. The baseline numbers will reflect "process new folder against existing library" rather than "process new folder into empty DB" — which is the case we actually care about going forward.

**Run plan:**

| Run | Folder | Mode | DB & library | Purpose |
|-----|--------|------|--------------|---------|
| Baseline 1 | 02_Lakuti | packaged | real | Primary baseline against real library state |
| Baseline 2 | 03_Martyn | packaged | real | Second data point — confirms run-to-run consistency |
| Re-measure 1 | 04_Josey_Rebelle | packaged | sacrificial | First post-optimisation measurement |
| Reserve | 05_Nick_Höppner | packaged | sacrificial | Held back. Use cases: (a) re-run 02 or 03 on sacrificial setup for a direct A/B against baseline; (b) final confirmation pass against the real library if optimisations are solid |

**Consequence to flag:** Baselines 1 and 2 advance Dale's real library as a side effect. This is intentional (real-state measurement matters), but the brief makes it explicit so the disk state evolution isn't a surprise.

**Sacrificial environment:** For post-optimisation runs, the harness sets `REKORDBOT_DB_URL` and `REKORDBOT_OUTPUT_DIR` (or whichever env var controls the organisation output root) to paths under `~/Library/Application Support/rekordbot/perf/`. The real library and DB remain untouched. Sacrificial setup must mirror real setup in all other ways: same code, same packaged mode, same external drive for source files. Only the DB path and output path differ.

---

## Profiling harness architecture

The harness is a thin instrumentation layer over the existing pipelines. It does not change pipeline behaviour. Each pipeline emits structured timing records to a known sink; the harness collects and reports them.

**Design constraints:**

- **Cheap to run.** Per-stage `time.perf_counter()` deltas and dict accumulators only — no cProfile, no tracing in the inner loop. Profiling overhead must be small enough that timings reflect real work, not the harness itself.
- **Always-on or opt-in?** Opt-in. The harness is enabled by an env var (e.g. `REKORDBOT_PERF_RECORD=1`). When unset, instrumentation is a no-op. This lets the same code path run in production without overhead.
- **Sink: structured JSON file.** When enabled, timing records are appended to `~/Library/Application Support/rekordbot/perf/run-<timestamp>.jsonl`. One JSON object per line, one line per timed event. Easy to parse with Python or jq, no DB writes in the hot path.
- **Works in packaged mode.** This is the mode we care about. The env var is set via the existing config-manager → env-var bridge (Phase 6a) or by running the packaged app with the env var prepended.
- **Records context, not just timings.** Each record includes: pipeline stage, track ID or file path, wall-clock duration, optional payload (file size, BPM result, ffprobe duration, librosa parameters used). Context lets us slice the data after the fact rather than re-running.

**Stages instrumented (Phase 6d scope):**

| Pipeline | Stages timed |
|----------|--------------|
| Ingestion | per-file: ffprobe inspect → conversion decision → ffmpeg convert → file hash → DB insert |
| Analysis | per-track: audio load (librosa) → BPM detect → key detect → DB update → tag write (if enabled) |
| AI tagging | per-batch: prompt build → API call → response parse → DB update; plus token usage per batch |
| XML export | whole-pipeline: collection build → playlist build → file write |
| XML import | whole-pipeline: parse → match → conflict detect → DB apply |

**Stages NOT instrumented** (out of scope as listed earlier):
- Crate Builder (Phase 5a) — module not in harness
- Set Planner (Phase 5b) — module not in harness
- UI rendering / frontend — different toolset, deferred to 6e

**Reporting:**

A separate Python script (`scripts/perf-report.py` or similar) reads the JSONL file and produces a summary. Summary format: per-pipeline aggregate (total wall-clock, per-stage breakdown, percentiles where N is large enough to be meaningful, e.g. p50/p95 of analysis-per-track timings). Output as markdown, suitable to commit to `docs/perf/`.

---

## Build order

**Step 1 — Profiling harness scaffolding** (1 commit)

Create `backend/services/perf.py` (or `backend/perf/`). Defines:
- A `PerfRecorder` class that wraps `time.perf_counter()` into a context manager and writes records to the JSONL sink. No-ops when `REKORDBOT_PERF_RECORD` is unset.
- Stage-name constants so we don't fat-finger string keys across the codebase.
- A `get_recorder()` singleton accessor for use throughout services.

Tests: unit tests for the recorder (timing accuracy, no-op behaviour when disabled, JSONL format correctness, file rotation if relevant). Pure logic — TDD candidate.

**Step 2 — Instrument the pipelines** (1 commit per pipeline, ~5 commits)

For each pipeline in the table above, add `with recorder.stage(...)` blocks at the timed boundaries. No business logic changes. One commit per pipeline keeps the audit trail clean and reverts cheap.

Order: ingestion → analysis → AI tagging → XML export → XML import.

Tests: each commit verifies the existing test suite still passes. New tests not required for the instrumentation itself — the harness has its own tests from Step 1; the pipelines are unchanged in behaviour.

**Step 3 — Reporting script** (1 commit)

Create `scripts/perf-report.py`. Reads a JSONL file, produces a markdown summary. Pure logic over data — TDD candidate. Fixture: a small synthetic JSONL file with known values; script's output is verified against a golden markdown snippet.

**Step 4 — Baseline measurement pass** (1 commit)

Run the harness end-to-end against `Panorama_Bar_Playlist_02_Lakuti/` and then `_03_Martyn/`. Both in packaged mode, against the real DB and library. Run the report script over each JSONL. Commit both reports to `docs/perf/baseline-02-lakuti.md` and `docs/perf/baseline-03-martyn.md`.

This commit also writes a short `docs/perf/README.md` explaining the methodology, the harness, the test corpus, and how to reproduce.

**Step 5 — DECISION POINT**

Read the baseline reports. Based on what they show, one of two paths:

- **Path A — bottleneck identified.** Scope optimisation work. Continue to Step 6.
- **Path B — nothing meaningfully slow.** Document why in the baseline README. Skip to Step 8.

This decision is made jointly between Dale and Claude in chat, not by CC. The brief commits to making the decision explicit and recording the rationale.

**Step 6 (conditional) — Targeted optimisations** (1+ commits, scope set at decision point)

Likely candidates if the bottleneck is analysis, ranked by Claude's prior intuition (subject to revision once baselines are in):
- (a) Re-enable concurrent conversion in ingestion (low risk, restores prior capability, named in CLAUDE.md line 475 as a 6d candidate)
- (b) Concurrent analysis workers — if librosa work is CPU-bound, a worker pool sized to physical cores should give roughly linear speedup
- (c) Reuse the audio decode between BPM and key detection — both currently load the file independently
- (d) librosa parameter tuning (hop_length, sr downsampling, etc.) for acceptable accuracy trade-off

(a), (b), and (c) are likely first targets. (d) is a scope-expansion that needs explicit sign-off — it touches detection accuracy, not just speed.

Each optimisation commit:
- Names the measured bottleneck it addresses (citing baseline report)
- States the predicted gain
- Includes any new or updated tests
- Notes regression risk

**Step 7 (conditional) — Post-optimisation measurement pass** (1 commit)

Run the harness against `_04_Josey_Rebelle/` in packaged mode, against the sacrificial DB and library. Generate the report. Commit to `docs/perf/post-opt-04-josey-rebelle.md`. Write a delta document (`docs/perf/delta.md`) comparing baselines to post-opt numbers, with explicit per-stage before/after for the stages that were optimised.

If `_05_Nick_Höppner/` is needed for the reserve scenarios (direct A/B or real-library confirmation), do that here as a follow-up commit.

**Step 8 — Phase close** (1 commit)

- Update `CLAUDE.md`: mark 6d done in Phased Build Plan, update Current Status block to 6e, append any new "Known Issues / Don't Touch" lines surfaced by the work (e.g. "concurrent conversion re-enabled with N workers; pipe-deadlock mitigation is the StreamHandler-removal in packaged mode").
- Update `SESSIONS.md` with the session log.
- Mark feature brief complete.
- Phase-completion checklist sweep, merge prep, merge to develop with `--no-ff` and `phase-6d-complete` tag.

---

## Acceptance criteria

The phase closes when ALL of the following are true:

- [ ] Profiling harness exists, has unit tests, is opt-in via env var, and is verified to be a no-op when disabled
- [ ] All in-scope pipelines (ingestion, analysis, AI tagging, XML export, XML import) emit timing records when the harness is enabled
- [ ] Reporting script exists with tests
- [ ] Baseline reports for 02_Lakuti and 03_Martyn committed under `docs/perf/`
- [ ] Decision point recorded in the baseline README: either bottleneck identified with optimisation plan, OR explicit "no meaningful bottleneck found, closing phase" with rationale
- [ ] If Path A: each optimisation has a documented before/after delta, and the post-optimisation report is committed
- [ ] Concurrent conversion re-enabled OR explicitly deferred with reason documented (this is a brief-level commitment regardless of which path the decision point takes — see secondary deliverable note in "What this phase does")
- [ ] pytest suite passes with no skipped tests outside the existing ignore set
- [ ] mypy clean, ruff clean, pre-commit hooks all pass
- [ ] CLAUDE.md updated to reflect new state
- [ ] SESSIONS.md updated with phase-close session log entry
- [ ] Phase merged to develop, tagged `phase-6d-complete`

---

## TDD candidates

Pure-logic pieces that should have tests written before implementation:

- `PerfRecorder` class — timing record format, JSONL serialisation, no-op-when-disabled behaviour, context-manager exit handling on exception
- Report aggregation functions — percentile calculations, per-stage rollups, markdown rendering against golden fixtures
- Any new concurrency primitives introduced for analysis or conversion (a `WorkerPool` wrapper, etc.) — concurrency contract tested with deterministic inputs

Integration-style (test after, not before):
- The instrumented pipelines themselves
- The end-to-end harness runs against fixture audio
- Anything that touches the filesystem or subprocess

---

## Risks

- **Profiling overhead may swamp real measurements.** Mitigation: `time.perf_counter()` and dict accumulators are cheap; the JSONL writer buffers and writes once per record (not per byte). If overhead becomes visible — say, instrumentation accounts for >2% of stage wall-clock — the harness is over-instrumented and needs scope cut.

- **Dev mode vs packaged mode discrepancies.** Phase 6c proved these matter (stdout pipe deadlock, ffprobe path resolution, uvloop GIL issues). Measurements must be taken in packaged mode, not dev mode. The harness must be tested in both modes during Step 1 to confirm it works in packaged before any measurement pass starts.

- **External-drive I/O variability.** `/Volumes/collection/` is an external drive. I/O timings will vary based on whether the drive's read cache is warm, whether the system is doing other I/O, etc. Mitigation: report run-to-run variance (the 02 and 03 baselines exist partly to surface this), note disk in the report header, accept that per-track times will have measurable variance.

- **Concurrent conversion re-enable could resurrect the pipe deadlock.** Mitigation: the StreamHandler-in-packaged-mode mitigation from Phase 6c is the foundational fix. Re-enabling concurrency tests whether that fix was complete. If the deadlock returns at higher concurrency, treat that as a separate diagnosis problem, not a Phase 6d optimisation — may need to revert and scope a focused investigation.

- **Optimisations may regress correctness.** Mitigation: every optimisation runs the full pytest suite before commit. For analysis changes specifically, BPM and key detection have existing tests against known audio fixtures — those guard against accuracy regressions from librosa parameter changes. If accuracy guards aren't tight enough for confidence (e.g. ±0.5 BPM tolerance), tighten them before changing parameters.

- **Sacrificial DB drift from real DB.** The post-opt pass on a sacrificial DB measures against an empty starting state, while baselines measured against a 30-track existing state. This is a real apples-to-oranges concern. Mitigation: the sacrificial setup optionally seeds the DB from a snapshot of the real DB before the baseline runs. Add this to Step 7 if the delta-vs-baseline comparison is materially affected. Decision deferred to the decision point.

---

## Claude Code prompt scaffolding

CC prompts will be written per-step at implementation time, not upfront. Each step is scoped enough to be a 1–2 commit unit of work. The "explain before you implement" rule applies per-step: Claude (oversight) drafts the prompt, Dale runs it in CC, CC reports back, Claude reviews output via filesystem tools before approving the next step.

General constraints to bake into every Phase 6d CC prompt:
- Do not optimise outside the named bottleneck for the current commit
- Do not touch Crate Builder or Set Planner code
- Do not touch UI / frontend code
- Do not run the build unless explicitly asked
- Report exact pytest counts and any new/changed tests

---

## What "done" looks like

A `docs/perf/` directory containing:
- `README.md` — methodology, harness, corpus, decision rationale
- `baseline-02-lakuti.md` — first baseline report
- `baseline-03-martyn.md` — second baseline report
- `post-opt-04-josey-rebelle.md` — post-optimisation report (Path A only)
- `delta.md` — before/after summary (Path A only)
- Optionally `post-opt-05-nick-hoppner.md` (reserve usage)

Plus a working profiling harness that can be re-run against any future corpus by setting one env var. The harness outlives the phase — it's the tool for any future performance investigation.
