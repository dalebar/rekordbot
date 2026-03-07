# Feature: Phase 0 — Project Scaffolding
**Branch:** `feature/phase-0-scaffold`
**Status:** Not Started

## Goal
A running skeleton: Tauri launches, spawns the Python backend, the React frontend confirms the connection, and it all shuts down cleanly. The database schema is in place. The dev workflow is smooth. Linting, logging, error handling patterns, and configuration management are established from day one.

## Deliverables

### 1. Repo & Tooling

- [ ] `develop` branch created from `main`
- [ ] `feature/phase-0-scaffold` branch created from `develop`
- [ ] `pyproject.toml` as the single source of truth for Python dependencies — no `requirements.txt`
  - All dependencies pinned to exact versions (e.g. `fastapi==0.115.0`)
  - Ruff configuration in `[tool.ruff]` section (see CLAUDE.md for exact config)
  - pytest configuration in `[tool.pytest.ini_options]` section
- [ ] Python virtual environment (`.venv/`) — gitignored
- [ ] `Makefile` with targets:
  - `dev-backend` — starts uvicorn with `--reload` on port 8420
  - `dev-frontend` — starts `tauri dev`
  - `build-backend` — runs PyInstaller `--onedir` build + renames output with target triple
  - `build` — full production build (backend then frontend)
  - `test` — runs `pytest`
  - `lint` — runs `ruff check .` and `ruff format --check .`
  - `format` — runs `ruff format .` and `ruff check --fix .`
- [ ] `.gitignore` covering: `.venv/`, `__pycache__/`, `.env`, `dist/`, `build/`, `*.pyc`, `frontend/src-tauri/binaries/`, `frontend/src-tauri/resources/`, `node_modules/`, `target/`, `rekordbot_dev.db`
- [ ] `.env.example` with all available config values:
  ```
  REKORDBOT_PORT=8420
  REKORDBOT_DB_URL=sqlite:///rekordbot_dev.db
  REKORDBOT_LOG_LEVEL=INFO
  REKORDBOT_FFMPEG_PATH=ffmpeg
  REKORDBOT_ANTHROPIC_API_KEY=
  ```
- [ ] `CLAUDE.md` — full project context file (already written, rename CrateAI → rekordbot as first commit)
- [ ] `SESSIONS.md` — session log (already initialised, rename as above)
- [ ] `README.md` — project overview, dev setup instructions, tech stack summary
- [ ] `docs/` folder structure:
  - `docs/features/phase-0-scaffold.md` (this file)
  - `docs/features/converter.md` (placeholder — to be written before Phase 1)
  - `docs/research/rekordbox-xml-cdj-compatibility.md` (already in place)
  - `docs/research/tauri-python-backend.md` (already in place)
  - `docs/architecture.md` (placeholder — to be fleshed out during Phase 0)
- [ ] `scripts/` folder:
  - `scripts/build-backend.sh` — PyInstaller build + target-triple rename
  - `scripts/dev-setup.sh` — one-command dev environment setup (create venv, install deps, install npm packages, confirm ffmpeg available)

### 2. Python Backend

- [ ] `backend/main.py` — FastAPI app entry point
  - `/health` endpoint returning `{"status": "ok", "version": "0.1.0"}`
  - `/shutdown` endpoint (POST) for graceful sidecar shutdown
  - CORS middleware configured for:
    - `http://tauri.localhost` (Tauri production)
    - `https://tauri.localhost` (Tauri production, some platforms)
    - `http://localhost:1420` (Vite dev server)
  - Global exception handler for `RekordBotError` → standard JSON error response
  - Fallback exception handler for unexpected errors → log traceback, return generic 500
  - Logging configured at startup (level from config, human-readable format)
  - `if __name__ == "__main__"` block running uvicorn (used by both dev mode and PyInstaller)

- [ ] `backend/config.py` — pydantic-settings configuration
  - `Settings` class with fields: `port`, `db_url`, `log_level`, `ffmpeg_path`, `anthropic_api_key`
  - Env prefix: `REKORDBOT_`
  - Reads from `.env` file if present

- [ ] `backend/exceptions.py` — custom exception hierarchy
  - `RekordBotError` base class with `error`, `detail`, `status_code` attributes
  - Placeholder subclasses: `ConversionError`, `DuplicateTrackError`, `TagReadError`, `TagWriteError`
  - These are stubs for now — they'll be used in later phases, but the pattern is established

