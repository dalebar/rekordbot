# rekordbot — Claude Context File

## Project Overview

rekordbot is a desktop application for digital DJs who use Rekordbox and CDJs. It handles the full file management workflow: ingest music files from any source/format, convert them with quality-preserving logic (lossless → AIFF, lossy left as-is or converted to MP3), auto-tag with BPM/key/genre/mood using algorithmic analysis and Claude AI, organise into a clean folder structure, build crates, plan sets, and export a Rekordbox-compatible XML library. All file operations use dry-run previews — nothing moves without user approval.

Target user: Dale and his DJ peers, with monetisation potential later.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, uvicorn
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS
- **Desktop shell:** Tauri v2 (Rust)
- **Database:** SQLite via SQLAlchemy + Alembic migrations
- **Audio conversion:** ffmpeg (via subprocess), ffprobe for container inspection
- **Metadata:** mutagen (ID3 tag reading/writing for AIFF and MP3)
- **BPM/Key detection:** aubio (start here; add librosa only if aubio accuracy insufficient)
- **AI layer:** Anthropic Python SDK (Claude) — genre/mood inference, crate building, set planning
- **Rekordbox export:** Custom XML generation via xml.etree.ElementTree
- **Packaging:** PyInstaller (`--onedir`) for Python backend + Tauri bundler for desktop app
- **Tag format target:** ID3v2.3 (universal CDJ compatibility)
- **Linting/Formatting:** Ruff (Python), ESLint + Prettier (TypeScript/React)
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
├── pyproject.toml                ← Python deps, Ruff config, project metadata
├── .env.example
├── backend/
│   ├── main.py                   ← FastAPI entry point
│   ├── config.py                 ← pydantic-settings configuration
│   ├── exceptions.py             ← Custom exception hierarchy
│   ├── alembic/                  ← Database migrations
│   ├── alembic.ini
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py           ← Engine, session, Base
│   │   └── track.py              ← Track model
│   ├── services/                 ← Business logic (converter, tagger, etc.)
│   ├── routes/                   ← FastAPI route handlers
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   └── api/
│   │       └── client.ts         ← Typed API client
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
│   ├── build-backend.sh
│   └── dev-setup.sh
└── docs/
    ├── features/
    │   └── phase-0-scaffold.md
    └── research/
        ├── rekordbox-xml-cdj-compatibility.md
        └── tauri-python-backend.md
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
- **Async:** Use `async`/`await` throughout FastAPI routes and services. Blocking I/O (ffmpeg subprocess calls, file operations) must run in thread pool executors via `asyncio.to_thread()` or `run_in_executor()`.
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

Configured in `pyproject.toml` under `[tool.ruff]`:

```toml
[tool.ruff]
target-version = "py312"
line-length = 99

[tool.ruff.lint]
select = [
    "E",     # pycodestyle errors
    "W",     # pycodestyle warnings
    "F",     # pyflakes
    "I",     # isort
    "N",     # pep8-naming
    "UP",    # pyupgrade
    "B",     # flake8-bugbear
    "SIM",   # flake8-simplify
    "TCH",   # flake8-type-checking
]

[tool.ruff.lint.isort]
known-first-party = ["backend"]
```

Run with `ruff check .` and `ruff format .`. Add both to the Makefile as a `lint` target.

### TypeScript — ESLint + Prettier

Standard Vite + React ESLint config. Prettier for formatting. Configured via `.eslintrc.cjs` and `.prettierrc` in the `frontend/` directory.

## Dependency Pinning

All Python dependencies in `pyproject.toml` must use **exact version pins** (e.g. `fastapi==0.115.0`, not `fastapi>=0.100`). This ensures reproducible builds, which matters for a desktop app distributed as a compiled binary.

When adding a new dependency:
1. Install it (`pip install <package>`)
2. Check the installed version (`pip show <package>`)
3. Pin that exact version in `pyproject.toml`
4. Note: transitive dependencies are not pinned (that would require a lockfile, which we can add later if needed)

## Configuration Management

Application configuration is managed via **pydantic-settings**. This gives us typed, validated configuration with support for environment variables and `.env` files.

Configuration lives in `backend/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="REKORDBOT_")

    port: int = 8420
    db_url: str = "sqlite:///rekordbot_dev.db"
    log_level: str = "INFO"
    ffmpeg_path: str = "ffmpeg"
    anthropic_api_key: str = ""
```

