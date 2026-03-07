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