- [ ] `backend/models/__init__.py` — SQLAlchemy base setup
- [ ] `backend/models/database.py` — engine, session factory, Base declarative class
  - SQLite database path from config (`Settings.db_url`)
  - During development: `./rekordbot_dev.db` in the repo root (gitignored)
- [ ] `backend/models/track.py` — Track model with full schema from research:

  **Core identification:**
  - `id` — Integer, primary key, autoincrement
  - `file_path` — Text, not null, unique (absolute path on disk)
  - `file_hash` — Text, nullable (SHA-256 for duplicate detection)

  **Audio properties (populated by converter in Phase 1):**
  - `source_format` — Text (original format: "mp3", "aiff", "wav", "flac", "alac", "aac")
  - `output_format` — Text (format after conversion)
  - `codec` — Text (actual codec string from ffprobe)
  - `bit_rate` — Integer (Kbps)
  - `sample_rate` — Integer (Hz)
  - `bit_depth` — Integer, nullable (16, 24, or null for lossy)
  - `duration` — Float (seconds)
  - `file_size` — Integer (bytes)
  - `channels` — Integer
  - `is_lossy` — Boolean
  - `quality_warning` — Text, nullable ("low_bitrate" for <192kbps lossy, else null)

  **Metadata (populated by tagger in Phase 2, or read from source tags):**
  - `title` — Text
  - `artist` — Text
  - `album` — Text
  - `genre` — Text
  - `composer` — Text
  - `remixer` — Text
  - `label` — Text
  - `mix_name` — Text
  - `grouping` — Text
  - `year` — Integer, nullable
  - `track_number` — Integer, nullable
  - `disc_number` — Integer, nullable
  - `comment` — Text
  - `key` — Integer, nullable (normalised 1–24 Camelot mapping)
  - `key_text` — Text, nullable (display string written to tags/XML)
  - `bpm` — Float, nullable (two decimal places)
  - `rating` — Integer, default 0 (0–5 internally; convert to 0/51/102/153/204/255 on XML export)
  - `colour` — Text, nullable (hex RGB, e.g. "0xFF007F")

  **AI enrichment (populated by Claude layer in Phase 3):**
  - `energy` — Integer, nullable (1–10)
  - `mood` — Text, nullable
  - `ai_genre` — Text, nullable
  - `ai_confidence` — Float, nullable (0.0–1.0)
  - `ai_tags` — Text, nullable (JSON string)

  **Operational:**
  - `date_added` — Text (yyyy-mm-dd)
  - `date_modified` — Text (yyyy-mm-dd)
  - `play_count` — Integer, default 0
  - `last_played` — Text, nullable
  - `conversion_status` — Text, default "pending" (pending/converted/skipped/error)
  - `organisation_status` — Text, default "pending" (pending/proposed/confirmed/error)

- [ ] Alembic initialised for database migrations
  - Initial migration creates the tracks table
  - `alembic.ini` and `alembic/` directory in `backend/`
- [ ] `backend/tests/test_health.py` — test that `/health` returns 200 with expected payload
- [ ] `backend/tests/test_models.py` — test that Track model can be created, saved, and queried
- [ ] `backend/tests/test_exceptions.py` — test that error handler returns correct JSON structure for RekordBotError and for unexpected exceptions
- [ ] `backend/tests/test_config.py` — test that Settings loads defaults and respects env vars

### 3. React Frontend

- [ ] Scaffolded with Vite + React + TypeScript
- [ ] Tailwind CSS installed and configured
- [ ] ESLint + Prettier configured
- [ ] Minimal `App.tsx`:
  - On mount, fetches `GET /health` from the backend
  - Displays connection status: "Connected to rekordbot backend v0.1.0" or "Backend unavailable"
  - Basic layout shell (header, sidebar placeholder, main content area) — does not need to look polished, just establishes the component structure
- [ ] API client utility (`src/api/client.ts`):
  - Base URL logic: reads from environment in dev, from Tauri-provided port in production
  - Typed fetch wrapper for backend requests
  - Error response type matching the backend's `{"error": str, "detail": str}` schema
- [ ] `package.json` with scripts: `dev`, `build`, `preview`, `lint`, `format`

### 4. Tauri Shell

- [ ] Tauri v2 initialised inside `frontend/src-tauri/`
- [ ] `tauri.conf.json`:
  - App identifier: `com.rekordbot.app`
  - Window title: "rekordbot"
  - Default window size: 1280x800
  - CSP configured with `connect-src` allowing `localhost:8420` and `127.0.0.1:8420`
  - `externalBin` pointing to `binaries/rekordbot-server`
  - `beforeDevCommand`: starts Vite dev server
  - `beforeBuildCommand`: runs frontend build
