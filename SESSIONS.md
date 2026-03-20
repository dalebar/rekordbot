# rekordbot — Session Log

---

## Session 1 — 2025-03-07

### What was worked on
Pre-Phase-0 planning. Full project review, research coordination, and decision-making.

### Summary
- Reviewed the full project plan (project instructions + phased build plan)
- Flagged concerns and open questions about the plan:
  - Tauri + Python backend lifecycle (how does the sidecar work?)
  - Rekordbox XML format and CDJ tag compatibility (affects DB schema)
  - librosa dependency weight (suggested aubio-only to start)
  - Rekordbox XML research spike needed before finalising schema
  - Cross-platform ambiguity needed resolving
  - `pyproject.toml` vs `requirements.txt` (chose pyproject.toml only)
- Split research into two focused chats:
  - **Chat A:** Rekordbox XML format + CDJ tag compatibility (combined because they're deeply intertwined)
  - **Chat B:** Tauri + Python sidecar architecture, dev workflow, packaging
- Both research documents completed and synthesised back in the main chat
- Identified gaps in CLAUDE.md (logging, error handling, linting, config management, git workflow, frontend conventions, pre-commit hooks, type checking, test infrastructure) and revised before starting Phase 0

### Key decisions made
1. Mac-first, Windows-compatible by design
2. Bundle ffmpeg (as Tauri resource, not sidecar)
3. pyproject.toml + uv for dependency management (uv.lock for reproducible builds, no requirements.txt)
4. PyInstaller `--onedir` mode (avoids zombie processes, easier to sign)
5. Hardcoded port 8420 with conflict detection
6. SSE for progress reporting (not WebSocket)
7. Apple Silicon only for initial builds
8. ID3v2.3 as primary tag target (universal CDJ compatibility)
9. Key stored as integer 1–24 (Camelot wheel mapping)
10. Rekordbox XML export-only in Phase 4 (import deferred to Phase 4b+)
11. Tauri IPC for desktop integration only; all business logic via HTTP to FastAPI
12. Sidecar integration must be tested at end of Phase 0
13. Start with aubio for BPM/key detection; add librosa only if accuracy insufficient
14. DB schema designed from Rekordbox XML track attributes (ensures clean export mapping)
15. No TEMPO/POSITION_MARK export initially (track metadata only)
16. Ruff for Python linting/formatting (replaces black + isort + flake8)
17. pydantic-settings for configuration (typed, validated, REKORDBOT_ prefix)
18. Python logging module with INFO default, DEBUG via config
19. Consistent API error schema: {"error": str, "detail": str} on all non-2xx responses
20. Custom exception hierarchy: RekordBotError base class with domain-specific subclasses
21. Project named "rekordbot"
22. Pre-commit hooks (Ruff, mypy, whitespace, merge conflicts) — prevents unlinted code entering repo
23. mypy in strict mode — type hints verified at dev time, not just decorative
24. Test infrastructure from day one: in-memory SQLite per test (conftest.py), httpx async client, pytest-asyncio with auto mode
25. Sync SQLAlchemy (not async) — async adds complexity for no benefit on a single-user desktop app with local SQLite
26. Alembic deferred to Phase 6 — during development, schema changes handled by recreating the dev database
27. mypy normal mode (not strict) — avoids friction with SQLAlchemy/pydantic type stubs while still catching real bugs

### Unresolved questions / blockers
- None blocking Phase 0. All foundational decisions are made.
- Rekordbox XML empirical testing (round-trip import, path encoding edge cases, AIFF artwork) to be done as a spike before Phase 4, not before Phase 0.
- Self-termination watchdog for the Python backend deferred to Phase 6.

### What's next
- Begin Phase 0 implementation: repo init, Python backend scaffold, React frontend scaffold, Tauri shell setup, DB schema, sidecar integration proof.
- Feature brief for Phase 0 is written and ready.
- CLAUDE.md and SESSIONS.md are finalised.

---

## Session 2 — 2026-03-07

### What was worked on
Phase 0 implementation — full project scaffolding from zero to working sidecar integration.

### Summary
- Created branch structure: `main` → `develop` → `feature/phase-0-scaffold`
- **Repo & Tooling:** pyproject.toml (deps, Ruff, mypy, pytest config), uv.lock, .pre-commit-config.yaml, Makefile (dev-backend, dev-frontend, build, test, lint, format), scripts/dev-setup.sh, scripts/build-backend.sh, .gitignore, .env.example, README.md, placeholder docs
- **Python Backend:** FastAPI app with /health and /shutdown endpoints, CORS middleware, lifespan-based startup, pydantic-settings config (REKORDBOT_ prefix), custom exception hierarchy with global error handler + UnhandledExceptionMiddleware, SQLAlchemy models (Base + Track with full Rekordbox-compatible schema), 8 tests (health, models, exceptions, config)
- **React Frontend:** Vite + React 19 + TypeScript, Tailwind CSS v4 via @tailwindcss/vite plugin, typed API client, App.tsx with health check and layout shell, ESLint (flat config) + Prettier
- **Tauri v2 Shell:** tauri.conf.json (app identifier, 1280x800 window, CSP, externalBin), Rust sidecar lifecycle (spawn on setup, health polling with retries, backend-ready event, kill on window close), tauri-plugin-shell + reqwest + tokio dependencies
- **Integration Proof:** Installed Rust toolchain, built PyInstaller --onedir binary, resolved sidecar path issues (_internal directory placement), verified full flow: Tauri window opens → sidecar spawns → uvicorn starts → health check passes → frontend displays "Connected to rekordbot backend v0.1.0"
- Confirmed ffmpeg available (/opt/homebrew/bin/ffmpeg v8.0.1)

### Issues encountered and resolved
1. **Hatchling build error** — pyproject.toml needed `[tool.hatch.build.targets.wheel] packages = ["backend"]` since the package name doesn't match the directory
2. **Pre-commit mypy missing deps** — mypy hook's `additional_dependencies` needed pytest, pytest-asyncio, httpx, uvicorn added alongside the framework deps
3. **FastAPI exception handler limitation** — `@app.exception_handler(Exception)` doesn't catch all exceptions in newer Starlette; switched to `UnhandledExceptionMiddleware` (BaseHTTPMiddleware)
4. **FastAPI on_event deprecation** — migrated from `@app.on_event("startup")` to the lifespan context manager pattern
5. **PyInstaller _internal path** — Tauri `externalBin` expects a single file, but PyInstaller `--onedir` produces a directory; solved by copying executable and `_internal/` separately, placing `_internal` next to the binary in `target/debug/` for dev mode
6. **uvicorn import string** — `"backend.main:app"` fails in PyInstaller since the module isn't importable by name; fixed by passing the `app` object directly (import string only used with `--reload`)
7. **Rust lifetime error** — MutexGuard temporary needed explicit binding in the window close handler

### Key decisions made
1. React 19 (not 18) — Vite scaffolded latest version, no reason to downgrade
2. Tailwind CSS v4 — new version uses `@import "tailwindcss"` pattern, configured via @tailwindcss/vite plugin
3. ESLint flat config — v9 default, simpler than legacy .eslintrc hierarchy
4. PyInstaller `--onedir` confirmed working — `--onefile` would have been simpler for Tauri but `--onedir` is correct for code signing and startup speed
5. Port 8420 hardcoded in both Rust and Python — conflict detection will be added but not in Phase 0
6. Health check polling interval: 500ms, up to 30 retries (15 seconds total) — generous enough for cold PyInstaller startup

### What's next
- Phase 1: File Ingestion & Conversion
- Feature brief to be written in planning chat before implementation begins

---

## Session 3 — 2026-03-07

### What was worked on
Phase 1 planning and implementation — File Ingestion & Conversion.

### Summary
- Wrote the full feature brief for Phase 1 (`docs/features/phase-1-file-ingestion-conversion.md`)
- Discussed and finalised all 8 decisions (AIFF bit depth, output structure, source file handling, concurrency, AAC→MP3, test fixtures, etc.)
- Implemented all 10 steps of the Phase 1 build plan via Claude Code
- Feature brief marked as complete
- All pre-commit hooks passing, all tests green

### Key decisions made
1. AIFF bit depth: preserve source, capped at 24-bit
2. Output directory: `{output_directory}/imports/{YYYY-MM-DD}/`
3. Source files never touched
4. Default 2 concurrent ffmpeg conversions
5. AIFF files always copied to output directory for consistency
6. SSE via sse-starlette package
7. AAC→MP3: optional, user-controlled, LAME VBR V0
8. Test audio fixtures committed as small files (~1s silence each)

### What's next
- Merge `feature/phase-1-converter` to `develop`
- Begin Phase 2 (Metadata & Tagging)

---

## Session 4 — 2026-03-07

### What was worked on
Phase 2 planning and implementation — Metadata & Tagging.

### Summary
- Wrote the full feature brief for Phase 2 (`docs/features/phase-2-metadata-tagging.md`)
- Discussed and finalised all decisions (tag format targets, BPM range, key storage, notation preferences, etc.)
- Implemented all steps of the Phase 2 build plan via Claude Code
- Feature brief marked as complete
- All pre-commit hooks passing, all tests green (390 total)

### Key decisions made
1. librosa for both BPM and key detection (revised from aubio-first plan — librosa more accurate)
2. Key stored as integer 1–24, Camelot wheel mapping
3. Key notation: configurable display preference (Camelot, Open Key, classical)
4. BPM auto-correction: half/double-time detection with configurable range
5. Tag writer: ID3v2.3 only (no v1), preserves unmanaged tags
6. Analysis pipeline: asyncio.Semaphore with max_concurrent_analyses=1 default (librosa is CPU-heavy)

### What's next
- Merge `feature/phase-2-metadata-tagging` to `develop`
- Begin Phase 3 (Claude AI Integration)

---

## Session 5 — 2026-03-08

### What was worked on
Phase 3 implementation — Claude AI Integration.

### Summary
- Created branch `feature/phase-3-claude` from `develop`
- Implemented all steps of the Phase 3 build plan
- Claude client with rate limiting and retry, prompt builder with DJ genre taxonomy, AI tagger pipeline with batch processing and SSE
- Extended frontend with AI columns, progress bar, token usage summary
- 462 tests passing (72 new)

### Key decisions made
1. Tool use (function calling) for structured AI output — more reliable than free-text parsing
2. Artist grouping in batches — tracks by the same artist are kept together to help Claude recognise stylistic patterns
3. Source genre preservation follows existing source_bpm/source_key pattern — original genre saved before AI overwrites it, enabling revert
4. Timestamp-based rate limiting (not token bucket) — simpler, sufficient for single-user desktop app
5. Per-batch error isolation — one batch failing doesn't abort the entire pipeline
6. Purple colour for AI Tag button — visually distinguishes from blue Analyse button
7. Energy colour coding: blue (low/chill) → neutral → amber (high) → red (peak) — intuitive for DJs
8. Token usage summary shown after completion with dismiss button — cost transparency without cluttering UI
9. Shared conftest.py `client` fixture updated with track cleanup — prevents cross-file test pollution

### What's next
- Merge `feature/phase-3-claude` to `develop`
- Begin Phase 2b (File Organisation) — template engine, automated org proposals, confidence scoring, review queue

---

## Session 6 — 2026-03-08

### What was worked on
Phase 3 verification — review of implementation against the feature brief to catch gaps before closing the phase.

### Summary
- Reviewed 5 items flagged for verification against the feature brief and codebase
- Found and fixed two gaps:
  1. **ai_status = "ai_failed" never set** — Frontend rendered the `ai_failed` status with red colour coding, but the backend AI tagger pipeline never actually set it. Tracks that failed (missing from Claude's response or batch exception) stayed as `"untagged"`. Fixed by setting `ai_status = "ai_failed"` in both failure paths in `ai_tagger.py:_process_batch()`
  2. **CLAUDE.md incomplete updates** — Phase 3 config settings (ai_model, ai_batch_size, ai_max_requests_per_minute) were missing from the Configuration Management example code block. Phase 3 was not bolded in the Phased Build Plan table. Both fixed.
- Confirmed 3 items were already correct:
  - write-tags endpoint transitions ai_status from "ai_tagged" to "ai_tags_written" (with integration test coverage)
  - anthropic SDK has `type: ignore[import-not-found]` and is documented in CLAUDE.md Known Issues
  - Feature brief already marked `Status: Complete`

### Issues encountered and resolved
1. **ai_failed status gap** — Backend pipeline incremented `tracks_failed` counter but never persisted the failure status to the track's `ai_status` column. Fixed in two places: tracks missing from Claude's tool response, and entire batch exception handler.
2. **CLAUDE.md config example stale** — The Settings code block in Configuration Management only showed up to Phase 2 settings. Added Phase 3 settings block.
3. **Build plan table styling** — Phase 3 row wasn't bolded like Phases 0–2. Fixed.

### Key decisions made
1. ai_failed is an intentional extension beyond the original spec's three states — mirrors the failure tracking pattern from Phase 1/2 analysis_status

### What's next
- Merge `feature/phase-3-claude` to `develop`
- Begin Phase 2b (File Organisation) — template engine, automated org proposals, confidence scoring, review queue

---

## Session 7 — 2026-03-08

### What was worked on
Phase 2b implementation — File Organisation & Structure, from feature brief to fully working organisation pipeline with review UI.

### Summary
- Created branch `feature/phase-2b-organiser` from `develop`
- Implemented all 11 steps of the Phase 2b build plan in order:
  1. **Config & exceptions** — Added folder_template, organise_confidence_threshold, organise_unknown_fallback to Settings; added OrganisationError exception
  2. **Track model & PreferenceRule model** — Added organisation columns (proposed_path, previous_output_path, organisation_status, organisation_confidence, organisation_reasoning) to Track; created PreferenceRule model with UniqueConstraint on (rule_type, key)
  3. **Template engine (TDD)** — Configurable folder templates with fallback syntax (`{variable|"literal"}`), path sanitisation (unsafe chars → underscore), output path building; 37 tests
  4. **Confidence scorer (TDD)** — Base 0.5 scoring with deltas for metadata presence/absence, VA compilation detection (Various Artists, VA, V/A patterns), bootleg indicator detection (bootleg, edit, mashup, vs, VIP, b2b with word boundaries); 34 tests
  5. **Preference store (TDD)** — CRUD operations for artist_folder/va_handling/custom_path rules, normalised key matching (lowercase), apply_rules() with priority ordering (custom_path > artist_folder > va_handling); 16 tests
  6. **Claude reasoner (TDD)** — PlacementSuggestion dataclass, system prompt for folder structure reasoning, tool use schema, batch processing for ambiguous tracks; 11 tests
  7. **File mover** — shutil.move wrapped in asyncio.to_thread(), collision handling (_1, _2 suffix), post-move verification, empty directory cleanup (bottom-up with safety bounds); 12 tests
  8. **Organiser pipeline** — Two-phase orchestrator (propose + execute), SSE progress events (organise_progress, organise_propose_complete, organise_move_complete), cancellation support, optional Claude enrichment for ambiguous tracks; 6 tests
  9. **API routes** — 9 endpoints: POST /api/organise/propose, GET /api/organise/progress (SSE), POST /api/organise/cancel, GET /api/organise/proposal, POST /api/organise/approve, POST /api/organise/resolve/{id}, GET/POST/DELETE /api/preferences; extended TrackDetailResponse with organisation fields; 19 tests
  10. **Frontend** — OrganiseControls (propose/approve buttons, emerald progress bar, organisation filter modes), ReviewQueue (accept/skip/custom path for ambiguous tracks, collapsible auto-approved list), PreferenceRulesPanel (CRUD with type/key/value form), TrackTable extended with organisation_status column and filter modes, API client with all organisation types and endpoints
  11. **Integration tests & docs** — End-to-end propose→approve flow, resolve flow, preference rule application, re-organisation after metadata changes, organisation fields in API; updated CLAUDE.md with Phase 2b status, repo structure, and deliverables summary; 5 tests
- **Total: 602 tests passing (140 new), 11 clean commits, all pre-commit hooks green**

### Issues encountered and resolved
1. **Dev DB schema mismatch** — After adding organisation columns to Track model, the dev DB had the old schema. Fixed by deleting rekordbot_dev.db.
2. **Test assertion for organisation_status** — test_models.py asserted "pending" but new default is "unorganised". Fixed by updating the test.
3. **Ruff SIM108/SIM103/UP031** — Template engine if/else could be ternary; detect_va_compilation had verbose boolean return; confidence scorer used `%s` in non-log strings (reasons list). All auto-fixed.
4. **mypy list variance** — `list[tuple[Track, Path]]` vs `list[tuple[object, Path]]` in move_files_batch. Fixed by using `Any` type for track parameter.
5. **mypy dict unpacking** — test_claude_reasoner.py used `**defaults` pattern with dataclasses. Fixed by using explicit keyword arguments.
6. **Cancellation test design** — `cancel()` before `propose_organisation()` didn't work because the method clears the cancel event. Fixed by using a side_effect function that cancels after 2 calls.
7. **Preference key normalisation** — Route test asserted "Test Artist" but preference store normalises keys to lowercase. Fixed test assertion to "test artist".
8. **Context window exhaustion** — Session exceeded context limit mid-implementation. Continued from summary in a new context window, picking up at Step 9 (partially complete).

### Key decisions made
1. TDD for pure logic modules (template engine, confidence scorer, preference store, claude reasoner); tests-after for framework integration (file mover, organiser, routes)
2. organisation_status default "unorganised" (not "pending") — clearer semantics for tracks that haven't been through the pipeline
3. Preference key normalisation to lowercase — case-insensitive matching for artist names
4. Custom path rules override everything (confidence 1.0, auto-approved) — user's explicit choice always wins
5. VA compilation detection uses a small set of exact-match names (not fuzzy matching) — "Various Artists", "VA", "V/A", "Various"
6. Bootleg detection uses regex word boundaries — prevents false positives on words like "edited" or "mashable"
7. File collision handling with _1, _2 suffix (not overwrite) — never lose files
8. Empty directory cleanup walks bottom-up with safety bound check (relative_to base_dir) — never traverse above the output directory
9. Emerald green colour for organisation buttons — visually distinct from blue (analysis) and purple (AI tagging)
10. OrganiseControls and AnalysisControls filters are mutually exclusive — selecting an organisation filter resets analysis filter to "all" and vice versa

### What's next
- Merge `feature/phase-2b-organiser` to `develop`
- Begin Phase 4 (Rekordbox XML Export) — XML generation from DB, track schema mapping, playlist/crate structure

---

## Session 8 — 2026-03-08

### What was worked on
Phase 4 implementation — Rekordbox XML Export, from feature brief to fully working export pipeline with UI.

### Summary
- Working on branch `feature/phase-4-rekordbox` (created from `develop`)
- Implemented all 8 steps of the Phase 4 build plan in order:
  1. **Config & exceptions** — Added rekordbox_xml_path to Settings; added ExportError exception (already staged from planning session)
  2. **Location encoder (TDD)** — RFC 3986 percent-encoding per path component via `urllib.parse.quote(safe="")`, `file://localhost/` URI generation, round-trip decodable; 25 tests
  3. **Schema mapper (TDD)** — Track model → XML attribute mapping: format_bpm() two-decimal float, format_rating() non-linear scale (0/51/102/153/204/255), format_kind() extension → "AIFF File"/"MP3 File", format_date() datetime → yyyy-mm-dd, track_to_xml_attrs() with fallbacks (filename stem for title, "Unknown Artist"), file size/mtime from disk, key notation via key_to_display(), optional attrs omitted when None; 35 tests
  4. **XML builder** — DJ_PLAYLISTS document construction with PRODUCT (Name="rekordbot"), COLLECTION with sequential TrackID assignment, PLAYLISTS with ROOT → rekordbot folder → "All Tracks" + per-artist playlists derived from folder hierarchy, write_xml() with XML declaration and UTF-8 encoding, ET.indent() for readable output; 19 tests
  5. **Export service** — Pipeline orchestrator: load tracks from DB, filter by file_path presence, build XML via builder, count playlists, write to disk; configurable output path with 3-level fallback (explicit → setting → output_directory/rekordbox.xml); 9 tests
  6. **API routes** — POST /api/export/rekordbox (trigger export, returns ExportResponse), GET /api/export/rekordbox/status (last export info with timestamp); registered in main.py; conftest.py updated with export module state reset; 5 tests
  7. **Frontend** — ExportControls.tsx (amber Export XML button, disabled when no tracks, result summary with exported/skipped counts, expandable warnings list, dismiss button); API client extended with ExportResult, ExportStatus, ExportOptions types, exportRekordboxXml() and getExportStatus() functions
  8. **Integration tests & docs** — End-to-end create tracks → export → parse XML → verify all attributes, location encoding round-trip with 7 path patterns (spaces, unicode, special chars, parentheses, apostrophes), playlist structure verification (All Tracks count, per-artist counts, TrackID/Key consistency), re-export after metadata change, API integration test; updated CLAUDE.md with Phase 4 status, repo structure, and deliverables; 11 tests
- **Total: 706 tests passing (104 new), 8 clean commits, all pre-commit hooks green**

### Issues encountered and resolved
1. **Research doc filename mismatch** — CLAUDE.md referenced `rekordbox-xml-cdj-compatibility.md` but actual file was `rekordbox-xml-cdj-compatibility-research.md`. Used Glob to find the correct filename.
2. **pytest not installed in venv** — `uv sync --dev` reported packages audited but pytest was missing. Fixed with explicit `uv pip install pytest pytest-asyncio httpx`.
3. **mypy MockTrack attr-defined errors** — Test helper class using empty `class MockTrack: pass` with dynamic attribute assignment caused 23+ mypy errors. Fixed by converting to `@dataclass` with explicit typed fields.
4. **mypy union-attr on Element.find()** — `Element.find()` returns `Element | None`, so chaining `.get()` or `.findall()` directly fails mypy. Fixed by storing result in variable and asserting `is not None` before use.
5. **Ruff formatting on every commit** — Pre-commit ruff-format reformatted test files on 5 of 8 commits. Re-added and committed on second attempt each time.
6. **Track model has `file_path` not `output_path`** — Feature spec referenced `Track.output_path` but the actual model uses `file_path` (updated by the organiser after moving files). Used `file_path` throughout the implementation.

### Key decisions made
1. TDD for pure logic modules (location encoder, schema mapper); tests-after for XML builder, export service, routes
2. `file_path` used as the canonical file location for export — after Phase 2b organisation, this is the organised path
3. Optional XML attributes (Composer, AlbumArtist, Grouping, Remixer, Label, Mix) omitted when None — matches Rekordbox export behaviour
4. File size and mtime read from disk at export time (not from DB) — files may have been modified since ingestion
5. `get_file_size()` and `_get_file_mtime()` mocked in tests — isolates XML generation logic from filesystem state
6. Playlist structure derived from `file_path` relative to `output_directory` — top-level folder becomes playlist name
7. Amber/orange colour for Export XML button — visually distinct from blue (analysis), purple (AI), emerald (organisation)
8. No SSE for export — sub-second operation for typical DJ library sizes

### What's next
- Wire ExportControls into App.tsx alongside existing toolbar sections
- Manual Rekordbox import verification (generate XML, import via File → Import Library, verify fields)
- Merge `feature/phase-4-rekordbox` to `develop`, then to `main`
- Begin Phase 4b (Rekordbox XML Import) or Phase 5 (Crate Builder & Set Planner)

---

## Session 9 — 2026-03-08

### What was worked on
Phase 4 close-out — doc fixes, UI wiring, and first real-world Rekordbox import test attempt.

### Summary
- Reviewed Phase 4 against the phase completion checklist, identified 3 gaps:
  1. ExportControls not wired into the UI
  2. Phase 4 not bolded in CLAUDE.md build plan table
  3. Feature brief status needed updating
- Applied all 3 fixes via Claude Code:
  - ExportControls wired into TrackTable.tsx (rendered after OrganiseControls, receives trackCount and onRefresh props)
  - Phase 4 bolded in CLAUDE.md
  - Feature brief status already set to "Complete ✅" (was updated earlier in Session 8)
- Ran first real-world ingestion test with `/Volumes/collection/music/import_test` (15 files: 7 FLAC, 1 AIF, 6 MP3, 1 M4A)
- Full pipeline executed: ingest → analyse → organise → (export pending)
- **Discovered Phase 1 bug: AIFF conversion drops all metadata tags**
  - Root cause: `build_ffmpeg_command()` in `converter.py` does not include `-write_id3v2 1` flag for AIFF output
  - ffmpeg's AIFF muxer silently drops Vorbis comments / ID3 tags without this flag
  - Confirmed by ffprobe: source FLAC has full tags (artist, album, genre, label, BPM, etc.), but converted AIFF only has a bare `title`
  - This affected all 7 FLAC → AIFF conversions (Q Lazzarus tracks) — all had null artist/album/genre in DB, causing them to be flagged as `review_needed` during organisation with confidence 0.0
  - MP3 and M4A files were unaffected (they use `copy_as_is`, no conversion)
  - Bug has been latent since Phase 1 — never caught because test fixtures were generated silence files, not real tagged audio

### Issues encountered and resolved
1. **Repo path changed** — Project directory is `/Users/daleb/Documents/projects/rekordbot`, not `~/Documents/projects/crateai` as referenced in CLAUDE.md. The repo was renamed at some point. CLAUDE.md needs updating.
2. **Tauri dev script missing** — `make dev-frontend` failed because `package.json` has no `"tauri"` script defined. Workaround: run `npm run dev` for Vite-only frontend, or add `"tauri": "tauri"` to scripts.
3. **analyse endpoint requires JSON body** — `POST /api/tracks/analyse` returns 422 without a body. Needs `{}` even though all fields are optional (Pydantic requires the body object to be present).
4. **librosa audioread deprecation** — M4A file triggered PySoundFile fallback to audioread with deprecation warning. Known and harmless (documented in CLAUDE.md Known Issues).

### Key decisions made
1. The `-write_id3v2 1` fix is a targeted bugfix on the Phase 4 branch — it's a Phase 1 code change but blocking Phase 4 acceptance testing
2. Re-ingest from clean slate after the fix (delete DB + clear output directory) to get correct metadata for the Rekordbox import test
3. Created `rekordbox-import-test-guide.md` — step-by-step guide for the full pipeline test including the bugfix

### Unresolved — blocking Phase 4 merge
- [x] Apply `-write_id3v2 1` bugfix to `converter.py`
- [ ] Re-ingest test files from clean slate
- [ ] Complete full pipeline: ingest → analyse → (AI tag optional) → organise → export
- [ ] Manual Rekordbox import verification (the actual acceptance test)
- [x] Update CLAUDE.md Known Issues with the `-write_id3v2` note
- [ ] Update CLAUDE.md repo path (rekordbot, not crateai)

### What's next
1. Re-run the full pipeline with clean data (re-ingest after bugfix)
2. Complete the Rekordbox import test
3. If test passes: merge `feature/phase-4-rekordbox` → `develop` → `main`, tag `phase-4-complete`
4. Decide next phase: Phase 4b (XML Import) or Phase 5 (Crate Builder & Set Planner)

---

## Session 10 — 2026-03-08

### What was worked on
AIFF metadata bugfix — applying the `-write_id3v2 1` fix identified in Session 9.

### Summary
- Applied the `-write_id3v2 1` bugfix to `build_ffmpeg_command()` in `backend/services/converter.py` — added the flag before the output path argument for all AIFF conversions
- Updated all 4 existing AIFF test assertions in `backend/tests/test_converter.py` to include the new flag in expected command lists
- Added new dedicated test `test_aiff_conversion_includes_write_id3v2_flag` that verifies the flag is present and positioned correctly (before output path)
- Added note to CLAUDE.md Known Issues documenting ffmpeg's AIFF muxer default behaviour
- All 9 converter tests passing, all pre-commit hooks green
- Committed as `6f4dbaa`

### Issues encountered and resolved
1. **pytest not in venv** — Same issue as Session 8: `uv sync --dev` reports packages audited but pytest missing. Fixed with explicit `uv pip install pytest pytest-asyncio httpx`.

### What's next
- Re-ingest test files from clean slate (delete DB + clear output directory)
- Run full pipeline: ingest → analyse → organise → export
- Manual Rekordbox import verification
- Merge to `develop` → `main` if acceptance test passes

---

## Session 11 — 2026-03-08

### What was worked on
Phase 4 acceptance test — full pipeline re-run with bugfix applied, and manual Rekordbox import verification.

### Summary
- Deleted dev DB and cleared output directory for clean re-ingest
- Ran full pipeline against `/Volumes/collection/music/import_test` (15 files: 7 FLAC, 1 AIF, 6 MP3, 1 M4A):
  1. **Ingest** — 15 files processed. FLAC → AIFF conversions now preserve all metadata tags (bugfix confirmed — ffprobe shows artist, album, genre, label, etc. in converted AIFFs)
  2. **Analyse** — 15/15 succeeded, BPM and key detected for all tracks. Known audioread deprecation warning on M4A (harmless)
  3. **Organise** — 14/15 auto-approved (confidence 0.8), 1 flagged as `review_needed` (confidence 0.6). The flagged track was "Goodbye Horses (single edit)" — "edit" in the title triggered the bootleg detection regex. Resolved manually via `POST /api/organise/resolve/1` with `action: "accept"`, then approved. All 15 files moved to artist/album folder structure.
  4. **Export** — 15 tracks exported, 0 skipped, 10 playlists created, no warnings. XML written to `/Volumes/collection/music/rekordbot_library/rekordbox.xml`
- **Rekordbox import test: PASS**
  - Imported via File → Import Library in Rekordbox 7
  - All 15 tracks visible — none greyed out or missing (Location encoding correct)
  - Waveform previews generated by Rekordbox (files readable)
  - Titles, artists, albums all display correctly (including special characters: commas, ampersands, parentheses)
  - BPM values present (Rekordbox re-analysed with its own values, as expected per research doc §1.10)
  - Key values display correctly — Rekordbox shows classical notation (C, Fm, Ab, Db, etc.) converted from our Camelot XML values
  - File types correct: AIFF for converted lossless, MP3 for copies, M4A for AAC
  - Playlists visible: All Tracks + per-artist playlists under rekordbot folder
  - Date Added showing correctly as 08/03/2026

### Issues encountered and resolved
1. **Resolve endpoint requires `action` field** — `POST /api/organise/resolve/{id}` returned 422 when given only `proposed_path`. Requires `action` field: one of "accept", "custom", or "skip". Used `action: "accept"` since the proposed path was already correct.
2. **Bootleg false positive on "single edit"** — confidence scorer's `\bedit\b` regex matches "single edit", which is a standard release format, not a bootleg. Track was correctly handled via the review queue. Logged as a future refinement: ignore "edit" when preceded by "single", "radio", "album", "extended", or "club".

### Minor issues logged for future phases (not blocking)
1. **BitRate="0" on all tracks in XML** — AIFF bitrate not computed during conversion; MP3 `source_bitrate` not carried to the export mapper. Cosmetic — Rekordbox doesn't rely on this field. Fix in Phase 6.
2. **Bootleg false positive refinement** — "single edit", "radio edit", "extended edit" etc. are standard release formats that should not trigger the bootleg indicator. Phase 2b or Phase 6 refinement.
3. **Repo path stale in docs** — CLAUDE.md and project instructions reference `~/Documents/projects/crateai` but the actual path is `~/Documents/projects/rekordbot`. Needs updating.
4. **Tauri dev script missing** — `package.json` has no `"tauri"` script, so `make dev-frontend` fails. Workaround: `cd frontend && npm run dev` for Vite-only. Fix by adding `"tauri": "tauri"` to package.json scripts.

### What's next
- Merge `feature/phase-4-rekordbot` → `develop` with `--no-ff`, tag `phase-4-complete`
- Decide next phase: Phase 4b (XML Import) or Phase 5 (Crate Builder & Set Planner)

---

## Session 12 — 2026-03-08

### What was worked on
Phase 5a implementation — Crate Builder, from feature brief to fully working AI-powered crate system.

### Summary
- Working on branch `feature/phase-5a-crate-builder`
- Implemented all 10 steps of the Phase 5a build plan in order:
  1. **Config & exceptions** — Added `crate_assignment_batch_size: int = 30` to Settings; added `CrateError` exception
  2. **Data models** — Created `Crate` (name, description, parsed_criteria JSON, auto_refresh, timestamps) and `CrateTrack` (many-to-many association with assignment_method) in `backend/models/crate.py`; UniqueConstraint on (crate_id, track_id); ORM cascade delete; 8 tests
  3. **Key compatibility (TDD)** — Camelot wheel harmonic mixing: `are_keys_compatible()`, `get_compatible_keys()`, `get_compatibility_type()` with same key, adjacent, relative major/minor, energy boost/drop, wrap-around (12→1); 29 tests
  4. **Crate prompt builder (TDD)** — `build_criteria_prompt()` for description→criteria parsing, `parse_criteria_result()` with energy clamping (1–10) and BPM range validation, `build_assignment_prompt()` for batch track evaluation, `parse_assignment_result()` with deduplication and invalid ID filtering; 19 tests
  5. **Crate assigner** — Batched Claude assignment pipeline: load tracks → batch by `crate_assignment_batch_size` → Claude API via `asyncio.to_thread` → store CrateTrack records; SSE progress events (`crate_assignment_progress`, `crate_assignment_complete`); cancellation via `asyncio.Event`; `clear_ai_assignments()` preserves manual; 6 tests
  6. **Crate manager** — CRUD: `list_crates()` with track counts, `get_crate()` with track IDs, `create_crate()`, `update_crate()` (description change triggers re-assignment), `delete_crate()`, `add_tracks()` (manual, dedup), `remove_tracks()`, `refresh_crate()` (clears AI, preserves manual, re-assigns), `auto_refresh_crates()` for newly ingested tracks; 16 tests
  7. **API routes** — 9 endpoints: POST/GET/PUT/DELETE `/api/crates`, POST `/api/crates/{id}/refresh`, POST/DELETE `/api/crates/{id}/tracks`, GET `/api/crates/{id}/progress` (SSE); background assignment on create with module-level `_assigner` for SSE; 11 tests
  8. **XML export integration** — Extended `build_playlists()` with optional `crates` parameter; `build_crate_playlists()` generates playlist nodes sorted alphabetically alongside folder-based playlists; extended `export_library()` with `_load_crates()` helper; 7 tests
  9. **Frontend** — `CrateSidebar.tsx` (playlist tree with "All Tracks" + per-crate items, track counts, click-to-filter, "+ New" button, right-click context menu with Refresh/Toggle Auto-refresh/Delete); `CrateCreateDialog.tsx` (modal with name/description/auto-refresh fields, SSE progress bar during assignment, result display); `App.tsx` refactored with sidebar layout and `selectedCrateId` state; `TrackTable.tsx` extended with `crateId` prop and `crateTrackIds` filter in `filteredTracks` useMemo; API client extended with full crate types and endpoints
  10. **Integration tests & docs** — End-to-end create→assign→verify, refresh with manual preservation, overlapping assignment (track in multiple crates), delete isolation, manual add/remove, list with counts, XML export with crates (playlists, sorting, coexistence); updated CLAUDE.md with Phase 5a status, repo structure, config settings, build plan; 12 tests
- **Total: 814 tests passing (108 new), 10 clean commits, all pre-commit hooks green**

### Issues encountered and resolved
1. **SQLite CASCADE not enforced by default** — `ON DELETE CASCADE` in ForeignKey doesn't trigger in SQLite without `PRAGMA foreign_keys = ON`. Fixed by using SQLAlchemy ORM-level cascade via `relationship("CrateTrack", cascade="all, delete-orphan", passive_deletes=True)` and accessing `crate.crate_tracks` before delete to trigger lazy load.
2. **Ruff B011** — `assert False` in tests flagged by bugbear; replaced with `raise AssertionError(...)`.
3. **mypy arg-type on `json.loads`** — `crate.parsed_criteria` is `str | None`; fixed with `assert crate.parsed_criteria is not None` guard.
4. **Cancellation test timing** — Setting cancel event before `assign_tracks()` didn't work (method clears it). Fixed by using `side_effect` on `messages.create` to cancel after first batch call.
5. **conftest client fixture test pollution** — Only cleaned Track table, not CrateTrack/Crate tables, causing failures when running test files together. Fixed by adding CrateTrack and Crate deletion to the client fixture.
6. **Context window exhaustion** — Session exceeded context limit during Step 9 (frontend). Continued from summary in a new context window, completing TrackTable crate filtering and Step 10.
7. **Integration test mock field mismatch** — Mock Claude response used `track_ids` but `parse_assignment_result()` expects `matching_track_ids`. Fixed.
8. **`build_xml()` signature** — Integration tests called `build_xml(tracks, crates=crate_data)` but it requires `key_notation` and `output_directory` positional args. Fixed to `build_xml(tracks, "camelot", "/output", crates=crate_data)`.
9. **`asyncio.to_thread` in tests** — Mocking `claude_client.client.messages.create` directly didn't work because the assigner wraps the call in `asyncio.to_thread`. Fixed by patching `backend.services.crate_assigner.asyncio.to_thread` to return the mock response directly.
10. **Track model field name** — Used `output_path` in test helper but actual model uses `file_path`. Fixed.

### Key decisions made
1. TDD for pure logic modules (key compatibility, crate prompt builder); tests-after for framework integration (assigner, manager, routes, XML integration)
2. Camelot wheel math: odd ints = minor (A), even = major (B), number = `(int+1)//2`, wrap via `((n-1) % 12) + 1`
3. Overlapping assignment — tracks can be in any number of crates (many-to-many via CrateTrack association table)
4. Manual additions preserved during refresh — `clear_ai_assignments()` only deletes `assignment_method="ai"` records
5. Auto-refresh runs assignment on newly ingested tracks only (not full library re-scan) for crates with `auto_refresh=True`
6. Crate playlists appear alongside (not nested within) folder-based playlists under the `rekordbot` folder in XML export
7. Description update triggers re-parse and re-assignment; name-only update does not
8. Module-level `_assigner` in routes for SSE event streaming (same pattern as Phase 2/3 pipelines)

### What's next
- Merge `feature/phase-5a-crate-builder` → `develop`
- Begin Phase 5b (Set Planner) — energy arc sequencing, lock-and-shuffle refinement, key compatibility

---

## Session 13 — 2026-03-08

### What was worked on
Phase 5b implementation — Set Planner, from feature brief to fully working AI-powered set planning system.

### Summary
- Working on branch `feature/phase-5b-set-planner`
- Implemented all 9 steps of the Phase 5b build plan in order:
  1. **Config & exceptions** — Added `set_track_duration_minutes: int = 7`, `set_candidate_multiplier: float = 2.5`, `set_max_tracks: int = 50` to Settings; added `SetPlanError` exception
  2. **Data models** — Created `SetPlan` (name, description, duration_minutes, target_bpm_start/end, energy_arc, source_type, source_crate_ids JSON, harmonic_mixing, status), `SetTrack` (set_id, track_id, position, is_locked, is_candidate) with UniqueConstraint on (set_id, track_id), `SetSegment` (set_id, start/end_track_position, description); cascade delete; 11 tests
  3. **BPM transition scoring (TDD)** — `score_bpm_transition()` returns 0.0–1.0 using threshold table (0–2 BPM diff = 1.0, 20+ = 0.0), `get_transition_quality()` returns labels (smooth/acceptable/noticeable/jarring/unknown), `suggest_bpm_range()` for sequence position; 29 tests
  4. **Set prompt builder (TDD)** — System prompts for initial planning, replace, and reorder operations; tool schemas (`plan_set`, `replace_tracks`, `reorder_tracks`); `build_initial_prompt()` with description/tracks/parameters, `parse_initial_result()` with dedup and validation; `build_replace_prompt()` with locked tracks and segments; `build_reorder_prompt()` with lock indicators; result parsers that reject locked track modifications; 20 tests
  5. **Set planner service** — `SetPlanner` class with SSE event queue and cancellation; CRUD operations (`create_set`, `get_set`, `list_sets`, `update_set`, `delete_set`); `lock_track`/`unlock_track` with automatic `recalculate_segments()`; `recalculate_segments()` rebuilds from locked positions preserving descriptions where boundaries unchanged; manual editing (`add_track_at_position`, `remove_track`, `move_track`); `get_candidates()`; async operations (`plan_initial_sequence`, `shuffle_replace`, `shuffle_reorder`) with Claude API calls; 26 tests
  6. **API routes** — 14 endpoints: POST/GET `/api/sets`, GET/PUT/DELETE `/api/sets/{id}`, POST lock/unlock, PUT segments, POST shuffle, POST/DELETE tracks, POST move, GET candidates, POST export, GET progress (SSE); Pydantic request/response models; background task pattern with module-level `_planner`; 12 tests (including export route)
  7. **XML export integration** — Added `build_set_playlists()` to xml_builder.py (preserves track position order, unlike unordered crate playlists); extended `build_playlists()` and `build_xml()` with optional `sets` parameter; added `_load_sets()` to xml_exporter.py (only exports sets with status "complete"); per-set export endpoint; 8 tests
  8. **Frontend** — `SetPlannerView.tsx` (track sequence table with lock toggle, BPM/key transition indicators, segment dividers with inline editing, collapsible candidate panel, shuffle replace/reorder buttons, export button); `SetCreateDialog.tsx` (name, description, duration, BPM start/end, energy arc selector with custom option, source type with crate picker, harmonic mixing toggle, SSE progress); `SetListPanel.tsx` (set list with status badges and counts); `CrateSidebar.tsx` extended with Sets section (list, counts, + New button); `App.tsx` updated with set planner view switching; API client with all set types and 14 functions
  9. **Integration tests & docs** — End-to-end create→lock→segment→export, track add/remove/move, segment description preservation across recalculation, XML playlist order verification, set/crate playlist coexistence, API route lifecycle test (create→lock→unlock→export with XML verification); updated CLAUDE.md with Phase 5b status, repo structure, and deliverables; 10 tests
- **Total: 930 tests passing (116 new), 10 clean commits (including feature brief), all pre-commit hooks green**

### Issues encountered and resolved
1. **SQLite CASCADE not enforced** — Same issue as Phase 5a: tests needed to load relationships before delete and use `expire_all()` after. Changed one test to verify reference instead of cascade.
2. **mypy `set()` type annotation** — `locked_positions = set()` needed explicit `locked_positions: set[int] = set()` for mypy.
3. **Ruff SIM105** — `try/except pass` blocks for `json.loads` needed `contextlib.suppress(json.JSONDecodeError, TypeError)`.
4. **mypy `to_thread` overloaded function** — Added `# type: ignore[arg-type]` on `asyncio.to_thread()` calls with `claude_client.client.messages.create` (same pattern as crate_assigner.py).
5. **Unique file_path constraint in tests** — `_create_track` helpers generated duplicate paths across tests. Fixed with global counters.
6. **Route tests using wrong DB** — Tests initially used `db_session` fixture (in-memory) while routes use `SessionLocal` (dev DB). Rewrote to use `SessionLocal` directly.
7. **Integration test key mismatch** — Segment dict uses `start_track_position` not `start_position`. Fixed after inspecting `get_set()` return format.
8. **Integration test table isolation** — Non-API tests using `SessionLocal` needed explicit table cleanup. Added `_clean_tables()` helper with `init_db()` call.
9. **Frontend ESLint errors** — `deleteSet` imported but unused in CrateSidebar (removed); `setRefreshTrigger` state name collided with setter name from another state variable (renamed to `setsRefreshTrigger`).
10. **Context window exhaustion** — Session exceeded context limit during Step 6 (API routes). Continued from summary in a new context window, completing Steps 6–9.
11. **Ruff auto-formatting on commits** — Pre-commit ruff-format reformatted files on 5 of 10 commits. Re-staged and committed on second attempt each time.

### Key decisions made
1. TDD for pure logic modules (BPM transition, set prompt builder); tests-after for service, routes, XML integration
2. Lock-and-shuffle is the core interaction pattern — locked tracks define segment boundaries, unlocked tracks are replaced or reordered by Claude
3. Segment recalculation preserves descriptions when boundaries are unchanged — avoids losing user-written mood descriptions during iterative refinement
4. 2.5x candidate multiplier — Claude suggests more tracks than needed, giving users a deep bench for swaps
5. Two shuffle modes: "replace" (swap unlocked tracks with candidates) and "reorder" (rearrange unlocked tracks without changing the pool)
6. Only sets with status "complete" are included in full library XML export — draft/planning sets excluded
7. Per-set export endpoint triggers full library export with the set included (not standalone XML)
8. Set playlists appear after crate playlists in the XML, sorted alphabetically, with track order preserved (unlike unordered crate playlists)
9. Blue colour for set planner buttons — visually distinct from purple (crates/AI), amber (export), emerald (organisation)
10. SetPlannerView is a full-page view (not a panel), accessed via sidebar set list or SetCreateDialog completion

### What's next
- Merge `feature/phase-5b-set-planner` → `develop`
- Decide next phase: Phase 4b (Rekordbox XML Import) or Phase 6 (Polish & Packaging)

---

## Session 14 — 2026-03-08

### What was worked on
Phase 6a implementation — App Shell & Packaging, transforming rekordbot from a dev-mode-only project into a working desktop application.

### Summary
- Working on branch `feature/phase-6a-app-shell`
- Implemented all 10 steps of the Phase 6a build plan in order:
  1. **Config manager (TDD)** — JSON config persistence at `~/Library/Application Support/rekordbot/config.json`. Config file → env vars → pydantic-settings pipeline (env vars take precedence). `CONFIGURABLE_FIELDS` set controls what's stored. API key masking with `sk-ant-` prefix special case. Directory validation (exists or parent writable). 34 tests.
  2. **Settings routes** — GET/PUT `/api/settings` with API key masking, POST `validate-key` (Anthropic SDK test call with claude-haiku-4-5-20251001), POST `validate-directory`, GET `status` (configured check, ffmpeg availability). Pydantic request/response models. `_apply_to_settings()` updates in-memory singleton via `object.__setattr__`. 12 tests.
  3. **Watchdog** — Self-termination daemon thread: polls parent PID every 5s via `os.kill(pid, 0)`, 10s grace period before `os._exit(0)`. `parse_parent_pid()` extracts `--parent-pid` from `sys.argv`. Tauri passes PID on sidecar spawn. 8 tests.
  4. **Error handling** — `RequestValidationError` handler returning standard `{error, detail}` JSON. `UnhandledExceptionMiddleware` catch-all. Non-blocking startup health checks (ffmpeg, output directory, API key — log warnings only). 4 tests.
  5. **BitRate fix (TDD)** — `compute_bitrate(sample_rate, bit_depth, channels)` pure function for lossless; `_resolve_bitrate(track)` dispatches lossy (source_bitrate) vs lossless (computed). 11 tests including integration with XML export.
  6. **Main.py integration** — Config loading before Settings instantiation, packaged-mode DB path (`--parent-pid` detection), router registration, watchdog startup in lifespan, startup health checks.
  7. **Toast system** — `ToastProvider` React context with `useToast()` hook. Toast types: success/error/warning/info. Auto-dismiss: success/info 5s, warning 8s, error sticky. Global API error handler via `setApiErrorHandler()`.
  8. **Settings panel** — Main section: API key (password + test), output directory (text + Tauri folder dialog), key notation dropdown, folder template with live preview, AAC toggle. Advanced section (collapsible): BPM range, confidence threshold, track duration, max tracks. Save with bpmMin/bpmMax validation.
  9. **First-run wizard** — Three steps: Welcome → Config → Done. Output directory required with validation. API key optional with test button. Gated by `/api/settings/status` endpoint. App.tsx routing: null = loading spinner, true = wizard, false = main app.
  10. **Integration tests & docs** — First-run flow, settings persistence, API key masking round-trip, directory validation, error format standardisation, bitrate computation. Updated CLAUDE.md. 13 tests.
- **Total: 1013 tests passing (83 new), 10 clean commits, all pre-commit hooks green**

### Issues encountered and resolved
1. **save_config test used non-configurable field** — `{"new": "value"}` was filtered out by `CONFIGURABLE_FIELDS`. Fixed by using `{"output_directory": "/new/path"}`.
2. **mask_api_key prefix handling** — `mask_api_key("sk-ant-api03-...")` returned `"sk-a...mnop"` instead of `"sk-ant-...mnop"`. Fixed by adding special case for `sk-ant-` prefix.
3. **test_config.py pollution** — Real API key from config file loaded via `apply_config_to_env()` at import time. Fixed with `monkeypatch.delenv` on all `REKORDBOT_*` vars and `Settings(_env_file=None)`.
4. **E402 lint errors** — Router imports after config loading code in main.py. Fixed with `# noqa: E402`.
5. **mypy `json.loads` return type** — Returns `Any`, causing "Returning Any" error. Fixed with explicit `data: dict = json.loads(content)`.
6. **MockTrack bitrate test** — `test_bitrate_fallback_zero` still had default audio properties, so `_resolve_bitrate` computed 2116 instead of 0. Fixed by overriding all fields to None.
7. **mypy `getattr` returns `Any`** — In xml_schema_mapper.py, fixed by wrapping in `int()`.
8. **Wrong working directory** — After `npx tsc` in frontend/, git commands failed. Fixed with absolute paths.

### Key decisions made
1. Config file → env vars → pydantic-settings pipeline: config file values are loaded into env vars with `REKORDBOT_` prefix, but existing env vars are never overridden (env vars always win).
2. `CONFIGURABLE_FIELDS` set explicitly controls which settings are persisted to JSON (avoids accidental persistence of internal/derived settings).
3. API key masking uses `sk-ant-...XXXX` pattern (showing prefix and last 4 chars) with special handling for `sk-ant-` prefix.
4. Masked key detection (`is_key_masked()`) prevents accidentally overwriting real keys when frontend sends back masked values.
5. Watchdog uses `os.kill(pid, 0)` (no signal sent, just existence check) with 10s grace period to avoid false positives during brief parent hangs.
6. Startup health checks are non-blocking (log warnings only) — app starts even without ffmpeg, API key, or valid output directory.
7. First-run wizard only gates on `configured` status from `/api/settings/status`; once any settings are saved, wizard is bypassed.
8. Toast notifications use React context pattern; global API error handler intercepts all non-2xx responses.

### What's next
- Merge `feature/phase-6a-app-shell` → `develop`
- Decide next phase: Phase 6b (Polish & Distribution) or Phase 4b (Rekordbox XML Import)

---

## Session 15 — 2026-03-08

### What was worked on
Phase 4b — Rekordbox XML Import. Full implementation from Track model changes through integration tests.

### Summary
Built the complete Rekordbox XML import pipeline in 8 steps:
1. **Track model** — Added `import_source` and `import_conflicts` fields
2. **XML parser (TDD)** — `xml_parser.py` with location decoding, BPM/rating/tonality parsing, playlist extraction
3. **Track matcher (TDD)** — `track_matcher.py` with path match → hash match → new track strategy, field-level conflict detection
4. **Conflict resolver** — `conflict_resolver.py` with per-track and bulk resolution (accept rekordbox / keep rekordbot)
5. **Import service** — `xml_importer.py` orchestrator with SSE progress, playlist-to-crate conversion
6. **API routes** — `import_xml.py` with SSE progress streaming, cancel support, conflict endpoints
7. **Frontend UI** — `ImportControls.tsx` (Tauri file dialog, progress bar) and `ConflictReviewPanel.tsx` (per-field toggle, bulk resolve)
8. **Integration tests** — 6 end-to-end tests covering full round-trip, playlists, hash matching, large imports, missing files, bulk resolution

### Tests
130 new tests (5 model + 63 parser + 25 matcher + 11 resolver + 11 importer + 9 routes + 6 integration). Total: 1143 passing.

### Files created
- `backend/services/xml_parser.py` — Rekordbox XML parser
- `backend/services/track_matcher.py` — Track matching and conflict detection
- `backend/services/conflict_resolver.py` — Conflict resolution service
- `backend/services/xml_importer.py` — Import pipeline orchestrator
- `backend/routes/import_xml.py` — Import API routes
- `frontend/src/ImportControls.tsx` — Import toolbar component
- `frontend/src/ConflictReviewPanel.tsx` — Conflict review UI
- `backend/tests/test_track_import_fields.py`
- `backend/tests/test_xml_parser.py`
- `backend/tests/test_track_matcher.py`
- `backend/tests/test_conflict_resolver.py`
- `backend/tests/test_xml_importer.py`
- `backend/tests/test_import_routes.py`
- `backend/tests/test_phase4b_integration.py`

### Files modified
- `backend/models/track.py` — Added import_source, import_conflicts columns
- `backend/exceptions.py` — Added XmlImportError
- `backend/main.py` — Registered import_xml router
- `backend/tests/conftest.py` — Schema refresh and import state reset
- `frontend/src/api/client.ts` — Phase 4b types and API functions
- `frontend/src/App.tsx` — ImportControls and ConflictReviewPanel integration
- `CLAUDE.md` — Updated status, repo structure, design decisions

### Key decisions made
1. Track matching: path first (exact file_path match), then SHA-256 hash (handles moved files), else create new track
2. Conflict detection thresholds: BPM difference > 0.5, any difference for key/rating/genre, string fields only when both non-empty
3. Conflicts stored as JSON in Track.import_conflicts (denormalized, temporary) — cleared to None on resolution
4. Imported tracks get import_source="rekordbox_xml", conversion_status="complete", analysis_status="not_analysed"
5. Playlists become Crates with folder paths flattened to name prefixes (e.g. "Genre/House")
6. SSE progress uses asyncio.Queue bridge for thread→async communication
7. Cancel support via threading.Event checked between track imports

### Issues encountered and resolved
1. **conftest.py schema stale** — `create_all(checkfirst=True)` didn't add new columns. Fixed with `drop_all` before `init_db()`.
2. **Ruff SIM102/SIM105/B904/E501/F841** — Various lint fixes (nested ifs, contextlib.suppress, raise from, line length, unused vars).
3. **mypy arg-type/union-attr** — Type ignore for test helper kwargs, assert not None before attribute access.
4. **5 pre-existing export test failures** — PermissionError on `/Volumes/collection` in test_export_routes.py and test_phase4_integration.py (not caused by Phase 4b).

### What's next
- Merge `feature/phase-4b-xml-import` → `develop` → `main`
- Phase 6b — Polish & Distribution

---

## Session 16 — 2026-03-09/10

### What was worked on
Phase 6b — .dmg Packaging & Migration Setup. Alembic migration infrastructure (Steps 1–3) and .dmg build pipeline (Step 4).

### Summary
Spanned two context windows due to the complexity of resolving PyInstaller + Tauri bundling incompatibilities.

**Steps 1–3: Alembic Migration Infrastructure**
- Added Alembic dependency via `uv add alembic`
- Created baseline migration (`001_baseline.py`) capturing all 7 tables as a single snapshot
- Implemented `migration_runner.py` with three-way DB state detection (fresh/pre-Alembic/migrated)
- Replaced `init_db()` with `run_migrations(engine)` in the lifespan handler
- `env.py` imports Base from models and conditionally sets DB URL (supports both programmatic and Settings-based URL resolution)
- 11 new tests for migration runner; 1154 tests total (11 new)

**Step 4: .dmg Build Pipeline**
- Researched PyInstaller `--onedir` + Tauri bundling incompatibility: Tauri's `externalBin` only copies a single executable, not PyInstaller's `_internal/` directory. Documented 5 options in `docs/research/pyinstaller-onedir-tauri-bundling.md`.
- Tried Option 1 (`bundle.macOS.files`) — failed because placing sidecar directly in `Contents/MacOS/` triggers PyInstaller's `.app` bundle mode, which changes library resolution paths
- Implemented Option 3 (post-build injection): `scripts/build-dmg.sh` runs a 4-step pipeline (PyInstaller → Tauri .app → inject sidecar into `Contents/MacOS/sidecar/` → hdiutil .dmg)
- Updated `lib.rs` with dual-mode sidecar spawning: production uses `std::process::Command` from sidecar/ subdir, dev uses Tauri sidecar API
- Fixed CORS: WebKit preflight returning 400 because FastAPI's `allow_origins` didn't match the actual webview origin. Fixed with `allow_origins=["*"]` (safe — backend is local-only on 127.0.0.1)
- Fixed Content-Type header: API client was setting `Content-Type: application/json` on GET requests, triggering unnecessary CORS preflights. Now only set on POST/PUT/PATCH.
- Fixed CSP: Added `ipc:` and `http://ipc.localhost` to `connect-src` for Tauri IPC protocol
- Fixed frontend startup: Added polling-based backend readiness (20 retries × 500ms) instead of single immediate health check that failed before sidecar was ready
- Fixed UTF-8 encoding: PyInstaller sidecar stdout defaults to ASCII when piped. Added `reconfigure(encoding="utf-8")` in `main.py`
- Updated app icons (user-provided custom icons)
- Enabled Tauri `devtools` feature for debugging production builds
- Added `build-backend.sh` `--add-data` flags for Alembic files in PyInstaller bundle
- Added `"tauri"` script to `package.json`
- Added `build-dmg` target to Makefile
- Successfully built and launched .dmg: wizard completes, file ingestion works (15/15 files succeeded)

### Files created
- `backend/services/migration_runner.py` — Alembic startup migration runner
- `backend/alembic.ini` — Alembic configuration
- `backend/alembic/env.py` — Migration environment
- `backend/alembic/script.py.mako` — Migration template
- `backend/alembic/versions/001_baseline.py` — Baseline migration (7 tables)
- `backend/tests/test_migration_runner.py` — Migration runner tests
- `scripts/build-dmg.sh` — Full .dmg build pipeline
- `docs/features/phase-6b-dmg-packaging.md` — Feature brief
- `docs/research/pyinstaller-onedir-tauri-bundling.md` — Research document

### Files modified
- `backend/main.py` — Migration runner replaces init_db, CORS wildcard, UTF-8 stdout
- `frontend/src-tauri/src/lib.rs` — Dual-mode sidecar spawning (production vs dev)
- `frontend/src-tauri/tauri.conf.json` — Bundle targets, CSP with IPC, DMG layout
- `frontend/src-tauri/Cargo.toml` — devtools feature
- `frontend/src/App.tsx` — Polling-based backend readiness
- `frontend/src/api/client.ts` — Content-Type only on POST/PUT/PATCH
- `frontend/src/ImportControls.tsx` — TypeScript fix for dialog result type
- `frontend/package.json` — Added tauri script
- `scripts/build-backend.sh` — Alembic data files in PyInstaller
- `Makefile` — build-dmg target
- `CLAUDE.md` — Phase 6b status, repo structure, design decisions, known issues
- `docs/djapp-project-plan.md` — Phase 6b–6f breakdown
- `.gitignore` — screenshots directory
- `frontend/src-tauri/icons/*` — Custom app icons

### Issues encountered and resolved
1. **PyInstaller not found** — `uv sync` doesn't install optional deps; fixed with `uv sync --extra dev`
2. **Missing npm "tauri" script** — Added `"tauri": "tauri"` to package.json
3. **Cargo not installed** — Installed via `rustup`; fixed `~/.zshenv` ownership (`sudo chown`)
4. **TypeScript error in ImportControls.tsx** — `result.path` on `never` type; simplified to `result`
5. **Empty resources/ directory** — Tauri build failed on `resources/*` glob; user copied ffmpeg binary
6. **`com.apple.provenance` xattr** — macOS Sequoia security flag causing permission denied; fixed with `cargo clean`
7. **PyInstaller `.app` mode detection** — Sidecar in `Contents/MacOS/` triggers wrong library resolution; fixed by placing in `Contents/MacOS/sidecar/` subdirectory
8. **Alembic env.py overriding DB URL** — Always set URL from Settings, overriding test URLs; made conditional
9. **Alembic autogenerate empty migration** — Ran against existing dev DB; used temp empty DB
10. **CORS preflight 400** — WebKit origin not matching `allow_origins`; fixed with wildcard `["*"]`
11. **Content-Type triggering preflight** — GET requests had `Content-Type: application/json`; now only on POST/PUT/PATCH
12. **CSP blocking Tauri IPC** — Added `ipc:` and `http://ipc.localhost` to `connect-src`
13. **Frontend "Backend unavailable"** — Single immediate health check failed before sidecar ready; replaced with polling retries
14. **ASCII codec error on unicode** — PyInstaller piped stdout defaults to ASCII; forced UTF-8 via `reconfigure()`
15. **`resource_dir()` path wrong in lib.rs** — Changed to `std::env::current_exe()` for reliable sidecar path resolution
16. **Ruff B017** — `pytest.raises(Exception)` flagged; changed to `pytest.raises((CommandError, Exception))`
17. **mypy import-not-found for alembic** — No type stubs; added `# type: ignore[import-not-found]`

### Key decisions made
1. `--onedir` maintained (not `--onefile`) — deliberate Session 1 decision backed by research (zombie process risk, code signing, startup time)
2. Sidecar in `Contents/MacOS/sidecar/` subdirectory — prevents PyInstaller `.app` mode detection
3. Post-build injection approach (Option 3) — Tauri builds .app, then script injects PyInstaller output
4. CORS wildcard `["*"]` — safe for local-only desktop app (backend binds to 127.0.0.1 only)
5. Frontend polling (not Tauri event listener) for backend readiness — more reliable, avoids race condition with event registration timing
6. Tauri `devtools` feature kept enabled during development for production debugging

### What's next
- End-to-end verification with full pipeline (wizard → ingest → analyse → organise → export)
- Merge `feature/phase-6b-dmg-packaging` → `develop` → `main`
- Phase 6c — UI Review & Bug Fixing (dogfooding with real library)

---

## Session 17 — 2026-03-15

### What was worked on
Phase 6b close-out — manual end-to-end verification from .dmg install, bug triage, merge decision.

### Summary
Ran the .dmg through manual acceptance testing. App installs, launches, connects to backend, and the core ingestion pipeline works. Several bugs discovered during testing — triaged as Phase 6c items rather than 6b blockers, since 6b's deliverable (installable .dmg + safe schema evolution) is met.

**What passed:**
- .dmg installs to Applications via drag-and-drop
- App launches (right-click → Open for Gatekeeper bypass)
- Backend sidecar spawns, frontend connects ("Connected to rekordbot backend v0.1.0")
- First-run wizard completes, config persisted to `~/Library/Application Support/rekordbot/`
- File ingestion: 15/15 files converted successfully
- Converted files tagged correctly and playable in Rekordbox

**Bugs found (deferred to 6c):**
1. **Organisation not applied after ingestion** — Files converted and tagged but not placed into the expected folder structure (Artist/Album). Needs investigation: may be a missing auto-organisation step, or a path resolution issue in packaged mode.
2. **Ghost tracks after file deletion** — Deleting converted files from disk leaves orphaned DB records. UI shows tracks without details. No way to clean up orphaned records from the UI — need a delete/remove tracks feature.
3. **Re-import blocked by ghost tracks** — Re-importing the same files fails (15 failed) because SHA-256 duplicate detection collides with the orphaned DB records pointing to deleted files. Duplicate detection needs to handle the case where the existing file is missing from disk.

### Key decisions made
1. Merge 6b as-is — the phase deliverable (installable .dmg + Alembic migrations) is complete. Bugs are dogfooding issues for 6c.
2. Phase 6c will prioritise the ingestion → organisation → export loop since that's the immediately useful workflow.
3. The three bugs above become the initial 6c backlog.

### What's next
- Merge `feature/phase-6b-dmg-packaging` → `develop` → `main` with `--no-ff` and phase tag
- Branch `feature/phase-6c-dogfooding` from `develop`
- Begin Phase 6c focusing on ingestion/organisation/export workflow bugs

---

## Session 18 — 2026-03-17

### What was worked on
Phase 6c — first round of bug fixes from dogfooding. Ghost tracks, duplicate detection, track deletion, packaged-mode logging, and ffmpeg path resolution.

### Summary
Fixed the three bugs triaged in Session 17, plus two packaged-mode infrastructure issues discovered during debugging.

**Bug fixes:**
- **Orphaned track cleanup (Bug 3):** Duplicate detection in `converter.py` now checks whether the matched track's output file still exists on disk. If missing, deletes the orphaned Track record and related CrateTrack/SetTrack rows, then allows ingestion to continue. 3 new tests (TDD).
- **Track deletion (Bug 2):** Added `DELETE /api/tracks` endpoint in `tagging.py` accepting `{track_ids, delete_files}`. Explicitly deletes CrateTrack/SetTrack associations before Track records (SQLite FK cascades not enabled). Optional file deletion from disk with graceful handling of already-missing files. 6 new tests.
- **Delete UI:** "Delete Selected" button in TrackTable with confirmation dialog, "also delete files" checkbox, toast notification on completion.
- **DELETE body parsing:** FastAPI doesn't parse JSON body for DELETE by default — added `Body(...)` annotation with `# noqa: B008` for Ruff compatibility.
- **DELETE Content-Type:** Frontend `request()` function wasn't setting `Content-Type: application/json` for DELETE method — added to the method list.

**Infrastructure fixes:**
- **File logging:** Added `RotatingFileHandler` (5MB, 3 backups) to `~/Library/Application Support/rekordbot/rekordbot.log` when `--parent-pid` is present. Diagnostic message logged immediately after handler setup.
- **Bundled ffmpeg path:** In packaged mode, `main.py` resolves `Contents/Resources/ffmpeg` relative to the sidecar executable and sets `REKORDBOT_FFMPEG_PATH` via `os.environ.setdefault()` before Settings instantiation.
- **`build_ffmpeg_command()` parameterised:** Now accepts `ffmpeg_path` parameter instead of hardcoding `"ffmpeg"`. `convert_file()` passes `settings.ffmpeg_path`.

**Test count:** 1154 → 1163 (+9 tests)

### Bugs encountered during development
1. **SQLite rowid reuse** — Test assertions checking orphan deletion by ID failed because SQLite reused the deleted row's primary key for the new track. Fixed by asserting on hash uniqueness and file_path instead of ID.
2. **DetachedInstanceError in test** — CrateTrack/SetTrack test accessed SQLAlchemy objects after `db.close()`. Fixed by capturing IDs into local variables before closing the session.

### Key decisions made
1. Explicit CrateTrack/SetTrack deletion rather than relying on FK cascades — SQLite doesn't enforce `ON DELETE CASCADE` without `PRAGMA foreign_keys = ON`, which isn't set in the app's engine configuration.
2. `Body(...)` with `# noqa: B008` for DELETE endpoint — standard FastAPI pattern, Ruff's B008 rule is a false positive for dependency injection defaults.
3. ffmpeg path resolved via `sys.executable` relative path, not PATH manipulation — more reliable, doesn't affect other subprocesses.

### Known remaining issues
- ffprobe is NOT bundled in `frontend/src-tauri/resources/` (only ffmpeg). In packaged mode, ffprobe will fail PATH lookup. Needs to be copied alongside ffmpeg before next .dmg build.
- Bug 1 (organisation not applied after ingestion) not yet investigated.

### What's next
- Bundle ffprobe in Tauri resources
- Rebuild .dmg and verify all fixes with real library
- Investigate Bug 1 (organisation pipeline in packaged mode)

---

## Session 19 — 2026-03-20

### What was worked on
Phase 6c — continued dogfooding fixes: packaged-mode logging, ffmpeg path resolution, and track table UX improvements.

### Summary
Fixed remaining packaged-mode infrastructure issues and several track table UX problems discovered during real-world testing with a large library.

**Packaged-mode fixes:**
- **Tauri resource path:** Fixed bundled ffmpeg path to use `Contents/Resources/resources/` (Tauri nests the `resources/` directory, not flattening it into `Contents/Resources/`).
- **File logging surviving uvicorn:** uvicorn's `dictConfig()` was stripping the root logger's file handler. Split handler creation (module level) from attachment (lifespan handler, after uvicorn init). Two iterations needed — first moved everything into lifespan, then split create/attach for cleaner separation.

**Track table UX fixes:**
- **Shift+click text selection:** Added `select-none` to table, but this broke row clicks in Tauri's WebKit webview. Reverted and used `e.preventDefault()` in `handleRowClick` when Shift is held instead.
- **Select All / Deselect All:** Button in the actions bar toggles between selecting and deselecting all visible tracks. Cmd+A keyboard shortcut intercepted to select all.
- **Vertical scrolling:** Table now scrolls within its viewport container (`min-h-0` on flex parent, `overflow-auto` on table wrapper).
- **Track limit:** Increased from 500 to 5000 (both frontend fetch and backend API validation) to support large libraries. Proper pagination deferred to Phase 6e.

### Bugs encountered during development
1. **`select-none` breaks WebKit clicks** — Tailwind's `select-none` (CSS `user-select: none`) prevents click events from firing in Tauri's WebKit webview. Fixed by using `e.preventDefault()` on Shift+click only.
2. **File handler stripped by uvicorn** — `uvicorn.run()` calls `logging.config.dictConfig()` which replaces all root logger handlers. Handler must be attached after uvicorn starts (in lifespan), not at module level.

### Key decisions made
1. `e.preventDefault()` on Shift+click rather than CSS `user-select: none` — WebKit compatibility.
2. File handler created at module level but attached in lifespan — clean separation, survives uvicorn's logger reconfiguration.
3. Track limit increased to 5000 as a pragmatic fix — full pagination is a Phase 6e concern.

### What's next
- ~~Bundle ffprobe in Tauri resources~~ ✅ Done
- Rebuild .dmg and verify all fixes with real library
- Investigate Bug 1 (organisation pipeline in packaged mode)

---

## Session 20 — 2026-03-20 (continued)

### What was worked on
Phase 6c Part 1 — full end-to-end dogfooding with 211-track real library.

### Summary
Completed a full dogfooding run: ingest → analyse → organise with a real 211-track library downloaded via slsk-batchdl. Confirmed the core pipeline works end-to-end in packaged mode. Also fixed processing queue layout overflow.

**What works in packaged mode (.dmg):**
- File ingestion: 211/211 succeeded (FLAC → AIFF conversion, MP3 copy)
- Tag reading: mutagen reads existing ID3/FLAC tags correctly — Title, Artist, Album, Genre populated
- BPM/Key analysis: librosa analysis completes (slow — ~15-20 min for 211 tracks at 1 concurrent)
- Organisation propose: 203 auto-approved, 8 need review (based on metadata quality)
- Organisation approve: files moved into Artist/Album folder structure correctly
- Review queue: Accept/Skip/Custom path options work
- Track selection: click, Cmd+click, Shift+click, Select All button all work
- Track deletion: Delete Selected with confirmation dialog works
- Processing queue: auto-collapses on completion with Show/Hide toggle
- Data persistence: tracks survive app quit and relaunch

**Fixes applied during dogfooding:**
- **Processing queue overflow:** Queue showing 211 file results pushed TrackTable off screen. Fixed with max-height constraint, auto-collapse on batch completion, and Show/Hide toggle button.
- **CLAUDE.md updated:** ffprobe now bundled, added known issues for uvicorn handler stripping and FastAPI DELETE body parsing.

**Bugs discovered (to fix in Part 2):**
1. **AI Tagging silently fails** — clicking "AI Tag All Untagged" or "AI Tag Selected" does nothing. No toast error visible. API key is configured in Settings. Needs log investigation.
2. **Layout breaks at normal window sizes** — track table invisible without maximising/full-screen. Drop zone + toolbars + processing queue consume all viewport space. Fundamental flex layout issue.
3. **Horizontal scroll reveals broken layout** — white space and split colour scheme when scrolling right.
4. **Analysis state lost on Settings navigation** — opening Settings panel while analysis is running disconnects SSE stream. On return, analysis appears stuck. Backend may still be running but frontend lost connection.
5. **Analysis restart blocked** — after Settings navigation interruption, "Analyse All Unanalysed" does nothing (backend thinks previous batch is still running).
6. **Scrolling breaks on relaunch** — track table not scrollable after app restart with existing data.
7. **File logging still not capturing post-startup logs** — the lifespan handler approach still doesn't work. uvicorn may be reconfiguring logging AFTER the lifespan handler runs. Need a different approach (e.g. uvicorn log_config parameter override).
8. **Review queue text invisible** — dark text on dark background in the review queue panel.
9. **Shift+click still selects text** — preventDefault in handleRowClick doesn't fully prevent browser text selection in WebKit.
10. **Bug 1 resolved** — "Organisation not applied after ingestion" was not a bug. Organisation needs metadata (from analysis/tagging) to make sensible proposals. Freshly ingested tracks with no metadata all go to "needs review" with 0% confidence, which is correct behaviour.

### Key decisions made
1. Bug 1 is not a bug — organisation correctly requires metadata before proposing folder structure.
2. Layout issues are the highest priority for Part 2 — the app is barely usable at normal window sizes.
3. AI tagging investigation needs working logs first — the logging issue blocks diagnosis.
4. Analysis performance (~4-5s per track) is acceptable for Phase 6c; optimisation deferred to 6d.

### What's next — Phase 6c Part 2 priorities
1. **Fix logging** — try uvicorn log_config override instead of root logger handler attachment
2. **Fix layout** — fundamental rework of App.tsx flex structure so track table is always visible
3. **Investigate AI tagging** — check logs (once working) or code to find why it silently fails
4. **Export XML** — test Rekordbox XML export with organised tracks
5. **Minor UX** — review queue text visibility, Shift+click text selection, deselect behaviour

---

## Session 21 — 2026-03-20 (continued)

### What was worked on
Phase 6c Part 2 — fixed the three highest-priority bugs from Session 20: file logging, layout, and AI tagging silent failure.

### Summary
Addressed Part 2 priorities #1–3 from Session 20. All three were code-only fixes (no tests, no build).

**1. File logging fixed (main.py, alembic/env.py):**
- Three iterations to find the real root cause:
  1. `_build_log_config()` dict passed via `log_config=` to `uvicorn.run()` — startup logs appeared but post-startup route handler logs did not.
  2. Added `"backend"` logger entry and belt-and-suspenders re-attachment in lifespan — handler was confirmed present but logs still missing.
  3. **Root cause found:** Alembic's `env.py` calls `fileConfig(config.config_file_name)` which reads `alembic.ini`'s `[loggers]` section, replacing root logger handlers and setting level to WARNING. Everything after `run_migrations()` went silent.
- Final fix: removed `fileConfig()` call from `env.py` (Alembic loggers inherit app config). Passed `log_config=None` to `uvicorn.run()` (skip `dictConfig()` entirely). Removed `_build_log_config()`. File handler attached in lifespan AFTER `run_migrations()`. `logging.basicConfig()` handles console logging for the whole process.
- Added `logger.info("Ingest request received: %d paths", ...)` in `routes/ingest.py` as a post-startup test point.

**2. Layout fixed (App.tsx, DropZone.tsx, TrackTable.tsx):**
- **App.tsx:** Added `shrink-0` to drop zone/import controls wrapper div. Wrapped TrackTable in `<div className="min-h-0 flex-1">` so it fills remaining space.
- **DropZone.tsx:** Made compact — changed from stacked vertical layout (`flex-col gap-4`, `p-12`) to inline row (`flex items-center gap-3`, `px-6 py-4`). Drop target text and format hint sit side-by-side. Button alongside drop target. Text sizes reduced (`text-lg` → `text-sm`, `text-sm` → `text-xs`).
- **TrackTable.tsx:** Wrapped AnalysisControls, OrganiseControls, ExportControls each in `<div className="shrink-0">`. Added `shrink-0` to track count/actions bar. Wrapped ReviewQueue in `<div className="max-h-48 shrink-0 overflow-auto">` to cap its height.
- Track table is now visible and scrollable at 800px window height with all toolbars showing.

**3. AI tagging silent failure diagnosed and fixed (AnalysisControls.tsx, ai_tagging.py):**
- Root cause: `postValidateApiKey()` makes a real `messages.create` call. If the Anthropic API returns a transient error (429 rate limit, 529 overload), the SDK raises `APIError`, the route returns `valid: false`, and the frontend disables the button — even with a valid key.
- Fix (backend): `validate_api_key` endpoint now distinguishes auth failures (`AuthenticationError` / "Invalid" in error) from transient API errors. Auth failures return `valid=false`; transient errors return `valid=true` with an error message (assume key is valid if not explicitly rejected).
- Fix (frontend): validation effect now only sets `hasApiKey=false` on genuine auth rejection. Transient errors and unreachable backend default to `hasApiKey=true`. Amber "API key not configured" hint only shows when no key is set (`apiKeyMissing` state), not on transient failures. Added `console.warn` in catch block.

**4. AI tagging encoding error investigated (turned out to be corrupted config — see Session 22):**
- AI tagging in packaged mode failed with `httpcore.LocalProtocolError: Illegal header value` — appeared to be `'ascii' codec can't encode character '\u2013'`.
- Initially appeared to be a PyInstaller ASCII encoding issue. Added `PYTHONUTF8=1`/`LANG`/`LC_ALL` env vars in main.py and later in Rust sidecar spawn.
- **Actual root cause discovered in Session 22:** the `anthropic_api_key` in config.json contained a previous error message string, not a real API key. The "encoding error" was the literal text of the error message being sent as the `X-Api-Key` header.

### Key decisions made
1. `log_config=None` to uvicorn — bypass `dictConfig()` entirely rather than fighting it. Simpler than building a dict config that survives uvicorn's internal handling.
2. Alembic `fileConfig()` removed — app logging is already configured; letting Alembic reconfigure it was the real culprit for silent post-startup logs.
3. DropZone made compact inline rather than hero-sized — it's a secondary action area, not the primary focus.
4. AI tagging validation: transient API errors should not disable the button. Only genuine auth rejection (invalid/missing key) should prevent usage.
5. `PYTHONUTF8=1` / `LANG` / `LC_ALL` set in Rust sidecar spawn as belt-and-suspenders for encoding in PyInstaller bundles, even though the immediate issue turned out to be corrupted config data (see Session 22).

### What's next
- Rebuild .dmg and verify all fixes with real library
- Test Rekordbox XML export with organised tracks
- Minor UX: review queue text visibility, Shift+click text selection

---

## Session 22 — 2026-03-20 (continued)

### What was worked on
Phase 6c Part 2 continued — packaged-mode testing of Session 21 fixes, debugging logging and AI tagging.

### Summary
Rebuilt .dmg and tested all three fixes from Session 21. Layout fix worked immediately. Logging and AI tagging required multiple iterations to resolve.

**Logging — iterative debugging to find root cause:**
- Session 21's `_build_log_config()` approach: file handler installed, startup logs captured, but post-startup route handler logs missing. Multiple iterations tried:
  1. Added `"backend"` logger with `propagate: False` to dictConfig — no improvement.
  2. Belt-and-suspenders handler re-attachment in lifespan — handler confirmed present, still no post-startup logs.
  3. Bypassed uvicorn entirely with `log_config=None` — same result.
- **Actual root cause found:** Alembic's `env.py` calls `fileConfig(config.config_file_name)` which reads `alembic.ini`'s `[loggers]/[handlers]/[formatters]` sections. This replaces root logger handlers (removing our RotatingFileHandler) and sets root level to WARNING. Everything after `run_migrations()` went silent.
- **Final fix:** Removed `fileConfig()` call from `env.py`. Kept `log_config=None` for uvicorn. File handler attached in lifespan AFTER `run_migrations()`. Full post-startup logging confirmed working: startup, access logs, ingest pipeline, converter decisions, batch completion, AI tagging validation.

**AI tagging — root cause was corrupted config, not encoding:**
- Logs revealed: `httpcore.LocalProtocolError: Illegal header value b" API error: 'ascii' codec can't encode character '\u2013' in position 138"` — looked like an encoding issue.
- Attempted fixes: `PYTHONUTF8=1`/`LANG`/`LC_ALL` as env vars in main.py (no effect — too late), then in Rust sidecar spawn (no effect — the error was not actually an encoding problem).
- **Actual root cause:** The `anthropic_api_key` value in `config.json` was the literal error message string `" API error: 'ascii' codec can't encode character '\u2013' in position 138: ordinal not in range(128)"` — a previous validation error had been saved as the key value. This garbage string was being sent as the `X-Api-Key` header, which Anthropic rejected, and httpcore reported as an illegal header value.
- After clearing the corrupted key and entering a fresh one, the Anthropic API was reached successfully (proper HTTP 400 response about credit balance, not a connection error).
- AI tagging is blocked only by Anthropic account billing — the `400 Bad Request` / "credit balance too low" error persists despite $5 balance showing in the Console. Likely a propagation delay or spending limit issue on Anthropic's side.

**Layout — confirmed working:**
- Track table visible and scrollable at normal window size (~1280x800). Drop zone compact inline. All toolbars visible with `shrink-0`.

### Bugs encountered during development
1. **Alembic `fileConfig()` nukes logging** — `env.py`'s `fileConfig(alembic.ini)` replaces root logger handlers and sets level to WARNING. Removing the call is safe; Alembic loggers inherit from the app's logging config.
2. **Corrupted API key in config.json** — An error message string was saved as the `anthropic_api_key` value. The Settings save pathway needs investigation — how did a validation error end up persisted as a config value? Low priority since it's a one-time occurrence and manually correctable.

### Key decisions made
1. `PYTHONUTF8=1` / `LANG` / `LC_ALL` env vars kept in Rust sidecar spawn despite not being the fix for this specific issue — they're still good practice for PyInstaller bundles on macOS.
2. The "encoding error" in AI tagging was a red herring — always check the actual config/data before assuming an encoding issue.
3. AI tagging end-to-end test deferred to Part 3 — blocked by Anthropic billing, not by app code.

### Remaining Session 20 bugs not yet addressed
- Bug 3: Horizontal scroll reveals broken layout (white space, split colour)
- Bug 4: Analysis state lost on Settings navigation (SSE disconnect)
- Bug 5: Analysis restart blocked after Settings interruption
- Bug 6: Scrolling breaks on relaunch
- Bug 8: Review queue text invisible (dark on dark)
- Bug 9: Shift+click still selects text in WebKit

### What's next — Phase 6c Part 3 priorities
1. **AI tagging end-to-end test** — once Anthropic billing resolves, test full tagging pipeline in packaged mode
2. **Export XML** — test Rekordbox XML export with organised tracks
3. **Investigate Settings save bug** — how did an error message get saved as the API key?
4. **Minor UX bugs** — review queue text visibility, horizontal scroll layout, analysis SSE interruption
5. **Full pipeline test with real library** — ingest → analyse → AI tag → organise → export
