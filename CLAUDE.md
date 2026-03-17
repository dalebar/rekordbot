# rekordbot — Claude Context File

## Project Overview

rekordbot is a desktop application for digital DJs who use Rekordbox and CDJs. It handles the full file management workflow: ingest music files from any source/format, convert them with quality-preserving logic (lossless → AIFF, lossy left as-is or converted to MP3), auto-tag with BPM/key/genre/mood using algorithmic analysis and Claude AI, organise into a clean folder structure, build crates, plan sets, and export a Rekordbox-compatible XML library. All file operations use dry-run previews — nothing moves without user approval.

Target user: Dale and his DJ peers, with monetisation potential later.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, uvicorn
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS v4
- **Desktop shell:** Tauri v2 (Rust)
- **Database:** SQLite via SQLAlchemy (sync mode), Alembic for schema migrations (Phase 6b)
- **Audio conversion:** ffmpeg (via subprocess), ffprobe for container inspection
- **Metadata:** mutagen (ID3 tag reading/writing for AIFF and MP3)
- **BPM/Key detection:** librosa (BPM via beat_track, key via chroma + Krumhansl-Schmuckler)
- **AI layer:** Anthropic Python SDK (Claude) — genre/mood inference, crate building, set planning
- **Rekordbox XML:** Custom export/import via xml.etree.ElementTree
- **Packaging:** PyInstaller (`--onedir`) for Python backend + Tauri bundler for desktop app
- **Tag format target:** ID3v2.3 (universal CDJ compatibility)
- **Package management:** uv (fast resolver, lockfile, venv management)
- **Linting/Formatting:** Ruff (Python), ESLint + Prettier (TypeScript/React)
- **Type checking:** mypy (normal mode — avoids friction with framework type stubs)
- **Pre-commit:** pre-commit framework (Ruff, mypy, trailing whitespace, merge conflict markers)
- **Configuration:** pydantic-settings (env vars + .env files with type validation)

## Architecture

Local web app wrapped in a native desktop shell:

- React frontend runs inside a Tauri webview
- FastAPI backend runs as a Tauri sidecar process (PyInstaller binary)
- Frontend ↔ Backend communication via localhost HTTP (port 8420)
- Progress reporting via SSE (Server-Sent Events)
- Tauri IPC used only for desktop integration (file dialogs, path resolution, port handoff)
- ffmpeg bundled as a Tauri resource (not sidecar), called via subprocess from Python

## Repo Structure