- [ ] Shell plugin (`tauri-plugin-shell`) installed and configured
- [ ] `src-tauri/capabilities/default.json` with sidecar execution permission
- [ ] `src-tauri/src/main.rs`:
  - Spawn sidecar on `RunEvent::Ready`
  - Poll `/health` endpoint until backend responds (with timeout and retry)
  - Emit "backend-ready" event to frontend once health check passes
  - Kill sidecar on `RunEvent::ExitRequested`
  - Forward sidecar stdout/stderr to Tauri's log system
- [ ] `src-tauri/binaries/` directory (gitignored, populated by build script)
- [ ] `src-tauri/resources/` directory (gitignored, for ffmpeg later)

### 5. Integration Proof

- [ ] PyInstaller `--onedir` build of the Python backend succeeds
- [ ] Build script renames output with correct target triple (e.g., `rekordbot-server-aarch64-apple-darwin`)
- [ ] Full app launch via `cargo tauri dev` with sidecar:
  - Tauri window opens
  - Backend sidecar spawns
  - Frontend displays "Connected" after health check passes
  - Closing the window kills the sidecar process (verify no orphan `rekordbot-server` process remains)
- [ ] Confirm ffmpeg is available via Homebrew (`which ffmpeg` succeeds) — no bundling yet

## Acceptance Criteria

- [ ] `make dev-backend` starts FastAPI with hot reload on port 8420
- [ ] `make dev-frontend` starts Tauri dev mode with React HMR
- [ ] Frontend connects to backend and displays health status in both dev modes
- [ ] `make test` passes — health endpoint, model, exception, and config tests all green
- [ ] `make lint` passes with no warnings
- [ ] `make build-backend` produces a working PyInstaller binary
- [ ] Full sidecar integration works: launch → health check → display → clean shutdown
- [ ] No orphan processes after app close
- [ ] Database migrations run cleanly (`alembic upgrade head` creates the tracks table)
- [ ] All files committed with meaningful messages
- [ ] `CLAUDE.md` reflects current project state
- [ ] `SESSIONS.md` has entry for the Phase 0 session(s)

## Out of Scope

- File conversion logic (Phase 1)
- Audio processing or metadata reading (Phase 2)
- Any real UI beyond the health check and layout shell (Phase 1+)
- ffmpeg bundling (confirm availability only; bundling is a packaging concern for Phase 6)
- Claude/Anthropic SDK integration (Phase 3)
- Rekordbox XML generation (Phase 4)
- macOS code signing and notarisation (Phase 6)
- Auto-update mechanism (Phase 6)

## Dependencies

- Python 3.12 installed
- Node.js 18+ installed
- Rust toolchain installed (for Tauri)
- ffmpeg installed via Homebrew (for later phases; confirm in Phase 0)
- No external services or API keys required for Phase 0

## Notes / Decisions Already Made

Decisions confirmed in the main project chat before this brief was written:

1. **Mac-first, Windows-compatible by design** — build and test on macOS, keep code OS-agnostic
2. **pyproject.toml only** — no requirements.txt, exact version pins
3. **PyInstaller `--onedir`** — avoids zombie processes, easier to sign
4. **ffmpeg as Tauri resource** (not sidecar) — Python calls it via subprocess
5. **Hardcoded port 8420** with conflict detection — add dynamic assignment later if needed
6. **SSE for progress reporting** — unidirectional server-push, simpler than WebSocket
7. **Apple Silicon only** for initial builds — Intel support later if needed
8. **ID3v2.3 as primary tag target** — universal CDJ compatibility
9. **Key stored as integer 1–24** (Camelot wheel mapping) — convert to display notation on output
10. **Rekordbox XML export-only in Phase 4** — import is Phase 4b or later
11. **Tauri IPC for desktop integration only** — all business logic via HTTP to FastAPI
12. **Sidecar integration tested at end of Phase 0** — don't proceed to Phase 1 without this proof
13. **Ruff for Python linting/formatting** — replaces black + isort + flake8 in one tool
14. **pydantic-settings for configuration** — typed, validated, env var support with REKORDBOT_ prefix
15. **Standard logging module** — INFO default, DEBUG via config, human-readable in dev
16. **Consistent error response schema** — `{"error": str, "detail": str}` on all non-2xx responses
17. **Custom exception hierarchy** — RekordBotError base class, subclasses per domain
