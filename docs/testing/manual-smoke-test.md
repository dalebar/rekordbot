# Manual Smoke Test

A repeatable checklist for verifying core rekordbot behaviour before any build is considered shippable.

**When to run:**
- Before starting a dogfooding session against a real library
- After every fix to a UI fundamental (scrolling, layout, drag-and-drop, persistence)
- Before every `develop` merge

**Test fodder:** A small folder of 20–30 FLAC files. Currently using subfolders of `/Volumes/collection/music/downloads/soulseek/complete/` (Panorama Bar playlist folders, ~24 tracks each).

**Mode:** Packaged `.app` from `/Applications/rekordbot.app`, never dev mode and never the mounted DMG.

**Convention:** Tick the box if the step passes. Note any observation under the step regardless of pass/fail. If a step fails, do not skip — note it and continue. The point is to surface all issues in one pass.

---

## Scope

This smoke test covers the **primary ingest → analyse → tag → organise loop**. It is intentionally focused on the workflow Dale uses day-to-day.

**Out of scope (deliberately):**
- Rekordbox XML export and import
- Crate building and set planning
- Alternative workflows (e.g. import XML first then add new tracks; manual metadata editing before organise)
- Performance assertions and timing baselines

Alternative workflows and regression scenarios will live in `docs/testing/test-scenarios.md` (not yet written). The smoke test stays focused so it stays fast.

---

## Pre-flight

- [ ] Repo is on `feature/phase-6c-dogfooding` with clean working tree
- [ ] `.app` modification timestamp is newer than the HEAD commit timestamp (or rebuild)
- [ ] `~/Library/Application Support/rekordbot/rekordbot.db` is either absent (fresh test) or contains only expected state
- [ ] `~/Library/Application Support/rekordbot/rekordbot.log` is either absent or rotated for a clean run
- [ ] `~/Library/Application Support/rekordbot/config.json` has a valid API key (Settings → Test API Key passes)
- [ ] No existing rekordbot process running (Activity Monitor check)

**Re-run policy:** Use a folder you haven't ingested before (e.g. a different Panorama Bar playlist for each run), OR clear the DB and output directory before starting. The smoke test assumes a clean import path so duplicate-detection logic doesn't muddy the results.

---

## 1. Launch

- [ ] Double-click `rekordbot.app` in `/Applications/`
- [ ] Window appears within 5 seconds
- [ ] Window shows "Connected to rekordbot backend vX.Y.Z" or equivalent connection-success indicator within 10 seconds
- [ ] No error dialogs, no crash reporter, no Gatekeeper warnings (right-click → Open if needed)
- [ ] `rekordbot.log` exists in Application Support after launch

**Observations:**

---

## 2. Window Layout (at default size)

- [ ] Window opens at a reasonable default size (~1280×800 or similar)
- [ ] Sidebar visible on the left (crate/playlist tree)
- [ ] Main content area shows track table (empty if fresh DB) or drop zone
- [ ] All toolbar buttons visible — no truncation, no overlap
- [ ] No coloured bands, broken splits, or weird overflows
- [ ] Footer/status area (if any) visible at bottom

**Resize test:**
- [ ] Drag window wider — layout reflows cleanly, no broken splits
- [ ] Drag window narrower (down to ~900px) — layout reflows, content remains usable
- [ ] Maximise window — content uses available space, no orphaned whitespace

**Observations:**

---

## 3. File Ingestion (via Select files…)

Test fodder: `Panorama_Bar_Playlist_01_Tama_Sumo` (~24 FLAC files)

- [ ] Click "Select files…" button
- [ ] Native macOS file dialog opens
- [ ] Navigate to and select the test folder (or select all FLAC files within)
- [ ] Dialog closes, ingestion begins
- [ ] Progress bar appears
- [ ] Progress bar stays **inside** the window — does not overflow, does not stretch UI
- [ ] Per-file progress visible (filename + counter)
- [ ] Conversion completes for all files within reasonable time (~3-5 min for 24 FLACs)
- [ ] On completion, track table populates with the new tracks
- [ ] No error toasts, no crashes

**Observations:**

---

## 4. Drag-and-Drop

**Status:** Known broken (last confirmed Part 5, 2026-04-16). Skipped this run to avoid re-ingestion conflict with §3. Will be diagnosed in a dedicated session.

**To re-verify after fix:** Run §3 with one folder, then drag a *different* folder onto the window. Both should produce identical ingestion behaviour.

- [ ] Skipped this run

**Observations:**