```
rekordbot/
├── CLAUDE.md                     ← This file
├── SESSIONS.md                   ← Session log
├── README.md
├── Makefile
├── pyproject.toml                ← Python deps, Ruff config, mypy config, project metadata
├── uv.lock                       ← Lockfile (pins all transitive deps, committed)
├── .pre-commit-config.yaml       ← Pre-commit hooks (Ruff, mypy, whitespace, merge conflicts)
├── .env.example
├── backend/
│   ├── main.py                   ← FastAPI entry point
│   ├── config.py                 ← pydantic-settings configuration
│   ├── exceptions.py             ← Custom exception hierarchy
│   ├── alembic.ini               ← Alembic config (DB URL set in env.py, not here)
│   ├── alembic/
│   │   ├── env.py                ← Migration environment (imports Base, engine, Settings)
│   │   ├── script.py.mako        ← Migration template
│   │   └── versions/
│   │       └── 001_baseline.py   ← Initial migration: full current schema (Phase 6b)
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py           ← Engine, session, Base
│   │   ├── track.py              ← Track model (Rekordbox-compatible + ingestion fields)
│   │   ├── preference_rule.py    ← PreferenceRule model (Phase 2b)
│   │   ├── crate.py              ← Crate and CrateTrack models (Phase 5a)
│   │   └── set_plan.py           ← SetPlan, SetTrack, SetSegment models (Phase 5b)
│   ├── services/
│   │   ├── migration_runner.py   ← Alembic startup migration (fresh/pre-Alembic/migrated detection)
│   │   ├── format_inspector.py   ← ffprobe wrapper, FileInfo dataclass
│   │   ├── conversion.py         ← Conversion decision engine (pure logic)
│   │   ├── naming.py             ← Output path generation with collision handling
│   │   ├── converter.py          ← ffmpeg execution, file hashing, pipeline orchestrator
│   │   ├── queue.py              ← Batch processing with concurrency control and SSE
│   │   ├── key_notation.py       ← Camelot/Open Key/classical key conversion (Phase 2)
│   │   ├── tag_reader.py         ← mutagen-based tag reading (AIFF, MP3, M4A)
│   │   ├── tag_writer.py         ← mutagen-based tag writing (ID3v2.3, MP4 atoms)
│   │   ├── bpm_detector.py       ← librosa BPM detection with auto-correction
│   │   ├── key_detector.py       ← librosa chroma + Krumhansl-Schmuckler key detection
│   │   ├── analysis.py           ← Analysis pipeline orchestrator with batch SSE
│   │   ├── claude_client.py      ← Anthropic SDK wrapper with rate limiting and retry (Phase 3)
│   │   ├── prompt_builder.py     ← Claude prompt/tool schema, batch grouping, result parsing (Phase 3)
│   │   ├── ai_tagger.py          ← AI tagging pipeline orchestrator with SSE (Phase 3)
│   │   ├── template_engine.py    ← Folder template parsing and resolution (Phase 2b)
│   │   ├── confidence_scorer.py  ← Organisation confidence scoring (Phase 2b)
│   │   ├── preference_store.py   ← Preference rule CRUD and application (Phase 2b)
│   │   ├── claude_reasoner.py    ← Claude placement suggestions for ambiguous tracks (Phase 2b)
│   │   ├── file_mover.py         ← File move operations with collision handling (Phase 2b)
│   │   ├── organiser.py          ← Organisation pipeline orchestrator (Phase 2b)
│   │   ├── key_compatibility.py  ← Camelot wheel harmonic mixing logic (Phase 5a)
│   │   ├── crate_prompt_builder.py ← Crate description parsing and assignment prompts (Phase 5a)
│   │   ├── crate_assigner.py     ← Batched Claude assignment pipeline with SSE (Phase 5a)
│   │   ├── crate_manager.py      ← Crate CRUD, refresh, and auto-refresh orchestration (Phase 5a)
│   │   ├── bpm_transition.py    ← BPM transition scoring and quality labels (Phase 5b)
│   │   ├── set_prompt_builder.py ← Set planning prompt/tool schemas and result parsers (Phase 5b)
│   │   ├── set_planner.py       ← Set planner service: CRUD, lock/shuffle, Claude planning (Phase 5b)
│   │   ├── location_encoder.py   ← Rekordbox Location URI encoding (Phase 4)
│   │   ├── xml_schema_mapper.py  ← Track model → XML attribute mapping (Phase 4)
│   │   ├── xml_builder.py        ← Rekordbox XML document construction (Phase 4)
│   │   ├── xml_exporter.py       ← Export pipeline orchestrator (Phase 4)
│   │   ├── xml_parser.py         ← Rekordbox XML parsing with location decoding (Phase 4b)
│   │   ├── track_matcher.py      ← Track matching (path/hash) and conflict detection (Phase 4b)
│   │   ├── conflict_resolver.py  ← Import conflict resolution (per-track and bulk) (Phase 4b)
│   │   ├── xml_importer.py       ← XML import pipeline orchestrator with SSE progress (Phase 4b)
│   │   ├── config_manager.py    ← JSON config persistence and env var integration (Phase 6a)
│   │   └── watchdog.py          ← Self-termination watchdog for sidecar lifecycle (Phase 6a)
│   ├── routes/
│   │   ├── ingest.py             ← POST /api/ingest, SSE progress
│   │   ├── tagging.py            ← Analysis, tag editing, revert, write-tags, enhanced /tracks
│   │   ├── ai_tagging.py         ← AI tagging endpoints: tag, progress, cancel, status, validate (Phase 3)
│   │   ├── organise.py           ← Organisation endpoints: propose, approve, resolve, preferences (Phase 2b)
│   │   ├── export.py             ← Rekordbox XML export endpoints (Phase 4)
│   │   ├── crates.py             ← Crate CRUD, assignment, progress SSE endpoints (Phase 5a)
│   │   ├── sets.py               ← Set planner CRUD, shuffle, export, progress SSE (Phase 5b)
│   │   ├── settings.py          ← Settings CRUD, validation, first-run status (Phase 6a)
│   │   └── import_xml.py        ← Rekordbox XML import, conflicts, SSE progress (Phase 4b)
│   └── tests/
│       ├── conftest.py           ← Shared fixtures (test DB, API client)
│       └── fixtures/audio/       ← Test audio files (WAV, FLAC, AIFF, MP3, M4A)
├── frontend/
│   ├── src/
│   │   ├── App.tsx               ← Main layout with drop zone, queue, track table
│   │   ├── DropZone.tsx          ← Drag-and-drop + Tauri folder dialog
│   │   ├── ProcessingQueue.tsx   ← SSE consumer, live file status
│   │   ├── TrackTable.tsx        ← Rekordbox-style sortable table with inline editing
│   │   ├── AnalysisControls.tsx  ← Analysis toolbar with progress bar and filters
│   │   ├── ColumnMenu.tsx        ← Right-click column visibility toggle
│   │   ├── TrackDetailPanel.tsx  ← Side panel with full track editing
│   │   ├── OrganiseControls.tsx  ← Organisation toolbar with propose/approve (Phase 2b)
│   │   ├── ExportControls.tsx    ← Rekordbox XML export toolbar (Phase 4)
│   │   ├── CrateSidebar.tsx      ← Crate playlist tree with counts and context menu (Phase 5a)
│   │   ├── CrateCreateDialog.tsx ← Crate creation modal with progress (Phase 5a)
│   │   ├── SetPlannerView.tsx   ← Set planning interface with track sequence and controls (Phase 5b)
│   │   ├── SetCreateDialog.tsx  ← Set creation modal with parameters (Phase 5b)
│   │   ├── SetListPanel.tsx     ← Set list with status and counts (Phase 5b)
│   │   ├── SettingsPanel.tsx    ← Settings panel with main and advanced sections (Phase 6a)
│   │   ├── ImportControls.tsx    ← Rekordbox XML import toolbar with progress (Phase 4b)
│   │   ├── ConflictReviewPanel.tsx ← Import conflict review and resolution UI (Phase 4b)
│   │   ├── SetupWizard.tsx      ← First-run setup wizard (Phase 6a)
│   │   ├── ToastProvider.tsx    ← Toast notification context and hook (Phase 6a)
│   │   ├── ReviewQueue.tsx       ← Review queue for ambiguous tracks (Phase 2b)
│   │   ├── PreferenceRulesPanel.tsx ← Preference rule management UI (Phase 2b)
│   │   └── api/
│   │       └── client.ts         ← Typed API client (health, ingest, analysis, tracks, SSE)
│   ├── package.json
│   ├── vite.config.ts
│   ├── .eslintrc.cjs
│   ├── .prettierrc
│   └── src-tauri/
│       ├── src/
│       │   └── main.rs           ← Sidecar lifecycle management
│       ├── binaries/             ← PyInstaller output (gitignored)
│       ├── resources/            ← ffmpeg binary (gitignored)
│       ├── capabilities/
│       │   └── default.json
│       ├── icons/
│       ├── tauri.conf.json
│       └── Cargo.toml
├── scripts/
│   ├── build-backend.sh          ← PyInstaller build (includes Alembic data files)
│   ├── build-dmg.sh              ← Full .dmg pipeline (PyInstaller → Tauri → inject sidecar → hdiutil)
│   └── dev-setup.sh
└── docs/
    ├── features/
    │   ├── phase-0-scaffold.md
    │   ├── phase-1-file-ingestion-conversion.md
    │   ├── phase-2-metadata-tagging.md
    │   ├── phase-2b-file-organisation.md
    │   ├── phase-3-claude-integration.md
    │   ├── phase-4-rekordbox-xml-export.md
    │   ├── phase-5a-crate-builder.md
│   ├── phase-5b-set-planner.md
│   ├── phase-6a-app-shell.md
│   ├── phase-4b-xml-import.md
│   └── phase-6b-dmg-packaging.md
    └── research/
        ├── rekordbox-xml-cdj-compatibility.md
        ├── tauri-python-backend.md
        └── pyinstaller-onedir-tauri-bundling.md
```

