# Feature: Scope Reduction — Retire Crate Builder, Set Planner, and Key Detection
**Branch:** `feature/scope-reduction`
**Status:** Closing — Commit 6 (re-baseline) outstanding.
**Phase:** 6d.1
**Depends on:** Phase 6d (complete, merged at `phase-6d-complete` tag)

---

## What this phase does

Phase 6d's measurement-then-decide outcome was scope reduction, not optimisation. This phase executes that outcome.

Three things happen:

1. **Soft-retire Crate Builder (Phase 5a) and Set Planner (Phase 5b).** Their UI entry points, API routes, and DB-touching call paths from the rest of the app are removed. Service code, models, tests, and DB tables are preserved verbatim. The features are not deleted; they are deactivated.

2. **Remove key detection from the analysis pipeline.** The `analysis_detect_key` stage and its DB writes are removed from `analyse_track()`. `KeyDetector` and `key_notation.py` remain in the codebase as dormant code reachable only by direct call.

3. **Refocus the app's value proposition** on ingest → analyse (BPM only) → AI-tag → organise → Rekordbox XML export and import. CLAUDE.md's Project Overview and the project plan are updated to match.

After all changes land, a re-baseline against `Panorama_Bar_Playlist_04_Josey_Rebelle/` confirms the expected ~25× analysis-stage speedup in practice.

**Source of truth for scope:** the Decision Point section in `docs/perf/README.md` (Phase 6d Step 5). That document is the lock; this brief sequences its execution.

---

## Why

Two independent Phase 6d baselines (76 tracks total, Lakuti + Martyn) showed `analysis_detect_key` consumes 94–96% of analysis-per-track wall-clock. The other inner stages of analysis are negligible — librosa decode 1.9–3.4%, BPM detection 2.0–2.1%, tag reading 0.1%, DB update rounding-error.

The Phase 6d brief's named optimisation candidate (re-using the librosa decode between BPM and key detectors) caps at ~2–3% improvement. Concurrent analysis workers would give a further 4–6× on top via a worker pool. Both are real, both are viable — but both assume the work needs doing at all.

The Decision Point identified that key data inside rekordbot is consumed by four things: Crate Builder (5a), Set Planner (5b), the track-table UI column, and the `Tonality` attribute in Rekordbox XML export. The 5a/5b features were trialled in Session 34 against the real library and architecturally mismatch realistic workflow (AI clustering assumes a comprehensive analysed library; realistic ingestion is a few hundred new tracks at a time against a much larger Rekordbox-managed library known through listening, not algorithmic mining). The UI column and `Tonality` attribute are surface-level — informational, not load-bearing. Rekordbox performs its own key analysis on import.

Removing the consumers makes the producer (key detection) deadweight. The cheapest correct optimisation is to stop doing the work. Expected result: analysis stage drops from ~11.9s/track to ~0.5s/track, a 25× speedup on the dominant phase, without optimising a single line of code.

The full reasoning, including the architectural critique of 5a/5b, lives in `docs/perf/README.md` under "Decision point (Phase 6d Step 5)". This brief does not re-litigate it; it executes it.

---

## In scope

Eight deliverables, derived from the Decision Point's "In scope for the scope-reduction phase" list. Items 1–4 came from the Decision Point as written; items 5–7 are concrete changes the Decision Point named; item 8 is the AI-prompt verification that was open at brief-drafting time and is now resolved (see below).

1. **Soft-retire Crate Builder.** Remove `CrateSidebar`, `CrateCreateDialog` from `App.tsx`. Deregister `crates_router` from `backend/main.py`. Service code (`crate_assigner.py`, `crate_manager.py`, `crate_prompt_builder.py`, `key_compatibility.py`), models (`Crate`, `CrateTrack`), tests, and DB tables all preserved.

2. **Soft-retire Set Planner.** Remove `SetPlannerView`, `SetCreateDialog`, `SetListPanel` from `App.tsx`. Deregister `sets_router` from `backend/main.py`. Service code (`set_planner.py`, `set_prompt_builder.py`, `bpm_transition.py`), models (`SetPlan`, `SetTrack`, `SetSegment`), tests, and DB tables all preserved.

