# Feature: .dmg Packaging & Migration Setup
**Branch:** `feature/phase-6b-dmg-packaging`
**Status:** Complete ✅
**Phase:** 6b
**Depends on:** Phase 4b (complete)

---

## Goal

Get rekordbot into a state where Dale can double-click a `.dmg`, drag to Applications, and start using the app with real data — with the confidence that future updates won't destroy the database.

This phase has two components:

1. **Alembic migration setup** — so the database schema can evolve without data loss. This must be in place before dogfooding begins, because once real data exists, `drop_all()` is no longer acceptable.
2. **`.dmg` packaging** — so the app is distributable as a single file that installs like any Mac app (drag to Applications).

This is deliberately minimal. No code signing, no UI polish, no performance work. Just: installable app + safe schema evolution.

---

## Inputs

- Working `.app` bundle from Phase 6a (Tauri build)
- Existing SQLAlchemy models across all phases (Track, Crate, CrateTrack, SetPlan, SetTrack, SetSegment, PreferenceRule)
- Existing `init_db()` in `backend/models/database.py`
- Tauri v2's built-in macOS `.dmg` bundler

## Outputs

- Alembic configured and integrated into the backend
- Baseline migration capturing the full current schema
- Automatic migration on backend startup (no manual `alembic upgrade` needed)
- `.dmg` installer that works on macOS (Apple Silicon)
- Verified end-to-end: install from `.dmg` → first-run wizard → full pipeline

---

## Decisions

| # | Question | Decision |
|---|---|---|
| 1 | When do migrations run? | On backend startup, before the FastAPI app begins serving requests. The app calls `alembic.command.upgrade("head")` programmatically during the lifespan handler. |
| 2 | What about existing databases? | If a database exists but has no Alembic version table (`alembic_version`), the app stamps it as current (`alembic.command.stamp("head")`) rather than trying to replay migrations. This handles the dev → production transition. |
| 3 | What about fresh installs? | `alembic upgrade head` on an empty database creates all tables from the migration chain. `init_db()` is no longer called in production — Alembic owns table creation. |
| 4 | Does `init_db()` change? | In production (packaged mode), Alembic creates tables. In tests, `init_db()` continues to use `Base.metadata.create_all()` for speed — test databases don't need migration history. |
| 5 | Where does Alembic config live? | `backend/alembic.ini` and `backend/alembic/` directory. The `env.py` imports our existing `Base` and `engine` from `database.py`. |
| 6 | How is the `.dmg` built? | Tauri v2's built-in macOS bundler produces a `.dmg` as part of `npm run tauri build`. No additional tooling needed. |
| 7 | `.dmg` appearance? | Default Tauri `.dmg` layout (app icon + Applications shortcut). Custom background image deferred to Phase 6e (polish). |
| 8 | Does the `.dmg` include the sidecar and ffmpeg? | Yes — same as the existing `.app` bundle. The `.dmg` wraps the `.app` which already contains the PyInstaller sidecar and ffmpeg resource. |

---

## Architecture & Key Components

### 1. Alembic Setup

**Directory structure:**
```
backend/
├── alembic.ini                    ← Alembic config (DB URL, migration directory)
├── alembic/
│   ├── env.py                     ← Migration environment (imports Base, engine)
│   ├── script.py.mako             ← Migration template
│   └── versions/
│       └── 001_baseline.py        ← Initial migration: full current schema
```

**`alembic.ini`** — Points to the migration directory. The database URL is set programmatically in `env.py` (not hardcoded in the `.ini`) so it respects the app's config system.

**`env.py`** — Imports `Base` from `backend.models.database` and the configured database URL from Settings. This means Alembic always sees the same models and database as the running app.

**`001_baseline.py`** — Auto-generated from the current model state using `alembic revision --autogenerate`. This captures every table and column across all phases as a single baseline. Future schema changes will be individual migrations on top of this baseline.

### 2. Startup Migration Runner

In `backend/main.py`'s lifespan handler, before the app starts serving:

