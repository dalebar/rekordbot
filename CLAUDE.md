# rekordbot — Claude Context File

## Project Overview

rekordbot is a desktop application for digital DJs who use Rekordbox and CDJs. It handles the full file management workflow: ingest music files from any source/format, convert them with quality-preserving logic (lossless → AIFF, lossy left as-is or converted to MP3), auto-tag with BPM/key/genre/mood using algorithmic analysis and Claude AI, organise into a clean folder structure, build crates, plan sets, and export a Rekordbox-compatible XML library. All file operations use dry-run previews — nothing moves without user approval.

Target user: Dale and his DJ peers, with monetisation potential later.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, uvicorn
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS v4
- **Desktop shell:** Tauri v2 (Rust)
- **Database:** SQLite via SQLAlchemy (sync mode) — Alembic deferred until real users need schema migrations
- **Audio conversion:** ffmpeg (via subprocess), ffprobe for container inspection
- **Metadata:** mutagen (ID3 tag reading/writing for AIFF and MP3)
- **BPM/Key detection:** librosa (BPM via beat_track, key via chroma + Krumhansl-Schmuckler)
- **AI layer:** Anthropic Python SDK (Claude) — genre/mood inference, crate building, set planning
- **Rekordbox export:** Custom XML generation via xml.etree.ElementTree
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
│   ├── models/
│   │   ├── __init__.py
│   │   ├── database.py           ← Engine, session, Base
│   │   └── track.py              ← Track model (Rekordbox-compatible + ingestion fields)
│   ├── services/
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
│   │   └── analysis.py           ← Analysis pipeline orchestrator with batch SSE
│   ├── routes/
│   │   ├── ingest.py             ← POST /api/ingest, SSE progress
│   │   └── tagging.py            ← Analysis, tag editing, revert, write-tags, enhanced /tracks
│   └── tests/
│       ├── conftest.py           ← Shared fixtures (test DB, API client)
│       └── fixtures/audio/       ← Test audio files (WAV, FLAC, AIFF, MP3, M4A)
├── frontend/
│   ├── src/
│   │   ├── App.tsx               ← Main layout with drop zone, queue, track table
│   │   ├── DropZone.tsx          ← Drag-and-drop + Tauri folder dialog
│   │   ├── ProcessingQueue.tsx   ← SSE consumer, live file status
│   │   ├── TrackList.tsx         ← Basic track list (Phase 1, superseded by TrackTable)
│   │   ├── TrackTable.tsx        ← Rekordbox-style sortable table with inline editing
│   │   ├── AnalysisControls.tsx  ← Analysis toolbar with progress bar and filters
│   │   ├── ColumnMenu.tsx        ← Right-click column visibility toggle
│   │   ├── TrackDetailPanel.tsx  ← Side panel with full track editing
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

## Type Checking

### Python — mypy

mypy verifies type hints at development time, catching real bugs before they reach runtime. Configured in `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false
check_untyped_defs = true
```

We use **normal mode** (not strict) to avoid friction with SQLAlchemy, pydantic, and FastAPI — their type stubs are incomplete and strict mode generates false positives on framework boilerplate. Normal mode still catches wrong return types, missing None handling, and incompatible arguments. We can tighten to strict later once the codebase is larger and the framework layer is stable.

Run with `mypy backend/`. Included in both the `make lint` target and the pre-commit hooks.

## Pre-commit Hooks

The `pre-commit` framework runs checks automatically before every `git commit`. This prevents unlinted, unformatted, or type-unsafe code from entering the repo.

**`.pre-commit-config.yaml`:**

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-merge-conflict
      - id: check-yaml
      - id: check-toml

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0
    hooks:
      - id: mypy
        additional_dependencies: [pydantic, pydantic-settings, fastapi, sqlalchemy]
        args: [--config-file=pyproject.toml]
