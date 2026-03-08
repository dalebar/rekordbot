# rekordbot — Project Plan v1.0
*A desktop DJ file management, format conversion, and AI-powered crate-building tool*

---

## 1. Vision & Scope

A desktop application that solves the full DJ file management workflow in one place:

- Ingest music files from any source in any format
- Convert or prepare files for CDJ/Rekordbox compatibility in a quality-preserving way
- Auto-tag with BPM, key, genre, energy, and mood using AI
- Organise files into a logical folder structure according to user preference
- Organise into crates intelligently using Claude
- Plan and sequence sets with AI assistance
- Export a Rekordbox-compatible XML library
- Dry-run previews before any file operation that moves, renames, or modifies — no surprises

**Target user:** Digital DJs who use Rekordbox and CDJs and are tired of doing this manually.
**Initial goal:** Personal use + peers, with monetisation potential later.

---

## 2. Tech Stack

Finalised during Phase 0 planning (Session 1). Full details in CLAUDE.md.

| Layer | Choice | Rationale |
|---|---|---|
| **Backend** | Python 3.12 (FastAPI, uvicorn) | Strongest language; huge audio library ecosystem |
| **Frontend** | React 19 (TypeScript, Vite, Tailwind CSS v4) | Modern UI; component model fits the app well |
| **Desktop shell** | Tauri v2 | Lightweight vs Electron; Rust-based; packages cleanly |
| **Audio processing** | ffmpeg + ffprobe (via subprocess) | Industry standard; handles every format |
| **Metadata** | mutagen | Best Python library for ID3/AIFF tags |
| **BPM/Key detection** | librosa (BPM via beat_track, key via chroma + Krumhansl-Schmuckler) | Best accuracy for both BPM and key; heavier dependency but worth it |
| **Claude integration** | Anthropic Python SDK | AI tagging, crate logic, set planning |
| **Rekordbox XML** | Custom generator (xml.etree.ElementTree) | No official library; straightforward XML |
| **Database** | SQLite via SQLAlchemy (sync mode) | Local, zero-config, perfect for a desktop tool |
| **Package management** | uv (lockfile + venv) | Fast resolver, reproducible builds |
| **Packaging** | PyInstaller (`--onedir`) + Tauri bundler | Cross-platform distribution |

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      TAURI v2 SHELL                          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │                 REACT FRONTEND                       │    │
│  │  File Drop → Progress → Library View → Crates       │    │
│  └───────────────────────┬─────────────────────────────┘    │
│                          │ HTTP (localhost:8420)              │
│  ┌───────────────────────▼─────────────────────────────┐    │
│  │              FASTAPI BACKEND (Python)                │    │
│  │                                                      │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │    │
│  │  │Converter │ │  Tagger  │ │  File    │ │Rekord- │ │    │
│  │  │ (ffmpeg) │ │(mutagen/ │ │Organiser │ │box XML │ │    │
│  │  │          │ │ librosa) │ │          │ │Export  │ │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────┘ │    │
│  │                                                      │    │
│  │  ┌────────────────────────────────────────────────┐ │    │
│  │  │            CLAUDE INTEGRATION LAYER             │ │    │
│  │  │    Smart Tagging · File Org · Crates · Planner  │ │    │
│  │  └────────────────────────────────────────────────┘ │    │
│  │                                                      │    │
│  │  ┌────────────────────────────────────────────────┐ │    │
│  │  │          SQLITE DATABASE (SQLAlchemy)            │ │    │
│  │  └────────────────────────────────────────────────┘ │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

**Key architectural decisions:**
- Frontend ↔ Backend via localhost HTTP (port 8420, hardcoded with conflict detection)
- Progress reporting via SSE (Server-Sent Events), not WebSocket
- Tauri IPC used only for desktop integration (file dialogs, path resolution)
- Python backend runs as Tauri sidecar (PyInstaller `--onedir` binary)
- ffmpeg bundled as a Tauri resource (not sidecar), called via subprocess from Python
- Mac-first, Apple Silicon only for initial builds; Windows-compatible by design

---

## 3. Feature Map

