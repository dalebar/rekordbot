# Feature: Crate Builder
**Branch:** `feature/phase-5a-crate-builder`
**Status:** Complete (Phase 5a) → Soft-retired (Phase 6d.1) ⛔
**Phase:** 5a
**Depends on:** Phase 4 (complete)

---

## ⛔ Superseded — Soft-retired in Phase 6d.1

This feature was built and shipped in Phase 5a (Session 22, October 2025), and was soft-retired in Phase 6d.1 (Session 35, May 2026).

**Reason:** Empirical use during Phase 6c dogfooding established that the AI-clustering model behind Crate Builder didn't fit realistic DJ workflow. The model assumed a comprehensive analysed library against which Claude could cluster tracks into vibe-described crates. Real-world DJ ingestion looks different: a handful of new tracks at a time, fed into a much larger Rekordbox-managed library that the DJ already knows through listening rather than through algorithmic mining. Inviting Claude to cluster a 3-track batch into vibe-described crates produced output that wasn't useful — it lacked the breadth to be meaningful and competed with the DJ's own contextual knowledge rather than augmenting it.

**Endstate as of Phase 6d.1:**
- UI entry points removed (`CrateSidebar`, `CrateCreateDialog` no longer imported by `App.tsx`).
- Backend routes deregistered (`/api/crates/*` returns 404).
- XML exporter no longer emits crate playlists.
- Code, data models, DB tables, and tests preserved as dormant.

**Future:** A hard-delete pass (working name "Path X") may eventually `git rm` this entire feature. Until then, the brief below is preserved as historical record of what was built and why.

---

## Goal

Allow the user to create AI-powered smart playlists ("crates") by describing a vibe in free text. Claude interprets the description into structured criteria (mood, energy range, BPM range, genre hints) and assigns every matching track from the library. Crates are pools to draw from — overlapping, refreshable, and exported as Rekordbox playlists.

This is the foundation for Phase 5b (Set Planner), which will pull from crates to build ordered sequences.

---

## Inputs

- All tracks in the database with metadata from Phases 1–3 (title, artist, genre, subgenre, BPM, key, mood, energy, AI confidence)
- User-provided free-text crate description (e.g. "Deep & dubby minimal house, 118–124 BPM, hypnotic and warm")
- Existing Claude client infrastructure from Phase 3 (rate limiting, retry, token tracking)

## Outputs

- Crate records in the database with name, description, and Claude's parsed criteria
- Many-to-many track assignments (overlapping — a track can be in multiple crates)
- Crate playlists in the exported Rekordbox XML (alongside existing folder-based playlists)
- Sidebar UI showing crate tree with track counts

---

## Architecture & Key Components

### 1. Data Model

**Crate table (`backend/models/crate.py`):**

| Column | Type | Purpose |
|---|---|---|
| `id` | Integer, PK | Internal ID |
| `name` | String, not null | Display name (e.g. "Deep & Dubby") |
| `description` | Text, not null | User's original free-text description |
| `parsed_criteria` | Text (JSON) | Claude's structured interpretation (mood, energy_min, energy_max, bpm_min, bpm_max, genres, keywords) |
| `auto_refresh` | Boolean, default False | Whether to automatically re-run assignment on newly ingested tracks |
| `created_at` | DateTime | Creation timestamp |
| `updated_at` | DateTime | Last modified timestamp |

**CrateTrack association table (`backend/models/crate.py`):**

| Column | Type | Purpose |
|---|---|---|
| `id` | Integer, PK | Row ID |
| `crate_id` | Integer, FK → crates.id | Crate reference |
| `track_id` | Integer, FK → tracks.id | Track reference |
| `assignment_method` | String | "ai" or "manual" — how the track was added |
| `created_at` | DateTime | When the assignment was made |

UniqueConstraint on `(crate_id, track_id)` to prevent duplicates.