3. **Remove `analysis_detect_key` from the analysis pipeline.** Delete the Step 4 (key detection) block in `analyse_track()` in `backend/services/analysis.py`. Remove `Stage.ANALYSIS_DETECT_KEY` emissions. `track.key` and `track.key_confidence` are no longer written by ingestion-driven analysis runs.

4. **Remove the key column from the track table UI.** `TrackTable.tsx` no longer displays Key; column visibility menu no longer exposes it; sorting/filtering on key no longer wired up. (The DB column persists — see Open decisions below.)

5. **Remove the `Tonality` attribute from the Rekordbox XML export.** `xml_schema_mapper.py` no longer emits `Tonality`. Existing exporter tests must be updated to reflect the removal. (Rekordbox will perform its own key analysis on import — confirmed in the Decision Point reasoning.)

6. **Remove crate/set hooks from the XML exporter.** Phase 5a integrated crate-as-playlist export; Phase 5b integrated set-as-ordered-playlist export. Both must be removed from the XML export pipeline (no crate playlists, no set playlists). Auto-generated folder-hierarchy playlists from Phase 4 remain unchanged.

7. **Remove key from the AI tagging prompt.** Three coupled changes in one commit:
   - In `prompt_builder.py:SYSTEM_PROMPT`, remove the line `"BPM and key are strong genre signals (e.g. 170+ BPM suggests DnB or hard techno; 120-126 BPM with minor key suggests deep/tech house)."` and replace with an equivalent BPM-only line.
   - In `prompt_builder.py:build_track_summary()`, remove the `key_display` parameter and the `("Key", key_display)` row from the field list.
   - In `prompt_builder.py:build_batch_message()`, remove the `key_displays` parameter and its `get()` resolution.
   - In `ai_tagger.py:_process_batch()`, remove the `key_displays` construction loop, the `key_to_display` import, and the `key_displays` argument to `build_batch_message`.

8. **Re-baseline against `Panorama_Bar_Playlist_04_Josey_Rebelle/`.** Same packaged-mode harness flow as Baselines 1 and 2. Output committed as `docs/perf/post-scope-reduction-04-josey-rebelle.md` plus `docs/perf/delta.md` documenting before/after wall-clock change.

In addition (project-state housekeeping, not in the Decision Point but required by phase-completion-checklist):

