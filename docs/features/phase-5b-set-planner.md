# Feature: Set Planner
**Branch:** `feature/phase-5b-set-planner`
**Status:** Complete ✅
**Phase:** 5b
**Depends on:** Phase 5a (complete)

---

## Goal

Allow the user to describe a DJ set with a time dimension, energy arc, and mood — then have Claude suggest an ordered track sequence drawn from crates or the full library. The user iteratively refines the set by locking anchor tracks in place and shuffling unlocked slots, with the ability to change the mood description for different segments of the set between shuffle passes.

This is the creative culmination of the app: crates provide the *pools*, the set planner provides the *sequence*.

---

## Inputs

- All tracks in the database with metadata from Phases 1–3 (title, artist, genre, subgenre, BPM, key, mood, energy, AI confidence)
- Crates from Phase 5a (optional — user can source from specific crates or the full library)
- Key compatibility module from Phase 5a (optional harmonic mixing)
- User-provided set description (duration, energy arc, mood, destination BPM, source selection)
- Existing Claude client infrastructure from Phase 3

## Outputs

- Set records in the database with description, parameters, and track sequence
- Ordered track lists with position, lock state, and segment assignments
- Exportable Rekordbox playlists (ordered, preserving sequence)
- Set planner UI with lock/unlock, segment editing, shuffle controls, and key compatibility indicators

---

## Core Concepts

### Sets are ordered sequences, not pools
Unlike crates (unordered pools), a set is an ordered sequence of tracks intended for playback in a specific order. Position matters. The user is building a DJ set with transitions, energy flow, and harmonic progression in mind.

### The 2–3x track multiplier
When Claude suggests tracks for a set, it should suggest 2–3x more tracks than the set needs. This gives the user a deep bench to swap from during refinement. For a 1-hour set at ~7 min/track (~9 tracks), Claude might suggest 20–25 candidates. The initial sequence uses the best-fit tracks; the extras are available as replacements during shuffle.

### Lock-and-shuffle is the core interaction pattern
1. Claude suggests an initial sequence
2. User reviews, locks tracks they want to keep in place
3. User triggers a shuffle — Claude replaces or reorders the unlocked slots
4. Repeat until satisfied

### Segmented mood descriptions
Locked tracks act as segment boundaries. Between any two locked tracks (or between a locked track and the start/end of the set), the user can write a different mood description. On the next shuffle, Claude fills each gap according to its local description.

Example: A 1-hour set where the user locks track #3 and track #7:
- Segment A (tracks 1–3): "Ambient and meditative, slowly building"
- Segment B (tracks 4–7): "Dark and aggressive minimal techno"
- Segment C (tracks 8–end): "Uplifting resolution, euphoric energy"

Each segment gets its own mood brief. Claude respects the locked anchors and fills the gaps to match each segment's description.

### Two shuffle modes
- **Replace** — swap unlocked tracks for different ones from the candidate pool (or the full source). New tracks that better match the segment description and surrounding context.
- **Reorder** — keep the same tracks but optimise their sequence for better BPM progression, key compatibility, and energy flow. No new tracks added.

---

## Architecture & Key Components

### 1. Data Model

**Set table (`backend/models/set_plan.py`):**

| Column | Type | Purpose |
|---|---|---|
| `id` | Integer, PK | Internal ID |
| `name` | String, not null | Display name (e.g. "Friday Warm-Up") |
| `description` | Text, not null | User's overall set description |
| `duration_minutes` | Integer, nullable | Target set length |
| `target_bpm_start` | Float, nullable | Starting BPM target |
| `target_bpm_end` | Float, nullable | Ending BPM target |
| `energy_arc` | String, nullable | Energy shape description (e.g. "build", "peak-valley-peak", "slow-build") |
| `source_type` | String, not null | "crates", "library", or "both" |
| `source_crate_ids` | Text (JSON), nullable | List of crate IDs to source from (when source_type includes crates) |
| `harmonic_mixing` | Boolean, default False | Whether to prefer key-compatible transitions |
| `status` | String, default "draft" | "draft", "planning", "complete" |
| `created_at` | DateTime | Creation timestamp |
| `updated_at` | DateTime | Last modified timestamp |

**SetTrack table (`backend/models/set_plan.py`):**

| Column | Type | Purpose |
|---|---|---|
| `id` | Integer, PK | Row ID |
| `set_id` | Integer, FK → sets.id | Set reference |
| `track_id` | Integer, FK → tracks.id | Track reference |
| `position` | Integer, not null | Order in the set (1-indexed) |
| `is_locked` | Boolean, default False | Whether the user has locked this track in place |
| `is_candidate` | Boolean, default False | True = in the candidate pool but not in the active sequence |
| `segment_id` | Integer, FK → set_segments.id, nullable | Which segment this track belongs to |
| `created_at` | DateTime | When assigned |

UniqueConstraint on `(set_id, track_id)` to prevent duplicate track entries within a set.
UniqueConstraint on `(set_id, position)` where `is_candidate = False` to prevent position collisions in the active sequence.