**Parsed criteria JSON schema:**
```json
{
  "mood": ["hypnotic", "warm", "deep"],
  "energy_min": 3,
  "energy_max": 6,
  "bpm_min": 118,
  "bpm_max": 124,
  "genres": ["Deep House", "Minimal House", "Dub Techno"],
  "keywords": ["dubby", "minimal"],
  "exclude_genres": [],
  "notes": "Claude's reasoning about what the user is looking for"
}
```

All fields are optional — Claude fills in what it can infer from the description. Fields left null mean "no constraint on this dimension."

### 2. Key Compatibility Utility (`backend/services/key_compatibility.py`)

Standalone Camelot wheel logic. Pure math — TDD candidate.

**Functions:**
- `are_keys_compatible(key_a: int, key_b: int) -> bool` — True if keys are harmonic neighbours
- `get_compatible_keys(key: int) -> list[int]` — returns all compatible keys for a given key
- `get_compatibility_type(key_a: int, key_b: int) -> str | None` — returns the type of compatibility ("same", "adjacent", "relative_major_minor", "energy_boost", "energy_drop") or None if incompatible

**Camelot wheel compatibility rules:**
- **Same key** — identical (e.g. 8A → 8A)
- **Adjacent** — ±1 on the wheel, same letter (e.g. 8A → 7A, 8A → 9A)
- **Relative major/minor** — same number, different letter (e.g. 8A → 8B)
- **Energy boost** — +1 number and switch letter (e.g. 8A → 9B) — increases energy
- **Energy drop** — -1 number and switch letter (e.g. 8A → 7B) — decreases energy

The wheel wraps: 12A → 1A is adjacent, 12B → 1B is adjacent.

Built in Phase 5a because it's small, self-contained, and the test infrastructure is worth having before 5b needs it.

### 3. Crate Prompt Builder (`backend/services/crate_prompt_builder.py`)

Constructs prompts for two Claude operations: (a) interpreting a crate description into structured criteria, and (b) assigning tracks to a crate.

