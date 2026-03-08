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
3. PyInstaller sidecar structure: executable gets target-triple suffix for Tauri, `_internal/` placed alongside it
4. Lifespan pattern over on_event for FastAPI startup/shutdown hooks

### What's next
- Merge `feature/phase-0-scaffold` to `develop` once manually verified
- Write Phase 1 feature brief (File Ingestion & Conversion)
- Begin Phase 1 implementation

---

## Session 3 — 2026-03-07

### What was worked on
Phase 1 implementation — File Ingestion & Conversion, from feature brief to fully working pipeline.

### Summary
- Created branch `feature/phase-1-converter` from `develop`
- Implemented all 10 steps of the Phase 1 build plan in order:
  1. **Dependencies & config** — Added sse-starlette, ffprobe_path, output_directory, max_concurrent_conversions, convert_aac_to_mp3 to Settings
  2. **Track model updates** — Added source_path, source_codec, source_bitrate, source_bit_depth, conversion_action, imported_at; changed file_hash to String(64) with unique index; changed quality_warning from Text to Boolean
  3. **Format inspector (TDD)** — FileInfo dataclass, parse_ffprobe_output(), determine_lossless(), get_quality_warning(), inspect_file(); 37 tests
  4. **Conversion decision engine (TDD)** — ConversionAction dataclass, decide_conversion() implementing full decision table; 18 tests
  5. **Output naming (TDD)** — generate_output_path() with date-batched dirs and collision handling; 12 tests
  6. **Converter service** — build_ffmpeg_command(), compute_file_hash(), convert_file() orchestrator; 8 tests
  7. **Processing queue** — ProcessingQueue with asyncio.Semaphore, SSE events, cancellation; 6 tests
  8. **API routes** — POST /api/ingest, GET /api/ingest/progress (SSE), POST /api/ingest/cancel, GET /api/tracks; 8 tests
  9. **Frontend** — DropZone, ProcessingQueue, TrackList components; API client extended with ingest/tracks/SSE methods
  10. **Test fixtures & integration** — 8 audio fixtures (1s silence each), 17 integration tests covering all format paths + duplicate detection
- **Total: 114 tests passing, 10 clean commits, all pre-commit hooks green**

### Issues encountered and resolved
1. **ffprobe `bits_per_raw_sample` missing for PCM** — ffprobe uses `bits_per_sample` for PCM codecs and `bits_per_raw_sample` for FLAC/ALAC. Fixed by checking both fields with fallback.
2. **ffprobe `bits_per_sample=0` for MP3** — Lossy codecs report 0, which was being picked up as a valid bit depth. Fixed by treating 0 as absent.
3. **sse-starlette missing mypy stubs** — Added `type: ignore[import-not-found]` on the import.
4. **Pydantic `class Config` deprecation** — Changed to `model_config = {"from_attributes": True}` in TrackResponse.
5. **Test DB tables not created** — ASGITransport client doesn't trigger FastAPI lifespan; added `init_db()` call in the client fixture.
6. **Module-level queue state leaking between tests** — Reset `_queue` to None in the client fixture.
7. **Tauri dialog import fails in Vite build** — `@tauri-apps/api/dialog` doesn't exist in Tauri v2; installed `@tauri-apps/plugin-dialog` and used dynamic import with try/catch for browser fallback.
8. **Ruff formatting on every commit** — Several files needed reformatting by ruff-format after initial write; fixed on second commit attempt each time.

### Key decisions made
1. Track model keeps both `codec` (general) and `source_codec` (Phase 1 provenance) — they serve different purposes
2. quality_warning changed from Text to Boolean — the warning detail is in the ConversionAction, not stored in DB
3. Bit depth capped at 24 in ConversionAction (decision engine), not in build_ffmpeg_command (executor just follows the decision)
4. Source file hash computed before conversion for cross-format duplicate detection
5. Module-level ProcessingQueue singleton in routes — only one batch at a time
6. Tauri dialog via dynamic import so the app degrades gracefully in browser dev mode

### What's next
- Merge `feature/phase-1-converter` to `develop`
- Begin Phase 2 (Metadata & Tagging) — mutagen tag reading/writing, BPM detection, key detection

---

## Session 4 — 2026-03-08

### What was worked on
Phase 2 implementation — Metadata & Tagging, from feature brief to fully working analysis pipeline with Rekordbox-style review UI.