### Module A — File Ingestion & Conversion ✅ (Phase 1 — Complete)
- Drag-and-drop or folder selection (Tauri dialog)
- **Conversion is quality-preserving only** — the core principle:
  - ✅ **Convert to AIFF:** WAV, FLAC, ALAC (lossless → lossless, bit depth preserved, capped at 24-bit)
  - ⏭️ **Leave as-is:** MP3 (lossy, but universally CDJ-compatible — no benefit to converting)
  - ⏭️ **Leave as-is:** AIFF (already target format — copied to output directory for consistency)
  - ⚠️ **M4A requires inspection:** M4A is a container, not a codec — ffprobe inspects the contents before deciding:
    - M4A containing ALAC → convert to AIFF
    - M4A containing AAC → treat as lossy (see below)
  - 🔄 **AAC → MP3 (optional, user-controlled):** Global default in Settings (`convert_aac_to_mp3`, default false). Per-ingest override available. When enabled, uses LAME VBR V0 (`-q:a 0`, ~245 kbps avg) for best quality.
- Bitrate warning flag for any lossy file below 192kbps — surfaced in the UI as a quality alert
- Source format, codec, bitrate, and bit depth recorded in DB for every track
- SHA-256 hash-based duplicate detection (hash computed on source file before conversion)
- Concurrent processing queue (asyncio.Semaphore, default 2 concurrent conversions)
- SSE progress reporting (file-level: queued → processing → complete/failed)
- Output to `{output_directory}/imports/{YYYY-MM-DD}/` (Phase 2b reorganises later)
- Source files are never touched — rekordbot only writes to its output directory

### Module B — Metadata & Tagging Engine ✅ (Phase 2 — Complete)
- ✅ Read existing tags from output files (mutagen: AIFF ID3v2, MP3 ID3v2, M4A MP4 atoms)
- ✅ BPM detection (librosa beat_track with configurable half/double-time auto-correction)
- ✅ Key detection (librosa chroma_cqt + HPSS + Krumhansl-Schmuckler algorithm, 24 keys)
- ✅ Confidence scoring for BPM and key (0.0–1.0, threshold-based flagging)
- ✅ Original tag values preserved for comparison/revert (source_bpm, source_key)
- ✅ Write ID3v2.3 tags to AIFF and MP3, MP4 atoms to M4A (on explicit user action only)
- ✅ BPM ×2/÷2 quick-fix for half/double-time correction
- ✅ Rekordbox-style tag review UI with sortable table, column visibility toggle, inline editing
- ✅ Analysis pipeline separate from ingestion (tracks analysed after import, not during)

### Module C — Claude AI Layer (Phase 3)
- Genre and subgenre inference from filename + existing tags
- Mood/energy scoring (e.g. 1–10 scale)
- Smart tag suggestions (label, year, style descriptors)
- Batch processing with rate limiting

### Module B2 — File Organisation & Structure (Phase 2b)
- User-configurable folder template (e.g. `Artist/Album/Track`, `Genre/Artist/Track`, custom)
- Automated organisation pass based on AI-enriched tags (genre, mood, energy from Phase 3)
- Ambiguity detection — flags low-confidence cases for human review
- Review queue UI: ambiguous cases surfaced with Claude-powered reasoning (integrated from the start, not bolted on)
- "Decide once, remember forever" preference engine — stores user decisions as rules for future imports
- Handles edge cases: bootlegs, white labels, VA compilations, remixer vs original artist ambiguity
- Duplicate detection before moving (hash + near-match filename)
- Files are only moved once user has approved — no silent background renaming
- Runs *after* AI tagging (uses fully enriched metadata) and *before* Rekordbox XML export (so paths are final)

### Module D — Rekordbox XML Export (Phase 4)
- Map internal DB schema to Rekordbox track schema
- Generate `rekordbox.xml` with track entries
- Track paths as `file://localhost/` URIs with percent-encoded path components
- CDJ generation compatibility handling
- Export function
- No TEMPO or POSITION_MARK export initially (track metadata only)

### Module D2 — Rekordbox XML Import (Phase 4b — Deferred)
- Parse existing `rekordbox.xml`
- Merge with internal DB
- Conflict resolution

### Module E — Crate Builder (Phase 5)
- AI-powered crate organisation by mood/energy/genre
- User defines crate schema (e.g. "Opening Ambient", "Peak Time", "Cool Down")
- Claude assigns tracks to crates based on profile
- Manual override UI

### Module F — Set Planner (Phase 5)
- User defines set arc (duration, energy curve)
- Claude suggests track sequence
- Key compatibility checking
- Export as Rekordbox playlist