- Update CLAUDE.md (Project Overview, Phased Build Plan, Known Issues / Don't Touch).
- Update `docs/rekordbot-project-plan.md` to reflect the new value proposition.
- Update SESSIONS.md.
- Mark the feature brief done.

---

## Out of scope

Explicitly NOT part of Phase 6d.1:

- **Hard deletion of Crate Builder or Set Planner code, models, tests, or DB tables.** The Decision Point committed to soft retirement specifically so the work can be revived if the architectural assumption changes (e.g. once the library has been comprehensively analysed and the clustering assumption becomes valid). Hard deletion is a future decision, not a 6d.1 decision.

- **Algorithmic improvements inside `key_detector.py`.** Moot once the consumer is gone. Code preserved for any future revival.

- **Re-enabling concurrent conversion.** Named as a Phase 6d secondary deliverable and explicitly deferred at Phase 6d close (CLAUDE.md "Known Issues" entry). On a post-scope-reduction analysis pipeline running at ~0.5s/track, the absolute savings from concurrent conversion are small. Revisited in a future scoped session if profiling against the post-scope-reduction baseline shows it matters.

- **Dropping the `key` and `key_confidence` columns from the `Track` model.** D1 locked as KEEP (see Open decisions below). No Alembic migration in this phase.

- **Migration of existing key data in the DB.** The 30 historical tracks plus Baseline 1 and 2 additions have populated key data. With the column kept (per D1), no migration is needed.

- **UI polish or design changes beyond the strict subtractions named above.** Removing `CrateSidebar` will leave a layout gap. The minimum acceptable response is "the layout still works without it" — full re-design is Phase 6e.

- **Touching `KeyDetector`, `key_notation.py`, or any key-related test in those services.** They remain as dormant code reachable by direct call. Their tests continue to pass because the functions themselves are unchanged.

---

## Soft retirement — semantics

The term "soft retire" is used informally in the Decision Point and SESSIONS.md. This brief locks the exact meaning so implementation has no wiggle room:

**Preserved verbatim:**
- Service modules (`crate_*.py`, `set_*.py`, `key_compatibility.py`, `bpm_transition.py`, `set_prompt_builder.py`, `crate_prompt_builder.py`)
- Models (`crate.py`, `set_plan.py`)
- Tests for the above (in `backend/tests/`)
- DB tables created by these models (Alembic baseline migration unchanged; runtime `create_all` / `upgrade head` still creates them in fresh installs)
- The 5a/5b feature briefs in `docs/features/` (untouched, marked as superseded by 6d.1 rather than deleted)

**Removed:**
- Route registrations in `backend/main.py` (`app.include_router(crates_router)` and `app.include_router(sets_router)`)
- Frontend components from `App.tsx` (imports and JSX)
- The XML exporter's crate/set integration code paths
- Any keyboard shortcuts, context menu items, or sidebar entries that route to the removed features

**Consequence:** the `/api/crates/*` and `/api/sets/*` HTTP endpoints return 404 in 6d.1. The route modules themselves (`backend/routes/crates.py`, `backend/routes/sets.py`) remain in the repo. They can be re-registered with one line each if the features are revived.

This is deliberate. Re-registration is one line. Re-implementation from a Git deletion would be a hard rollback. The cost of keeping deactivated code is small; the cost of premature deletion is large if the architectural assumption flips later.

---

## Build order

Six commits, each tightly scoped. The phase opens on `feature/scope-reduction` (already created from `develop`). The brief itself lands as commit 0 before any code change, per the project's "explain before you implement" principle.

**Commit 0 — Feature brief**
- `docs/features/phase-6d.1-scope-reduction.md` (this file).
- No code change. Establishes the lock before implementation.

**Commit 1 — UI removal (frontend only)**
- `App.tsx`: remove imports of `CrateSidebar`, `CrateCreateDialog`, `SetPlannerView`, `SetCreateDialog`, `SetListPanel`. Remove related state (`selectedCrateId`, `activeSetId`, `showCreateDialog`, `showSetCreateDialog`, `crateRefreshTrigger`, `setsRefreshTrigger`, `handleCrateCreated`, `handleSetCreated`, `handleSetSelect`, `handleBackToLibrary`). Remove the JSX for the sidebar, the conditional `SetPlannerView` render, and the two create-dialog modals. Adjust the header label logic.
- `TrackTable.tsx`: remove the Key column (header, body cell, sort, filter, column-visibility-menu entry).
- Frontend component files (`CrateSidebar.tsx`, `CrateCreateDialog.tsx`, `SetPlannerView.tsx`, `SetCreateDialog.tsx`, `SetListPanel.tsx`) **stay in the repo, unimported**. This matches the soft-retire principle on the backend.
- No test changes yet (backend tests still pass; frontend has no test suite).
- Run the dev server and confirm the app boots, the Library view renders, ingestion works, analysis works, and there's no console error from missing components. The layout gap from `CrateSidebar` removal is acceptable as-is — it goes into Phase 6e.

**Commit 2 — Route deregistration and XML exporter cleanup (backend, no pipeline change yet)**
- `backend/main.py`: remove the two `app.include_router(...)` calls for `crates_router` and `sets_router`. Remove their imports.
- `backend/services/xml_exporter.py` and `backend/services/xml_builder.py`: remove the crate-as-playlist and set-as-ordered-playlist code paths. The auto-generated folder-hierarchy playlists from Phase 4 remain.
- `backend/services/xml_schema_mapper.py`: remove the `Tonality` attribute emission.
- Run the full pytest suite. Expect failures in:
  - XML exporter tests that assert on `Tonality` presence (update to assert absence)
  - XML exporter tests that assert on crate or set playlist generation (delete those assertions; tests for folder-hierarchy playlists remain)
  - Crate/Set route integration tests that hit the deregistered endpoints (mark with `pytest.mark.skip(reason="Routes deregistered in Phase 6d.1 — module preserved for future revival")` — do not delete)
- Tighten expectations: ruff clean, mypy no new errors against develop's baseline (the existing 21-error baseline is the bar).

**Commit 3 — Remove key detection from the analysis pipeline**
- `backend/services/analysis.py`: delete the `# Step 4: Detect key` block (lines roughly 268–276). Remove the `key_result` field from `AnalysisResult` (or keep as always-None for backward compatibility — locked at implementation time, lean is remove). Remove the `from backend.services.key_detector import KeyResult, detect_key` import.
- The `track.key` and `track.key_confidence` fields are no longer written during ingestion-driven analysis. Existing values in the DB remain (D1 keeps the columns).
- Tests:
  - `backend/tests/test_analysis.py` (or wherever the analysis pipeline tests live): remove assertions on key being populated post-analysis. Add a regression assertion: after running `analyse_track()`, `track.key` is None on a track that had no prior `track.key`.
  - The perf harness `Stage.ANALYSIS_DETECT_KEY` constant stays in `backend/services/perf.py` so historical JSONL files still parse, but it will no longer be emitted by new runs. The reporter handles missing stages gracefully (golden tests for "stage not present" already exist from Phase 6d).

**Commit 4 — Remove key from the AI tagging prompt**
- `backend/services/prompt_builder.py`:
  - Replace the "BPM and key are strong genre signals…" line in `SYSTEM_PROMPT` with: `"- BPM is a strong genre signal (e.g. 170+ BPM suggests DnB or hard techno; 120–126 BPM suggests deep or tech house)."` Note: the "minor key" half of the original hint is gone — accept the small accuracy cost (see Risks).
  - `build_track_summary()`: remove the `key_display` parameter and the `("Key", key_display)` row.
  - `build_batch_message()`: remove the `key_displays` parameter and the per-track lookup.
- `backend/services/ai_tagger.py`:
  - Remove the `from backend.services.key_notation import key_to_display` import.
  - In `_process_batch()`, remove the `key_displays` construction loop and the `key_displays` argument to `build_batch_message`.
- Tests:
  - `backend/tests/test_prompt_builder.py`: update tests that assert on key presence in the summary or system prompt. Add a regression test: `build_track_summary()` with a track that has `track.key = 1` produces a summary that does not contain the string "Key:".
  - `backend/tests/test_ai_tagger.py` (if it has tests that mock the prompt builder): update to match the new signature.

**Commit 5 — CLAUDE.md, project plan, supersession notes**
- `CLAUDE.md`:
  - Update Project Overview to remove crate-building and set-planning from the value proposition. New framing: ingest → analyse (BPM only) → AI-tag → organise → Rekordbox XML export and import.
  - Phased Build Plan: mark 6d.1 done. Update 6e's description to mention the layout gap from removed sidebar.
  - Tech Stack: no change (Anthropic SDK still used by AI tagging, even though crate/set use of it is now dormant).
  - Known Issues / Don't Touch: add an entry stating that 5a/5b are deactivated and must not be modified; reference this brief.
- `docs/rekordbot-project-plan.md`: update feature map and phased build plan to mirror CLAUDE.md.
- `docs/features/phase-5a-crate-builder.md` and `docs/features/phase-5b-set-planner.md`: add a header banner: `**Superseded by Phase 6d.1 — feature deactivated (soft retirement). See `phase-6d.1-scope-reduction.md`.**` Do not delete the briefs themselves.

**Commit 6 — Re-baseline and delta**
- Install the new `.app` to `/Applications/` (run `make build-dmg` then drag from the new `.dmg`). Verify the install timestamp before running.
- Take pre-run snapshots per `docs/perf/README.md` § Reproduction Step 2.
- Run the harness against `Panorama_Bar_Playlist_04_Josey_Rebelle/` in packaged mode against the real DB and library.
- Generate the reporter output. Write `docs/perf/post-scope-reduction-04-josey-rebelle.md` following the structure of `baseline-02-lakuti.md` and `baseline-03-martyn.md`.
- Write `docs/perf/delta.md`: per-stage before/after, expressed as both absolute (s/track) and relative (% change), comparing the new run against the mean of Baselines 1 and 2. Headline: analysis-stage wall-clock per track, and the % share that `analysis_detect_key` no longer occupies.
- Update `docs/perf/README.md` Run history table to add the new row.

**Phase close (post-commit-6, lands as part of commit 6 or as a small commit 7):**
- SESSIONS.md updated with the phase-close session log entry.
- Mark this brief complete (frontmatter status to `done`).
- Phase-completion-checklist sweep.
- Merge to develop with `--no-ff`, tag `phase-6d.1-complete`.

---

## Acceptance criteria

The phase closes when ALL of the following are true:

- [x] `App.tsx` does not import or render `CrateSidebar`, `CrateCreateDialog`, `SetPlannerView`, `SetCreateDialog`, or `SetListPanel`
- [x] `backend/main.py` does not register `crates_router` or `sets_router`
- [x] The `Tonality` attribute is absent from XML export output (verified by exporter tests against a fixture)
- [x] The XML exporter does not emit crate or set playlists (folder-hierarchy playlists still emitted)
- [x] `analyse_track()` does not call `detect_key()` and does not write `track.key` or `track.key_confidence`
- [x] `prompt_builder.py:build_track_summary()` does not emit a "Key:" row
- [x] `prompt_builder.py:SYSTEM_PROMPT` does not mention key
- [x] `ai_tagger.py:_process_batch()` does not construct or pass `key_displays`
- [x] Service modules and tests for Crate Builder, Set Planner, `KeyDetector`, and `key_notation.py` are unchanged on disk *(softened mid-phase: minimal-touch-for-compilation in `crate_assigner.py`, `set_prompt_builder.py`, and `routes/sets.py` — see Session 35 in SESSIONS.md for the precedent)*
- [x] Pytest suite passes. New test count documented in commit message and SESSIONS.md. Skipped tests (route-deregistration integration tests) are explicitly marked with a reason.
- [x] mypy: no new errors against develop's baseline (21-error baseline at Phase 6d close holds — Phase 6d.1 should not add errors and ideally clears a few) — currently 15 errors (down 6)
- [x] Ruff clean, pre-commit hooks all pass
- [ ] The packaged `.app` boots, completes ingestion of `_04_Josey_Rebelle/`, completes analysis (BPM only), completes AI tagging, completes XML export to a Rekordbox-importable file
- [ ] `docs/perf/post-scope-reduction-04-josey-rebelle.md` committed
- [ ] `docs/perf/delta.md` committed showing the analysis-stage speedup
- [ ] `docs/perf/README.md` Run history table updated
- [x] CLAUDE.md updated (Project Overview, Phased Build Plan, Known Issues)
- [x] `docs/rekordbot-project-plan.md` updated
- [x] 5a and 5b briefs have supersession headers
- [x] SESSIONS.md updated with the phase-close entry
- [x] This brief marked done
- [ ] Branch merged to develop, tagged `phase-6d.1-complete`

---

## TDD candidates

This phase is mostly removal and verification, not new pure-logic introduction. The TDD surface is narrow:

**Test-first (small):**
- `test_prompt_builder.py`: regression test that `build_track_summary()` with `track.key` populated does not emit "Key:" anywhere in the output.
- `test_prompt_builder.py`: regression test that `SYSTEM_PROMPT` does not contain the substring "key" (case-insensitive). This is the simplest possible guard against accidental re-introduction.
- `test_analysis.py`: regression test that `analyse_track()` on a fixture with no prior `track.key` leaves `track.key` as None post-analysis.
- `test_xml_schema_mapper.py`: regression test that a track with `track.key = 1` does not produce a `Tonality` attribute on the emitted XML element.

**Test-after (update existing):**
- All XML exporter tests that asserted on `Tonality`, crate playlists, or set playlists.
- All analysis pipeline tests that asserted on `track.key` being populated.
- All AI tagging tests that exercised the `key_displays` parameter.
- Route integration tests for `/api/crates/*` and `/api/sets/*` — mark skipped with reason.

**Out of TDD scope:**
- The re-baseline measurement (commit 6). It's a manual run, not a unit test.
- The CLAUDE.md and project-plan updates. Reviewed manually, not via test.

---

## Risks

- **AI prompt accuracy regression.** Removing the "120–126 BPM with minor key suggests deep/tech house" hint reduces the genre-classification signal available to Claude. The hint was non-trivial — it specifically called out a genre cluster where BPM alone is ambiguous (deep house, tech house, melodic house all sit in that range). Mitigation: the AI tagging is reviewable by Dale in the UI and revertable per-track via Phase 3's `source_genre` preservation. If the post-6d.1 baseline AI tags show a meaningful accuracy drop in the 120–126 BPM range, the prompt can be refined in a follow-up commit without re-introducing key data — e.g. by asking Claude to weight artist and label more heavily in that BPM band. **The brief accepts this risk** rather than working around it, because half-retiring the key data (kept for AI prompt, removed for everything else) would be worse — the column would be ambiguously alive.

- **Test surface fallout larger than expected.** Phase 5a added 108 tests and Phase 5b added 116 (per SESSIONS.md Session 34 §4). Most of those test the soft-retired services and continue to pass — the code paths are unchanged. But integration tests that exercise full ingest → analyse → crate-assign or full ingest → analyse → set-plan flows will fail and need either updating or skipping. Mitigation: in Commit 2, run pytest and inventory the failures before fixing anything. If the failure list exceeds ~20 tests, pause and re-scope. If it's under ~10, fix in place.

- **The re-baseline may not show the predicted 25× speedup.** The prediction is based on baselines where `analysis_detect_key` was 94.4% (Lakuti) and 96.0% (Martyn) of analysis-per-track wall-clock. Removing it should drop analysis to ~0.5s/track, equivalent to a 25× speedup on the dominant phase. If the actual delta is materially smaller (say, <10×), something is wrong — either there's residual key-detection work happening that the perf harness missed, or another stage has expanded to fill the void, or the corpus characteristic differs more than expected from Baselines 1 and 2. Mitigation: the `delta.md` documents whatever the actual result is. If the actual result is anomalous, it gets its own diagnostic session in 6d.1, not a workaround.

- **Stale `/Applications/` install at re-baseline time.** Session 33 lost ~90 minutes to this exact failure mode. Mitigation: `docs/perf/README.md` § Reproduction Step 1 is the explicit pre-flight check. Commit 6 must verify the install timestamp before running the harness, not after.

- **The Decision Point's "verify the AI tagging prompt does not consume key" item was open at brief-drafting time and is now resolved: it does consume key, in three places.** The scope of the prompt-builder change is therefore non-trivial, not a one-line removal. This is reflected in Commit 4 above. The brief flagged it specifically because had the verification flipped (no key consumption), Commit 4 would have been a no-op verification commit. As things stand, Commit 4 has a real diff with real test impact.

- **Soft retirement leaves dormant code paying maintenance cost.** Future Python version upgrades, FastAPI upgrades, or SQLAlchemy upgrades may require touching dormant code to keep it compiling. The 11 pre-existing mypy errors in Phase 5a/5b code (CLAUDE.md "Known Issues") will persist after 6d.1 and stay on the develop baseline. Mitigation: accepted. The cost of dormant code is small relative to the cost of premature deletion. If the dormant maintenance cost becomes irritating during 6e or 6f, hard deletion can be revisited then.

- **Removing the Key column from `TrackTable.tsx` may reveal layout assumptions in column widths or scroll behaviour.** Mitigation: Commit 1 includes a manual dev-server boot to confirm the table renders without console errors. Layout polish is Phase 6e.

---

## Open decisions

One explicit decision the brief asks Dale to lock before implementation starts:

**D1 — Keep or drop the `key` and `key_confidence` columns on `Track`?**

- **Keep (LOCKED — chosen):** No Alembic migration. Historical key data preserved. Column dormant — not written, not read, not displayed. Cost: one nullable INT column and one nullable FLOAT column on every Track row. Negligible storage cost.
- **Drop (not chosen):** Alembic migration required. Historical key data destroyed. Slightly cleaner schema. Cost: migration must be written, tested, and rolled forward against the real DB. Drift risk between fresh installs and migrated installs.

**Decision (Session 35):** KEEP. The migration is non-trivial and the dormant column is cheap. If `KeyDetector` is ever revived, having the existing data still in the DB is a head start. Dropping is reversible only by re-running analysis on the entire library.

Commit 3 proceeds as written. No additional migration commit needed.

---

## Claude Code prompt scaffolding

CC prompts will be written per-commit at implementation time, not upfront. The "explain before you implement" rule applies per-commit: Claude (oversight) drafts the prompt, Dale runs it in CC, CC reports back, Claude reviews the output via filesystem tools before approving the next commit.

General constraints to bake into every Phase 6d.1 CC prompt:
- **Do not modify any file under `backend/services/crate_*.py`, `backend/services/set_*.py`, `backend/services/key_*.py`, or `backend/services/bpm_transition.py`.** Soft retirement preserves these verbatim.
- **Do not modify any test file under `backend/tests/test_crate_*.py`, `backend/tests/test_set_*.py`, `backend/tests/test_key_*.py`, or `backend/tests/test_bpm_transition.py`.** Same reason.
- **Do not delete `CrateSidebar.tsx`, `CrateCreateDialog.tsx`, `SetPlannerView.tsx`, `SetCreateDialog.tsx`, or `SetListPanel.tsx`.** Unimport them; leave the files in place.
- **Do not modify the Alembic baseline migration.** The schema does not change in this phase (D1 = keep).
- **Do not run the build (`make build-dmg`) unless explicitly asked.** The re-baseline in Commit 6 is the only step that requires a fresh build.
- **Do not introduce new dependencies, new modules, or new abstractions.** This phase is pure subtraction.
- **Report exact pytest counts, mypy error counts, and ruff status after every commit.** Track regressions vs develop baseline.

---

## What "done" looks like

A `develop` branch where:

- The app, when launched, presents a single-column library view: drop zone, import controls, processing queue, track table. No sidebar. No crate or set entry points anywhere in the UI.
- The track table has columns for ID, title, artist, album, label, year, genre, subgenre, mood, energy, BPM, AI confidence, AI status — but no Key.
- `/api/crates/*` and `/api/sets/*` return 404.
- The XML export emits a valid Rekordbox XML with no `Tonality` attribute, no crate playlists, and no set playlists. Auto-generated folder-hierarchy playlists are present.
- Analysing a new folder of tracks runs in ~0.5s/track average, not ~12s/track. AI tagging runs unchanged. XML export runs unchanged.
- `docs/perf/` contains: `README.md` (with updated run history), `baseline-02-lakuti.md`, `baseline-03-martyn.md`, `post-scope-reduction-04-josey-rebelle.md`, `delta.md`. Plus the existing JSONL files for forensic reproduction.
- CLAUDE.md's Project Overview describes the new five-stage value proposition.
- The 5a/5b briefs in `docs/features/` carry supersession headers but remain readable in full for any future revival session.
- Phase 6e starts from a smaller, faster, more focused codebase than Phase 6d ended on.

---

## Commit Log (actual)

1. `282edbd` — docs(6d.1): add scope-reduction feature brief
2. `52d5d0a` — chore(6d.1): remove Crate Builder, Set Planner, and Key UI surface area (frontend)
3. `3b30064` — chore(6d.1): deregister Crate Builder and Set Planner routes; remove Tonality, key_notation, and crate/set hooks from XML exporter
4. `2f67e90` — chore(6d.1): remove key detection from the analysis pipeline
5. `9389364` — chore(6d.1): remove key from the AI tagging prompt
6. (this commit) — chore(6d.1): housekeeping — documentation, supersession headers, vestigial UI cleanup
7. (commit 6, pending) — chore(6d.1): re-baseline analysis perf against Josey Rebelle corpus