**SetSegment table (`backend/models/set_plan.py`):**

| Column | Type | Purpose |
|---|---|---|
| `id` | Integer, PK | Row ID |
| `set_id` | Integer, FK → sets.id | Set reference |
| `position` | Integer, not null | Segment order (1-indexed) |
| `description` | Text, nullable | Mood description for this segment (e.g. "Dark and aggressive minimal") |
| `start_track_position` | Integer, not null | First track position in this segment |
| `end_track_position` | Integer, not null | Last track position in this segment |
| `created_at` | DateTime | When created |
| `updated_at` | DateTime | Last modified |

Segments are recalculated whenever tracks are locked/unlocked. Locked tracks define segment boundaries.

### 2. Set Prompt Builder (`backend/services/set_prompt_builder.py`)

Constructs prompts for three Claude operations:

**Prompt A — Initial sequence suggestion:**
- Input: set description, track candidates (summaries from source crates/library), parameters (duration, BPM targets, energy arc)
- Output: ordered list of track IDs for the initial sequence + candidate pool
- Claude considers: BPM progression, energy flow, genre coherence, mood match
- If harmonic_mixing enabled: Claude receives key compatibility data and factors it into ordering
- Tool use schema returns `{ "sequence": [{"track_id": N, "reasoning": "..."}], "candidates": [{"track_id": N, "reasoning": "..."}] }`

**Prompt B — Shuffle (replace mode):**
- Input: current set state (locked tracks with positions, segment descriptions, unlocked slot positions), available tracks (candidates + source pool), parameters
- Output: replacement tracks for unlocked slots, respecting locked anchor context
- Claude sees the full set structure: locked tracks as fixed points, each segment's mood description, and fills gaps accordingly
- Tool use schema returns `{ "replacements": [{"position": N, "track_id": M, "reasoning": "..."}] }`

**Prompt C — Shuffle (reorder mode):**
- Input: current set state (locked tracks, unlocked tracks, segment descriptions)
- Output: reordered positions for unlocked tracks only (no new tracks)
- Claude optimises for BPM flow, key compatibility, and energy arc within segment constraints
- Tool use schema returns `{ "reordered": [{"track_id": N, "new_position": M, "reasoning": "..."}] }`

**TDD targets:**
- `build_initial_prompt()` — prompt construction with all parameters
- `parse_initial_result()` — sequence + candidate list validation, position assignment
- `build_replace_prompt()` — locked tracks, segment descriptions, available tracks
- `parse_replace_result()` — replacement validation, position bounds checking
- `build_reorder_prompt()` — current sequence, locked positions
- `parse_reorder_result()` — position validation, locked tracks unchanged
- `build_track_summary_for_set()` — track metadata + key compatibility info

### 3. Set Planner Service (`backend/services/set_planner.py`)

Orchestrates the planning pipeline. This is the main service layer.

**Functions:**
- `create_set(name, description, params, db_session, settings)` → creates Set record, gathers tracks from source, calls Claude for initial sequence, stores SetTrack records
- `get_set(set_id, db_session)` → full set state (tracks in order, segments, candidates, lock states)
- `list_sets(db_session)` → all sets with track counts and status
- `update_set(set_id, name, description, params, db_session)` → update metadata (does NOT re-plan)
- `delete_set(set_id, db_session)` → cascade delete
- `lock_track(set_id, position, db_session)` → lock track at position, recalculate segments
- `unlock_track(set_id, position, db_session)` → unlock, recalculate segments
- `update_segment_description(segment_id, description, db_session)` → set mood for a segment
- `shuffle_replace(set_id, db_session, settings)` → replace unlocked tracks using Claude, respecting segment descriptions
- `shuffle_reorder(set_id, db_session, settings)` → reorder unlocked tracks for optimal flow
- `remove_track(set_id, position, db_session)` → remove a track from the sequence, reindex positions
- `add_track_at_position(set_id, track_id, position, db_session)` → insert a track, shift others down
- `move_track(set_id, from_position, to_position, db_session)` → manual reorder
- `recalculate_segments(set_id, db_session)` → rebuild segment boundaries from locked track positions
- `get_candidates(set_id, db_session)` → return the candidate pool for manual browsing

**Segment recalculation logic:**
When tracks are locked/unlocked, segments are rebuilt:
1. Find all locked track positions, sorted
2. Segment 1: position 1 → first locked position (or end if no locks)
3. Subsequent segments: after each locked position → next locked position (or end)
4. Preserve existing segment descriptions where segment boundaries haven't changed
5. New segments get null description (user fills in before next shuffle)

### 4. BPM Transition Scorer (`backend/services/bpm_transition.py`)

Pure utility for evaluating BPM progressions. Used by the prompt builder to give Claude context, and potentially by the UI for transition quality indicators.