### Summary
- Created branch `feature/phase-2-metadata-tagging` from `develop`
- Implemented all 11 steps of the Phase 2 build plan in order:
  1. **Dependencies & config** — Added mutagen, librosa, numpy; added bpm_range_min/max, confidence_threshold, max_concurrent_analyses, default_key_notation to Settings
  2. **Track model updates** — Added source_bpm, source_key, bpm_confidence, key_confidence, analysis_status columns
  3. **Key notation mapping (TDD)** — Full Camelot ↔ Open Key ↔ classical key conversion; 171 tests covering all 24 keys × multiple notations
  4. **Tag reader** — mutagen-based tag extraction from AIFF (ID3v2), MP3 (ID3v2), M4A (MP4 atoms); 24 tests
  5. **BPM detector (TDD)** — librosa onset/beat_track with configurable half/double-time auto-correction; 20 tests
  6. **Key detector (TDD)** — librosa chroma + HPSS harmonic separation + Krumhansl-Schmuckler algorithm; 14 tests
  7. **Tag writer** — ID3v2.3 for AIFF/MP3 (no v1), MP4 atoms for M4A, preserves unmanaged tags; 12 tests
  8. **Analysis pipeline** — asyncio.Semaphore batch processing, per-track error isolation, SSE progress events; 7 tests
  9. **API routes** — POST /api/tracks/analyse, SSE progress, cancel, PUT /api/tracks/{id}, revert, bpm-multiply, POST /api/tracks/write-tags, enhanced GET /api/tracks; 15 tests
  10. **Frontend** — TrackTable (Rekordbox-style sortable table, column visibility toggle via ColumnMenu, inline editing, BPM ×2/÷2, confidence indicators, filter modes), AnalysisControls toolbar with progress bar, TrackDetailPanel side panel
  11. **Integration tests** — End-to-end ingest→analyse→write flow, tag round-trips, revert/multiply; 13 tests
- **Total: 390 tests passing (276 new), 12 clean commits, all pre-commit hooks green**

### Issues encountered and resolved
1. **Stale dev database schema** — After adding new columns to the Track model, the on-disk dev DB didn't have them. `init_db()` in the test client fixture used the dev DB's engine, causing `OperationalError: no such column: tracks.source_bpm`. Fixed by deleting the stale dev DB so `init_db()` would recreate it with all columns. This surfaced twice (after model changes and during route tests).
2. **AIFF `IffID3.save()` does not support `v1` parameter** — Tag writer initially called `audio.save(v1=0)` for all ID3 formats. AIFF's `IffID3` class doesn't accept this kwarg. Fixed with isinstance-based type detection: MP3 gets `save(v1=0)`, AIFF gets plain `save()`.
3. **Test isolation / dev DB data leaking** — Tagging route tests inserted data via `SessionLocal` (dev DB). Subsequent tests asserting empty state failed because data persisted. Fixed by adding cleanup logic to the client fixture.
4. **BPM conflict detection threshold** — Conflict detection used `> 0.5` BPM difference, but test data had exactly 0.5 difference (128.0 vs 127.5). Adjusted test data to clearly exceed the threshold.
5. **Ruff lint violations on every commit** — Pre-commit hooks caught SIM118 (unnecessary `.keys()`), SIM105 (`try/except/pass` → `contextlib.suppress()`), E501 (line too long), and import ordering issues throughout Phase 2 code. All fixed before committing.
6. **mypy type errors with numpy/mutagen/librosa** — All three lack mypy stubs; added `type: ignore[import-not-found]` on imports. Integration tests also needed explicit None guards where `float | None` values were used in arithmetic.
7. **ESLint unused vars in frontend** — Unused imports (`useEffect`) and variables (`confidenceThreshold`) caught during frontend commit. Fixed before committing.
8. **librosa audioread fallback warnings** — `PySoundFile failed. Trying audioread instead` warnings appeared with M4A files. Known librosa behavior, harmless, documented in Known Issues.

### Key decisions made
1. AIFF vs MP3 tag save divergence — isinstance-based type detection for format-specific save calls rather than a single code path
2. TDD for pure logic modules (key notation, BPM correction, key correlation); tests-after for framework integration (routes, pipeline)
3. Key stored internally as integer 1–24 (Camelot wheel mapping), converted to user-preferred notation on display/export
4. TrackTable replaces TrackList as the primary track view — Rekordbox-style sortable table with inline editing
5. Pragmatic test isolation fix (clean tracks table in fixture) rather than full test DB rearchitecture
6. Per-track error isolation in analysis pipeline — one track failing doesn't abort the batch
7. Confidence scores stored alongside detected values (bpm_confidence, key_confidence) for UI display and conflict detection
8. Source values preserved (source_bpm, source_key) to enable revert-to-original after edits

### What's next
- Merge `feature/phase-2-metadata-tagging` to `develop`
- Begin Phase 2b (File Organisation) or Phase 3 (Claude Integration)

---

## Session 5 — 2026-03-08

### What was worked on
Phase 3 implementation — Claude AI Integration, from feature brief to fully working AI tagging pipeline with UI.

