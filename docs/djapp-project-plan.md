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

### Module B2 — File Organisation & Structure ✅ (Phase 2b — Complete)
- ✅ User-configurable folder template (default `{artist}/{album}/{title}`, with fallback syntax `{variable|"literal"}`)
- ✅ Automated organisation pass — proposes moves based on enriched tags from Phases 1–3
- ✅ Confidence scoring — flags ambiguous cases (missing tags, VA compilations, bootlegs, low AI confidence) for human review
- ✅ Review queue UI: ambiguous tracks surfaced with Claude-powered placement suggestions (reuses Module C's client infrastructure)
- ✅ "Decide once, remember forever" preference engine — user decisions saved as rules (`artist_folder`, `va_handling`, `custom_path`) and applied to future imports
- ✅ Handles edge cases: bootlegs, white labels, VA compilations, remixer vs original artist ambiguity
- ✅ Dry-run default — proposes folder structure without moving anything; batch approval for high-confidence, individual review for ambiguous
- ✅ Path collision handling before moving (suffix `_1`, `_2`); exact duplicate detection via Phase 1's SHA-256 hash (near-duplicate audio fingerprinting deferred)
- ✅ Files are only moved once user has approved — no silent background renaming
- ✅ Runs *after* AI tagging (uses enriched metadata including genre, mood, energy) and *before* Rekordbox XML export (so paths are final)

### Module C — Claude AI Layer ✅ (Phase 3 — Complete)
- ✅ Anthropic SDK integration with rate limiting (timestamp-based throttle) and exponential backoff retry on 429/529
- ✅ Tool use (function calling) for structured output — genre, subgenre, mood, energy (1–10), confidence (high/medium/low), reasoning per track
- ✅ DJ-centric genre taxonomy (~50 electronic genres) with BPM/key as classification signals
- ✅ Batch processing (configurable batch size, artist-grouped for context) with per-batch error isolation
- ✅ Token usage tracking and cost estimation surfaced in SSE events and API responses
- ✅ Original genre preserved for comparison/revert (source_genre)
- ✅ AI tagging pipeline separate from ingestion and analysis (tracks tagged after analysis, not during)
- ✅ User review UI: energy colour coding, AI confidence indicators, genre tooltip with reasoning, AI filter modes

### Module D — Rekordbox XML Export ✅ (Phase 4 — Complete)
- ✅ Location encoder: RFC 3986 percent-encoding per path component, `file://localhost/` URI generation
- ✅ Schema mapper: Track model → Rekordbox XML TRACK attributes (BPM, rating, key, kind, dates, fallbacks)
- ✅ XML builder: DJ_PLAYLISTS document with PRODUCT, COLLECTION, PLAYLISTS sections
- ✅ Auto-generated playlists from organised folder hierarchy (All Tracks + per-artist)
- ✅ Rating scale mapping (0–5 → 0/51/102/153/204/255)
- ✅ BPM as two-decimal float, Tonality in user's preferred key notation
- ✅ Export service with configurable output path and warning collection
- ✅ Manual Rekordbox import test passed — 15 tracks imported, all metadata correct, files playable
- ✅ No TEMPO or POSITION_MARK export (track metadata only, beat grid deferred)

### Module D2 — Rekordbox XML Import ✅ (Phase 4b — Complete)
- ✅ XML parser: location URI decoding, BPM/rating/tonality parsing, playlist extraction with folder path flattening
- ✅ Track matching: path match (primary) → SHA-256 hash match (secondary) → new track creation
- ✅ Conflict detection: field-specific thresholds (BPM > 0.5 difference, any difference for key/rating/genre)
- ✅ Conflict resolution: per-track field toggle (accept rekordbox / keep rekordbot), bulk resolve actions
- ✅ Import service: SSE progress reporting, cancellation support, playlist-to-crate conversion
- ✅ Imported tracks enter with analysis_status="not_analysed", ai_status="untagged" (ready for rekordbot pipeline)
- ✅ No TEMPO or POSITION_MARK import (metadata only, matching export behaviour)
- ✅ Import UI: Tauri file dialog, progress bar, conflict review panel with per-field toggle

### Module E — Crate Builder ✅ (Phase 5a — Complete)
- ✅ User creates crates by providing a free-text description of the vibe (e.g. "Deep & dubby minimal house, 118–124 BPM, hypnotic and warm")
- ✅ Claude interprets the description into searchable criteria (mood, energy range, BPM range, genre hints) and stores both the original description and parsed interpretation
- ✅ Claude assigns every matching track from the library — crates are pools to draw from, not curated short lists
- ✅ Track assignment is overlapping — a track can appear in multiple crates
- ✅ Two refresh modes: manual ("refresh this crate") and automatic (re-run on newly ingested tracks)
- ✅ Crates export as Rekordbox playlists in the XML (coexisting with folder-based playlists from Phase 4)
- ✅ Sidebar panel UI in Rekordbox playlist tree style
- ✅ Manual override: user can add/remove individual tracks from any crate

### Module E2 — Set Planner ✅ (Phase 5b — Complete)
- ✅ User describes a set with time dimension, energy arc, and destination state (e.g. "1 hour, build from ambient to moderate house, positive mood, hand off at 120–125 BPM")
- ✅ Claude pulls from crates or the full library to suggest a track sequence
- ✅ 2–3x track multiplier — provides enough options for the user to customise the final plan
- ✅ Lock-and-shuffle iterative refinement: user locks anchor tracks in place, shuffles unlocked slots with alternatives that respect the arc context of locked neighbours
- ✅ Segmented mood descriptions: user can change the brief between shuffle passes, so different sections of the set can target different moods (e.g. meditative → dark/aggressive → uplifting resolution). Locked tracks define segment boundaries; each gap between locks can have its own description.
- ✅ Two shuffle modes: "replace" (swap unlocked tracks for different ones from the pool) and "reorder" (optimise sequence of current unlocked tracks)
- ✅ BPM transition scoring (smooth/acceptable/noticeable/jarring) for adjacent tracks
- ✅ Key compatibility module (Camelot wheel utility) available for harmonic mixing suggestions — optional, for users who want it
- ✅ Export set as ordered Rekordbox playlist (track order preserved, unlike unordered crate playlists)
- ✅ Set planner UI: track sequence table with lock toggle, BPM/key transition indicators, segment dividers with inline editing, candidate pool panel, shuffle controls, export button

### Module F — Key Compatibility Utility ✅ (Phase 5a — Complete)
- ✅ Standalone Camelot wheel logic: given two key integers, determine compatibility (same key, adjacent on wheel, relative major/minor)
- ✅ Pure math module, no Claude dependency
- ✅ Used by Set Planner (5b) for sequencing, and available for future UI features (related tracks, visual indicators)

### Module G — UI / UX Shell (progressive, across all phases)
- Library grid view (sortable, filterable)
- File drop zone ✅ (Phase 1)
- Processing queue with progress ✅ (Phase 1)
- Rekordbox-style tag review table with column visibility toggle, inline editing, confidence indicators ✅ (Phase 2)
- AI tagging controls: AI Tag button, progress bar with token usage summary, AI filter modes ✅ (Phase 3)
- AI-enriched columns: mood, energy (colour-coded), subgenre, AI confidence (colour-coded), genre tooltip with AI reasoning ✅ (Phase 3)
- Organisation controls: propose/approve buttons, progress bar, organisation filter modes ✅ (Phase 2b)
- Review queue: ambiguous track review with accept/edit/skip, preference rule creation ✅ (Phase 2b)
- Preference rules panel: view and delete saved rules ✅ (Phase 2b)
- Export controls: Export XML button, result summary with warning expansion ✅ (Phase 4)
- Crate sidebar: Rekordbox-style playlist tree with crate list, track counts, context menu ✅ (Phase 5a)
- Set planner view: full-page track sequence with lock/unlock, BPM/key transition indicators, segment dividers, candidate pool, shuffle controls ✅ (Phase 5b)
- Set create dialog: name, description, duration, BPM range, energy arc, source crates, harmonic mixing ✅ (Phase 5b)
- Sidebar sets section: set list with track counts and + New button ✅ (Phase 5b)
- Settings panel: API key (password + test), output directory (text + native folder dialog), key notation dropdown, folder template with live preview, AAC toggle, advanced section (BPM range, confidence, track duration, max tracks) ✅ (Phase 6a)
- First-run wizard: Welcome → Config (output directory required, API key optional) → Done, gates app entry via /api/settings/status ✅ (Phase 6a)
- Toast notifications: success/error/warning/info with auto-dismiss, global API error handler ✅ (Phase 6a)
- Settings button in sidebar footer ✅ (Phase 6a)
- Import controls: Import XML button with Tauri file dialog, progress bar, summary display ✅ (Phase 4b)
- Conflict review panel: expandable per-track conflicts, per-field toggle (RB/rbot), bulk resolve actions ✅ (Phase 4b)

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

### Phase 3 — Claude Integration ✅ Complete
**Goal:** Claude enriches tags beyond what algorithms can do.

**Delivered (8 commits, 462 tests total / 72 new):**
- Claude client: Anthropic SDK wrapper with timestamp-based rate limiting, exponential backoff retry on 429/529, token usage tracking, cost estimation
- Prompt builder: System prompt with DJ-centric genre taxonomy (~50 genres), tool use schema for structured output, artist-grouped batch message builder, result parser with validation
- AI tagger pipeline: Batch orchestrator with per-batch error isolation, cancellation via asyncio.Event, SSE progress events, source genre preservation for revert
- API routes: POST /api/tracks/ai-tag, GET /api/tracks/ai-tag/progress (SSE), POST /api/tracks/ai-tag/cancel, GET /api/tracks/ai-tag/status, POST /api/tracks/ai-tag/validate-key
- Track model: subgenre, mood, energy (1–10), ai_confidence (high/medium/low), ai_reasoning, source_genre, ai_status
- Frontend: TrackTable with mood, energy (colour-coded), AI confidence columns, genre tooltip with AI reasoning, AI filter modes; AnalysisControls with AI Tag button, progress bar, token usage summary
- Feature brief: `docs/features/phase-3-claude-integration.md`

---

### Phase 2b — File Organisation & Structure ✅ Complete
**Goal:** Clean metadata now drives a clean, user-approved file structure before anything touches Rekordbox.

**Delivered (11 commits, 602 tests total / 140 new):**
- Template engine: configurable folder templates with fallback syntax (`{variable|"literal"}`), chained fallbacks, path sanitisation (unsafe chars, unicode preserved), output path building with extension derivation; 37 tests (TDD)
- Confidence scorer: base 0.5 scoring with deltas for metadata presence/absence, VA compilation detection (Various Artists, VA, V/A patterns), bootleg indicator detection (word-boundary regex); 34 tests (TDD)
- Preference store: CRUD for artist_folder/va_handling/custom_path rules, normalised key matching (lowercase), apply_rules() with priority ordering (custom_path > artist_folder > va_handling); 16 tests (TDD)
- Claude reasoner: placement suggestions for ambiguous tracks via tool use, batch processing, reuses Phase 3 ClaudeClient; 11 tests (TDD)
- File mover: shutil.move wrapped in asyncio.to_thread(), collision handling (_1, _2 suffix), post-move verification, empty directory cleanup (bottom-up with safety bounds); 12 tests
- Organiser pipeline: two-phase orchestrator (propose + execute), SSE progress events, cancellation support, optional Claude enrichment for ambiguous tracks; 6 tests
- API routes: POST /api/organise/propose, GET /api/organise/progress (SSE), POST /api/organise/cancel, GET /api/organise/proposal, POST /api/organise/approve, POST /api/organise/resolve/{id}, GET/POST/DELETE /api/preferences; 19 tests
- Track model: proposed_path, previous_output_path, organisation_status (unorganised/proposed/review_needed/organised), organisation_confidence, organisation_reasoning
- PreferenceRule model: rule_type + key UniqueConstraint, normalised key matching
- Frontend: OrganiseControls (propose/approve buttons, emerald progress bar, organisation filter modes), ReviewQueue (accept/skip/custom path), PreferenceRulesPanel (CRUD), TrackTable organisation_status column
- Integration tests: end-to-end propose→approve flow, resolve flow, preference rule application, re-organisation after metadata changes; 5 tests
- Feature brief: `docs/features/phase-2b-file-organisation.md`

---

### Phase 4 — Rekordbox XML Export ✅ Complete
**Goal:** Library exports cleanly into Rekordbox.

**Delivered (10 commits, 706 tests total / 104 new):**
- Location encoder: RFC 3986 percent-encoding per path component, `file://localhost/` URI generation, round-trip decodable; 25 tests (TDD)
- Schema mapper: Track model → Rekordbox XML attribute mapping, BPM/rating/kind/date formatting, key notation conversion, file size/mtime from disk, fallbacks for missing metadata; 35 tests (TDD)
- XML builder: DJ_PLAYLISTS document construction with PRODUCT/COLLECTION/PLAYLISTS, sequential TrackID assignment, folder-based playlist auto-generation (All Tracks + per-artist), UTF-8 encoding; 19 tests
- Export service: full pipeline orchestrator, track filtering, warning collection, configurable output path with settings fallback; 9 tests
- API routes: POST /api/export/rekordbox, GET /api/export/rekordbox/status; 5 tests
- Frontend: ExportControls (amber Export XML button, result summary, warning expansion), API client types and endpoints
- Integration tests: end-to-end create→export→parse→verify, location encoding round-trips, playlist structure verification, re-export after metadata changes; 11 tests
- Bugfix: added `-write_id3v2 1` flag to AIFF conversion command (ffmpeg was silently dropping metadata tags during lossless → AIFF conversion)
- Manual Rekordbox import test: 15 tracks imported via File → Import Library, all metadata correct, files playable, playlists generated
- Feature brief: `docs/features/phase-4-rekordbox-xml-export.md`

---

### Phase 5a — Crate Builder ✅ Complete
**Goal:** AI-powered smart playlists — describe a vibe, get a crate full of matching tracks.

**Delivered (10 commits, 814 tests total / 108 new):**
- Key compatibility module: Camelot wheel harmonic mixing — same key, adjacent, relative major/minor, energy boost/drop, wrap-around; 29 tests (TDD)
- Crate data models: Crate (name, description, parsed_criteria JSON, auto_refresh) and CrateTrack (many-to-many association with assignment_method), UniqueConstraint on (crate_id, track_id), ORM cascade delete; 8 tests
- Crate prompt builder: description→criteria parsing, batch track assignment prompts, result parsing with deduplication and invalid ID filtering; 19 tests (TDD)
- Crate assigner: batched Claude assignment pipeline with SSE progress, cancellation via asyncio.Event, clear_ai_assignments preserves manual additions; 6 tests
- Crate manager: full CRUD, refresh (clears AI, preserves manual, re-assigns), auto-refresh for newly ingested tracks; 16 tests
- API routes: 9 endpoints — POST/GET/PUT/DELETE /api/crates, POST /api/crates/{id}/refresh, POST/DELETE /api/crates/{id}/tracks, GET /api/crates/{id}/progress (SSE); 11 tests
- XML export integration: crate playlists alongside folder-based playlists, sorted alphabetically; 7 tests
- Frontend: CrateSidebar (playlist tree, context menu with Refresh/Toggle Auto-refresh/Delete), CrateCreateDialog (modal with SSE progress), TrackTable crate filtering
- Integration tests: end-to-end create→assign→verify, refresh with manual preservation, overlapping assignment, XML export with crates; 12 tests
- Feature brief: `docs/features/phase-5a-crate-builder.md`

---

### Phase 5b — Set Planner ✅ Complete
**Goal:** Given a set description with time and energy arc, suggest a track sequence — then iteratively refine it section by section.

**Delivered (10 commits, 930 tests total / 116 new):**
- BPM transition scoring: threshold-based scoring (0.0–1.0), quality labels (smooth/acceptable/noticeable/jarring), BPM range suggestion for sequence positions; 29 tests (TDD)
- Set prompt builder: system prompts and tool schemas for initial planning, replace, and reorder operations; track summary builder; result parsers with dedup and validation; 20 tests (TDD)
- Set planner service: CRUD, lock/unlock with automatic segment recalculation, segment description preservation across recalculation, manual track editing (add/remove/move), candidate pool management, async Claude planning and shuffle operations with SSE progress; 26 tests
- Data models: SetPlan (name, description, duration, BPM targets, energy arc, source type, harmonic mixing, status), SetTrack (position, lock, candidate flag), SetSegment (position range, description); UniqueConstraint on (set_id, track_id), cascade delete; 11 tests
- API routes: 14 endpoints — POST/GET /api/sets, GET/PUT/DELETE /api/sets/{id}, POST lock/unlock, PUT segments, POST shuffle, POST/DELETE tracks, POST move, GET candidates, POST export, GET progress (SSE); 12 tests
- XML export integration: ordered set playlists alongside folder-based and crate playlists, track position order preserved, alphabetical sorting; 8 tests
- Frontend: SetPlannerView (track sequence table with lock toggle, BPM/key transition indicators, segment dividers with inline editing, collapsible candidate panel, shuffle controls, export button), SetCreateDialog (name, description, duration, BPM start/end, energy arc selector, source type with crate picker, harmonic mixing toggle), SetListPanel, CrateSidebar with Sets section
- Integration tests: end-to-end create→lock→segment→export, track add/remove/move, segment description preservation, XML playlist order verification, API route lifecycle; 10 tests
- Feature brief: `docs/features/phase-5b-set-planner.md`

---

### Phase 4b — Rekordbox XML Import ✅ Complete
**Goal:** Import and merge an existing Rekordbox library.

**Delivered (8 commits, 1143 tests total / 130 new):**
- XML parser: Rekordbox XML parsing with location URI decoding (`file://localhost/` → filesystem path), BPM/rating/tonality extraction, playlist tree traversal with folder path flattening to name prefixes; 63 tests (TDD)
- Track matcher: path match (primary) → SHA-256 hash match (secondary) → new track strategy, field-level conflict detection with configurable thresholds (BPM > 0.5, any difference for key/rating/genre); 25 tests (TDD)
- Conflict resolver: per-track resolution with field toggle (accept rekordbox / keep rekordbot), bulk resolution (resolve all rekordbox / resolve all rekordbot), JSON conflict storage in Track.import_conflicts; 11 tests
- Import service: pipeline orchestrator with SSE progress, playlist-to-crate conversion (assignment_method="imported", auto_refresh=False), cancellation via threading.Event; 11 tests
- API routes: POST /api/import/rekordbox, GET /api/import/progress (SSE), POST /api/import/cancel, GET /api/import/conflicts, POST /api/import/conflicts/{id}/resolve, POST /api/import/conflicts/resolve-all; 9 tests
- Frontend: ImportControls (Tauri file dialog, progress bar, summary display), ConflictReviewPanel (expandable per-track conflicts, per-field RB/rbot toggle, bulk resolve actions)
- Track model: import_source, import_conflicts columns
- Integration tests: full round-trip, playlist import, hash matching, large imports, missing files, bulk resolution; 6 tests
- Feature brief: `docs/features/phase-4b-xml-import.md`

---

### Phase 6a — App Shell & Packaging ✅ Complete
**Goal:** Transform rekordbot from a dev-mode-only project into a working desktop application launchable from Finder.

**Delivered (10 commits, 1013 tests total / 83 new):**
- Config manager: JSON config persistence at `~/Library/Application Support/rekordbot/config.json`, config → env vars → pydantic-settings pipeline (env vars take precedence), `CONFIGURABLE_FIELDS` set, API key masking (`sk-ant-...XXXX`); 34 tests (TDD)
- Settings API: GET/PUT `/api/settings` with key masking, POST `validate-key` (Anthropic SDK test call), POST `validate-directory`, GET `status` (first-run check, ffmpeg availability); 12 tests
- Self-termination watchdog: daemon thread polling parent PID every 5s via `os.kill(pid, 0)`, 10s grace period, `--parent-pid` CLI arg, Tauri passes PID on spawn; 8 tests
- Error handling: `RequestValidationError` handler with standard `{error, detail}` JSON, startup health checks (ffmpeg, output dir, API key — non-blocking), unhandled exception middleware; 4 tests
- BitRate fix: lossy files use `source_bitrate`, lossless compute from `sample_rate × bit_depth × channels`, `compute_bitrate()` pure function; 11 tests
- Frontend: ToastProvider (context + hook, auto-dismiss, global API error handler), SettingsPanel (API key test, folder dialog, key notation, folder template preview, AAC toggle, advanced section), SetupWizard (Welcome → Config → Done, gated by status endpoint)
- Tauri: dialog plugin for folder picker, `--parent-pid` passed to sidecar, resources config for ffmpeg
- Integration tests: first-run flow, settings persistence, API key masking, directory validation, error format, bitrate; 13 tests
- Feature brief: `docs/features/phase-6a-app-shell.md`

---

### Phase 6b — Polish & Distribution
**Goal:** Something you'd hand to a friend without embarrassment.

- [ ] UI polish pass
- [ ] Performance profiling (large libraries)
- [ ] Alembic migration setup
- [ ] Code signing and notarisation
- [ ] `.dmg` packaging
- [ ] Basic onboarding tutorial (beyond the first-run wizard)
- [ ] Bootleg detection refinement (false positives on "single edit", "radio edit" etc.)
- [ ] Folder template editor UI (visual drag-and-drop)
- [ ] Drag-and-drop reordering in set planner
- [ ] Windows packaging

**Deliverable:** Distributable, signed app.

---

## 5. Git Strategy

### Branch Structure

```
main                         ← stable, always works, tagged releases
develop                      ← integration branch
feature/phase-0-scaffold     ← merged ✅
feature/phase-1-converter    ← merged ✅
feature/phase-2-metadata-tagging ← merged ✅
feature/phase-3-claude       ← merged ✅
feature/phase-2b-organiser   ← merged ✅
feature/phase-4-rekordbox    ← merged ✅
feature/phase-5a-crate-builder ← merged ✅
feature/phase-5b-set-planner   ← merged ✅
feature/phase-6a-app-shell     ← merged ✅
feature/phase-4b-xml-import    ← current (ready to merge)
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

See `docs/features/` for all phase briefs (phase-0 through phase-6a, plus phase-4b).

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
| Alembic migrations? | Deferred to Phase 6. During dev, schema changes handled by recreating the dev database. |