**Functions:**
- `score_bpm_transition(bpm_a: float, bpm_b: float) -> float` — returns 0.0–1.0 score (1.0 = perfect, 0.0 = jarring). Smooth transitions score higher; large jumps score lower.
- `get_transition_quality(bpm_a: float, bpm_b: float) -> str` — returns "smooth", "acceptable", "noticeable", "jarring" based on the delta
- `suggest_bpm_range(sequence_bpms: list[float], target_bpm: float | None, position: int) -> tuple[float, float]` — given current sequence BPMs and a target, suggest an ideal BPM range for a given slot

**Transition scoring rules:**
- ±0 BPM: 1.0 (same tempo)
- ±1–2 BPM: 0.95 (imperceptible)
- ±3–5 BPM: 0.8 (smooth, common DJ technique)
- ±6–10 BPM: 0.5 (noticeable, needs mixing skill)
- ±11–20 BPM: 0.2 (significant jump, transition track territory)
- >20 BPM: 0.0 (genre change, needs a deliberate break)

This is a TDD candidate — pure math, fixed scoring table.

### 5. API Routes (`backend/routes/sets.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/sets` | Create a set (name, description, parameters) |
| GET | `/api/sets` | List all sets with track counts and status |
| GET | `/api/sets/{id}` | Get set detail: tracks in order, segments, candidates, lock states |
| PUT | `/api/sets/{id}` | Update set metadata |
| DELETE | `/api/sets/{id}` | Delete set |
| POST | `/api/sets/{id}/lock/{position}` | Lock track at position |
| POST | `/api/sets/{id}/unlock/{position}` | Unlock track at position |
| PUT | `/api/sets/{id}/segments/{segment_id}` | Update segment description |
| POST | `/api/sets/{id}/shuffle` | Shuffle unlocked tracks (body: `{"mode": "replace" \| "reorder"}`) |
| POST | `/api/sets/{id}/tracks` | Add track at position (body: `{"track_id": N, "position": M}`) |
| DELETE | `/api/sets/{id}/tracks/{position}` | Remove track at position |
| POST | `/api/sets/{id}/tracks/move` | Move track (body: `{"from_position": N, "to_position": M}`) |
| GET | `/api/sets/{id}/candidates` | Get candidate pool |
| POST | `/api/sets/{id}/export` | Export set as Rekordbox playlist |
| GET | `/api/sets/{id}/progress` | SSE progress for Claude operations |

**Request/response patterns follow existing conventions** (Pydantic models, consistent error format).

SSE progress is included for shuffle and initial creation — these involve Claude API calls.

### 6. XML Export Integration

Extend the existing XML export to include set playlists. Sets are exported as ordered playlists (track order preserved, unlike crate playlists which are unordered pools).

**Two export modes:**
- **Per-set export** — `POST /api/sets/{id}/export` exports a single set as a standalone playlist XML, or adds it to the main rekordbot XML
- **Full export** — the existing `POST /api/export/rekordbox` includes set playlists alongside folder-based and crate playlists

**Playlist tree structure:**
```xml
<NODE Type="0" Name="ROOT" Count="1">
  <NODE Type="0" Name="rekordbot" Count="N">
    <NODE Name="All Tracks" Type="1" ... />
    <!-- folder-based playlists -->
    <NODE Name="Calibre" Type="1" ... />
    <!-- crate playlists -->
    <NODE Name="Deep & Dubby" Type="1" ... />
    <!-- set playlists -->
    <NODE Name="Friday Warm-Up" Type="1" ... />
  </NODE>
</NODE>
```

Set playlists appear after crate playlists, sorted alphabetically. Track order in the XML matches set position order.

### 7. Frontend

**SetPlannerView.tsx** — The main set planning interface. This is a new view/page, not a panel within the existing library view. Navigation between library view and set planner view via tabs or sidebar.

Layout:
- **Header:** Set name, description, duration, status
- **Track sequence:** Vertical list of tracks in order. Each row shows:
  - Position number
  - Lock/unlock toggle (padlock icon)
  - Track info (title, artist, BPM, key, energy, mood)
  - Key compatibility indicator with adjacent tracks (green = compatible, amber = neutral, red = clash)
  - BPM transition indicator (smooth/acceptable/noticeable/jarring)
  - Remove button
- **Segment dividers:** Visual separators between segments, showing:
  - Segment description (editable inline text field)
  - "Set description for this section" placeholder when empty
- **Candidate pool panel:** Collapsible side panel showing unused candidates for manual drag-in or click-to-add
- **Controls toolbar:**
  - "Shuffle: Replace" button — replaces unlocked tracks
  - "Shuffle: Reorder" button — reorders unlocked tracks
  - Progress indicator during Claude operations
  - "Export to Rekordbox" button
  - Set settings (harmonic mixing toggle, source crates selection)

