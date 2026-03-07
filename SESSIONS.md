# rekordbot — Session Log

---

## Session 1 — 2025-03-07

### What was worked on
Pre-Phase-0 planning. Full project review, research coordination, and decision-making.

### Summary
- Reviewed the full project plan (project instructions + phased build plan)
- Flagged concerns and open questions about the plan:
  - Tauri + Python backend lifecycle (how does the sidecar work?)
  - Rekordbox XML format and CDJ tag compatibility (affects DB schema)
  - librosa dependency weight (suggested aubio-only to start)
  - Rekordbox XML research spike needed before finalising schema
  - Cross-platform ambiguity needed resolving
  - `pyproject.toml` vs `requirements.txt` (chose pyproject.toml only)
- Split research into two focused chats:
  - **Chat A:** Rekordbox XML format + CDJ tag compatibility (combined because they're deeply intertwined)
  - **Chat B:** Tauri + Python sidecar architecture, dev workflow, packaging
- Both research documents completed and synthesised back in the main chat
- Identified gaps in CLAUDE.md (logging, error handling, linting, config management, git workflow, frontend conventions) and revised before starting Phase 0

### Key decisions made
1. Mac-first, Windows-compatible by design
2. Bundle ffmpeg (as Tauri resource, not sidecar)
3. pyproject.toml as single dependency source (no requirements.txt), exact version pins
4. PyInstaller `--onedir` mode (avoids zombie processes, easier to sign)
5. Hardcoded port 8420 with conflict detection
6. SSE for progress reporting (not WebSocket)
7. Apple Silicon only for initial builds
8. ID3v2.3 as primary tag target (universal CDJ compatibility)
9. Key stored as integer 1–24 (Camelot wheel mapping)
10. Rekordbox XML export-only in Phase 4 (import deferred to Phase 4b+)
11. Tauri IPC for desktop integration only; all business logic via HTTP to FastAPI
12. Sidecar integration must be tested at end of Phase 0
13. Start with aubio for BPM/key detection; add librosa only if accuracy insufficient
14. DB schema designed from Rekordbox XML track attributes (ensures clean export mapping)
15. No TEMPO/POSITION_MARK export initially (track metadata only)
16. Ruff for Python linting/formatting (replaces black + isort + flake8)
17. pydantic-settings for configuration (typed, validated, REKORDBOT_ prefix)
18. Python logging module with INFO default, DEBUG via config
19. Consistent API error schema: {"error": str, "detail": str} on all non-2xx responses
20. Custom exception hierarchy: RekordBotError base class with domain-specific subclasses
21. Project named "rekordbot"

### Unresolved questions / blockers
- None blocking Phase 0. All foundational decisions are made.
- Rekordbox XML empirical testing (round-trip import, path encoding edge cases, AIFF artwork) to be done as a spike before Phase 4, not before Phase 0.
- Self-termination watchdog for the Python backend deferred to Phase 6.

### What's next
- Begin Phase 0 implementation: repo init, Python backend scaffold, React frontend scaffold, Tauri shell setup, DB schema, sidecar integration proof.
- Feature brief for Phase 0 is written and ready.
- CLAUDE.md and SESSIONS.md are finalised.
