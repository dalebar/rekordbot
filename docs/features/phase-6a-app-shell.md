# Feature: App Shell & Packaging
**Branch:** `feature/phase-6a-app-shell`
**Status:** Complete ✅
**Phase:** 6a
**Depends on:** Phase 5b (complete)

---

## Goal

Transform rekordbot from a dev-mode-only project into a working desktop application that can be launched from Finder. This means: a settings UI so the user can configure the app without editing `.env` files, a first-run wizard that gets essential config in place on first launch, user-facing error messages instead of console stack traces, a self-termination watchdog so the Python backend doesn't outlive the Tauri shell, a bitrate fix for the XML export, and a Tauri `.app` bundle that packages everything together.

This is not a polish phase — it's a "make it actually work as a standalone app" phase. UI polish, code signing, `.dmg` packaging, and distribution are deferred to Phase 6b.

---

## Inputs

- All existing backend services and frontend components from Phases 0–5b
- Existing `.env`-based pydantic-settings configuration
- Existing PyInstaller `--onedir` build scripts
- Existing Tauri v2 shell with sidecar lifecycle management
- Bundled ffmpeg in Tauri resources

## Outputs

- JSON-based settings persistence in platform app data directory
- Settings panel UI with main and advanced sections
- First-run wizard for essential configuration
- Toast notification system for user-facing error messages
- Self-termination watchdog in the Python backend
- BitRate correctly populated in Rekordbox XML export
- Working `.app` bundle launchable from Finder

---

## Decisions (Finalised)

| # | Question | Decision |
|---|---|---|
| 1 | How are settings persisted? | JSON config file at `~/Library/Application Support/rekordbot/config.json`. Env vars override for dev. |
| 2 | Which settings are user-facing? | Main: API key, output directory, key notation, folder template, convert AAC to MP3. Advanced: BPM range min/max, confidence threshold, track duration per set, max tracks per set. |
| 3 | What does the first-run wizard look like? | Three steps: Welcome → Essential config (output directory + API key) → Done. Writes config file on completion. |
| 4 | What triggers the wizard? | Config file doesn't exist yet. Once written, wizard never shows again. |
| 5 | How does the watchdog work? | Parent PID polling. Tauri passes its PID to the sidecar on spawn. Backend background thread checks `os.kill(parent_pid, 0)` every 5 seconds. 10-second grace period before shutdown. |
| 6 | What's the packaging target? | Working `.app` bundle. No code signing, no notarisation, no `.dmg`. Right-click → Open to bypass Gatekeeper. |
| 7 | How are errors surfaced? | Toast/notification system in the frontend. Backend returns standard `{"error": str, "detail": str}` on all error paths. |

---

## Architecture & Key Components

### 1. Config Manager (`backend/services/config_manager.py`)

Manages reading and writing the JSON config file. This sits alongside pydantic-settings — it doesn't replace it.

**Config file location:** `~/Library/Application Support/rekordbot/config.json`

**How it integrates with the existing Settings class:**
1. On backend startup, `config_manager.load_config()` reads the JSON file (if it exists)
2. Values from the JSON file are set as environment variables (with `REKORDBOT_` prefix)
3. pydantic-settings picks them up as normal — env vars take precedence, so dev `.env` files still override
4. When the user saves settings via the API, `config_manager.save_config()` writes the JSON file and updates the in-memory `Settings` singleton

**Config file schema:**
```json
{
  "anthropic_api_key": "sk-ant-...",
  "output_directory": "/Users/daleb/Music/rekordbot",
  "default_key_notation": "camelot",
  "folder_template": "{artist}/{album}/{title}",
  "convert_aac_to_mp3": false,
  "bpm_range_min": 70,
  "bpm_range_max": 180,
  "confidence_threshold": 0.6,
  "set_track_duration_minutes": 7,
  "set_max_tracks": 50
}
```

Only user-configurable fields are stored in the JSON. Internal settings (port, db_url, log_level, batch sizes, etc.) are never written to the config file.

**Functions:**
- `get_config_path() -> Path` — returns platform-appropriate config directory, creates it if needed
- `load_config() -> dict` — reads JSON file, returns empty dict if file doesn't exist
- `save_config(settings: dict) -> None` — writes JSON file, creates directory if needed
- `apply_config_to_env(config: dict) -> None` — sets env vars from config so pydantic-settings picks them up
- `config_exists() -> bool` — whether the config file exists (used by wizard check)
- `validate_api_key(key: str) -> bool` — test Claude API call to verify the key works
- `validate_output_directory(path: str) -> tuple[bool, str]` — check path exists, is writable, has sufficient space