## Git Workflow

**Branch structure:**
```
main        ← stable, always works, tagged releases
develop     ← integration branch, all feature branches merge here
feature/*   ← one branch per feature or phase (e.g. feature/phase-0-scaffold)
```

**Rules:**
- All work happens on feature branches, never directly on `main` or `develop`
- Feature branches are created from `develop` and merge back into `develop`
- `develop` merges to `main` only when a phase is complete and all acceptance criteria pass
- Every commit should leave the codebase in a working state (tests pass)
- Commit messages: imperative mood, concise but descriptive (e.g. "Add Track model with full Rekordbox-compatible schema", not "updated models")

## Coding Conventions

### Python

- **Style:** PEP 8, enforced by Ruff
- **Type hints:** Required on all function signatures (parameters and return types)
- **Docstrings:** Required on all public methods and classes. Use Google-style docstrings.
- **Async:** Use `async`/`await` for FastAPI route handlers. Blocking I/O (ffmpeg subprocess calls, heavy file operations) should run via `asyncio.to_thread()`. **SQLAlchemy uses sync mode** — async SQLAlchemy adds significant complexity (AsyncSession, relationship loading restrictions) for no practical benefit on a single-user desktop app with local SQLite. Database calls are fast enough on local disk that wrapping them in `to_thread()` is not needed unless profiling shows otherwise.
- **Imports:** Standard library → third-party → local, separated by blank lines. Enforced by Ruff's isort rules.
- **Naming:** `snake_case` for functions, variables, and modules. `PascalCase` for classes. `UPPER_SNAKE_CASE` for constants.
- **SQL:** SQLAlchemy ORM exclusively — no raw SQL strings.
- **Tests:** pytest. Coverage on all service-layer logic. Tests are part of the definition of done — a module is not complete without them.