### Module G — UI / UX Shell (progressive, across all phases)
- Library grid view (sortable, filterable)
- File drop zone ✅ (Phase 1)
- Processing queue with progress ✅ (Phase 1)
- Track list ✅ (Phase 1, basic — replaced by Rekordbox-style tag review table in Phase 2)
- Rekordbox-style tag review table with column visibility toggle, inline editing, confidence indicators ✅ (Phase 2)
- Crate sidebar
- Settings panel (API key, output paths, CDJ generation target, BPM range, key notation preference)

---

## 4. Phased Build Plan

No hard deadlines. Each phase is complete when its acceptance criteria are met, tests pass, and docs are updated per the Phase Completion Checklist.

### Phase 0 — Project Scaffolding ✅ Complete
**Goal:** Repo, structure, tooling, and CLAUDE.md in place.

**Delivered:**
- Repo tooling: pyproject.toml, uv.lock, Makefile, pre-commit hooks (Ruff, mypy), scripts
- Python backend: FastAPI app with /health and /shutdown, CORS, pydantic-settings config, custom exception hierarchy, SQLAlchemy Track model (Rekordbox-compatible schema), 8 tests
- React frontend: Vite + React 19 + TypeScript + Tailwind CSS v4, typed API client, health check UI
- Tauri v2 shell: sidecar lifecycle management (spawn on setup, health polling, kill on close)
- Integration proof: PyInstaller binary builds, Tauri launches sidecar, health check passes
- Research: Rekordbox XML format, CDJ tag compatibility, Tauri + Python sidecar architecture

---

### Phase 1 — File Ingestion & Conversion ✅ Complete
**Goal:** Drop a file in, get the right output out — lossless files converted to AIFF, lossy files handled correctly, quality information recorded throughout.

**Delivered (10 commits, 114 tests):**
- Format inspector: ffprobe-based inspection for WAV, FLAC, AIFF, MP3, M4A (ALAC/AAC)
- Conversion decision engine: lossless → AIFF (bit depth preserved, capped at 24), lossy copy/optional convert
- Converter service: ffmpeg execution pipeline with SHA-256 duplicate detection
- Processing queue: asyncio.Semaphore concurrency control, SSE progress events, cancellation
- API routes: POST /api/ingest, GET /api/ingest/progress (SSE), POST /api/ingest/cancel, GET /api/tracks
- Frontend: DropZone (drag-and-drop + Tauri dialog), ProcessingQueue (live SSE status), TrackList
- Track model extended with ingestion provenance fields
- 8 test audio fixtures committed, integration tests covering all format paths
- Feature brief: `docs/features/phase-1-file-ingestion-conversion.md`

---

### Phase 2 — Metadata & Tagging ✅ Complete
**Goal:** Every track in the library has clean, accurate metadata — BPM, key, and existing tags read and enriched — with user review before anything is written to files.

**Delivered (12 commits, 390 tests):**
- Key notation: full Camelot/Open Key/classical mapping with 171 test cases (TDD)
- Tag reader: mutagen-based tag extraction from AIFF (ID3v2), MP3 (ID3v2), M4A (MP4 atoms)
- BPM detector: librosa onset analysis with configurable half/double-time auto-correction
- Key detector: librosa chroma + Krumhansl-Schmuckler algorithm with HPSS harmonic separation
- Tag writer: ID3v2.3 for AIFF/MP3 (no v1), MP4 atoms for M4A, preserves unmanaged tags
- Analysis pipeline: asyncio.Semaphore batch processing, per-track error isolation, SSE progress
- API routes: analyse, cancel, write-tags, track editing, revert, BPM multiply, enhanced track listing
- Frontend: TrackTable (Rekordbox-style sortable table, column visibility, inline editing), AnalysisControls, ColumnMenu, TrackDetailPanel
- Track model extended with source_bpm, source_key, bpm_confidence, key_confidence, analysis_status
- Feature brief: `docs/features/phase-2-metadata-tagging.md`

---

### Phase 3 — Claude Integration
**Goal:** Claude enriches tags beyond what algorithms can do.

- [ ] Anthropic SDK integration
- [ ] Prompt engineering for genre/mood/energy inference
- [ ] Batch tagging with rate limiting and retry logic
- [ ] User review / accept / reject UI for AI suggestions
- [ ] Store AI tag confidence scores in DB

**Deliverable:** Files with AI-enriched metadata; user can review before writing.

