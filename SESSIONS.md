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
- [ ] Apply `-write_id3v2 1` bugfix to `converter.py`
- [ ] Re-ingest test files from clean slate
- [ ] Complete full pipeline: ingest → analyse → (AI tag optional) → organise → export
- [ ] Manual Rekordbox import verification (the actual acceptance test)
- [ ] Update CLAUDE.md Known Issues with the `-write_id3v2` note
- [ ] Update CLAUDE.md repo path (rekordbot, not crateai)

### What's next
1. Apply the AIFF metadata bugfix (Claude Code prompt prepared in test guide)
2. Re-run the full pipeline with clean data
3. Complete the Rekordbox import test
4. If test passes: merge `feature/phase-4-rekordbox` → `develop` → `main`, tag `phase-4-complete`
5. Decide next phase: Phase 4b (XML Import) or Phase 5 (Crate Builder & Set Planner)