**SetCreateDialog.tsx** — Modal for creating a new set.
- Name field (required)
- Description textarea (required) — overall set description
- Duration (minutes, optional)
- Target BPM start/end (optional)
- Energy arc selector (predefined options: "slow build", "peak-valley-peak", "constant high", "wind down", custom text)
- Source: "All library" / "From crates" (multi-select crate picker)
- Harmonic mixing toggle
- "Create" triggers Claude planning + initial sequence

**SetListPanel.tsx** — List of existing sets, accessible from sidebar or a dedicated view.
- Set name, description preview, track count, status
- Click to open in SetPlannerView
- Delete, duplicate actions

**API client extension:**
- Types: `SetPlan`, `SetPlanDetail`, `SetTrack`, `SetSegment`, `SetCreateRequest`, `SetUpdateRequest`, `ShuffleRequest`, `ShuffleMode`
- Functions: `createSet()`, `listSets()`, `getSet()`, `updateSet()`, `deleteSet()`, `lockTrack()`, `unlockTrack()`, `updateSegment()`, `shuffleSet()`, `addTrackToSet()`, `removeTrackFromSet()`, `moveTrackInSet()`, `getCandidates()`, `exportSet()`
- SSE consumer for planning/shuffle progress

---

## Decisions to Finalise

These need to be agreed before implementation begins:

| # | Question | Options | Recommendation |
|---|---|---|---|
| 1 | How are tracks estimated per set duration? | A) Fixed average (e.g. 7 min/track). B) Calculate from actual BPMs in source pool (higher BPM → shorter perceived tracks). C) User specifies track count directly. | **A** — Fixed 7 min/track default is good enough. User can override by adding/removing tracks manually. Claude's initial suggestion uses this to determine sequence length. |
| 2 | What happens to candidates when a crate is refreshed? | A) Candidate pool is static (snapshot at set creation). B) Candidates refresh when source crates refresh. C) Manual "refresh candidates" action. | **C** — Manual refresh. Automatic would be confusing if a set you're working on suddenly gains new candidates. The user triggers it when ready. |
| 3 | Can a track appear in the sequence and the candidate pool simultaneously? | A) No — once in sequence, removed from candidates. B) Yes — candidates are just a suggestion list. | **A** — Clean separation. When a track moves from candidate to sequence (or vice versa), it moves, not copies. The `is_candidate` flag handles this. |
| 4 | Should segments auto-recalculate on every lock/unlock? | A) Yes, always. B) Only on explicit user action. | **A** — Always. Segments are a derived structure from lock positions. Keeping them in sync automatically prevents stale state. |
| 5 | How is key compatibility surfaced? | A) Just colour indicators on transitions. B) Indicators + Claude factors it into suggestions. C) Indicators + Claude + optional "optimise for harmonic mixing" mode. | **C** — The `harmonic_mixing` flag controls Claude's behaviour. Indicators always shown. |
| 6 | What's the maximum set size? | A) No limit. B) Soft limit with warning (e.g. 50 tracks). C) Hard limit. | **B** — Soft limit of 50 tracks with a warning. Beyond that, Claude's context window and prompt size become a concern. |
| 7 | Should shuffle be cancelable? | A) Yes (same pattern as Phase 3/5a). B) No (shuffles are fast). | **A** — Yes. Claude calls take time, especially for large sets. Reuse the cancellation pattern. |
| 8 | Colour scheme for set planner UI elements? | A) New colour. B) Reuse existing. | **A** — Rose/pink for set planner buttons. Visually distinct from blue (analysis), purple (AI tag), emerald (organise), amber (export), and whatever colour crates use. |
| 9 | Navigation: how does the user get to the set planner? | A) Tab in the main view. B) Button that opens a new view. C) Sidebar navigation. | **C** — Sidebar already exists from Phase 5a for crates. Add a "Sets" section below crates. Click a set to open it in the main content area (replacing the track table). |
| 10 | Should the export include transition notes? | A) Just the playlist. B) Playlist + a text summary with transition notes. | **A** — Just the playlist for now. Transition notes can be a Phase 6 polish item. |

---

## Acceptance Criteria

