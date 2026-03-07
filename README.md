# rekordbot

Desktop app for digital DJs who use Rekordbox and CDJs. Handles the full file management workflow: ingest, convert, tag, organise, build crates, plan sets, and export a Rekordbox-compatible XML library.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy (SQLite)
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS
- **Desktop shell:** Tauri v2 (Rust)
- **Audio:** ffmpeg, mutagen, aubio
- **AI:** Anthropic Claude SDK

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) — `brew install uv`
- Node.js 18+
- Rust toolchain — [rustup.rs](https://rustup.rs/)
- ffmpeg — `brew install ffmpeg`

## Dev Setup

```bash
# One-command setup
bash scripts/dev-setup.sh

# Or manually:
uv venv
uv sync --all-extras
uv run pre-commit install
cd frontend && npm install
```

## Development

```bash
# Backend only (hot reload)
make dev-backend

# Full app (Tauri + React + backend sidecar)
make dev-frontend

# Run tests
make test

# Lint and type check
make lint

# Auto-format
make format
```

## Project Structure

```
backend/          Python FastAPI backend
frontend/         React + Tauri frontend
scripts/          Build and setup scripts
docs/             Feature briefs and research
```

See `CLAUDE.md` for full project context and conventions.