### TypeScript / React

- **Style:** Enforced by ESLint + Prettier
- **Naming:** `camelCase` for variables and functions. `PascalCase` for components and types.
- **Components:** Functional components with hooks. No class components.
- **State management:** React state (useState, useReducer) for local state. Defer global state library decision until Phase 1 when we know the actual complexity.
- **File structure:** One component per file. Component files named in PascalCase (e.g. `HealthStatus.tsx`). Utility/hook files in camelCase (e.g. `useBackendStatus.ts`).
- **API calls:** All backend communication goes through the typed API client (`src/api/client.ts`), never raw `fetch` calls scattered through components.

### Commits

- Frequent, with clear descriptive messages in imperative mood
- One logical unit of work per commit
- Before every Claude Code session: ensure a clean commit is in place (makes `git diff` a reliable audit and `git checkout .` a safe undo)

## Linting & Formatting

### Python — Ruff

Configured in `pyproject.toml` under `[tool.ruff]`. Line length 99, Python 3.12 target. Rules: E, W, F, I, N, UP, B, SIM, TCH. Run with `ruff check .` and `ruff format .`.

### TypeScript — ESLint + Prettier

Standard Vite + React ESLint config. Prettier for formatting. Configured via `.eslintrc.cjs` and `.prettierrc` in the `frontend/` directory.

## Type Checking

### Python — mypy

Configured in `pyproject.toml` under `[tool.mypy]`. **Normal mode** (not strict) to avoid friction with SQLAlchemy/pydantic/FastAPI type stubs. Catches wrong return types, missing None handling, and incompatible arguments. Run with `mypy backend/`.

## Pre-commit Hooks

Configured in `.pre-commit-config.yaml`. Hooks: trailing-whitespace, end-of-file-fixer, check-merge-conflict, check-yaml, check-toml, ruff (with --fix), ruff-format, mypy. Setup: `pre-commit install`.

**Rules:**
- Pre-commit hooks are mandatory — never bypass with `--no-verify`
- If a hook fails, fix the issue before committing — don't disable the hook
- Hook versions are pinned and updated deliberately

## Test Infrastructure

- **pytest** + **pytest-asyncio** + **httpx** (ASGITransport) — dev dependencies
- Tests must never touch the dev database — all tests use in-memory SQLite (`sqlite://`)
- Fixtures in `backend/tests/conftest.py`: `engine` (session-scoped), `db_session` (per-test with rollback), `client` (async httpx client)
- `asyncio_mode = "auto"` in pyproject.toml — async tests don't need `@pytest.mark.asyncio`

### Rules

- Every test file goes in `backend/tests/` and is named `test_*.py`
- Use fixtures from `conftest.py` — never create DB sessions or API clients inline
- Tests must be independent — no test should depend on another test's side effects
- Use `db_session` for DB tests, `client` for API endpoint tests

### When To Write Tests First (TDD)

**Write tests before implementation** for pure logic functions with clearly defined inputs, outputs, and branching (conversion decisions, key notation, rating scale, URI encoding, conflict detection, any validation/transformation).

**Write tests after implementation** for framework integration, route handlers, model definitions, configuration, and UI code.

