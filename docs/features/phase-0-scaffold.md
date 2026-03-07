# Feature: Phase 0 — Project Scaffolding
**Branch:** `feature/phase-0-scaffold`
**Status:** Not Started

## Goal
A running skeleton: Tauri launches, spawns the Python backend, the React frontend confirms the connection, and it all shuts down cleanly. The database schema is in place. The dev workflow is smooth.

## Deliverables

### 1. Repo & Tooling

- [ ] Git repo initialised on `main`, with `develop` branch created
- [ ] `feature/phase-0-scaffold` branch created from `develop`
- [ ] `pyproject.toml` as the single source of truth for Python dependencies — no `requirements.txt`
- [ ] Python virtual environment (`.venv/`) — gitignored
- [ ] `Makefile` with targets:
  - `dev-backend` — starts uvicorn with `--reload` on port 8420
  - `dev-frontend` — starts `tauri dev`
  - `build-backend` — runs PyInstaller `--onedir` build + renames output with target triple
  - `build` — full production build (backend then frontend)
  - `test` — runs `pytest`
- [ ] `.gitignore` covering: `.venv/`, `__pycache__/`, `.env`, `dist/`, `build/`, `*.pyc`, `frontend/src-tauri/binaries/`, `frontend/src-tauri/resources/`, `node_modules/`, `target/`
- [ ] `.env.example` with placeholder for `ANTHROPIC_API_KEY` (not needed yet, but establishes the pattern)
- [ ] `CLAUDE.md` — full project context file (see separate document)
- [ ] `SESSIONS.md` — session log initialised with pre-Phase-0 planning session
- [ ] `README.md` — project overview, dev setup instructions, tech stack summary
- [ ] `docs/` folder structure:
  - `docs/features/phase-0-scaffold.md` (this file)
  - `docs/features/converter.md` (placeholder — to be written before Phase 1)
  - `docs/research/rekordbox-xml-cdj-compatibility.md` (Chat A output, archived)
  - `docs/research/tauri-python-backend.md` (Chat B output, archived)
  - `docs/architecture.md` (placeholder — to be fleshed out during Phase 0)
- [ ] `scripts/` folder:
  - `scripts/build-backend.sh` — PyInstaller build + target-triple rename
  - `scripts/dev-setup.sh` — one-command dev environment setup (create venv, install deps, install npm packages, confirm ffmpeg available)

### 2. Python Backend

- [ ] `backend/main.py` — FastAPI app entry point
  - `/health` endpoint returning `{"status": "ok", "version": "0.1.0"}`
  - CORS middleware configured for:
    - `http://tauri.localhost` (Tauri production)
    - `https://tauri.localhost` (Tauri production, some platforms)
    - `http://localhost:1420` (Vite dev server)
  - Configurable port via `--port` CLI argument (default: 8420)
  - `if __name__ == "__main__"` block running uvicorn (used by both dev mode and PyInstaller)
- [ ] `backend/models/__init__.py` — SQLAlchemy base setup
- [ ] `backend/models/database.py` — engine, session factory, Base declarative class
  - SQLite database file location: use platform-appropriate app data directory (not the repo)
  - During development: `./crateai_dev.db` in the repo root (gitignored)
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

### 3. React Frontend

- [ ] Scaffolded with Vite + React + TypeScript
- [ ] Tailwind CSS installed and configured
- [ ] Minimal `App.tsx`:
  - On mount, fetches `GET /health` from the backend
  - Displays connection status: "Connected to CrateAI backend v0.1.0" or "Backend unavailable"
  - Basic layout shell (header, sidebar placeholder, main content area) — does not need to look polished, just establishes the component structure
- [ ] API client utility (`src/api/client.ts`):
  - Base URL logic: reads from environment in dev, from Tauri-provided port in production
  - Typed fetch wrapper for backend requests
- [ ] `package.json` with scripts: `dev`, `build`, `preview`

### 4. Tauri Shell

- [ ] Tauri v2 initialised inside `frontend/src-tauri/`
- [ ] `tauri.conf.json`:
  - App identifier: `com.crateai.app`
  - Window title: "CrateAI"
  - Default window size: 1280x800
  - CSP configured with `connect-src` allowing `localhost:8420` and `127.0.0.1:8420`
  - `externalBin` pointing to `binaries/crateai-server`
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
- [ ] Build script renames output with correct target triple (e.g., `crateai-server-aarch64-apple-darwin`)
- [ ] Full app launch via `cargo tauri dev` with sidecar:
  - Tauri window opens
  - Backend sidecar spawns
  - Frontend displays "Connected" after health check passes
  - Closing the window kills the sidecar process (verify no orphan `crateai-server` process remains)
- [ ] Confirm ffmpeg is available via Homebrew (`which ffmpeg` succeeds) — no bundling yet

## Acceptance Criteria

- [ ] `make dev-backend` starts FastAPI with hot reload on port 8420
- [ ] `make dev-frontend` starts Tauri dev mode with React HMR
- [ ] Frontend connects to backend and displays health status in both dev modes
- [ ] `make test` passes — health endpoint test and model test both green
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
2. **pyproject.toml only** — no requirements.txt
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