```python
# Pseudocode — actual implementation will handle paths and config
from alembic import command
from alembic.config import Config

def run_migrations():
    alembic_cfg = Config("backend/alembic.ini")

    if database_exists and not has_alembic_version_table:
        # Existing DB from before Alembic — stamp as current
        command.stamp(alembic_cfg, "head")
    else:
        # Fresh DB or already-migrated DB — upgrade to head
        command.upgrade(alembic_cfg, "head")
```

**Key detail:** The migration runner must resolve the `alembic.ini` path correctly in both dev mode (running from repo root) and packaged mode (running from inside the `.app` bundle). The path resolution should use the same mechanism as the rest of the backend — likely relative to the `backend/` directory or configured via an environment variable.

### 3. `.dmg` Build

Tauri v2's `npm run tauri build` already produces a `.dmg` on macOS if the bundler config is set correctly. The key is verifying that `tauri.conf.json` includes the right bundle targets:

```json
{
  "bundle": {
    "targets": ["dmg", "app"],
    "macOS": {
      "dmg": {
        "appPosition": { "x": 180, "y": 170 },
        "applicationFolderPosition": { "x": 480, "y": 170 },
        "windowSize": { "width": 660, "height": 400 }
      }
    }
  }
}
```

The build pipeline is:
1. PyInstaller builds the sidecar binary
2. `npm run tauri build` builds the frontend, compiles the Rust shell, bundles sidecar + ffmpeg, produces both `.app` and `.dmg`

### 4. Makefile Target

A single command to build the distributable:

```makefile
build-dmg:
	@echo "Building Python sidecar..."
	./scripts/build-backend.sh
	@echo "Building Tauri app + DMG..."
	cd frontend && npm run tauri build
	@echo "DMG ready at frontend/src-tauri/target/release/bundle/dmg/"
```

---

## Acceptance Criteria

### Alembic setup
- [ ] `alembic.ini` and `alembic/` directory exist in `backend/`
- [ ] `env.py` imports Base and engine from existing database module
- [ ] Baseline migration (`001_baseline.py`) captures full current schema
- [ ] `alembic upgrade head` on empty DB creates all tables correctly
- [ ] `alembic upgrade head` on already-migrated DB is a no-op
- [ ] `alembic stamp head` on pre-Alembic DB marks it as current without modifying tables

### Startup integration
- [ ] Migrations run automatically on backend startup (lifespan handler)
- [ ] Fresh install: tables created by Alembic, app starts normally
- [ ] Existing DB without Alembic: stamped as current, app starts normally
- [ ] Already-migrated DB: upgrade is no-op, app starts normally
- [ ] Migration errors are logged and surfaced (app should not silently start with broken schema)
- [ ] Test databases still use `create_all()` (not Alembic) for speed

### `.dmg` packaging
- [ ] `npm run tauri build` produces a `.dmg` file
- [ ] `.dmg` opens in Finder showing app icon + Applications shortcut
- [ ] Drag to Applications installs correctly
- [ ] App launches from Applications (right-click → Open for Gatekeeper bypass)
- [ ] Sidecar spawns, backend starts, frontend connects
- [ ] Config and DB files created in `~/Library/Application Support/rekordbot/`
- [ ] ffmpeg resolves correctly in installed mode

### End-to-end verification (manual)
- [ ] Fresh install from `.dmg` → first-run wizard → configure → main view
- [ ] Import Rekordbox XML → tracks appear in library
- [ ] Drop audio files → ingest → analysis → AI tagging pipeline works
- [ ] Organisation proposal → approve → files moved
- [ ] Create crate → assignment runs
- [ ] Export Rekordbox XML → valid output
- [ ] Quit and relaunch → data persists (Alembic migration already applied, no-op on restart)
- [ ] No zombie processes after quit

### Build infrastructure
- [ ] `make build-dmg` (or equivalent) runs the full build pipeline
- [ ] Build script handles PyInstaller + Tauri in the correct order
- [ ] Build output location is documented

---

## Out of Scope

- **Code signing and notarisation** — Phase 6f. Right-click → Open bypasses Gatekeeper for now.
- **Custom `.dmg` background image** — Phase 6e (polish). Default Tauri layout is fine.
- **Auto-update mechanism** — Not yet scoped. Manual reinstall for updates.
- **Schema changes beyond baseline** — This phase creates the Alembic infrastructure. Actual schema migrations will happen in future phases as needed.
- **UI changes** — No frontend work in this phase. The `.dmg` packages what already exists.
- **Performance optimisation** — Phase 6d.
- **Windows packaging** — Separate project.
- **Rollback migrations** — Alembic supports downgrade, but we don't need to test or guarantee it yet. Forward-only for now.