**Environment variable naming:** All env vars are prefixed with `REKORDBOT_` (e.g. `REKORDBOT_PORT=8420`, `REKORDBOT_LOG_LEVEL=DEBUG`).

**`.env.example`** documents all available config values with sensible defaults. The actual `.env` file is gitignored.

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
- In production (sidecar): logs to stdout, captured by Tauri's sidecar event stream, forwarded to the app's log file via Tauri's log system

## Error Handling

### API Error Response Schema

All non-2xx responses from the FastAPI backend use a consistent JSON structure:

```json
{
    "error": "short_error_code",
    "detail": "Human-readable explanation of what went wrong."
}
```

`error` is a machine-readable string code (e.g. `"file_not_found"`, `"conversion_failed"`, `"duplicate_detected"`, `"validation_error"`). The frontend matches on this field for programmatic handling.

`detail` is a human-readable message suitable for displaying to the user.

### Exception Hierarchy

Define custom exceptions in `backend/exceptions.py`:

```python
class RekordBotError(Exception):
    """Base exception for all rekordbot errors."""
    def __init__(self, error: str, detail: str, status_code: int = 500):
        self.error = error
        self.detail = detail
        self.status_code = status_code

class FileNotFoundError(RekordBotError): ...
class ConversionError(RekordBotError): ...
class DuplicateTrackError(RekordBotError): ...
class TagReadError(RekordBotError): ...
class TagWriteError(RekordBotError): ...
```

### Pattern

- **Service layer** raises `RekordBotError` subclasses when something goes wrong
- **Route handlers** don't catch these — they propagate to a global exception handler
- **Global exception handler** (registered in `main.py`) catches `RekordBotError` and returns the standard JSON error response
- **Unexpected exceptions** (not `RekordBotError`) are caught by a fallback handler that logs the full traceback and returns a generic 500 response — never expose internal details to the frontend
- **Never silently swallow exceptions.** If an exception is caught and handled, log it. If it's not expected, let it propagate.

### FastAPI Exception Handler

```python
@app.exception_handler(RekordBotError)
async def rekordbot_error_handler(request: Request, exc: RekordBotError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "detail": exc.detail},
    )
```

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
- Export-only in Phase 4 (import/merge deferred to Phase 4b or later)
- Track paths as `file://localhost/` URIs with percent-encoded path components
- Rating uses non-linear scale: 0/51/102/153/204/255 for 0–5 stars
- BPM as two-decimal float (e.g. "128.00")
- Playlists reference tracks by TrackID (KeyType="0")
- No TEMPO or POSITION_MARK export initially (metadata only)

### Tauri/Backend Integration
- Python backend runs as Tauri sidecar (PyInstaller `--onedir`)
- Hardcoded port 8420 with conflict detection
- Rust spawns sidecar on Ready, kills on ExitRequested
- Health check polling before marking backend as ready
- HTTP shutdown endpoint as graceful shutdown mechanism
- Self-termination watchdog deferred to Phase 6

## Current Status

**Phase:** 0 — Project Scaffolding
**State:** Feature brief written. No code yet.

Research completed:
- Rekordbox XML format and CDJ tag compatibility (see `docs/research/`)
- Tauri + Python sidecar architecture (see `docs/research/`)

All foundational design decisions are made. Ready to begin implementation.

## Known Issues / Don't Touch

Nothing yet — greenfield project.

## Phased Build Plan

| Phase | Name | Summary |
|-------|------|---------|
| **0** | Scaffolding | Repo, tooling, DB schema, Tauri+FastAPI skeleton, sidecar proof ← **CURRENT** |
| 1 | File Ingestion & Conversion | Drop zone, format detection, ffprobe inspection, ffmpeg pipeline, duplicate detection |
| 2 | Metadata & Tagging | mutagen tag reading/writing, BPM detection (aubio), key detection, tag review UI |
| 2b | File Organisation | Template engine, automated org proposals, confidence scoring, review queue, user preference store |
| 3 | Claude Integration | Anthropic SDK, genre/mood/energy inference, batch processing, AI review UI |
| 4 | Rekordbox XML Export | Generate XML from DB, track schema mapping, playlist/crate structure, CDJ compatibility |
| 4b | Rekordbox XML Import | Parse existing XML, merge with internal DB, conflict resolution (deferred) |
| 5 | Crate Builder & Set Planner | AI crate assignment, energy arc definition, track sequencing, key compatibility |
| 6 | Polish & Packaging | UI polish, error handling, settings panel, macOS packaging, code signing, auto-update |
