# CrateAI — Claude Context File

## Project Overview

CrateAI is a desktop application for digital DJs who use Rekordbox and CDJs. It handles the full file management workflow: ingest music files from any source/format, convert them with quality-preserving logic (lossless → AIFF, lossy left as-is or converted to MP3), auto-tag with BPM/key/genre/mood using algorithmic analysis and Claude AI, organise into a clean folder structure, build crates, plan sets, and export a Rekordbox-compatible XML library. All file operations use dry-run previews — nothing moves without user approval.

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
crateai/
├── CLAUDE.md                     ← This file
├── SESSIONS.md                   ← Session log
├── README.md
├── Makefile
├── pyproject.toml
├── .env.example
├── backend/
│   ├── main.py                   ← FastAPI entry point
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

## Coding Conventions

- **Python:** PEP 8, type hints on all functions, docstrings on all public methods
- **Async:** Use async/await throughout FastAPI routes and services
- **Error handling:** Never silently swallow exceptions; log and surface to frontend
- **Tests:** pytest, coverage on all service-layer logic. Tests are part of the definition of done.
- **Imports:** Standard library → third-party → local, separated by blank lines
- **Naming:** snake_case for Python, camelCase for TypeScript/React
- **SQL:** SQLAlchemy ORM exclusively — no raw SQL strings
- **Commits:** Frequent, with clear descriptive messages. One logical unit of work per commit.

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