**Startup sequence change in `main.py`:**
```python
# Before Settings() is instantiated:
config = load_config()
apply_config_to_env(config)
# Now Settings() reads from env vars (which include JSON config values)
```

### 2. Settings API Routes (`backend/routes/settings.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/settings` | Get current settings (API key masked) |
| PUT | `/api/settings` | Update settings, write to JSON, update in-memory Settings |
| POST | `/api/settings/validate-key` | Test API key validity |
| POST | `/api/settings/validate-directory` | Test output directory validity |
| GET | `/api/settings/status` | First-run check: `{"configured": bool, "has_api_key": bool, "has_output_directory": bool}` |

**GET `/api/settings` response shape:**
```json
{
  "anthropic_api_key": "sk-ant-...XXXX",
  "output_directory": "/Users/daleb/Music/rekordbot",
  "default_key_notation": "camelot",
  "folder_template": "{artist}/{album}/{title}",
  "convert_aac_to_mp3": false,
  "bpm_range_min": 70,
  "bpm_range_max": 180,
  "confidence_threshold": 0.6,
  "set_track_duration_minutes": 7,
  "set_max_tracks": 50
}
```

The API key is masked in GET responses (last 4 characters visible). PUT accepts the full key. If PUT receives a masked key (i.e. the user didn't change it), keep the existing value.

### 3. Self-Termination Watchdog (`backend/services/watchdog.py`)

Background thread that monitors whether the parent Tauri process is still running.

**How it works:**
1. Tauri passes its own PID to the sidecar as a command-line argument: `--parent-pid <PID>`
2. The backend parses this from `sys.argv` on startup
3. A daemon thread runs a loop: every 5 seconds, call `os.kill(parent_pid, 0)` (signal 0 = check existence, don't actually kill)
4. If `ProcessLookupError` is raised (process gone), wait 10 seconds (grace period for restarts), check again, then initiate shutdown
5. Shutdown calls `os._exit(0)` after a brief delay to allow in-flight requests to complete

**If no `--parent-pid` is provided** (i.e. running in dev mode via `make dev-backend`), the watchdog is not started. This is the normal dev workflow.

**Tauri side change in `main.rs`:**
When spawning the sidecar, append `--parent-pid` and the current process ID to the command arguments.

### 4. Error Handling

**Backend — audit and standardise:**
- Every route handler wraps service calls in try/except
- All exceptions map to the standard `{"error": str, "detail": str}` JSON response
- No 500s with stack traces reach the frontend — unhandled exceptions caught by the existing `UnhandledExceptionMiddleware` and returned as `{"error": "internal_error", "detail": "An unexpected error occurred"}`
- Specific error codes for common cases:
  - `api_key_missing` — no Anthropic API key configured
  - `api_key_invalid` — key failed validation
  - `output_directory_missing` — output directory not set or doesn't exist
  - `output_directory_not_writable` — permissions issue
  - `ffmpeg_not_found` — ffmpeg binary not found or not executable
  - `disk_full` — write failed due to insufficient space
  - `claude_rate_limited` — rate limited after retries exhausted
  - `claude_unavailable` — API unreachable
  - `track_not_found` — referenced track doesn't exist
  - `file_not_found` — referenced file doesn't exist on disk

**Frontend — toast notification system:**
- A `ToastProvider` context wrapping the app
- `useToast()` hook that any component can call
- Toast types: `success`, `error`, `warning`, `info`
- Auto-dismiss after 5 seconds for success/info, sticky for errors
- API client wrapper that catches non-2xx responses and shows toasts automatically
- Components no longer need individual error handling — the toast layer catches everything

**Startup health checks:**
On backend startup (in the lifespan handler), run checks and log warnings:
1. ffmpeg binary exists and is executable
2. Output directory exists and is writable (if configured)
3. API key is present (warning only — app works without it, just no AI features)

These aren't blocking — the app starts regardless — but warnings are logged and surfaced via the `/api/settings/status` endpoint so the frontend can show appropriate prompts.

### 5. BitRate Fix (`backend/services/xml_schema_mapper.py`)

Current state: `BitRate="0"` for all tracks.

Fix:
- **Lossy files (MP3, M4A/AAC):** Use `Track.source_bitrate` field (already populated by ffprobe during ingestion). Value is in kbps.
- **Lossless files (AIFF, WAV):** Compute from file metadata: `sample_rate × bit_depth × channels / 1000`. For typical 44.1kHz/16-bit stereo: `44100 × 16 × 2 / 1000 = 1411` kbps. Read from the actual file at export time using ffprobe or mutagen, since values may have changed since ingestion.
- **Fallback:** If bitrate can't be determined, keep `BitRate="0"` (harmless — Rekordbox doesn't rely on this field).

This is a small change to `map_track_to_xml_attrs()` in `xml_schema_mapper.py`, plus 2–3 new tests.

### 6. First-Run Wizard (Frontend)

**`SetupWizard.tsx`** — Full-page component shown when `GET /api/settings/status` returns `configured: false`.

**Step 1 — Welcome:**
- rekordbot logo/name
- One-line description: "Organise your DJ library with AI-powered tagging and crate building"
- "Get Started" button

**Step 2 — Essential Config:**
- **Output directory** — path input with "Browse" button (Tauri folder picker dialog). Validation on blur: calls `POST /api/settings/validate-directory`. Required field.
- **API key** — masked text input with "Test" button. Calls `POST /api/settings/validate-key`. Optional — show a note: "Required for AI tagging, crate building, and set planning. You can add this later in Settings."
- "Continue" button (disabled until output directory is set and validated)

**Step 3 — Done:**
- "You're ready to go. Drop some files in to get started."
- "Open Settings" link (for users who want to configure more)
- "Start" button → navigates to main library view

On completion, the wizard calls `PUT /api/settings` with the configured values. This writes the config file and clears the first-run state.

**App.tsx routing logic:**
```
if settings/status returns configured: false → show SetupWizard
else → show normal app (library view / set planner / etc.)
```

### 7. Settings Panel (Frontend)

**`SettingsPanel.tsx`** — Accessible via a gear icon in the sidebar or header. Could be a slide-out panel or a dedicated view.

**Main section:**
- **API Key** — masked input, "Test Connection" button, green tick / red cross indicator
- **Output Directory** — path display with "Change" button (Tauri folder picker), validation indicator
- **Key Notation** — dropdown: Camelot / Open Key / Classical
- **Folder Template** — text input with live preview showing what an example path would look like (e.g. given artist "Calibre", album "Shelflife 6", title "Falls to You", show the resulting path)
- **Convert AAC to MP3** — toggle with explanation text

**Advanced section** (collapsible, default collapsed):
- **BPM Range** — min/max number inputs
- **Confidence Threshold** — number input (0.0–1.0)
- **Set Track Duration** — number input (minutes)
- **Max Tracks Per Set** — number input

**Save behaviour:**
- "Save" button at the bottom (not auto-save — settings changes should be deliberate)
- On save: `PUT /api/settings` → success toast
- Validation before save: output directory writable, API key valid (if changed), BPM range min < max, confidence threshold in range

### 8. Tauri Packaging

**Goal:** Produce a working `.app` bundle that can be launched from Finder.

**Components that need to be bundled:**
1. **Frontend** — Vite build output (HTML/JS/CSS), loaded by Tauri webview
2. **Python sidecar** — PyInstaller `--onedir` output, registered as an external binary in `tauri.conf.json`
3. **ffmpeg** — Static binary, registered as a Tauri resource

**Build steps:**
1. `pyinstaller --onedir --name rekordbot-server backend/main.py` → produces `dist/rekordbot-server/`
2. Copy/rename sidecar to Tauri's expected path with platform triple suffix
3. `npm run tauri build` → produces `.app` bundle in `frontend/src-tauri/target/release/bundle/macos/`

**Key issues to resolve:**
- Sidecar binary naming: must match `externalBin` entry in `tauri.conf.json` with platform triple (e.g. `rekordbot-server-aarch64-apple-darwin`)
- PyInstaller `_internal` directory must be included alongside the binary in the bundle
- ffmpeg resource path resolution: in dev mode it's system ffmpeg (`/opt/homebrew/bin/ffmpeg`), in production it's `resources/ffmpeg` within the bundle. The backend needs to resolve the correct path based on whether it's running in dev or packaged mode.
- Config file path: `~/Library/Application Support/rekordbot/` should work in both dev and packaged mode (it's outside the bundle)
- Database path: currently `sqlite:///rekordbot_dev.db` (relative to CWD). In packaged mode, needs to be in the app data directory alongside the config file: `~/Library/Application Support/rekordbot/rekordbot.db`

**Tauri changes:**
- `tauri.conf.json`: verify `externalBin` paths, resource paths, app identifier
- `main.rs`: pass `--parent-pid` to sidecar on spawn
- Build script or Makefile target that orchestrates the full build

**What "working" means:**
- Double-click the `.app` in Finder (after right-click → Open to bypass Gatekeeper)
- Tauri window opens
- Sidecar spawns, backend starts
- First-run wizard appears (no config file yet)
- User sets output directory and API key
- Main library view loads
- User can drop files and run the full pipeline

---

## Acceptance Criteria

### Config management
- [ ] Config file created at `~/Library/Application Support/rekordbot/config.json`
- [ ] Config directory created if it doesn't exist
- [ ] Settings loaded from config file on backend startup
- [ ] Env vars override config file values
- [ ] Config file written when user saves settings
- [ ] In-memory Settings updated on save (no restart required)
- [ ] API key masked in GET response (last 4 chars visible)
- [ ] Masked key in PUT request preserves existing value

### Settings API
- [ ] GET `/api/settings` returns current config
- [ ] PUT `/api/settings` validates and saves
- [ ] POST `/api/settings/validate-key` tests API key
- [ ] POST `/api/settings/validate-directory` tests output path
- [ ] GET `/api/settings/status` returns first-run state

### First-run wizard
- [ ] Wizard shown when config file doesn't exist
- [ ] Output directory required, validated before proceeding
- [ ] API key optional, validated if provided
- [ ] Config file written on wizard completion
- [ ] Wizard never shown again after completion
- [ ] "Start" navigates to main library view

### Settings panel
- [ ] All main settings editable: API key, output directory, key notation, folder template, AAC conversion
- [ ] All advanced settings editable: BPM range, confidence threshold, track duration, max tracks
- [ ] Folder template preview updates live
- [ ] API key test button works
- [ ] Output directory browse button opens Tauri folder picker
- [ ] Save validates and persists
- [ ] Success/failure toast on save

### Error handling
- [ ] No 500 stack traces reach the frontend
- [ ] Standard error format on all non-2xx responses
- [ ] Toast notification system shows errors from API calls
- [ ] Toast auto-dismisses for success/info, sticky for errors
- [ ] Startup health checks log warnings for missing ffmpeg, missing output dir, missing API key
- [ ] Health check results available via `/api/settings/status`

### Self-termination watchdog
- [ ] Watchdog starts when `--parent-pid` argument provided
- [ ] Watchdog does not start in dev mode (no `--parent-pid`)
- [ ] Watchdog detects parent process death
- [ ] Backend shuts down cleanly after grace period
- [ ] No zombie processes after closing the Tauri window

### BitRate fix
- [ ] Lossy files: bitrate from `source_bitrate` field in XML export
- [ ] Lossless files: bitrate computed from sample rate, bit depth, channels
- [ ] Fallback to 0 if bitrate can't be determined
- [ ] Rekordbox import shows correct bitrate values

### Tauri packaging
- [ ] PyInstaller builds working sidecar binary
- [ ] `npm run tauri build` produces `.app` bundle
- [ ] `.app` launches from Finder (after Gatekeeper bypass)
- [ ] Sidecar spawns and backend starts
- [ ] Frontend connects to backend
- [ ] Config and DB files created in app data directory
- [ ] ffmpeg resolves correctly in packaged mode
- [ ] Full pipeline works: ingest → analyse → AI tag → organise → export

---

## Out of Scope

- **Code signing and notarisation** — Phase 6b. Users right-click → Open to bypass Gatekeeper.
- **`.dmg` packaging** — Phase 6b. Bare `.app` is sufficient.
- **Windows packaging** — Phase 6b or later.
- **UI polish pass** — Phase 6b. Functional, not pretty.
- **Onboarding tutorial** — Phase 6b. The wizard covers essential setup; a guided tour is extra.
- **Performance profiling** — Phase 6b. Not needed until large libraries are tested.
- **Alembic migrations** — Phase 6b. DB recreation is fine during personal use.
- **Drag-and-drop reordering** — Phase 6b.
- **Bootleg detection refinement** — Phase 6b.
- **Folder template editor UI** — The settings panel has a text input for the template. A visual drag-and-drop editor is Phase 6b.
- **Auto-update mechanism** — Not in scope at all yet.
- **Settings import/export** — Overkill for a single-user app.

---

## Dependencies

- **All previous phases** — this phase touches the frontend shell, backend startup, and packaging, but does not modify any phase's service logic
- **No new Python packages** — config management uses stdlib `json` and `pathlib`
- **No new npm packages** — toast system built with React state/context and Tailwind

---

## TDD Candidates

| Function | Location | Why TDD |
|---|---|---|
| `get_config_path()` | `config_manager.py` | Platform path resolution. Pure logic. |
| `load_config()` | `config_manager.py` | File I/O but deterministic — reads JSON, returns dict. |
| `save_config()` | `config_manager.py` | File I/O — write JSON, verify contents. |
| `apply_config_to_env()` | `config_manager.py` | Dict → env vars mapping. Pure logic. |
| `config_exists()` | `config_manager.py` | Path existence check. |
| `validate_output_directory()` | `config_manager.py` | Path validation. Testable with temp dirs. |
| `compute_bitrate()` | `xml_schema_mapper.py` | Arithmetic from sample rate, bit depth, channels. Pure math. |

**Write tests after implementation:**
- Settings API routes (HTTP integration)
- Watchdog (process lifecycle — harder to unit test, integration/manual)
- Frontend components (wizard, settings panel, toast system)
- Tauri packaging (manual verification)

---

## Commit Breakdown

### Commit 1: Config manager and settings persistence
- Create `backend/services/config_manager.py`
- Implement `get_config_path()`, `load_config()`, `save_config()`, `apply_config_to_env()`, `config_exists()`, `validate_output_directory()`, `validate_api_key()`
- Update `backend/main.py` startup to load config before Settings instantiation
- Update database path resolution for app data directory (packaged mode)
- Tests for config manager
- Commit: "Add config manager with JSON persistence and env var integration"

### Commit 2: Settings API routes
- Create `backend/routes/settings.py`
- Implement GET/PUT `/api/settings`, POST validate-key, POST validate-directory, GET status
- Pydantic request/response models with API key masking
- Register in main.py
- Tests for all endpoints
- Commit: "Add settings API routes with validation and first-run status"

### Commit 3: Self-termination watchdog
- Create `backend/services/watchdog.py`
- Implement parent PID polling with grace period
- Update `backend/main.py` to parse `--parent-pid` and start watchdog thread
- Update `frontend/src-tauri/src/main.rs` to pass PID to sidecar
- Tests for watchdog logic (mocked process checks)
- Commit: "Add self-termination watchdog for sidecar process lifecycle"

### Commit 4: Error handling standardisation
- Audit all route handlers for unhandled exceptions
- Ensure all error paths return standard JSON format
- Add specific error codes for common failures
- Startup health checks in lifespan handler
- Surface health check results in `/api/settings/status`
- Tests for error response format
- Commit: "Standardise error handling and add startup health checks"

### Commit 5: BitRate fix
- Update `map_track_to_xml_attrs()` in `xml_schema_mapper.py`
- Add `compute_bitrate()` helper for lossless files
- Use `source_bitrate` for lossy files
- Tests for bitrate computation and XML attribute mapping
- Commit: "Populate BitRate in Rekordbox XML export"

### Commit 6: Frontend — Toast notification system
- Create `ToastProvider.tsx` and `useToast()` hook
- Toast component with success/error/warning/info types
- Wrap API client to auto-show toasts on errors
- Integrate into App.tsx
- Commit: "Add toast notification system for user-facing error messages"

### Commit 7: Frontend — Settings panel
- Create `SettingsPanel.tsx` with main and advanced sections
- API key input with test button, output directory with browse button
- Folder template input with live preview
- All advanced settings
- Save with validation
- Accessible from sidebar/header
- Commit: "Add settings panel with main and advanced configuration"

### Commit 8: Frontend — First-run wizard
- Create `SetupWizard.tsx` with three-step flow
- App.tsx routing: check `/api/settings/status`, show wizard or main app
- Output directory and API key configuration with validation
- Config saved on completion
- Commit: "Add first-run setup wizard for initial configuration"

### Commit 9: Tauri packaging
- Verify/fix PyInstaller build script for sidecar binary
- Verify/fix sidecar naming convention with platform triple
- Verify/fix ffmpeg resource bundling and path resolution
- Verify/fix `tauri.conf.json` for production build
- Add/update Makefile target for full production build
- Manual test: build → launch from Finder → wizard → full pipeline
- Commit: "Configure Tauri packaging for production .app bundle"

### Commit 10: Integration tests and docs
- End-to-end: first-run → wizard → configure → ingest → full pipeline
- Settings persistence across restart
- Error handling verification
- Watchdog behaviour (manual/integration)
- Update CLAUDE.md with Phase 6a status
- Update SESSIONS.md
- Commit: "Add integration tests and update project docs for Phase 6a"

---

## Claude Code Prompt

```
You are implementing Phase 6a (App Shell & Packaging) of rekordbot.

Read these files first:
- CLAUDE.md (project conventions, architecture, coding standards)
- docs/features/phase-6a-app-shell.md (the feature brief — this is your specification)
- backend/config.py (existing Settings — you'll integrate with config manager)
- backend/main.py (existing FastAPI app — you'll modify startup sequence)
- backend/exceptions.py (existing exception hierarchy)
- backend/routes/ (all existing route files — reference for error handling patterns)
- frontend/src/App.tsx (current layout — you'll add wizard/settings routing)
- frontend/src/CrateSidebar.tsx (sidebar — you'll add settings access)
- frontend/src/api/client.ts (existing API client — you'll extend and add error handling)
- frontend/src-tauri/src/main.rs (Tauri sidecar lifecycle — you'll add parent PID passing)
- frontend/src-tauri/tauri.conf.json (build config — you'll verify for production)
- backend/services/xml_schema_mapper.py (schema mapper — you'll fix BitRate)
- scripts/build-backend.sh (existing build script — you'll verify/update)

## What you're building

A working desktop application shell that:
1. Persists settings in a JSON config file at ~/Library/Application Support/rekordbot/
2. Provides a settings panel UI (main + advanced sections)
3. Shows a first-run wizard on first launch (output directory + API key)
4. Surfaces errors as user-facing toast notifications
5. Monitors parent process and self-terminates when Tauri closes
6. Correctly populates BitRate in Rekordbox XML export
7. Builds as a .app bundle launchable from Finder
8. Runs the full pipeline end-to-end in packaged mode

## Build order (follow this exactly)

### Step 1: Config manager and settings persistence
- Create backend/services/config_manager.py
- WRITE TESTS FIRST for pure logic (get_config_path, load_config, save_config, apply_config_to_env, config_exists, validate_output_directory)
- Integrate into main.py startup (load config before Settings instantiation)
- Update DB path for app data directory in packaged mode
- Commit: "Add config manager with JSON persistence and env var integration"

### Step 2: Settings API routes
- Create backend/routes/settings.py
- GET/PUT /api/settings, POST validate-key, POST validate-directory, GET status
- API key masking in responses
- Register in main.py
- Tests for all endpoints
- Commit: "Add settings API routes with validation and first-run status"

### Step 3: Self-termination watchdog
- Create backend/services/watchdog.py
- Parent PID polling with 5-second interval and 10-second grace period
- Parse --parent-pid from sys.argv
- Update main.rs to pass PID on sidecar spawn
- Watchdog not started in dev mode (no --parent-pid)
- Commit: "Add self-termination watchdog for sidecar process lifecycle"

### Step 4: Error handling standardisation
- Audit all existing routes for unhandled exceptions
- Ensure standard {"error": str, "detail": str} on all error paths
- Add startup health checks (ffmpeg, output directory, API key)
- Surface results in /api/settings/status
- Commit: "Standardise error handling and add startup health checks"

### Step 5: BitRate fix
- Update xml_schema_mapper.py: source_bitrate for lossy, computed for lossless
- Add compute_bitrate() helper
- Tests
- Commit: "Populate BitRate in Rekordbox XML export"

### Step 6: Frontend — Toast system
- ToastProvider context + useToast() hook
- Auto-show toasts on API errors
- Commit: "Add toast notification system for user-facing error messages"

### Step 7: Frontend — Settings panel
- SettingsPanel.tsx with main (API key, output dir, key notation, folder template, AAC toggle) and advanced (BPM range, confidence, track duration, max tracks) sections
- Save with validation, Tauri folder picker for output directory
- Commit: "Add settings panel with main and advanced configuration"

### Step 8: Frontend — First-run wizard
- SetupWizard.tsx with Welcome → Config → Done steps
- App.tsx routing based on /api/settings/status
- Commit: "Add first-run setup wizard for initial configuration"

### Step 9: Tauri packaging
- Verify PyInstaller build, sidecar naming, ffmpeg bundling
- Verify tauri.conf.json for production
- Makefile target for full build
- Manual test: Finder launch → wizard → pipeline
- Commit: "Configure Tauri packaging for production .app bundle"

### Step 10: Integration tests and docs
- End-to-end test coverage
- CLAUDE.md and SESSIONS.md update
- Commit: "Add integration tests and update project docs for Phase 6a"

## Constraints
- Follow all conventions in CLAUDE.md
- Do NOT modify any Phase 1/2/2b/3/4/5a/5b service code (except xml_schema_mapper BitRate fix)
- Reuse existing exception hierarchy — add specific error codes, not new exception classes
- Toast system built with React context and Tailwind — no new npm dependencies
- Config manager uses stdlib json and pathlib — no new Python dependencies
- Watchdog uses os.kill signal 0 for process checking — cross-platform compatible
- All new backend modules get their own logger via logging.getLogger(__name__)
- Use %s string formatting in log calls (not f-strings)
- Use sync SQLAlchemy (not async)

## Important
- Do NOT implement code signing or notarisation
- Do NOT create a .dmg wrapper
- Do NOT implement auto-update
- Do NOT implement settings import/export
- Do NOT do a UI polish pass — functional, not pretty
- Do NOT implement undo/redo for settings changes
- The config file is ONLY for user-configurable settings — internal settings stay in env vars
- The wizard is MINIMAL — three steps, not a tutorial
- Error toasts are the PRIMARY error surface — no modal dialogs for errors
```

### Continuation Prompt

```
We are continuing Phase 6a (App Shell & Packaging) of rekordbot.

Read these files for context:
- CLAUDE.md (project conventions and current status)
- SESSIONS.md (latest entry has where we left off and what's next)
- docs/features/phase-6a-app-shell.md (the feature specification)

Pick up from where we left off. Check SESSIONS.md for the last completed step
and what was identified as the next task. Confirm what you think the next step
is before writing any code.
```

---

## Notes

- The config manager pattern (JSON → env vars → pydantic-settings) is designed to be minimally invasive. The existing Settings class doesn't change its interface — it just gets its values from a different source in production. This means all existing code that reads from Settings continues to work without modification.
- The API key masking in GET responses is important — we don't want the full key sent to the frontend unnecessarily. The mask format is `sk-ant-...XXXX` (last 4 chars). When the user saves settings without changing the key, the frontend sends back the masked value. The backend detects masked values (contains `...`) and keeps the existing key.
- The watchdog's `os.kill(pid, 0)` is a POSIX standard — it checks process existence without sending a signal. It works on macOS and Linux. On Windows, you'd use `ctypes.windll.kernel32.OpenProcess()` instead, but Windows support is deferred to 6b.
- The database path change (from relative `sqlite:///rekordbot_dev.db` to `~/Library/Application Support/rekordbot/rekordbot.db`) needs careful handling. In dev mode (no `--parent-pid`), the current behaviour should be preserved. In packaged mode, the DB should be in the app data directory. The config manager's `get_config_path()` can provide the base directory for both config and DB.
- The Tauri packaging step is the riskiest. The sidecar naming convention, PyInstaller `_internal` directory inclusion, and ffmpeg path resolution all have potential failure modes that can only be caught by building and testing the actual `.app` bundle. Budget extra time here.
- The toast notification system replaces the current pattern where each component handles errors individually (or doesn't). After this phase, the API client wrapper catches all non-2xx responses and shows toasts, so individual components don't need error handling boilerplate unless they want to do something specific with the error.