**Prompt A — Description interpretation:**
- Input: user's free-text description
- Output: structured JSON matching the `parsed_criteria` schema above
- Tool use schema for structured output (same pattern as Phase 3's AI tagger)
- Claude extracts mood keywords, energy range, BPM range, genre matches, and any exclusions

**Prompt B — Track assignment:**
- Input: parsed criteria + list of track summaries (same format as Phase 3's `build_track_summary()`)
- Output: list of track IDs that match the crate's vibe
- Batched: for large libraries, tracks are sent in batches (reuse Phase 3's batching pattern)
- Claude sees both the original description and the parsed criteria for context
- Tool use schema returns `{ "matching_track_ids": [1, 5, 12, ...], "reasoning": "..." }`

**TDD targets:**
- `build_criteria_prompt()` — prompt construction
- `parse_criteria_result()` — JSON validation, field extraction, range clamping
- `build_assignment_prompt()` — batch track summary + criteria
- `parse_assignment_result()` — track ID list validation
- `build_track_summary_for_crate()` — track metadata summary (may reuse or wrap Phase 3's `build_track_summary()`)

### 4. Crate Assigner (`backend/services/crate_assigner.py`)

Orchestrates the assignment pipeline: load tracks, batch them, send to Claude, store results.

**Pipeline:**
1. Load all tracks (or unassigned tracks for a refresh) from DB
2. Build track summaries in batches
3. For each batch, call Claude with the assignment prompt
4. Collect matching track IDs from all batches
5. Create CrateTrack records for each match (assignment_method = "ai")
6. Return assignment result (total matched, total processed)

**Refresh behaviour:**
- Manual refresh: clear existing AI assignments, re-run on all tracks
- Auto-refresh (on new ingestion): run only on tracks not already in the crate

Reuses `ClaudeClient` from Phase 3 for API calls.

### 5. Crate Manager (`backend/services/crate_manager.py`)

High-level operations — CRUD plus orchestration. This is the service layer that routes call.

**Functions:**
- `create_crate(name, description, db_session, settings)` → calls Claude to parse description, creates Crate record, triggers initial assignment
- `get_crate(crate_id, db_session)` → crate with track list
- `list_crates(db_session)` → all crates with track counts
- `update_crate(crate_id, name, description, db_session, settings)` → if description changed, re-parse and re-assign
- `delete_crate(crate_id, db_session)` → delete crate and all CrateTrack records
- `refresh_crate(crate_id, db_session, settings)` → re-run assignment
- `add_tracks(crate_id, track_ids, db_session)` → manual add (assignment_method = "manual")
- `remove_tracks(crate_id, track_ids, db_session)` → remove specific tracks
- `auto_refresh_crates(track_ids, db_session, settings)` → for newly ingested tracks, run assignment against all auto-refresh crates

### 6. API Routes (`backend/routes/crates.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/crates` | Create a crate (name + description) |
| GET | `/api/crates` | List all crates with track counts |
| GET | `/api/crates/{id}` | Get crate detail with track list |
| PUT | `/api/crates/{id}` | Update crate (name, description, auto_refresh) |
| DELETE | `/api/crates/{id}` | Delete crate |
| POST | `/api/crates/{id}/refresh` | Re-run assignment for this crate |
| POST | `/api/crates/{id}/tracks` | Manually add tracks |
| DELETE | `/api/crates/{id}/tracks` | Remove tracks |
| GET | `/api/crates/{id}/progress` | SSE progress for assignment (large libraries) |

**Request/response patterns follow existing conventions** (Pydantic models, consistent error format).

SSE progress is included for the assignment step — unlike Phase 4's sub-second export, crate assignment involves Claude API calls that take time for large libraries. Reuse the SSE pattern from Phase 2/3.

### 7. XML Export Integration

Extend `xml_builder.py:build_playlists()` to include crate playlists alongside the existing folder-based playlists.

**Playlist tree structure:**
```xml
<NODE Type="0" Name="ROOT" Count="1">
  <NODE Type="0" Name="rekordbot" Count="N">
    <NODE Name="All Tracks" Type="1" ... />
    <!-- existing folder-based playlists -->
    <NODE Name="Calibre" Type="1" ... />
    <NODE Name="Depeche Mode" Type="1" ... />
    <!-- crate playlists -->
    <NODE Name="Deep & Dubby" Type="1" ... />
    <NODE Name="Peak Time House" Type="1" ... />
  </NODE>
</NODE>
```

Crate playlists appear after the folder-based playlists, sorted alphabetically. Each crate playlist contains TRACK references using the same `KeyType="0"` pattern.

The `export_library()` function in `xml_exporter.py` needs to load crates from the database and pass them to the builder.

### 8. Frontend

**CrateSidebar.tsx** — Rekordbox-style playlist tree in a collapsible left panel.
- Tree structure: "Crates" folder → individual crate nodes
- Each node shows name and track count
- Click a crate to filter the TrackTable to show only that crate's tracks
- "New Crate" button opens creation dialog
- Right-click context menu: rename, refresh, delete, toggle auto-refresh

**CrateCreateDialog.tsx** — Modal/panel for creating a new crate.
- Name field (required)
- Description textarea (required) — free-text, can be multiple sentences
- Auto-refresh toggle (default off)
- "Create" triggers Claude interpretation + assignment
- Shows progress during assignment

**TrackTable integration:**
- When a crate is selected in the sidebar, table filters to show only that crate's tracks
- "Add to Crate" action available from track context menu or multi-select
- "Remove from Crate" action when viewing a crate's tracks

**API client extension:**
- Types: `Crate`, `CrateDetail`, `CrateCreateRequest`, `CrateUpdateRequest`, `CrateAssignmentProgress`
- Functions: `createCrate()`, `listCrates()`, `getCrate()`, `updateCrate()`, `deleteCrate()`, `refreshCrate()`, `addTracksToCrate()`, `removeTracksFromCrate()`
- SSE consumer for assignment progress

---

## Acceptance Criteria

### Data model
- [ ] Crate table created with all columns
- [ ] CrateTrack association table with unique constraint on (crate_id, track_id)
- [ ] Crate deletion cascades to CrateTrack records
- [ ] Track deletion cascades to CrateTrack records

### Key compatibility
- [ ] `are_keys_compatible()` correct for all compatibility types (same, adjacent, relative, energy boost/drop)
- [ ] Wheel wrapping works (12 → 1 is adjacent)
- [ ] `get_compatible_keys()` returns correct count (typically 5 compatible keys per input)
- [ ] Invalid key inputs handled gracefully

### Crate creation
- [ ] User provides name + free-text description
- [ ] Claude interprets description into structured criteria (mood, energy, BPM, genre)
- [ ] Both original description and parsed criteria stored in DB
- [ ] Parsed criteria JSON conforms to schema

### Track assignment
- [ ] Claude assigns matching tracks based on parsed criteria
- [ ] All matching tracks included (crates are pools, not curated lists)
- [ ] Overlapping assignment works (track in multiple crates)
- [ ] Assignment method recorded ("ai" vs "manual")
- [ ] Large libraries handled via batching with SSE progress

### Crate management
- [ ] List crates with track counts
- [ ] View crate detail with full track list
- [ ] Update name — no re-assignment
- [ ] Update description — triggers re-parse and re-assignment
- [ ] Delete crate — cascades to CrateTrack records
- [ ] Manual add/remove tracks
- [ ] Refresh crate — re-runs assignment, preserves manual additions

### Auto-refresh
- [ ] Crates with auto_refresh=True pick up newly ingested tracks
- [ ] Auto-refresh triggered after ingestion pipeline completes (hook into existing flow)
- [ ] Manual additions preserved during auto-refresh

### XML export
- [ ] Crate playlists appear in exported Rekordbox XML
- [ ] Crate playlists coexist with folder-based playlists
- [ ] Track references use correct TrackIDs (consistent with COLLECTION)
- [ ] Entries count accurate

### UI
- [ ] Sidebar shows crate tree with track counts
- [ ] Click crate filters TrackTable
- [ ] Create dialog accepts name + description
- [ ] Assignment progress shown during creation
- [ ] Right-click menu: rename, refresh, delete, toggle auto-refresh
- [ ] Manual add/remove from TrackTable context

---

## Out of Scope

- **Set planning / sequencing** — Phase 5b. Crates are unordered pools.
- **Drag-and-drop reordering within a crate** — crates are unordered. Ordering is a set planner concern.
- **Crate merging** — combine two crates into one. Can be added later.
- **Filter-based crates** (without Claude) — "all tracks where BPM > 120". Possible future feature but not the core concept here.
- **Crate folders / hierarchy** — all crates are flat, no nesting. Rekordbox supports nested folders but it adds complexity for little benefit at this stage.
- **Smart re-assignment when track metadata changes** — if a track's genre is edited after crate assignment, the crate doesn't auto-update. User can refresh manually.
- **Crate import from Rekordbox XML** — Phase 4b scope.
- **Album art / visual crate thumbnails** — deferred.

---

## Dependencies

- **Phase 3 infrastructure** — `ClaudeClient` for API calls, rate limiting, token tracking. `prompt_builder.py` patterns for tool use and batch processing.
- **Phase 4 infrastructure** — `xml_builder.py` for playlist generation (extended, not replaced).
- **No new Python packages** — all functionality uses existing deps (anthropic SDK, SQLAlchemy, xml.etree.ElementTree).

---

## DB Schema Changes

### New models

**Crate** — `backend/models/crate.py`
- id, name, description, parsed_criteria (JSON text), auto_refresh, created_at, updated_at

**CrateTrack** — `backend/models/crate.py` (same file)
- id, crate_id (FK), track_id (FK), assignment_method, created_at
- UniqueConstraint on (crate_id, track_id)

### Settings additions

| Setting | Type | Default | Purpose |
|---|---|---|---|
| `crate_assignment_batch_size` | int | 30 | Tracks per Claude API call during assignment |

### Exceptions

- `CrateError(RekordBotError)` — raised on crate operation failures

---

## Decisions (Finalised)

| # | Decision | Resolution |
|---|---|---|
| 1 | Track assignment overlap | Overlapping — a track can be in any number of crates. |
| 2 | Crate as pool vs curated list | Pool — Claude assigns every matching track, not a curated subset. User draws from the pool during set planning. |
| 3 | Parsed criteria storage | Store both original description and Claude's JSON interpretation. Enables re-running assignment without re-prompting. |
| 4 | Refresh modes | Manual ("refresh this crate") and automatic (auto_refresh flag, triggered after ingestion). Both available. |
| 5 | Manual additions during refresh | Preserved. Only AI assignments are cleared and re-run. Manual adds (assignment_method = "manual") are kept. |
| 6 | XML export integration | Crate playlists appear alongside folder-based playlists under the rekordbot folder. Not in a separate subfolder. |
| 7 | SSE for assignment | Yes — crate assignment involves Claude API calls that take time for large libraries. Reuse Phase 2/3 SSE patterns. |
| 8 | Key compatibility module placement | Built in Phase 5a as standalone utility. Used by 5b for sequencing, available for future UI features. |
| 9 | Sidebar style | Rekordbox playlist tree style — familiar to the target user. |
| 10 | Description update triggers re-assignment | Yes. Changing the description re-parses criteria and re-assigns all tracks (preserving manual additions). Changing only the name does not trigger re-assignment. |

---

## TDD Candidates

| Function | Location | Why TDD |
|---|---|---|
| `are_keys_compatible()` | `key_compatibility.py` | Fixed truth table. All compatibility types testable. Highest-value TDD target — used by 5b. |
| `get_compatible_keys()` | `key_compatibility.py` | Derived from compatibility rules. Test all 24 keys. |
| `get_compatibility_type()` | `key_compatibility.py` | Returns type string. Test all cases including wrap-around. |
| `build_criteria_prompt()` | `crate_prompt_builder.py` | Prompt construction. Verify key sections present. |
| `parse_criteria_result()` | `crate_prompt_builder.py` | JSON → CrateCriteria. Valid input, missing fields, range clamping, invalid types. |
| `build_assignment_prompt()` | `crate_prompt_builder.py` | Batch construction with criteria. |
| `parse_assignment_result()` | `crate_prompt_builder.py` | Track ID list validation. Duplicate removal, invalid IDs. |

**Write tests after implementation** (framework integration, I/O-dependent):
- Claude client calls (mock the SDK)
- Crate assigner pipeline orchestration
- Crate manager CRUD operations
- API route handlers
- SSE progress streaming
- XML export integration
- Frontend components

---

## Commit Breakdown

### Commit 1: Dependencies, config, and exceptions
- Add `crate_assignment_batch_size` to Settings in config.py
- Add `CrateError` to exceptions.py
- Commit: "Add Phase 5a configuration and exception types"

### Commit 2: Data models
- Create `backend/models/crate.py` with Crate and CrateTrack models
- Update `backend/models/__init__.py`
- Update `database.py:init_db()` to import new models
- Add model tests
- Commit: "Add Crate and CrateTrack models with many-to-many association"

### Commit 3: Key compatibility module (TDD)
- Create `backend/services/key_compatibility.py`
- WRITE TESTS FIRST in `backend/tests/test_key_compatibility.py`:
  - `are_keys_compatible()`: same key, adjacent (both directions), relative major/minor, energy boost/drop, non-compatible, wrap-around (12→1, 1→12)
  - `get_compatible_keys()`: all 24 keys, verify count and specific results
  - `get_compatibility_type()`: all types returned correctly, None for non-compatible
  - Edge cases: invalid key (0, 25, -1), same key
- Then implement
- Pure logic — no I/O, no DB
- Commit: "Add key compatibility module with Camelot wheel logic (TDD)"

### Commit 4: Crate prompt builder (TDD)
- Create `backend/services/crate_prompt_builder.py`
- WRITE TESTS FIRST in `backend/tests/test_crate_prompt_builder.py`:
  - `build_criteria_prompt()`: verify system prompt sections, user description included
  - `parse_criteria_result()`: valid JSON, missing fields, energy clamping (1–10), BPM range validation, empty moods/genres, invalid types
  - `build_assignment_prompt()`: criteria + track summaries, batch sizing
  - `parse_assignment_result()`: valid IDs, duplicates removed, invalid IDs filtered, empty list
- Then implement
- Pure logic — no I/O, no SDK
- Commit: "Add crate prompt builder with description parsing and assignment prompts (TDD)"

### Commit 5: Crate assigner
- Create `backend/services/crate_assigner.py`
- Implement assignment pipeline: load tracks → batch → Claude → store results
- Implement refresh logic (clear AI assignments, preserve manual)
- SSE progress events (crate_assignment_progress, crate_assignment_complete)
- Tests with mocked ClaudeClient
- Commit: "Add crate assigner with batched Claude assignment and SSE progress"

### Commit 6: Crate manager
- Create `backend/services/crate_manager.py`
- Implement all CRUD operations + refresh + auto-refresh
- Tests with mocked assigner and DB
- Commit: "Add crate manager with CRUD, refresh, and auto-refresh support"

### Commit 7: API routes
- Create `backend/routes/crates.py`
- Implement all endpoints from the architecture section
- Register in main.py
- Test all endpoints
- Commit: "Add crate API routes with CRUD, assignment, and progress SSE"

### Commit 8: XML export integration
- Extend `xml_builder.py:build_playlists()` to accept crates and generate crate playlist nodes
- Extend `xml_exporter.py:export_library()` to load crates from DB
- Tests: verify crate playlists appear in XML, track references correct, coexists with folder playlists
- Commit: "Extend XML export with crate playlists"

### Commit 9: Frontend
- Create `CrateSidebar.tsx` — playlist tree with crate list, counts, selection
- Create `CrateCreateDialog.tsx` — name + description input, progress during assignment
- Extend TrackTable: crate filter mode, add/remove from crate actions
- Extend API client with crate types and endpoints
- Commit: "Add crate sidebar, creation dialog, and TrackTable integration"

### Commit 10: Integration tests and cleanup
- End-to-end: create crate → assign tracks → verify → refresh → verify
- Overlapping assignment test (track in multiple crates)
- Manual add/remove preservation during refresh
- Auto-refresh on new ingestion (if hookable without modifying Phase 1 code)
- XML export with crates test
- Update CLAUDE.md with Phase 5a status
- Commit: "Add integration tests and update project docs for Phase 5a"

---

## Claude Code Prompt

The following prompt is designed to be given to Claude Code at the start of the implementation session. Copy it verbatim.

---

```
You are implementing Phase 5a (Crate Builder) of rekordbot.

Read these files first:
- CLAUDE.md (project conventions, architecture, coding standards)
- docs/features/phase-5a-crate-builder.md (the feature brief — this is your specification)
- backend/models/track.py (existing Track model)
- backend/models/preference_rule.py (reference for simple model + association patterns)
- backend/models/database.py (engine, session, Base, init_db)
- backend/config.py (existing Settings — you'll add new config fields)
- backend/exceptions.py (existing exception hierarchy — add CrateError)
- backend/main.py (existing FastAPI app — you'll register new routes)
- backend/services/claude_client.py (Phase 3 Claude client — you'll reuse this)
- backend/services/prompt_builder.py (Phase 3 prompt builder — reference for tool use patterns and build_track_summary)
- backend/services/ai_tagger.py (Phase 3 pipeline — reference for batch + SSE pattern)
- backend/services/key_notation.py (Phase 2 key notation — the key compatibility module builds on this)
- backend/services/xml_builder.py (Phase 4 XML builder — you'll extend build_playlists)
- backend/services/xml_exporter.py (Phase 4 export service — you'll extend export_library)
- backend/routes/organise.py (Phase 2b routes — reference for route patterns)
- frontend/src/api/client.ts (existing API client — you'll extend with crate endpoints)

## What you're building

An AI-powered crate system that:
1. Lets users create crates by describing a vibe in free text
2. Uses Claude to interpret descriptions into structured criteria (mood, energy, BPM, genre)
3. Uses Claude to assign every matching track from the library to the crate
4. Supports overlapping assignment (track in multiple crates)
5. Supports manual add/remove and refresh (manual + auto)
6. Includes a standalone key compatibility module (Camelot wheel math)
7. Exports crate playlists in the Rekordbox XML alongside folder-based playlists
8. Provides a Rekordbox-style sidebar UI for browsing crates

This feature reuses Phase 3's ClaudeClient for API calls. Do not create a new Claude client.

## Build order (follow this exactly)

### Step 1: Dependencies and config
- Add to Settings: crate_assignment_batch_size: int = 30
- Add CrateError to exceptions.py
- Commit: "Add Phase 5a configuration and exception types"

### Step 2: Data models
- Create backend/models/crate.py with Crate and CrateTrack models
- Crate: id, name, description, parsed_criteria (Text/JSON), auto_refresh (Boolean), created_at, updated_at
- CrateTrack: id, crate_id (FK), track_id (FK), assignment_method (String), created_at
- UniqueConstraint on (crate_id, track_id)
- Update database.py init_db() to import new models
- Commit: "Add Crate and CrateTrack models with many-to-many association"

### Step 3: Key compatibility module (TDD)
- Create backend/services/key_compatibility.py
- WRITE TESTS FIRST:
  - are_keys_compatible(): same key, adjacent both directions, relative major/minor, energy boost/drop, non-compatible, wrap-around 12↔1
  - get_compatible_keys(): all 24 keys, verify count and members
  - get_compatibility_type(): all type strings, None for non-compatible
  - Edge cases: invalid key values
- Then implement. Pure logic — no I/O, no DB.
- Commit: "Add key compatibility module with Camelot wheel logic (TDD)"

### Step 4: Crate prompt builder (TDD)
- Create backend/services/crate_prompt_builder.py
- WRITE TESTS FIRST:
  - build_criteria_prompt(): prompt construction, description included
  - parse_criteria_result(): valid JSON, missing fields, range clamping, invalid types
  - build_assignment_prompt(): criteria + track summaries
  - parse_assignment_result(): valid IDs, duplicates, invalid IDs, empty
- Then implement. Pure logic — no I/O, no SDK.
- Commit: "Add crate prompt builder with description parsing and assignment prompts (TDD)"

### Step 5: Crate assigner
- Create backend/services/crate_assigner.py
- Assignment pipeline: load → batch → Claude → store
- Refresh: clear AI assignments, preserve manual
- SSE progress events
- Tests with mocked ClaudeClient
- Commit: "Add crate assigner with batched Claude assignment and SSE progress"

### Step 6: Crate manager
- Create backend/services/crate_manager.py
- CRUD + refresh + auto-refresh orchestration
- Tests with mocked dependencies
- Commit: "Add crate manager with CRUD, refresh, and auto-refresh support"

### Step 7: API routes
- Create backend/routes/crates.py
- POST /api/crates, GET /api/crates, GET /api/crates/{id}, PUT /api/crates/{id}, DELETE /api/crates/{id}
- POST /api/crates/{id}/refresh, POST /api/crates/{id}/tracks, DELETE /api/crates/{id}/tracks
- GET /api/crates/{id}/progress (SSE)
- Register in main.py
- Test all endpoints
- Commit: "Add crate API routes with CRUD, assignment, and progress SSE"

### Step 8: XML export integration
- Extend xml_builder.py build_playlists() to include crate playlists
- Extend xml_exporter.py export_library() to load crates
- Tests: crate playlists in XML, correct track refs, coexistence with folder playlists
- Commit: "Extend XML export with crate playlists"

### Step 9: Frontend
- Create CrateSidebar.tsx — playlist tree, counts, selection
- Create CrateCreateDialog.tsx — name + description, progress
- Extend TrackTable: crate filter, add/remove actions
- Extend API client with crate types and endpoints
- Commit: "Add crate sidebar, creation dialog, and TrackTable integration"

### Step 10: Integration tests and cleanup
- End-to-end: create → assign → refresh → verify
- Overlapping assignment, manual preservation, XML with crates
- Update CLAUDE.md
- Commit: "Add integration tests and update project docs for Phase 5a"

## Constraints
- Follow all conventions in CLAUDE.md
- Reuse ClaudeClient from Phase 3 — do NOT create a new Claude client
- Reuse prompt_builder.py patterns for tool use and track summaries
- Reuse SSE patterns from Phase 2/3 for assignment progress
- Claude API calls via asyncio.to_thread()
- Do NOT modify Phase 1/2/2b/3 service code (except extending xml_builder and xml_exporter)
- All exceptions should be RekordBotError subclasses
- Every service module gets its own logger via logging.getLogger(__name__)
- Use %s string formatting in log calls (not f-strings)
- Use sync SQLAlchemy (not async)

## Important
- Do NOT implement set planning / sequencing — that's Phase 5b
- Do NOT implement drag-and-drop reordering within crates — crates are unordered
- Do NOT implement filter-based crates (without Claude)
- Do NOT implement crate folders / hierarchy — all crates are flat
- Crates are POOLS — include every matching track, not a curated subset
- Track assignment is OVERLAPPING — a track can be in any number of crates
- Manual additions MUST be preserved during refresh
```

### Continuation Prompt

If the session is interrupted and you need to resume in a new Claude Code session, use this:

```
We are continuing Phase 5a (Crate Builder) of rekordbot.

Read these files for context:
- CLAUDE.md (project conventions and current status)
- SESSIONS.md (latest entry has where we left off and what's next)
- docs/features/phase-5a-crate-builder.md (the feature specification)

Pick up from where we left off. Check SESSIONS.md for the last completed step
and what was identified as the next task. Confirm what you think the next step
is before writing any code.
```

---

## Notes

- The Crate model's `parsed_criteria` is stored as a JSON string in a Text column, not as a structured SQLAlchemy JSON type. This keeps things simple and consistent with the rest of the codebase (no JSON column type dependency). Parse with `json.loads()` / `json.dumps()` in the service layer.
- The `build_track_summary()` function from Phase 3's `prompt_builder.py` generates track metadata summaries for Claude. The crate prompt builder should reuse or wrap this rather than duplicating it.
- Auto-refresh after ingestion requires hooking into the ingestion pipeline's completion event. The cleanest approach is to have the ingest route handler call `crate_manager.auto_refresh_crates()` after the queue finishes, passing the newly created track IDs. This is a small addition to `routes/ingest.py` — it's acceptable because it's calling Phase 5a's service layer, not modifying Phase 1's service code.
- The XML export integration is a targeted extension: `build_playlists()` gains an optional `crates` parameter, and `export_library()` loads crates from the DB and passes them through. The existing folder-based playlists are untouched.
- The sidebar panel is new UI chrome that doesn't exist yet — App.tsx (or wherever the layout lives) will need a layout change to accommodate a sidebar alongside the main content area. This may require a CSS/layout refactor. Worth checking the current layout structure before starting the frontend commit.