## Dependency Management

Dependencies are managed with **uv**, which handles virtual environments, package installation, and lockfile generation.

**`pyproject.toml`** declares direct dependencies with version constraints (e.g. `fastapi>=0.115.0`). Exact pins are not needed here because uv's lockfile handles reproducibility.

**`uv.lock`** is the lockfile — it pins every direct and transitive dependency to an exact version. This file is committed to the repo and ensures reproducible builds across machines and CI.

**Workflow for adding a dependency:**
1. `uv add <package>` — adds to `pyproject.toml` and updates `uv.lock`
2. Commit both `pyproject.toml` and `uv.lock`

**Workflow for setting up the dev environment:**
1. `uv venv` — creates `.venv/`
2. `uv sync` — installs all dependencies from the lockfile

**Rules:**
- Never use `pip install` directly — always go through uv
- Always commit `uv.lock` alongside `pyproject.toml` changes
- Run `uv sync` after pulling to ensure your environment matches the lockfile

## Configuration Management

Application configuration is managed via **pydantic-settings** in `backend/config.py`. All env vars prefixed with `REKORDBOT_` (e.g. `REKORDBOT_PORT=8420`). In production, a JSON config file at `~/Library/Application Support/rekordbot/config.json` is loaded into env vars before Settings instantiation (env vars take precedence over config file). See `backend/services/config_manager.py` for the config file → env var bridge.

**`.env.example`** documents all available config values. The actual `.env` file is gitignored.

## Logging

Use Python's built-in `logging` module. No third-party logging library needed.

### Setup

- Configured once at application startup in `main.py`
- Log format: human-readable for dev, structured (JSON) for production — controlled via config
- Default log level: `INFO` (overridable via `REKORDBOT_LOG_LEVEL` env var)
- `DEBUG` level available for development — logs detailed info like ffprobe output, conversion parameters, SQL queries

### Pattern

```python
import logging

logger = logging.getLogger(__name__)

# In service functions:
logger.info("Converting %s from %s to AIFF", filename, source_format)
logger.debug("ffprobe output: %s", probe_result)
logger.warning("Low bitrate detected: %d kbps for %s", bitrate, filename)
logger.error("Conversion failed for %s: %s", filename, str(error))
```

### Rules

- Every service module gets its own logger via `logging.getLogger(__name__)`
- Use `%s` string formatting (not f-strings) in log calls — allows lazy evaluation
- Log at `INFO` for operations the user would care about (file converted, tag written, track added)
- Log at `DEBUG` for internal detail (ffprobe output, raw tag data, SQL queries)
- Log at `WARNING` for non-fatal issues (low bitrate, missing tag, ambiguous metadata)
- Log at `ERROR` for failures that need attention (conversion failed, file not found, API error)
- Never log sensitive data (API keys, full file paths with user home directory in production)

### Output

- During development (uvicorn): logs to stdout, human-readable format
- In production (sidecar): logs to stdout AND to a rotating file at `~/Library/Application Support/rekordbot/rekordbot.log` (5MB max, 3 backups). File handler added automatically when `--parent-pid` is present.

## Error Handling

All non-2xx responses use: `{"error": "short_error_code", "detail": "Human-readable message"}`. See `backend/exceptions.py` for the hierarchy (`RekordBotError` base with domain subclasses) and `backend/main.py` for the global handler + `UnhandledExceptionMiddleware`.

**Pattern:** Service layer raises `RekordBotError` subclasses → global handler returns standard JSON. Unexpected exceptions → `UnhandledExceptionMiddleware` → generic 500. Never silently swallow exceptions.

## Key Design Decisions

### Conversion Logic (Phase 1)
- Lossless (WAV, FLAC, ALAC) → AIFF (lossless-to-lossless, safe)
- MP3 → leave as-is (already CDJ-compatible)
- M4A → inspect with ffprobe first: ALAC inside → convert to AIFF; AAC inside → optional convert to MP3 (user preference)
- Never transcode lossy-to-lossy without explicit user opt-in
- Bitrate warning for lossy files below 192kbps

### Tag Strategy
- Write ID3v2.3 tags (maximum CDJ compatibility across all USB-capable models from 2009+)
- Do NOT write ID3v1 tags (causes Rekordbox comment field issues)
- AIFF: ID3v2 embedded in AIFF container via mutagen
- MP3: standard ID3v2 tags via mutagen
- Key stored internally as integer 1–24 (Camelot wheel mapping), converted to user-preferred notation on display/export