### Summary
- Created branch `feature/phase-3-claude` from `develop`
- Implemented all 8 steps of the Phase 3 build plan in order:
  1. **Dependencies, config & cleanup** — Added anthropic SDK; added ai_model, ai_batch_size, ai_max_requests_per_minute to Settings; added AiTagError exception; deleted dead TrackList.tsx (superseded by TrackTable in Phase 2)
  2. **Track model updates** — Replaced placeholder AI columns with spec-compliant ones: subgenre, mood, energy (1–10), ai_confidence (high/medium/low), ai_reasoning, source_genre, ai_status (untagged/ai_tagged/ai_tags_written/ai_failed); 2 tests
  3. **Prompt builder (TDD)** — System prompt with DJ-centric genre taxonomy (~50 genres), tool use schema for structured output, build_track_summary(), build_batch_message(), group_tracks_into_batches() with artist grouping optimisation, parse_tool_result() with energy clamping and confidence validation; 34 tests
  4. **Claude client** — Anthropic SDK wrapper with RateLimiter (timestamp-based throttle), exponential backoff retry on 429/529 (max 3 retries), TokenUsage tracking, cost estimation ($3/MTok input, $15/MTok output), validate_api_key(); 11 tests
  5. **AI tagger pipeline** — AiTagger orchestrator with AiTagPipelineResult, _process_batch() with per-batch error isolation, cancellation via asyncio.Event, SSE event_generator() emitting ai_tag_batch_progress and ai_tag_complete events, source genre preservation; 8 tests
  6. **API routes** — POST /api/tracks/ai-tag, GET /api/tracks/ai-tag/progress (SSE), POST /api/tracks/ai-tag/cancel, GET /api/tracks/ai-tag/status, POST /api/tracks/ai-tag/validate-key; 11 tests
  7. **Frontend** — Extended TrackTable with 5 new columns (subgenre, mood, energy, ai_confidence, ai_status), energy colour coding (1–3 blue, 4–6 neutral, 7–8 amber, 9–10 red), AI confidence colour coding (high=green, medium=amber, low=red), genre tooltip showing AI reasoning, inline editing for new fields, ai_tagged/not_ai_tagged filter modes; Extended AnalysisControls with purple AI Tag button (disabled without API key), AI progress bar with count, token usage summary after completion, dismiss button; Extended API client with all AI tagging types and endpoints
  8. **Integration tests & docs** — End-to-end AI tag flow, genre revert after AI tagging, re-tagging already-tagged tracks, missing API key error handling, write-tags ai_status transition; updated CLAUDE.md with Phase 3 status and repo structure; 7 tests
- **Total: 462 tests passing (72 new), 8 clean commits, all pre-commit hooks green**

### Issues encountered and resolved
1. **Pre-commit not installed** — `python3: No module named pre_commit` after environment setup. Fixed with `uv pip install pre-commit` after activating venv.
2. **pytest not found** — Dev dependencies were in `[project.optional-dependencies]` not `[dependency-groups]`. Fixed with `uv pip install -e ".[dev]"`.
3. **Ruff E501 in system prompt** — Long lines in multiline string literal can't use `# noqa`. Fixed by extracting `_GENRE_LIST` and `_MOOD_EXAMPLES` helper variables with line continuations.
4. **mypy FakeTrack.id** — Test helper class needed explicit type annotations on class attributes to satisfy mypy.
5. **mypy dict annotation** — `tool_input` dict needed explicit `dict[str, list[object]]` type annotation.
6. **Ruff B904 raise from** — 7 occurrences of `raise AiTagError(...)` inside except blocks needed `from None` or `from e`.
7. **AsyncMock making sync methods async** — `get_token_usage()` is sync but `AsyncMock()` made it return a coroutine. Fixed by using `MagicMock()` for the client and explicitly setting `mock_client.tag_batch = AsyncMock()`.
8. **Cancellation test design** — `cancel()` before `tag_tracks()` didn't work because the method clears the cancel event at start. Redesigned test to cancel during first batch processing via `side_effect`.
9. **mypy Track | None in loop** — `track_map.get()` returns `Track | None` but loop variable `track` was already typed as `Track`. Fixed by using `matched_track` variable name.
10. **SQLite "no such column: tracks.subgenre"** — Dev database had old schema. Fixed by deleting `rekordbot_dev.db` and letting `init_db()` recreate it.
11. **Test isolation between test files** — `test_ai_tagging_routes.py` left data in DB that caused `test_ingest_routes.py::test_list_tracks_empty` to fail. Fixed by adding track cleanup and module state reset to conftest.py's shared `client` fixture.

### Key decisions made
1. Tool use (function calling) for structured output — guarantees parseable JSON with exact field names, types, and constraints
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