---

## TDD Candidates

| Function | Location | Why TDD |
|---|---|---|
| `run_migrations()` | `main.py` or new migration helper | Branching logic: fresh DB vs pre-Alembic vs already-migrated |
| `has_alembic_version_table()` | migration helper | DB inspection — pure query, testable with in-memory SQLite |
| `get_alembic_config()` | migration helper | Path resolution for dev vs packaged mode |

---

## Build Order

### Step 1: Add Alembic dependency
- `uv add alembic`
- Commit both `pyproject.toml` and `uv.lock`
- Commit: "Add Alembic dependency"

### Step 2: Alembic initialisation
- Run `alembic init backend/alembic` to scaffold the directory
- Configure `alembic.ini`: set script_location, remove hardcoded sqlalchemy.url
- Configure `env.py`: import Base from backend.models.database, set target_metadata, configure DB URL from Settings
- Generate baseline migration: `alembic revision --autogenerate -m "baseline"`
- Verify: `alembic upgrade head` on empty DB creates all tables, matches `create_all()` output
- Commit: "Initialise Alembic with baseline migration for current schema"

### Step 3: Startup migration runner
- Create migration helper (could be in `backend/services/migration_runner.py` or inline in `main.py`)
- Implement: detect DB state (fresh / pre-Alembic / migrated), run appropriate command
- Integrate into lifespan handler in `main.py`
- Tests: fresh DB, pre-Alembic DB, already-migrated DB, migration error handling
- Update conftest.py if needed (tests should NOT run migrations)
- Commit: "Add automatic migration on backend startup"

### Step 4: `.dmg` build configuration
- Verify/update `tauri.conf.json` bundle targets to include "dmg"
- Verify/update build scripts (PyInstaller + Tauri sequence)
- Add `make build-dmg` target
- Build the `.dmg` and verify it opens correctly
- Commit: "Configure Tauri .dmg bundling and build pipeline"

### Step 5: End-to-end verification and docs
- Manual test: install from `.dmg`, full pipeline walkthrough
- Document any issues found and fixes applied
- Update CLAUDE.md with Phase 6b status
- Update SESSIONS.md
- Update `rekordbot-project-plan.md` phase listing
- Commit: "Verify end-to-end .dmg install and update project docs for Phase 6b"

---

## Claude Code Prompt