---

### Phase 2b — File Organisation & Structure
**Goal:** AI-enriched metadata now drives a clean, user-approved file structure before anything touches Rekordbox.

**Depends on:** Phase 3 (Claude Integration) — the organiser uses AI-enriched genre/mood/energy for placement decisions and Claude-powered reasoning for ambiguous cases.

- [ ] Template engine (configurable folder pattern with variables: `{artist}`, `{album}`, `{genre}`, `{year}`, etc.)
- [ ] Automated organisation pass — proposes moves based on AI-enriched tags
- [ ] Confidence scoring — flags ambiguous cases (missing tags, VA, bootlegs, edits)
- [ ] Review queue UI — ambiguous tracks surfaced with Claude-powered reasoning (integrated from the start)
- [ ] User preference store — decisions saved as rules and applied to future imports
- [ ] Duplicate check before any file is moved
- [ ] Dry-run mode — shows proposed structure without moving anything
- [ ] Confirmed moves written to DB (so Rekordbox XML uses final paths)

**Deliverable:** Files in a clean, user-approved folder structure. No files moved without explicit confirmation.

---

### Phase 4 — Rekordbox XML Export
**Goal:** Library exports cleanly into Rekordbox.

- [ ] Map internal DB schema to Rekordbox track schema
- [ ] Write XML entries (track paths as `file://localhost/` URIs, percent-encoded)
- [ ] CDJ generation compatibility handling
- [ ] Playlist/crate structure in XML
- [ ] Export function
- [ ] Rating scale mapping (0–5 → 0/51/102/153/204/255)
- [ ] BPM as two-decimal float

**Deliverable:** Generated XML that Rekordbox accepts without complaint.

*Note: Requires a Rekordbox XML research spike before implementation — empirical testing of round-trip import, path encoding edge cases, and AIFF artwork handling.*

---

### Phase 4b — Rekordbox XML Import (Deferred)
**Goal:** Import and merge an existing Rekordbox library.

- [ ] Parse existing `rekordbox.xml`
- [ ] Merge with internal DB
- [ ] Conflict resolution (existing tracks vs imported tracks)

**Deliverable:** Existing Rekordbox users can import their library into rekordbot.

*Deferred because export-only is sufficient for the initial workflow. Import adds significant complexity around conflict resolution.*

---

### Phase 5 — Crate Builder & Set Planner
**Goal:** The AI-powered creative layer.

- [ ] Crate schema definition UI
- [ ] Claude crate assignment logic (prompt-based)
- [ ] Energy arc definition for set planning
- [ ] Track sequencing suggestions
- [ ] Key compatibility logic (Camelot wheel)
- [ ] Export as Rekordbox playlist

**Deliverable:** You can describe a set, and the tool suggests a sequence.

---

### Phase 6 — Polish & Packaging
**Goal:** Something you'd hand to a friend without embarrassment.

- [ ] UI polish pass
- [ ] Error handling and user-facing messages
- [ ] Settings panel (API key management, paths, preferences)
- [ ] Tauri packaging (Mac .dmg)
- [ ] Basic onboarding / first-run experience
- [ ] Performance profiling (large libraries)
- [ ] Self-termination watchdog for Python backend
- [ ] Alembic migration setup (needed once real users have persistent databases)
- [ ] Code signing

**Deliverable:** Distributable app.

---

## 5. Git Strategy

### Branch Structure

```
main                         ← stable, always works, tagged releases
develop                      ← integration branch
feature/phase-0-scaffold     ← merged ✅
feature/phase-1-converter    ← merged ✅
feature/phase-2-metadata-tagging ← merged ✅
feature/phase-3-claude       ← next
feature/phase-2b-organiser
feature/phase-4-rekordbox
feature/phase-5-crates
feature/phase-6-polish
```

**Convention:** Branch names follow `feature/phase-N-descriptive-name`.

### Rules
- All work happens on feature branches, never directly on `main` or `develop`
- Feature branches are created from `develop` and merge back with `--no-ff`
- `develop` merges to `main` only when a phase is complete
- Every commit should leave the codebase in a working state (tests pass)
- Commit messages: imperative mood, concise but descriptive
- Tags mark phase completion: `phase-N-complete`

### Git Worktrees (Optional — for parallel development)