### Data model
- [ ] Set table created with all columns
- [ ] SetTrack table with unique constraints on (set_id, track_id) and (set_id, position) for active tracks
- [ ] SetSegment table with set reference and position
- [ ] Set deletion cascades to SetTrack and SetSegment records
- [ ] Track deletion removes SetTrack records (doesn't delete the set)

### Set creation
- [ ] User provides name, description, and optional parameters (duration, BPM targets, energy arc, source, harmonic mixing)
- [ ] Claude suggests initial sequence + candidate pool based on description
- [ ] Source filtering works: from specific crates, from full library, or both
- [ ] Sequence length derived from duration / 7 min per track (or full library if no duration specified)
- [ ] 2–3x candidate multiplier — more tracks suggested than needed

### Lock and unlock
- [ ] Lock/unlock toggle on each track in the sequence
- [ ] Locked tracks stay in place during shuffle
- [ ] Segments recalculated on lock/unlock
- [ ] Existing segment descriptions preserved when boundaries haven't changed

### Segment descriptions
- [ ] Segments auto-created between locked tracks
- [ ] User can edit segment description inline
- [ ] Segment description passed to Claude during shuffle
- [ ] Empty segment description means "use overall set description"

### Shuffle — replace mode
- [ ] Unlocked tracks replaced with alternatives from candidate pool / source
- [ ] Locked tracks unchanged
- [ ] Each segment filled according to its mood description
- [ ] BPM progression considered (smooth transitions preferred)
- [ ] Key compatibility considered when harmonic_mixing enabled
- [ ] SSE progress during Claude calls

### Shuffle — reorder mode
- [ ] Unlocked tracks reordered for optimal flow
- [ ] No new tracks introduced
- [ ] Locked tracks stay in their positions
- [ ] Reorder considers BPM, key, energy within segments

### Manual editing
- [ ] Add track at specific position (from candidates or search)
- [ ] Remove track from sequence (returns to candidates)
- [ ] Move track to different position (reindex)

### BPM transitions
- [ ] Transition score calculated between adjacent tracks
- [ ] Transition quality displayed in UI (smooth/acceptable/noticeable/jarring)
- [ ] Scoring follows defined rules (±0–2 smooth, ±3–5 acceptable, etc.)

### Key compatibility
- [ ] Key compatibility indicator between adjacent tracks in sequence
- [ ] Uses Phase 5a key_compatibility module
- [ ] Compatibility type shown (same, adjacent, relative, energy boost/drop, incompatible)

### XML export
- [ ] Set playlists appear in exported Rekordbox XML
- [ ] Track order preserved (position order)
- [ ] Coexists with folder-based and crate playlists
- [ ] Per-set export available

### UI
- [ ] Set planner view with track sequence, segments, candidates
- [ ] Lock/unlock toggle per track
- [ ] Segment dividers with editable descriptions
- [ ] Shuffle controls (replace and reorder)
- [ ] Key compatibility and BPM transition indicators
- [ ] Create dialog with all parameters
- [ ] Set list in sidebar (below crates)
- [ ] Progress indicator during Claude operations

---

## Out of Scope

- **Audio preview / waveform display** — requires audio playback infrastructure not built yet. Phase 6 or later.
- **Automatic mix point detection** — TEMPO/POSITION_MARK data from Rekordbox. Not exported in Phase 4, so not available.
- **Multi-deck set planning** — assumes single-deck linear sequence. B2B or multi-deck planning is a future feature.
- **BPM matching / pitch lock suggestions** — the planner suggests BPM-compatible sequences, but doesn't suggest pitch fader adjustments.
- **Transition type suggestions** — "blend", "cut", "loop transition" etc. are technique decisions the DJ makes in the moment.
- **Undo/redo for shuffle** — each shuffle is a forward operation. The user can shuffle again if unhappy. Full undo history is a Phase 6 polish item.
- **Collaborative set planning** — single user only.
- **Set templates / presets** — "warm-up template", "peak time template". Can be added later.
- **Drag-and-drop reordering in UI** — manual reorder via the `move` API. Drag-and-drop is a Phase 6 UX polish item.

---

## Dependencies

- **Phase 5a infrastructure** — `key_compatibility.py` for harmonic mixing, `Crate` model for source crate selection, `CrateTrack` for resolving crate contents.
- **Phase 3 infrastructure** — `ClaudeClient` for API calls, rate limiting, token tracking. `prompt_builder.py` patterns for tool use.
- **Phase 4 infrastructure** — `xml_builder.py` for playlist generation (extended again).
- **No new Python packages** — all functionality uses existing deps.

---

## DB Schema Changes

### New models

**SetPlan** — `backend/models/set_plan.py`
- id, name, description, duration_minutes, target_bpm_start, target_bpm_end, energy_arc, source_type, source_crate_ids (JSON text), harmonic_mixing, status, created_at, updated_at

**SetTrack** — `backend/models/set_plan.py` (same file)
- id, set_id (FK), track_id (FK), position, is_locked, is_candidate, segment_id (FK, nullable), created_at
- UniqueConstraint on (set_id, track_id)

**SetSegment** — `backend/models/set_plan.py` (same file)
- id, set_id (FK), position, description, start_track_position, end_track_position, created_at, updated_at

### Settings additions

| Setting | Type | Default | Purpose |
|---|---|---|---|
| `set_track_duration_minutes` | int | 7 | Assumed minutes per track for set length calculation |
| `set_candidate_multiplier` | float | 2.5 | Multiplier for candidate pool size vs sequence size |
| `set_max_tracks` | int | 50 | Soft maximum tracks per set (warning above this) |

### Exceptions

- `SetPlanError(RekordBotError)` — raised on set planning failures

---

## TDD Candidates

| Function | Location | Why TDD |
|---|---|---|
| `score_bpm_transition()` | `bpm_transition.py` | Fixed scoring table. Pure math. |
| `get_transition_quality()` | `bpm_transition.py` | Derived from score. String return. |
| `suggest_bpm_range()` | `bpm_transition.py` | Sequence analysis. Deterministic. |
| `build_initial_prompt()` | `set_prompt_builder.py` | Prompt construction with parameters. |
| `parse_initial_result()` | `set_prompt_builder.py` | Sequence + candidate validation. |
| `build_replace_prompt()` | `set_prompt_builder.py` | Locked tracks, segments, available tracks. |
| `parse_replace_result()` | `set_prompt_builder.py` | Replacement validation, position bounds. |
| `build_reorder_prompt()` | `set_prompt_builder.py` | Current state, locked positions. |
| `parse_reorder_result()` | `set_prompt_builder.py` | Position validation, locked unchanged. |
| `recalculate_segments()` | `set_planner.py` (or extracted utility) | Segment boundary derivation from lock positions. Pure logic if extracted. |

**Write tests after implementation** (framework integration, I/O-dependent):
- Set planner service (DB operations, Claude orchestration)
- API route handlers
- SSE progress streaming
- XML export integration
- Frontend components

---

## Commit Breakdown

### Commit 1: Dependencies, config, and exceptions
- Add to Settings: `set_track_duration_minutes`, `set_candidate_multiplier`, `set_max_tracks`
- Add `SetPlanError` to exceptions.py
- Commit: "Add Phase 5b configuration and exception types"

### Commit 2: Data models
- Create `backend/models/set_plan.py` with SetPlan, SetTrack, SetSegment models
- Update `backend/models/__init__.py`
- Update `database.py:init_db()` to import new models
- Add model tests (creation, relationships, cascade delete, unique constraints)
- Commit: "Add SetPlan, SetTrack, and SetSegment models"

### Commit 3: BPM transition scorer (TDD)
- Create `backend/services/bpm_transition.py`
- WRITE TESTS FIRST in `backend/tests/test_bpm_transition.py`:
  - `score_bpm_transition()`: exact match, small delta, medium, large, very large
  - `get_transition_quality()`: all quality levels
  - `suggest_bpm_range()`: with target, without target, at start/middle/end of sequence
  - Edge cases: zero BPM, None BPM
- Then implement. Pure logic — no I/O, no DB.
- Commit: "Add BPM transition scoring module (TDD)"

### Commit 4: Set prompt builder (TDD)
- Create `backend/services/set_prompt_builder.py`
- WRITE TESTS FIRST in `backend/tests/test_set_prompt_builder.py`:
  - `build_initial_prompt()`: all parameters present, optional params missing, source crate filtering
  - `parse_initial_result()`: valid response, missing fields, duplicate track IDs, invalid IDs
  - `build_replace_prompt()`: locked tracks included, segment descriptions included, available tracks
  - `parse_replace_result()`: valid replacements, position out of bounds, locked position replacement rejected
  - `build_reorder_prompt()`: current sequence, locked positions marked
  - `parse_reorder_result()`: valid reorder, locked positions unchanged, invalid positions
- Then implement. Pure logic — no I/O, no SDK.
- Commit: "Add set prompt builder with initial, replace, and reorder prompts (TDD)"

### Commit 5: Set planner service
- Create `backend/services/set_planner.py`
- Implement all service functions: create, get, list, update, delete, lock/unlock, segment update, shuffle (replace + reorder), manual editing, recalculate_segments, get_candidates
- SSE progress events for Claude operations
- Tests with mocked ClaudeClient
- Commit: "Add set planner service with lock-and-shuffle refinement"

### Commit 6: API routes
- Create `backend/routes/sets.py`
- Implement all endpoints from the architecture section
- Register in main.py
- Test all endpoints
- Commit: "Add set planner API routes with CRUD, shuffle, and progress SSE"

### Commit 7: XML export integration
- Extend `xml_builder.py:build_playlists()` to include set playlists (ordered)
- Extend `xml_exporter.py:export_library()` to load sets
- Add per-set export endpoint
- Tests: set playlists in XML, track order preserved, coexistence with folder + crate playlists
- Commit: "Extend XML export with ordered set playlists"

### Commit 8: Frontend — Set planner view
- Create `SetPlannerView.tsx` — main set planning interface with track sequence, segments, lock/unlock, key and BPM indicators
- Create `SetCreateDialog.tsx` — set creation modal with all parameters
- Create `SetListPanel.tsx` — set list for sidebar
- Extend sidebar with Sets section
- Extend API client with all set types and endpoints
- Commit: "Add set planner UI with sequence view, segments, and shuffle controls"

### Commit 9: Integration tests and cleanup
- End-to-end: create set → initial sequence → lock tracks → edit segment → shuffle replace → verify
- Shuffle reorder test
- Manual add/remove/move
- Segment recalculation on lock/unlock
- XML export with sets
- Candidate pool management
- Update CLAUDE.md with Phase 5b status
- Commit: "Add integration tests and update project docs for Phase 5b"

---

## Claude Code Prompt

The following prompt is designed to be given to Claude Code at the start of the implementation session. Copy it verbatim.

---

```
You are implementing Phase 5b (Set Planner) of rekordbot.

Read these files first:
- CLAUDE.md (project conventions, architecture, coding standards)
- docs/features/phase-5b-set-planner.md (the feature brief — this is your specification)
- backend/models/track.py (existing Track model)
- backend/models/crate.py (Phase 5a Crate and CrateTrack models — you'll query these for source tracks)
- backend/models/database.py (engine, session, Base, init_db)
- backend/config.py (existing Settings — you'll add new config fields)
- backend/exceptions.py (existing exception hierarchy — add SetPlanError)
- backend/main.py (existing FastAPI app — you'll register new routes)
- backend/services/claude_client.py (Phase 3 Claude client — you'll reuse this)
- backend/services/prompt_builder.py (Phase 3 prompt builder — reference for tool use patterns and build_track_summary)
- backend/services/crate_prompt_builder.py (Phase 5a — reference for crate-specific prompt patterns)
- backend/services/crate_assigner.py (Phase 5a — reference for batch + SSE pattern with Claude)
- backend/services/key_compatibility.py (Phase 5a — you'll use this for harmonic mixing indicators)
- backend/services/key_notation.py (Phase 2 — key display conversion)
- backend/services/xml_builder.py (Phase 4 — you'll extend build_playlists again)
- backend/services/xml_exporter.py (Phase 4 — you'll extend export_library again)
- backend/routes/crates.py (Phase 5a routes — reference for route patterns)
- frontend/src/App.tsx (current layout — you'll add set planner view)
- frontend/src/CrateSidebar.tsx (Phase 5a sidebar — you'll extend with Sets section)
- frontend/src/api/client.ts (existing API client — you'll extend with set endpoints)

## What you're building

An AI-powered set planning system that:
1. Lets users describe a DJ set (duration, energy arc, mood, BPM targets)
2. Uses Claude to suggest an initial ordered track sequence with a candidate pool
3. Supports lock-and-shuffle iterative refinement
4. Supports segmented mood descriptions — different vibes for different sections
5. Two shuffle modes: "replace" (swap tracks) and "reorder" (optimise sequence)
6. Includes BPM transition scoring and key compatibility indicators
7. Exports set playlists (ordered) in the Rekordbox XML
8. Provides a dedicated set planner view with sequence, segments, and controls

This feature reuses Phase 3's ClaudeClient for API calls. Do not create a new Claude client.
This feature reuses Phase 5a's key_compatibility module. Do not recreate key compatibility logic.

## Build order (follow this exactly)

### Step 1: Dependencies and config
- Add to Settings: set_track_duration_minutes: int = 7, set_candidate_multiplier: float = 2.5, set_max_tracks: int = 50
- Add SetPlanError to exceptions.py
- Commit: "Add Phase 5b configuration and exception types"

### Step 2: Data models
- Create backend/models/set_plan.py with SetPlan, SetTrack, SetSegment models
- SetPlan: id, name, description, duration_minutes, target_bpm_start, target_bpm_end, energy_arc, source_type, source_crate_ids (Text/JSON), harmonic_mixing (Boolean), status, created_at, updated_at
- SetTrack: id, set_id (FK), track_id (FK), position, is_locked, is_candidate, segment_id (FK, nullable), created_at
- SetSegment: id, set_id (FK), position, description, start_track_position, end_track_position, created_at, updated_at
- UniqueConstraint on (set_id, track_id), conditional unique on (set_id, position) for non-candidate tracks
- Update database.py init_db() to import new models
- Commit: "Add SetPlan, SetTrack, and SetSegment models"

### Step 3: BPM transition scorer (TDD)
- Create backend/services/bpm_transition.py
- WRITE TESTS FIRST:
  - score_bpm_transition(): exact match, small/medium/large deltas
  - get_transition_quality(): all quality strings
  - suggest_bpm_range(): with/without target, various positions
  - Edge cases: zero/None BPM
- Then implement. Pure logic — no I/O, no DB.
- Commit: "Add BPM transition scoring module (TDD)"

### Step 4: Set prompt builder (TDD)
- Create backend/services/set_prompt_builder.py
- WRITE TESTS FIRST:
  - build_initial_prompt(): all params, optional params missing
  - parse_initial_result(): valid, missing fields, dedup, invalid IDs
  - build_replace_prompt(): locked tracks, segments, available tracks
  - parse_replace_result(): valid replacements, out of bounds, locked rejected
  - build_reorder_prompt(): current state, locked positions
  - parse_reorder_result(): valid reorder, locked unchanged
- Then implement. Pure logic — no I/O, no SDK.
- Commit: "Add set prompt builder with initial, replace, and reorder prompts (TDD)"

### Step 5: Set planner service
- Create backend/services/set_planner.py
- All service functions: CRUD, lock/unlock, segment update, shuffle (replace + reorder), manual editing, recalculate_segments
- SSE progress events
- Tests with mocked ClaudeClient
- Commit: "Add set planner service with lock-and-shuffle refinement"

### Step 6: API routes
- Create backend/routes/sets.py
- All endpoints from architecture section
- Register in main.py
- Test all endpoints
- Commit: "Add set planner API routes with CRUD, shuffle, and progress SSE"

### Step 7: XML export integration
- Extend xml_builder.py build_playlists() to include ordered set playlists
- Extend xml_exporter.py export_library() to load sets
- Per-set export endpoint
- Tests: set playlists in XML, order preserved, coexistence
- Commit: "Extend XML export with ordered set playlists"

### Step 8: Frontend
- Create SetPlannerView.tsx — sequence, segments, lock/unlock, indicators, shuffle controls
- Create SetCreateDialog.tsx — creation modal with parameters
- Create SetListPanel.tsx — set list for sidebar
- Extend CrateSidebar to include Sets section
- Extend API client with set types and endpoints
- Commit: "Add set planner UI with sequence view, segments, and shuffle controls"

### Step 9: Integration tests and cleanup
- End-to-end: create → sequence → lock → segment edit → shuffle → verify
- Both shuffle modes tested
- Manual editing (add/remove/move)
- Segment recalculation
- XML export with sets
- Update CLAUDE.md
- Commit: "Add integration tests and update project docs for Phase 5b"

## Constraints
- Follow all conventions in CLAUDE.md
- Reuse ClaudeClient from Phase 3 — do NOT create a new Claude client
- Reuse key_compatibility from Phase 5a — do NOT recreate key logic
- Reuse prompt_builder.py patterns for tool use and track summaries
- Reuse SSE patterns from Phase 2/3/5a for progress
- Claude API calls via asyncio.to_thread()
- Do NOT modify Phase 1/2/2b/3 service code
- Phase 5a service code should not be modified (except extending the sidebar component)
- xml_builder and xml_exporter can be extended (same as Phase 5a)
- All exceptions should be RekordBotError subclasses
- Every service module gets its own logger via logging.getLogger(__name__)
- Use %s string formatting in log calls (not f-strings)
- Use sync SQLAlchemy (not async)

## Important
- Do NOT implement audio preview or waveform display
- Do NOT implement drag-and-drop reordering (use the move API instead)
- Do NOT implement undo/redo for shuffle
- Do NOT implement multi-deck planning
- Sets are ORDERED sequences — position matters
- Lock-and-shuffle is the CORE interaction — design everything around it
- Segments are DERIVED from lock positions — recalculate automatically on lock/unlock
- The 2–3x candidate multiplier is essential — Claude should suggest MORE tracks than needed
```

### Continuation Prompt

If the session is interrupted and you need to resume in a new Claude Code session, use this:

```
We are continuing Phase 5b (Set Planner) of rekordbot.

Read these files for context:
- CLAUDE.md (project conventions and current status)
- SESSIONS.md (latest entry has where we left off and what's next)
- docs/features/phase-5b-set-planner.md (the feature specification)

Pick up from where we left off. Check SESSIONS.md for the last completed step
and what was identified as the next task. Confirm what you think the next step
is before writing any code.
```

---

## Notes

- The `SetPlan` model uses `set_plan` as the table name (not `set`) to avoid collision with Python's `set` keyword and SQL reserved words.
- The `source_crate_ids` field stores a JSON array of crate IDs as a Text column, consistent with the `parsed_criteria` pattern from Phase 5a. Parse with `json.loads()` / `json.dumps()`.
- The conditional unique constraint on `(set_id, position)` for non-candidate tracks may need to be enforced at the application level rather than the database level, since SQLite doesn't support partial unique indexes cleanly. The service layer should validate position uniqueness for active (non-candidate) tracks before writes.
- Segment recalculation is the trickiest piece of logic. When locked tracks change, segments need to be rebuilt while preserving descriptions for segments whose boundaries haven't changed. The matching heuristic should be: if a segment's start and end positions are unchanged, keep its description. If boundaries shifted, attempt to match by closest overlap.
- The `build_track_summary()` function from Phase 3's `prompt_builder.py` and Phase 5a's `crate_prompt_builder.py` should be reused for generating track summaries in set prompts. The set planner may need an extended version that includes key compatibility info with adjacent tracks.
- Claude's context window limits set size: a 50-track set with full metadata summaries per track will consume significant context. The `set_max_tracks` setting exists for this reason. For larger sets, the prompt builder should summarise track data more aggressively.
- The frontend set planner view is the most complex UI in the entire app. It's a new view type (not just a panel or dialog). App.tsx will need a routing or view-switching mechanism. The simplest approach is a state variable that switches between "library" view and "set-planner" view, with the set planner receiving the selected set ID as a prop.
- Export of sets preserves track order (unlike crates, which are unordered). The XML builder needs to respect `SetTrack.position` when generating TRACK elements within set playlists.