```

**Setup:** `pre-commit install` (run once after cloning, included in `scripts/dev-setup.sh`).

**Rules:**
- Pre-commit hooks are mandatory — never bypass with `--no-verify` unless there is a specific, temporary reason discussed and agreed
- If a hook fails, fix the issue before committing — don't disable the hook
- The hook versions should be pinned and updated deliberately, not auto-bumped

## Test Infrastructure

### Framework and Dependencies

- **pytest** — test runner
- **pytest-asyncio** — required for testing async service functions directly
- **httpx** — used with `ASGITransport` for testing FastAPI endpoints (modern replacement for Starlette's `TestClient`)

All three are dev dependencies, added via `uv add --dev pytest pytest-asyncio httpx`.

### Test Database

Tests must never touch the dev database. All tests use an **in-memory SQLite instance** (`sqlite://`) that is created and destroyed per test session.

This is configured in `backend/tests/conftest.py`:

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base


@pytest.fixture(scope="session")
def engine():
    """Create an in-memory SQLite engine for the test session."""
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(engine):
    """Create a fresh database session for each test, rolled back after."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
```

The `db_session` fixture provides a clean, isolated session per test. The transaction rollback ensures tests don't pollute each other.

### FastAPI Test Client

Testing API endpoints uses httpx with ASGITransport. Also in `conftest.py`:

```python
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.main import app


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
```

### pytest Configuration

In `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["backend/tests"]
asyncio_mode = "auto"
```

`asyncio_mode = "auto"` means any `async def test_*` function is automatically treated as an async test — no need to decorate every test with `@pytest.mark.asyncio`.

### Rules

- Every test file goes in `backend/tests/` and is named `test_*.py`
- Use fixtures from `conftest.py` for database sessions and API client — never create these inline
- Tests must be independent — no test should depend on another test's side effects
- Use `db_session` fixture for any test that touches the database
- Use `client` fixture for any test that hits an API endpoint

### When To Write Tests First (TDD)

**Write tests before implementation** for any pure logic function with clearly defined inputs, outputs, and branching. These are functions where the test cases essentially form a truth table that drives the design. Examples:

- Conversion decision logic (given format X with codec Y, what action do we take?)
- Format detection and ffprobe result parsing
- Key notation conversion (integer 1–24 ↔ Camelot ↔ classical)
- Rekordbox rating scale mapping (0–5 ↔ 0/51/102/153/204/255)
- URI path encoding for Rekordbox XML Location field
- Bitrate quality warning logic
- Duplicate detection (hash comparison, near-match rules)
- Any validation or data transformation function

**Write tests after implementation** for framework integration, route handlers, model definitions, configuration, and UI code. The shape of this code is driven by framework conventions, not by test cases. Our "tests are part of the definition of done" rule ensures these still get tested — just not test-first.

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
    ffprobe_path: str = "ffprobe"
    output_directory: str = "~/rekordbot/library"
    max_concurrent_conversions: int = 2
    convert_aac_to_mp3: bool = False
    anthropic_api_key: str = ""

    # Phase 2: Analysis settings
    bpm_range_min: int = 70
    bpm_range_max: int = 180
    confidence_threshold: float = 0.6
    max_concurrent_analyses: int = 1
    default_key_notation: str = "camelot"
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
class AnalysisError(RekordBotError): ...
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

**Phase:** 2 — Metadata & Tagging
**State:** Complete. All 11 steps implemented, 390 tests passing.

Phase 2 deliverables:
- Tag reader: mutagen-based tag extraction from AIFF (ID3v2), MP3 (ID3v2), M4A (MP4 atoms)
- BPM detector: librosa onset analysis with configurable half/double-time auto-correction
- Key detector: librosa chroma + Krumhansl-Schmuckler algorithm with HPSS harmonic separation
- Key notation: full Camelot/Open Key/classical mapping with 171 test cases (TDD)
- Tag writer: ID3v2.3 for AIFF/MP3 (no v1), MP4 atoms for M4A, preserves unmanaged tags
- Analysis pipeline: asyncio.Semaphore batch processing, per-track error isolation, SSE progress
- API routes: POST /api/tracks/analyse, SSE progress, cancel, PUT /api/tracks/{id}, revert, bpm-multiply, POST /api/tracks/write-tags
- Enhanced GET /api/tracks with analysis metadata, confidence scores, conflict detection
- Frontend: TrackTable (Rekordbox-style sortable table, column visibility toggle, inline editing, BPM x2/÷2, confidence indicators, filter modes), AnalysisControls toolbar, TrackDetailPanel, ColumnMenu
- Track model extended with source_bpm, source_key, bpm_confidence, key_confidence, analysis_status
- Integration tests: end-to-end ingest→analyse→write flow, tag round-trips, revert/multiply
- Feature brief: `docs/features/phase-2-metadata-tagging.md`

Phase 1 deliverables:
- Format inspector: ffprobe-based inspection for WAV, FLAC, AIFF, MP3, M4A (ALAC/AAC)
- Conversion decision engine: lossless → AIFF (bit depth preserved, capped at 24), lossy copy/optional convert
- Converter service: ffmpeg execution pipeline with SHA-256 duplicate detection
- Processing queue: asyncio.Semaphore concurrency control, SSE progress events, cancellation
- API routes: POST /api/ingest, GET /api/ingest/progress (SSE), POST /api/ingest/cancel, GET /api/tracks
- Frontend: DropZone (drag-and-drop + Tauri dialog), ProcessingQueue (live SSE status), TrackList
- Track model extended with source_path, source_codec, source_bitrate, source_bit_depth, file_hash (unique index), conversion_action, imported_at
- 8 test audio fixtures committed, integration tests covering all format paths
- Feature brief: `docs/features/phase-1-file-ingestion-conversion.md`

Phase 0 deliverables (prior):
- Repo tooling: pyproject.toml, uv.lock, Makefile, pre-commit hooks, scripts
- Python backend: FastAPI app, config, exceptions, Track model
- React frontend: Vite + React 19 + TypeScript + Tailwind v4, API client
- Tauri v2 shell: sidecar lifecycle management, health polling, clean shutdown
- Integration proof: PyInstaller binary builds, Tauri launches sidecar, health check passes

Research completed:
- Rekordbox XML format and CDJ tag compatibility (see `docs/research/`)
- Tauri + Python sidecar architecture (see `docs/research/`)

## Known Issues / Don't Touch

- ffprobe does not report `bits_per_raw_sample` for PCM codecs — format inspector falls back to `bits_per_sample` field. Both fields are checked.
- sse-starlette has no mypy type stubs — `type: ignore[import-not-found]` used in `routes/ingest.py` and `routes/tagging.py`.
- mutagen, librosa, and numpy have no mypy type stubs — `type: ignore[import-not-found]` used throughout Phase 2 services.
- AIFF files use `IffID3.save()` which does not support the `v1` parameter — tag writer handles this with format-specific save calls.
- librosa emits deprecation warnings for audioread on Python 3.13 — harmless, librosa 1.0 will drop audioread.

## Phased Build Plan

| Phase | Name | Summary |
|-------|------|---------|
| **0** | Scaffolding | Repo, tooling, DB schema, Tauri+FastAPI skeleton, sidecar proof |
| **1** | File Ingestion & Conversion | Drop zone, format detection, ffprobe inspection, ffmpeg pipeline, duplicate detection |
| **2** | Metadata & Tagging | mutagen tag reading/writing, BPM detection (librosa), key detection (librosa chroma + K-S), tag review UI |
| 3 | Claude Integration | Anthropic SDK, genre/mood/energy inference, batch processing, AI review UI |
| 2b | File Organisation | Template engine, automated org proposals, confidence scoring, review queue, Claude-powered reasoning |
| 4 | Rekordbox XML Export | Generate XML from DB, track schema mapping, playlist/crate structure, CDJ compatibility |
| 4b | Rekordbox XML Import | Parse existing XML, merge with internal DB, conflict resolution (deferred) |
| 5 | Crate Builder & Set Planner | AI crate assignment, energy arc definition, track sequencing, key compatibility |
| 6 | Polish & Packaging | UI polish, error handling, settings panel, macOS packaging, code signing, auto-update |
