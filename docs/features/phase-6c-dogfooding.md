# Feature: UI Review & Bug Fixing (Dogfooding)
**Branch:** `feature/phase-6c-dogfooding`
**Status:** Not Started
**Phase:** 6c
**Depends on:** Phase 6b (complete)

---

## Goal

Use rekordbot with a real DJ library and fix everything that breaks. This phase is intentionally open-ended — the scope is determined by real-world use, not a pre-written specification.

The immediate priority is making the **ingestion → organisation → export** loop work end-to-end, since that's the workflow Dale wants to start using right away. Secondary features (crates, sets, XML import) get tested and fixed after the core loop is solid.

---

## Known Bugs (from 6b manual testing)

These are the starting backlog. More will be discovered during dogfooding.

### Bug 1: Organisation not applied after ingestion
**Observed:** Files converted and tagged correctly but not placed into the expected folder structure (Artist/Album/etc).
**Hypothesis:** Organisation is a separate step (propose → approve) that wasn't triggered, OR the organiser has a path resolution issue in packaged mode.
**Investigation:** Check whether the organiser pipeline runs in packaged mode. Check the folder template resolution. Test the propose → approve flow manually from the UI.

### Bug 2: Ghost tracks after file deletion
**Observed:** Deleting converted files from disk leaves orphaned DB records. UI shows tracks without details. No way to remove them.
**Root cause:** The database is the source of truth — there's no mechanism to detect or clean up tracks whose files no longer exist on disk.
**Fix needed:** Either (a) a "Delete track" action in the UI that removes the DB record (and optionally the file), or (b) an orphan detection sweep that flags/removes tracks with missing files, or (c) both.

### Bug 3: Re-import blocked by ghost tracks
**Observed:** Re-importing the same files fails because SHA-256 duplicate detection collides with orphaned DB records.
**Root cause:** Duplicate detection checks the hash against the DB but doesn't verify the existing file is still on disk.
**Fix needed:** Duplicate detection should check whether the matched file actually exists. If the existing file is missing, either update the existing record's path or allow re-import.

---

## Approach

This phase does NOT follow the usual feature-brief-then-implement pattern. Instead:

1. **Use the app** — Import real tracks, run through the full pipeline, take notes on what breaks or feels wrong.
2. **Triage** — For each issue, decide: fix now (blocks core workflow), fix later (annoying but not blocking), or defer (Phase 6d/6e territory).
3. **Fix in small commits** — Each bug fix or improvement is its own commit. No big multi-day implementation sessions.
4. **Test as you go** — If a fix touches service-layer logic, add or update tests. UI-only fixes don't need tests.
5. **Rebuild and retest** — After a batch of fixes, `make build-dmg` and verify the fixes work in the packaged app too.

### Priority order for testing
1. **Ingest files** — Drop folder, convert, verify output files
2. **Organisation** — Propose, review, approve, verify folder structure
3. **Analysis + AI tagging** — BPM/key detection, genre/mood inference
4. **Export** — Generate Rekordbox XML, import into Rekordbox, verify metadata
5. **Import** — Import existing Rekordbox XML, check matching and conflicts
6. **Crates** — Create from description, verify assignment
7. **Sets** — Plan a set, lock/shuffle, export
8. **Settings** — Change settings, verify persistence across restart

---

## Acceptance Criteria

Phase 6c is complete when:
- [ ] Dale can import a real folder of tracks, and they convert correctly
- [ ] Organisation proposes a sensible folder structure and moves files on approval
- [ ] Analysis detects BPM and key for all tracks
- [ ] AI tagging produces genre/mood/energy for all tracks
- [ ] Rekordbox XML export produces a valid file that Rekordbox imports correctly
- [ ] All three known bugs are resolved
- [ ] No showstopper bugs remain in the core workflow
- [ ] App data persists correctly across quit and relaunch
- [ ] No zombie processes after quit

The bar is "Dale is actively using the app with real data" — not "every edge case is handled."

---

## Out of Scope

- **Performance optimisation** — Phase 6d. If something is slow, log it, don't optimise it.
- **UI polish** — Phase 6e. If something is ugly but functional, leave it.
- **Code signing** — Phase 6f.
- **New features** — This phase fixes what exists. No new pipelines, no new AI prompts, no new UI panels.
- **Bootleg detection refinement** — Originally scoped here but can wait for 6e unless it causes false positives that break organisation.

---

## Notes

- The .dmg build pipeline is: `make build-dmg` (runs `scripts/build-dmg.sh`). Rebuild after each batch of fixes to verify in packaged mode.
- Dev mode testing (uvicorn + Vite) is faster for iteration. Use it for most bug fixing, then verify in packaged mode periodically.
- If a fix requires a schema change, add a new Alembic migration. The infrastructure from Phase 6b handles this automatically.
- This phase may produce a lot of small commits. That's fine — each fix should be atomic and independently revertable.