---

## 5. Analysis (BPM/Key)

- [ ] Click Analyse on the ingested tracks
- [ ] Progress UI appears
- [ ] BPM and key populate for each track as analysis progresses
- [ ] Progress reaches 100% without hang or crash
- [ ] BPM values are within sensible range (typically 60–180 for house/techno; halve/double if obviously off)
- [ ] Key values populate (1–24 internal; displayed as Camelot/Open Key/classical per settings)
- [ ] Navigating to Settings during analysis does not crash (known bug 4: may interrupt SSE)
- [ ] If interrupted, restarting analysis works (known bug 5)

**Observations:**

---

## 6. AI Tagging (Claude)

Requires API credit; skip if budget is uncertain.

- [ ] Click AI Tag on the ingested tracks
- [ ] Progress UI appears, token usage visible
- [ ] Genre, mood, energy, confidence populate for each track
- [ ] Reasoning column shows Claude's justification
- [ ] No silent failures (no tracks left blank without an error)
- [ ] On completion, the toast / status message confirms success

**Observations:**

---

## 7. Organisation / Review Queue

- [ ] Run Organise on the ingested tracks (button on main view)
- [ ] Review queue panel becomes visible
- [ ] Review queue text is readable — not dark-on-dark, not invisible (known bug 8)
- [ ] Each item shows proposed destination path clearly
- [ ] Approve / Reject buttons are visible and clickable
- [ ] Approving an item moves it out of the queue
- [ ] Approved files actually move to the proposed destination on disk
- [ ] Track table reflects new file paths

**Observations:**

---

## 8. Track Table Scrolling

Run this *after* §3–§7 so the table has real data with all columns populated.

- [ ] Vertical scrollbar appears when track count exceeds visible rows
- [ ] Mouse wheel scrolls the track table vertically
- [ ] Trackpad two-finger scroll works
- [ ] Clicking scrollbar handle and dragging works
- [ ] Scrolling to the bottom reveals the last track without cut-off
- [ ] Horizontal scrollbar appears if columns exceed window width
- [ ] Horizontal scroll reveals correct content (not white space, not broken layout)
- [ ] Shift+click on a row selects a range without highlighting text (known bug 9)

**Observations:**

---

## 9. Settings Panel

- [ ] Open Settings (gear icon, menu, or wherever it lives)
- [ ] All settings fields are visible
- [ ] Current values populate (API key shows masked `sk-ant-...XXXX`, output dir, template, etc.)
- [ ] Click "Test API Key" — result returned within 5s, message is sane (not raw Python exception)
- [ ] Change one setting (e.g. folder template), save
- [ ] Navigate away and back — change persists
- [ ] Close and relaunch the app — change still persists in `config.json`

**Observations:**

---

## 10. Quit and Relaunch (Persistence)

- [ ] Quit the app via Cmd+Q (or window close)
- [ ] App quits cleanly — no hung process in Activity Monitor (sidecar terminates)
- [ ] Relaunch from `/Applications/`
- [ ] Previously ingested tracks still present in track table
- [ ] Previously approved organisation moves still reflected
- [ ] Settings values still populated correctly
- [ ] Scrolling still works after relaunch (known bug 6)

**Observations:**

---

## 11. Log Verification

After the smoke test run, check `~/Library/Application Support/rekordbot/rekordbot.log`:

- [ ] Log file exists and is non-empty
- [ ] Startup lines present (migration runner, FastAPI boot, port 8420 bound)
- [ ] No ERROR or CRITICAL lines that weren't expected
- [ ] No silent gaps — log activity matches the user-facing pipeline timeline

**Observations:**

---

## Known-Open Bugs (Reference)

Track which of these reproduce in this run:

| # | Bug | Reproduced? | Smoke-Test Step |
|---|-----|-------------|-----------------|
| 3 | Horizontal scroll reveals broken layout | ☐ | §8 |
| 4 | Analysis state lost on Settings navigation | ☐ | §5 |
| 5 | Analysis restart blocked after Settings interruption | ☐ | §5 |
| 6 | Scrolling breaks on relaunch | ☐ | §10 |
| 8 | Review queue text invisible (dark on dark) | ☐ | §7 |
| 9 | Shift+click selects text (WebKit) | ☐ | §8 |

---

## Run History

Append a row per smoke-test run. Keep this short — full notes go in `SESSIONS.md`.

| Date | Build commit | Test folder | Outcome | Session |
|------|--------------|-------------|---------|---------|
| | | | | |