### Rekordbox XML
- Export (Phase 4) and import (Phase 4b) via xml.etree.ElementTree
- Track paths as `file://localhost/` URIs with percent-encoded path components
- Rating uses non-linear scale: 0/51/102/153/204/255 for 0–5 stars
- BPM as two-decimal float (e.g. "128.00")
- Playlists reference tracks by TrackID (KeyType="0")
- No TEMPO or POSITION_MARK export/import (metadata only)
- Import matching: path match (primary) → SHA-256 hash match (secondary) → new track
- Import conflicts stored as JSON in Track.import_conflicts (cleared on resolution)
- Imported playlists become Crates with folder paths flattened to name prefixes

### Tauri/Backend Integration
- Python backend runs as Tauri sidecar (PyInstaller `--onedir`)
- Hardcoded port 8420 with conflict detection
- Rust spawns sidecar on Ready, kills on ExitRequested
- Health check polling before marking backend as ready
- HTTP shutdown endpoint as graceful shutdown mechanism
- Self-termination watchdog: daemon thread polling parent PID every 5s with 10s grace period, started via `--parent-pid` CLI arg
- Production sidecar lives in `Contents/MacOS/sidecar/` subdirectory (prevents PyInstaller `.app` mode detection)
- Rust code detects production vs dev mode: `std::process::Command` from sidecar/ subdir vs Tauri sidecar API
- Frontend polls backend health on mount with retries (20 attempts × 500ms) for sidecar startup delay
- CORS allows all origins (`allow_origins=["*"]`) — safe since backend only binds to 127.0.0.1
- Bundled ffmpeg resolved at startup: sidecar detects `Contents/Resources/ffmpeg` relative to its own executable and sets `REKORDBOT_FFMPEG_PATH` before Settings instantiation
- `.dmg` built via `make build-dmg`: PyInstaller → Tauri .app → inject sidecar/_internal/ → hdiutil .dmg

### Database Migrations (Phase 6b)
- Alembic manages schema evolution — `init_db()` with `create_all()` is no longer called in production
- Baseline migration (`001_baseline.py`) captures the full current schema as a single snapshot (not per-phase migrations)
- Migration runs automatically on backend startup in the lifespan handler, before FastAPI begins serving
- Three DB states handled: fresh DB → `alembic upgrade head` creates all tables; pre-Alembic DB (exists but no `alembic_version` table) → `alembic stamp head` marks as current without modifying tables; already-migrated DB → `upgrade head` is a no-op
- `env.py` imports `Base` from `backend.models.database` — single source of truth for model metadata
- Database URL in Alembic comes from the same Settings/config system as the rest of the app
- Test databases continue using `create_all()` for speed — tests do NOT run Alembic
- Alembic config path must resolve correctly in both dev mode and packaged mode (PyInstaller `sys._MEIPASS`)
- Future schema changes add new migration files to `backend/alembic/versions/`; startup runner applies them automatically

## Current Status

**Phase:** 6c — UI Review & Bug Fixing (in progress)
**Branch:** `feature/phase-6c-dogfooding`
**Tests:** 1163 passing across all phases
**Next step:** Rebuild .dmg and verify fixes with real library

### Phase Summary

| Phase | Tests | Feature Brief |
|-------|-------|---------------|
| 0 — Scaffolding | 8 | `docs/features/phase-0-scaffold.md` |
| 1 — File Ingestion | 114 | `docs/features/phase-1-file-ingestion-conversion.md` |
| 2 — Metadata & Tagging | 390 | `docs/features/phase-2-metadata-tagging.md` |
| 3 — Claude AI Integration | 462 | `docs/features/phase-3-claude-integration.md` |
| 2b — File Organisation | 602 | `docs/features/phase-2b-file-organisation.md` |
| 4 — Rekordbox XML Export | 706 | `docs/features/phase-4-rekordbox-xml-export.md` |
| 5a — Crate Builder | 814 | `docs/features/phase-5a-crate-builder.md` |
| 5b — Set Planner | 930 | `docs/features/phase-5b-set-planner.md` |
| 6a — App Shell & Packaging | 1013 | `docs/features/phase-6a-app-shell.md` |
| 4b — Rekordbox XML Import | 1143 | `docs/features/phase-4b-xml-import.md` |
| 6b — .dmg Packaging & Migration | 1154 | `docs/features/phase-6b-dmg-packaging.md` |
| 6c — UI Review & Bug Fixing | 1163 | (dogfooding — no feature brief) |