```
You are implementing Phase 6b (.dmg Packaging & Migration Setup) of rekordbot.

Read these files first:
- CLAUDE.md (project conventions, architecture, coding standards)
- docs/features/phase-6b-dmg-packaging.md (the feature brief — this is your specification)
- backend/models/database.py (existing engine, session, Base, init_db)
- backend/models/track.py (Track model — largest table, has all Phase 0–4b columns)
- backend/models/crate.py (Crate and CrateTrack models)
- backend/models/set_plan.py (SetPlan, SetTrack, SetSegment models)
- backend/models/preference_rule.py (PreferenceRule model)
- backend/main.py (FastAPI app — lifespan handler is where migration runs)
- backend/config.py (Settings — database URL configuration)
- backend/tests/conftest.py (test fixtures — must NOT run Alembic migrations)
- frontend/src-tauri/tauri.conf.json (Tauri config — bundle targets)
- scripts/build-backend.sh (PyInstaller build script)
- Makefile (existing build targets)

## What you're building

Two things:

1. **Alembic migration infrastructure** — so the database schema can evolve without data loss. A baseline migration captures the full current schema. On startup, the backend automatically runs migrations (or stamps an existing pre-Alembic database as current).

2. **`.dmg` packaging** — so the app installs like a normal Mac app. Tauri's built-in bundler handles this; we just need to configure it and verify the output.

## Build order (follow this exactly)

### Step 1: Add Alembic dependency
- uv add alembic
- Commit pyproject.toml and uv.lock
- Commit: "Add Alembic dependency"

### Step 2: Alembic initialisation
- Scaffold alembic directory, configure env.py to use existing Base and engine
- Generate baseline migration from current models
- Verify upgrade on empty DB matches create_all() output
- Commit: "Initialise Alembic with baseline migration for current schema"

### Step 3: Startup migration runner
- Detect DB state (fresh / pre-Alembic / migrated)
- Run appropriate Alembic command on startup
- Tests for all three DB states
- conftest.py must NOT run Alembic
- Commit: "Add automatic migration on backend startup"

### Step 4: .dmg build configuration
- Verify tauri.conf.json bundle targets include "dmg"
- Verify build scripts work in sequence
- Add make build-dmg target
- Commit: "Configure Tauri .dmg bundling and build pipeline"

### Step 5: End-to-end verification and docs
- Manual test of full pipeline from .dmg install
- Update CLAUDE.md, SESSIONS.md
- Commit: "Verify end-to-end .dmg install and update project docs for Phase 6b"

## Constraints
- Follow all conventions in CLAUDE.md
- Do NOT modify any existing model definitions (this phase captures them as-is)
- Do NOT modify test infrastructure to use Alembic (tests keep using create_all)
- Do NOT implement code signing or notarisation
- Do NOT make any UI changes
- Do NOT add a custom .dmg background image
- Alembic env.py must import Base from backend.models.database (single source of truth for models)
- Database URL in Alembic must come from the same Settings/config system as the rest of the app
- Migration runner must handle all three DB states: fresh, pre-Alembic, already-migrated
- All new backend modules get their own logger via logging.getLogger(__name__)
- Use %s string formatting in log calls (not f-strings)

## Important
- The baseline migration must capture ALL tables from ALL phases (Track, Crate, CrateTrack, SetPlan, SetTrack, SetSegment, PreferenceRule)
- init_db() with create_all() is still used in tests — do NOT remove it
- In production, Alembic owns table creation — init_db() is NOT called
- Pre-Alembic databases (from dev use) must be stamped, not migrated from scratch
- The .dmg build depends on PyInstaller running first — build order matters
- The Alembic config must resolve paths correctly in BOTH dev mode and packaged mode
```

### Continuation Prompt

```
We are continuing Phase 6b (.dmg Packaging & Migration Setup) of rekordbot.

Read these files for context:
- CLAUDE.md (project conventions and current status)
- SESSIONS.md (latest entry has where we left off and what's next)
- docs/features/phase-6b-dmg-packaging.md (the feature specification)

Pick up from where we left off. Check SESSIONS.md for the last completed step
and what was identified as the next task. Confirm what you think the next step
is before writing any code.
```

---

## Risks

- **Alembic autogenerate may miss things.** Autogenerate compares models to DB state and produces a migration. It doesn't always catch index changes, constraint name changes, or server defaults. The baseline migration must be manually reviewed against `create_all()` output to confirm they produce identical schemas.
- **Path resolution in packaged mode.** Alembic needs to find `alembic.ini` and the `versions/` directory. In dev mode these are at known relative paths. In packaged mode (inside a PyInstaller bundle), the paths are different. The migration runner must handle both. PyInstaller's `sys._MEIPASS` or `__file__` resolution may be needed.
- **Tauri `.dmg` bundler quirks.** Tauri v2's macOS bundler should produce a `.dmg` out of the box, but the exact config keys may have changed between Tauri versions. Verify against current Tauri v2 docs if the build fails.
- **First real data loss risk.** This phase introduces the first mechanism that touches the database schema at runtime. A bug in the migration runner could corrupt an existing database. The stamp-vs-upgrade branching logic must be tested thoroughly.

---

## Notes

- The Alembic baseline migration is a snapshot, not a replay of history. We don't need individual migrations for Phases 0–4b. One migration captures everything.
- Future phases that change the schema (e.g. adding a column) will add a new migration file to `backend/alembic/versions/`. The startup runner's `upgrade("head")` will apply it automatically.
- The `.dmg` is just a container for the `.app`. If the `.app` works (verified in Phase 6a), the `.dmg` should work. The risk is in the install-to-Applications step, not the app itself.
- Alembic adds one new dependency (`alembic`, which depends on `Mako`). Both are lightweight.