Worktrees let you have multiple branches checked out simultaneously in separate folders, all sharing the same git history. Useful if you want to run parallel Claude Code sessions on different features.

```bash
# Create a worktree for a feature
git worktree add ../rekordbot-tagger feature/phase-2-tagger

# List active worktrees
git worktree list

# Clean up when merged
git worktree remove ../rekordbot-tagger
```

**Rules:**
- Don't check out the same branch in two worktrees simultaneously
- CLAUDE.md in the root is shared across all worktrees automatically
- Database and config files should be in a user data directory (not the repo) to avoid conflicts

---

## 6. Claude Workflow

### The Core Principle

Claude has no persistent memory across sessions. All context is externalised into files so that Claude always has what it needs, regardless of which session or tool you're using.

### Key Files

| File | Purpose |
|---|---|
| `CLAUDE.md` | Project conventions, architecture, current status — Claude Code reads this automatically |
| `SESSIONS.md` | Session log — what was built, decisions made, what's next |
| `docs/features/<phase>.md` | Feature brief for each phase — the specification Claude Code implements against |
| `docs/claude-code-session-checklist.md` | Step-by-step for starting new phases and continuing interrupted sessions |
| `docs/phase-completion-checklist.md` | End-of-phase close-out process |

### Feature Brief Format

Every phase gets a feature brief in `docs/features/` before implementation starts. The brief includes:

- Goal, inputs, outputs
- Architecture and component design
- Decision table for any branching logic
- Acceptance criteria (specific, testable)
- Out of scope (prevents creep)
- TDD candidates (pure logic functions that get tests written first)
- Commit breakdown (logical build order)
- Claude Code prompt (initial + continuation)
- Finalised decisions table

See `docs/features/phase-1-file-ingestion-conversion.md` and `docs/features/phase-2-metadata-tagging.md` for reference examples.

### Session Workflow

**Starting a new phase:**
1. Write the feature brief in this planning chat
2. Agree all decisions before implementation
3. Follow `docs/claude-code-session-checklist.md` — branch, venv, clean commit, paste prompt

**Continuing mid-phase:**
1. Update SESSIONS.md with where you left off
2. Start fresh Claude Code session
3. Use the continuation prompt from the feature brief

**Closing a phase:**
1. Follow `docs/phase-completion-checklist.md`
2. Update CLAUDE.md, SESSIONS.md, feature brief
3. Merge to develop with `--no-ff`

### Prompting Principles

**Be specific about the file and function, not the whole project**
> ❌ "Build me the tagging system"
> ✅ "In `/backend/services/bpm_detector.py`, write a `detect_bpm` function that takes a filepath (Path) and returns a BPMResult using librosa. Include half/double-time auto-correction and error handling for corrupt files. Follow the patterns in `/backend/services/converter.py`."

**Give Claude a reference implementation to match** — pointing at an existing file that follows your conventions is more effective than describing conventions in words.

**Ask for a plan before code on complex tasks** — "Before writing any code, outline the approach you'll take for the Rekordbox XML parser."

**Keep sessions focused** — one session = one feature or one clearly-scoped problem.

---

## 7. Resolved Decisions

These questions were raised during initial planning and resolved in Session 1. Recorded here for reference.

| Question | Resolution |
|---|---|
| Mac-only or cross-platform? | Mac-first (Apple Silicon only). Windows-compatible by design, but not tested until Phase 6. |
| Which CDJ generations to target? | All USB-capable models from 2009+. ID3v2.3 as tag target for maximum compatibility. |
| Bundle ffmpeg or require user install? | Bundle as Tauri resource. |
| Hot folder watch vs manual import? | Manual import only. Hot folder deferred (architectural decision not yet made). |
| Free tool vs freemium? | No licensing/auth layer. Personal use first; monetisation deferred. |
| librosa vs aubio? | librosa from day 1. Better accuracy for both BPM and key detection. Heavier dependency (numpy, scipy, numba) but worth it. Decision revised in Phase 2 planning (Session 4). |
| Async vs sync SQLAlchemy? | Sync. Async adds complexity for no benefit on single-user desktop app with local SQLite. |
| Alembic migrations? | Deferred to Phase 6. During development, recreate dev database on schema changes. |
| pyproject.toml vs requirements.txt? | pyproject.toml + uv exclusively. No requirements.txt. |
| Rekordbox XML import? | Deferred to Phase 4b. Export-only is sufficient for initial workflow. |