Test counts are cumulative. Each phase's feature brief has full deliverables, architecture, and acceptance criteria. Research docs in `docs/research/`.

## Known Issues / Don't Touch

- ffprobe does not report `bits_per_raw_sample` for PCM codecs — format inspector falls back to `bits_per_sample` field. Both fields are checked.
- sse-starlette has no mypy type stubs — `type: ignore[import-not-found]` used in `routes/ingest.py` and `routes/tagging.py`.
- mutagen, librosa, numpy, anthropic, and alembic have no mypy type stubs — `type: ignore[import-not-found]` used throughout Phase 2/3 services and migration runner.
- AIFF files use `IffID3.save()` which does not support the `v1` parameter — tag writer handles this with format-specific save calls.
- librosa emits deprecation warnings for audioread on Python 3.13 — harmless, librosa 1.0 will drop audioread.
- ffmpeg's AIFF muxer defaults to `-write_id3v2 0`, silently dropping all metadata tags. The converter explicitly passes `-write_id3v2 1` to preserve ID3v2 tags in AIFF output.
- PyInstaller `--onedir` sidecar must live in `Contents/MacOS/sidecar/` (not directly in `Contents/MacOS/`) to prevent PyInstaller's bootloader from detecting `.app` bundle mode, which changes library resolution paths and breaks `_internal/` lookup.
- In bundled mode, Python stdout/stderr defaults to ASCII encoding (no terminal attached). `main.py` forces UTF-8 via `reconfigure()` to prevent crashes on unicode characters in logs/metadata.
- ffprobe is NOT bundled as a Tauri resource (only ffmpeg is). In packaged mode, ffprobe falls back to PATH lookup which may fail. Needs to be added to `frontend/src-tauri/resources/` alongside ffmpeg.
- Duplicate detection checks file existence: if a hash-matched track's output file is missing from disk, the orphaned DB record (and related CrateTrack/SetTrack rows) is cleaned up and ingestion continues.

## Phased Build Plan

| Phase | Name | Status | Summary |
|-------|------|--------|---------|
| **0** | Scaffolding | ✅ Done | Repo, tooling, DB schema, Tauri+FastAPI skeleton, sidecar proof |
| **1** | File Ingestion & Conversion | ✅ Done | Drop zone, format detection, ffprobe inspection, ffmpeg pipeline, duplicate detection |
| **2** | Metadata & Tagging | ✅ Done | mutagen tag reading/writing, BPM detection (librosa), key detection (librosa chroma + K-S), tag review UI |
| **3** | Claude Integration | ✅ Done | Anthropic SDK, genre/mood/energy inference, batch processing, AI review UI |
| **2b** | File Organisation | ✅ Done | Template engine, automated org proposals, confidence scoring, review queue, Claude-powered reasoning |
| **4** | Rekordbox XML Export | ✅ Done | Generate XML from DB, track schema mapping, playlist/crate structure, CDJ compatibility |
| **5a** | Crate Builder | ✅ Done | AI-powered smart playlists from free-text descriptions, key compatibility utility, sidebar UI, XML playlist export |
| **5b** | Set Planner | ✅ Done | Energy arc set sequencing, lock-and-shuffle refinement, segmented mood descriptions, key compatibility |
| **6a** | App Shell & Packaging | ✅ Done | Settings persistence, settings UI, first-run wizard, toast errors, watchdog, BitRate fix, .app bundle |
| **4b** | Rekordbox XML Import | ✅ Done | Parse Rekordbox XML, track matching, conflict resolution, playlist-to-crate import |
| **6b** | .dmg Packaging & Migration Setup | ✅ Done | Alembic baseline migration, automatic startup migration, .dmg packaging, post-build sidecar injection |
| **6c** | UI Review & Bug Fixing | ⬅️ Current | Dogfooding phase — import real library, fix bugs and UX friction |
| 6d | Performance Optimisation | Not started | Profile with real library data, targeted optimisation |
| 6e | UI Polish & Design | Not started | Serious design pass, folder template editor, drag-and-drop, custom .dmg background |
| 6f | Signing & Distribution | Not started | Code signing, notarisation, signed .dmg, onboarding docs |
