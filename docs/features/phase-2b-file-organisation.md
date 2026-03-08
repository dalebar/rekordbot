# Feature: File Organisation & Structure
**Branch:** `feature/phase-2b-organiser`
**Status:** Not Started
**Phase:** 2b
**Depends on:** Phase 3 (complete)

---

## Goal

Organise every track in the rekordbot library into a clean, user-approved folder structure based on enriched metadata — with a template engine for configurable paths, confidence scoring that flags ambiguous cases for review, Claude-powered reasoning for uncertain placements, and a preference engine that learns from user decisions so the same question is never asked twice.

The file organiser runs **after** ingestion (Phase 1), analysis (Phase 2), and AI tagging (Phase 3). It uses all available metadata to propose file moves, but never moves anything without explicit user approval.

---

## Inputs

- Tracks already in the SQLite database with metadata from Phases 1–3:
  - Phase 1: `source_path`, `output_path`, `source_format`, `source_codec`
  - Phase 2: `title`, `artist`, `album`, `album_artist`, `genre`, `label`, `year`, `bpm`, `key`
  - Phase 3: `subgenre`, `mood`, `energy`, `ai_confidence`, `ai_reasoning`
- User preferences (from settings, persisted in config):
  - `folder_template`: str (default `"{artist}/{album}/{title}"`) — configurable folder structure
  - `organise_unknown_fallback`: str (default `"Unsorted"`) — literal string used when all fallbacks fail
- Preference rules in SQLite (learned from user decisions)
- Anthropic API key (optional — for Claude reasoning on ambiguous tracks)

## Outputs

- An organisation **proposal**: a list of proposed file moves with confidence scores and reasoning, presented to the user for review before execution
- Organised audio files moved from `{output_directory}/imports/{YYYY-MM-DD}/` to their final template-derived paths within `{output_directory}/`
- Updated `Track` records in SQLite:
  - `output_path` updated to the new file location after move
  - `previous_output_path` records the pre-move path
  - `organisation_status` tracks state: `"unorganised"` → `"proposed"` → `"organised"` (or `"review_needed"`)
  - `organisation_confidence` float score for the proposed path
  - `organisation_reasoning` text explanation of why this path was chosen
  - `proposed_path` the path the organiser wants to move the file to (before approval)
- Preference rules created from user decisions (stored in `preference_rules` table)
- SSE progress events for organisation batches

---

## Architecture & Key Components

### 1. Template Engine (`backend/services/template_engine.py`)

Parses and resolves folder templates against track metadata. Pure logic — this is a TDD candidate.

**Template syntax:**
- Variables: `{variable}` — resolved from Track model fields
- Fallbacks: `{variable|"literal"}` — if variable is None or empty, use the literal string
- Chained fallbacks: `{variable1|variable2|"literal"}` — try variable1, then variable2, then literal
- Available variables: `artist`, `album_artist`, `album`, `title`, `genre`, `subgenre`, `year`, `label`
- The file extension is always derived from the output format — not part of the template

**Examples:**
```
{artist}/{album}/{title}
  → Calibre/Shelflife 6/Falls to You.aiff

{artist}/{album|"Singles"}/{title}
  → Bicep/Singles/Glue.aiff  (album was empty)

{genre}/{artist}/{title}
  → Melodic Techno/Âme/Rej.aiff

{artist}/{album|"Singles"}/{title}
  → Unknown Artist/Unknown Album/untitled.aiff  (all fields missing — multiple fallbacks)
```

**Path sanitisation:**
After template resolution, sanitise each path component:
- Replace characters unsafe on macOS/Windows: `/ \ : * ? " < > |`
- Strip leading/trailing dots and spaces from each component
- Collapse multiple spaces to single space
- Trim each component to a reasonable max length (255 chars — filesystem limit)
- Preserve unicode (accented characters, non-Latin scripts are fine on modern filesystems)

**Functions:**
- `parse_template(template: str) -> list[TemplateSegment]` — parse template string into typed segments (variable, fallback chain, literal, separator)
- `resolve_template(template: str, track: Track) -> ResolvedPath` — resolve a template against track data, returning the resolved path, list of variables that used fallbacks, and list of variables that failed entirely
- `sanitise_path_component(component: str) -> str` — clean a single path component
- `build_output_path(template: str, track: Track, output_dir: Path) -> ResolvedPath` — full pipeline: resolve → sanitise → join with output dir and extension

**Return type:**
```
TemplateSegment:
    type: Literal["variable", "literal", "separator"]
    value: str                      # variable name, literal string, or "/"
    fallbacks: list[str]            # for variables: ordered fallback list (variable names or quoted literals)

ResolvedPath:
    path: Path                      # the fully resolved output path
    fallbacks_used: list[str]       # variables that fell through to a fallback
    unresolved: list[str]           # variables that couldn't be resolved at all
    components: dict[str, str]      # variable name → resolved value (for debugging/display)
```

### 2. Confidence Scorer (`backend/services/confidence_scorer.py`)

Evaluates a track's readiness for automatic organisation. Pure logic — TDD candidate.

**Scoring criteria:**

| Criterion | Effect | Reasoning |
|---|---|---|
| All template variables resolved directly | +0.3 | Strong metadata, clear path |
| Single fallback used | 0.0 (neutral) | Common and acceptable (e.g. no album → "Singles") |
| Multiple fallbacks used (≥2) | -0.3 | Sparse metadata, path is mostly defaults |
| Unresolved variable (no fallback available) | -0.5 | Template can't be fully resolved |
| `ai_confidence = "high"` | +0.2 | AI is confident in genre/mood (relevant if template uses genre) |
| `ai_confidence = "low"` | -0.2 | AI genre may be wrong |
| VA compilation detected | -0.2 | Artist attribution is ambiguous |
| Bootleg/edit indicators in title or filename | -0.2 | Artist attribution is ambiguous |
| Preference rule exists for this artist | +0.3 | User has already decided how this artist is handled |
| Missing genre after AI tagging | -0.2 | Something went wrong in the AI pipeline |

**VA detection logic:**
- `album_artist` is not None and differs from `artist`
- `artist` contains any of: "Various", "VA", "V/A", "Various Artists" (case-insensitive)

**Bootleg/edit detection logic:**
- Title or source filename contains any of: "bootleg", "edit", "mashup", "vs", "vs.", "b2b", "VIP", "remix" where the remixer is the same as the artist (self-remix — attribution is clear)
- Note: "remix" alone is NOT a flag — remixes have clear attribution. Only flag when combined with ambiguous artist patterns.

**Confidence calculation:**
- Start at base score 0.5
- Apply each criterion's delta
- Clamp to [0.0, 1.0]
- Threshold for auto-approval: configurable, default 0.7

**Functions:**
- `score_track(track: Track, resolved_path: ResolvedPath, preference_rules: list[PreferenceRule]) -> ConfidenceResult`
- `detect_va_compilation(track: Track) -> bool`
- `detect_bootleg_indicators(track: Track) -> list[str]` — returns list of matched indicator strings

**Return type:**
```
ConfidenceResult:
    score: float                    # 0.0–1.0
    auto_approve: bool              # score >= threshold
    reasons: list[str]             # human-readable list of factors that affected the score
    flags: list[str]               # machine-readable flag codes: "multiple_fallbacks", "va_detected", "low_ai_confidence", etc.
```

### 3. Preference Store (`backend/services/preference_store.py`)

CRUD operations for the `preference_rules` table. Rules are created from user decisions in the review queue and applied automatically to future tracks.

**Rule types:**

| Type | Key | Value | Example |
|---|---|---|---|
| `artist_folder` | artist name (normalised lowercase) | canonical folder name | "aphex twin" → "Aphex Twin" |
| `va_handling` | album name (normalised lowercase) | handling strategy: `"use_album_artist"`, `"use_album"`, `"use_literal:{value}"` | "fabric 99" → "use_album_artist" |
| `custom_path` | track ID (as string) | explicit full relative path | "42" → "Specials/That One Track.aiff" |

**Normalisation:** Rule keys are stored lowercase with whitespace trimmed for consistent matching. Lookup is case-insensitive.

**Functions:**
- `get_rule(rule_type: str, key: str) -> PreferenceRule | None` — look up a specific rule
- `get_rules_for_track(track: Track) -> list[PreferenceRule]` — find all applicable rules for a track
- `create_rule(rule_type: str, key: str, value: str) -> PreferenceRule` — create a new rule
- `delete_rule(rule_id: int) -> None`
- `list_rules(rule_type: str | None = None) -> list[PreferenceRule]` — list all rules, optionally filtered by type
- `apply_rules(track: Track, resolved_path: ResolvedPath) -> ResolvedPath` — apply applicable rules to modify a resolved path

**Rule application order:**
1. `custom_path` — if a custom path rule exists for this track ID, use it directly (highest priority)
2. `artist_folder` — if a rule exists for this artist, replace the artist component in the resolved path
3. `va_handling` — if the track is a VA compilation and a rule exists for this album, apply the handling strategy

### 4. Claude Reasoner (`backend/services/claude_reasoner.py`)

Sends ambiguous tracks to Claude for placement suggestions. Reuses the Phase 3 `ClaudeClient` for API calls, rate limiting, and token tracking.

**Responsibilities:**
- Build a prompt describing the ambiguous track and the user's folder template
- Ask Claude to suggest a folder path and explain its reasoning
- Parse the tool use response
- Return a suggestion that the user can accept, modify, or reject

**System prompt:**

```
You are helping a DJ organise their music library into folders. The user has a folder template that determines the directory structure, but some tracks have ambiguous or missing metadata that makes automatic placement difficult.

For each track, suggest the best folder path and explain your reasoning. Consider:
- The user's folder template pattern
- Available metadata (artist, album, genre, BPM, key, etc.)
- Common DJ library conventions
- Whether the track is a VA compilation, bootleg, edit, or remix
- The artist's typical genre or style (from your knowledge)

When metadata is missing, make a reasonable inference from what IS available. For example:
- A filename like "Bicep - Glue (Original Mix).flac" tells you the artist and title even if tags are empty
- A BPM of 174 strongly suggests Drum & Bass
- A label name often implies a genre
```

**Tool schema:**
```python
ORGANISE_TOOL_SCHEMA = {
    "name": "suggest_placement",
    "description": "Suggest a folder path for an ambiguous track in the DJ's music library.",
    "input_schema": {
        "type": "object",
        "properties": {
            "track_id": {
                "type": "integer",
                "description": "The track ID from the input"
            },
            "suggested_path": {
                "type": "string",
                "description": "Suggested relative folder path (e.g. 'Bicep/Isles/Glue')"
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "Your confidence in this suggestion"
            },
            "reasoning": {
                "type": "string",
                "description": "One-sentence explanation of why you chose this path"
            }
        },
        "required": ["track_id", "suggested_path", "confidence", "reasoning"]
    }
}
```

**Functions:**
- `build_organisation_prompt(track: Track, template: str, resolved_path: ResolvedPath, confidence_result: ConfidenceResult) -> tuple[str, str]` — returns (system_prompt, user_message)
- `suggest_placement(track: Track, template: str, resolved_path: ResolvedPath, confidence_result: ConfidenceResult, claude_client: ClaudeClient) -> PlacementSuggestion`
- `suggest_placements_batch(tracks: list[tuple[Track, ResolvedPath, ConfidenceResult]], template: str, claude_client: ClaudeClient) -> list[PlacementSuggestion]` — batch multiple ambiguous tracks into one API call

**Return type:**
```
PlacementSuggestion:
    track_id: int
    suggested_path: str             # relative path without extension
    confidence: str                 # "high", "medium", "low"
    reasoning: str
```

**Batching:** Ambiguous tracks are batched together (up to `ai_batch_size` per request) to reduce API calls. The prompt includes the user's template and all ambiguous tracks in one message.

### 5. File Mover (`backend/services/file_mover.py`)

Executes approved file moves and updates DB records. This is the only component that actually touches the filesystem.

**Responsibilities:**
- Move a file from its current `output_path` to the approved destination path
- Handle path collisions (`_1`, `_2` suffix — reuse Phase 1's `naming.py` collision logic)
- Create intermediate directories as needed
- Update the Track record: `output_path` → new path, `previous_output_path` → old path, `organisation_status` → `"organised"`
- Clean up empty directories left behind after moves
- Verify the moved file exists and is the expected size (basic integrity check)

**Functions:**
- `move_file(track: Track, destination: Path, db_session) -> MoveResult`
- `move_files_batch(moves: list[tuple[Track, Path]], db_session) -> BatchMoveResult`
- `cleanup_empty_dirs(base_dir: Path) -> int` — recursively remove empty directories, return count removed

**Return types:**
```
MoveResult:
    track_id: int
    status: Literal["moved", "failed"]
    old_path: Path
    new_path: Path
    error: str | None

BatchMoveResult:
    total: int
    moved: int
    failed: int
    results: list[MoveResult]
    dirs_cleaned: int
```

**Error handling:**
- Source file doesn't exist → fail that track, continue batch
- Destination path collision → apply suffix
- Permission error → fail that track, log error
- Disk full → fail remaining tracks, log error
- All failures are non-fatal to the batch (per-file error isolation)

### 6. Organisation Pipeline (`backend/services/organiser.py`)

Orchestrates the full organisation flow. Two phases: **propose** (dry-run) and **execute** (approved moves).

**Propose flow:**
1. Load unorganised tracks from DB (or specified track IDs)
2. Load preference rules
3. For each track:
   a. Apply any `custom_path` rules → if found, use directly with confidence 1.0
   b. Resolve template against track metadata
   c. Apply `artist_folder` and `va_handling` rules to the resolved path
   d. Score confidence
   e. If auto-approve (score ≥ threshold): mark as ready to move
   f. If not auto-approve: flag for review
4. Optionally: send all flagged tracks to Claude for placement suggestions (if API key is available and user opted in)
5. Store proposals in DB (`proposed_path`, `organisation_confidence`, `organisation_reasoning`, `organisation_status = "proposed"`)
6. Emit SSE progress events
7. Return proposal summary

**Execute flow:**
1. Accept a list of approved track IDs (or "all auto-approved")
2. For each approved track: call file mover
3. Update DB records
4. Clean up empty directories
5. Emit SSE progress events
6. Return execution summary

**Cancellation:** Supported via `asyncio.Event` (same pattern as Phases 1–3).

**SSE event schema:**
```json
{
  "event": "organise_progress",
  "data": {
    "phase": "proposing",
    "tracks_processed": 45,
    "tracks_total": 150,
    "auto_approved": 120,
    "needs_review": 25,
    "failed": 5
  }
}
```

```json
{
  "event": "organise_move_progress",
  "data": {
    "phase": "moving",
    "files_moved": 30,
    "files_total": 120,
    "files_failed": 0
  }
}
```

**Return types:**
```
OrganisationProposal:
    total_tracks: int
    auto_approved: int
    needs_review: int
    failed: int
    token_usage: TokenUsage | None  # if Claude was used

OrganisationResult:
    total_moved: int
    failed: int
    dirs_cleaned: int
    results: list[MoveResult]
```

### 7. API Routes (`backend/routes/organise.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/organise/propose` | Generate organisation proposal (dry-run) |
| GET | `/api/organise/progress` | SSE endpoint for organisation progress |
| POST | `/api/organise/cancel` | Cancel current operation |
| GET | `/api/organise/proposal` | Get current proposal (list of proposed moves) |
| POST | `/api/organise/approve` | Approve and execute moves |
| POST | `/api/organise/resolve/{id}` | Resolve an ambiguous track (accept, edit, skip) |
| GET | `/api/preferences` | List preference rules |
| POST | `/api/preferences` | Create a preference rule |
| DELETE | `/api/preferences/{id}` | Delete a preference rule |

**POST `/api/organise/propose` request body:**
```json
{
  "track_ids": [1, 2, 3],
  "options": {
    "use_claude": true,
    "skip_if_organised": true,
    "confidence_threshold": 0.7
  }
}
```
If `track_ids` is empty or absent, propose for all tracks with `organisation_status = "unorganised"`.

**POST `/api/organise/propose` response:**
```json
{
  "batch_id": "uuid",
  "total_tracks": 150,
  "message": "Organisation proposal started"
}
```

**GET `/api/organise/proposal` response:**
```json
{
  "proposal": {
    "auto_approved": [
      {
        "track_id": 1,
        "title": "Falls to You",
        "artist": "Calibre",
        "current_path": "/library/imports/2026-03-08/falls_to_you.aiff",
        "proposed_path": "/library/Calibre/Shelflife 6/Falls to You.aiff",
        "confidence": 0.95,
        "reasoning": "All template variables resolved directly, artist preference rule applied"
      }
    ],
    "needs_review": [
      {
        "track_id": 42,
        "title": "untitled",
        "artist": null,
        "current_path": "/library/imports/2026-03-08/track_03.aiff",
        "proposed_path": "/library/Unsorted/untitled.aiff",
        "confidence": 0.2,
        "reasoning": "Missing artist and album. Filename suggests this may be a rip without tags.",
        "claude_suggestion": {
          "suggested_path": "Unknown Artist/track_03",
          "confidence": "low",
          "reasoning": "No metadata available to infer artist or genre."
        },
        "flags": ["multiple_fallbacks", "low_ai_confidence"]
      }
    ],
    "failed": [],
    "summary": {
      "total": 150,
      "auto_approved": 120,
      "needs_review": 25,
      "failed": 5
    }
  }
}
```

**POST `/api/organise/approve` request body:**
```json
{
  "mode": "auto_approved",
  "track_ids": null
}
```
`mode` can be `"auto_approved"` (move all auto-approved tracks), `"specific"` (move only listed `track_ids`), or `"all"` (move everything including reviewed tracks).

**POST `/api/organise/resolve/{id}` request body:**
```json
{
  "action": "accept",
  "custom_path": null,
  "save_preference": true,
  "preference_type": "artist_folder"
}
```
`action` can be `"accept"` (use proposed path), `"custom"` (use `custom_path`), or `"skip"` (leave track unorganised).
If `save_preference` is true, create a preference rule from this decision.

**POST `/api/preferences` request body:**
```json
{
  "rule_type": "artist_folder",
  "key": "aphex twin",
  "value": "Aphex Twin"
}
```

**Enhanced GET `/api/tracks` response (additional fields):**
```json
{
  "tracks": [
    {
      "...existing fields...",
      "organisation_status": "organised",
      "proposed_path": null,
      "previous_output_path": "/library/imports/2026-03-08/falls_to_you.aiff",
      "organisation_confidence": 0.95
    }
  ]
}
```

### 8. Frontend — Organisation UI (`frontend/src/`)

**Components:**

- **OrganiseControls.tsx** — Toolbar section added alongside existing AnalysisControls.
  - "Organise Library" button — triggers proposal generation
  - Progress bar (SSE-driven, two phases: proposing → moving)
  - Status summary after proposal: "120 ready to move, 25 need review, 5 failed"
  - "Move Approved" button — executes all auto-approved moves
  - "Review Ambiguous" button — opens the review queue

- **ProposalSummary.tsx** — Summary card showing proposal statistics.
  - Auto-approved count (with "Move All" action)
  - Needs review count (with "Review" action)
  - Failed count (with details expandable)
  - Token usage if Claude was used

- **ReviewQueue.tsx** — List of ambiguous tracks requiring user decisions.
  - Each track shows: current path, proposed path, confidence score, reasoning, flags
  - If Claude suggestion is available: show it alongside the template-based proposal
  - Actions per track: "Accept" (use proposed path), "Edit" (modify path manually), "Skip" (leave unorganised)
  - Checkbox: "Remember this decision for future tracks by this artist" (creates preference rule)
  - Batch actions: "Accept All Remaining", "Skip All Remaining"

- **PreferenceRulesPanel.tsx** — Management panel for saved preference rules.
  - Accessible from settings or from a link in the OrganiseControls area
  - List of all rules, grouped by type (artist_folder, va_handling, custom_path)
  - Delete button per rule
  - No manual creation UI (rules are created via the review queue) — but the API supports direct creation for power users

- **TrackTable extensions:**
  - New column config: `organisation_status` (visible: false by default)
  - New filter mode: `"unorganised"`, `"organised"`, `"review_needed"`
  - Existing `output_path` column shows updated path after organisation

---

## Acceptance Criteria

### Template engine
- [ ] Default template `{artist}/{album}/{title}` correctly resolves for tracks with full metadata
- [ ] Template is configurable via Settings (`folder_template`)
- [ ] Fallback syntax works: `{album|"Singles"}` uses "Singles" when album is empty
- [ ] Chained fallbacks work: `{variable1|variable2|"literal"}` tries each in order
- [ ] Multiple fallbacks in one path flagged as ambiguous (not silently resolved)
- [ ] Path components are sanitised: unsafe characters stripped, leading/trailing dots removed
- [ ] Unicode characters preserved in path components
- [ ] File extension derived from output format, not template
- [ ] Path collision handling: `_1`, `_2` suffix when destination exists

### Confidence scoring
- [ ] Tracks with full metadata and no ambiguity score ≥ 0.7 (auto-approved)
- [ ] Tracks with multiple fallbacks score < 0.7 (flagged for review)
- [ ] VA compilation detected and flagged
- [ ] Bootleg/edit indicators detected and flagged
- [ ] Low AI confidence contributes to lower score
- [ ] Existing preference rule for artist boosts confidence
- [ ] Confidence threshold is configurable

### Preference engine
- [ ] `artist_folder` rules: canonical folder name applied when organising
- [ ] `va_handling` rules: VA compilation handling strategy applied
- [ ] `custom_path` rules: explicit override path used for specific tracks
- [ ] Rules created from user decisions in review queue
- [ ] Rules applied automatically to future tracks (no re-prompting)
- [ ] Rules stored in SQLite `preference_rules` table
- [ ] Rules can be listed and deleted via API

### Claude reasoning
- [ ] Claude only called for ambiguous tracks (not auto-approved)
- [ ] Claude suggestions displayed alongside template-based proposals in review queue
- [ ] Claude reasoning stored in `organisation_reasoning` column
- [ ] Claude reasoning is optional (works without API key — tracks just go to review queue without AI suggestion)
- [ ] Reuses Phase 3's `ClaudeClient` (rate limiting, retry, token tracking)
- [ ] Token usage reported in proposal summary

### File moves
- [ ] Dry-run is the default — nothing moves until user approves
- [ ] Batch approval: all auto-approved tracks moved at once
- [ ] Individual approval: ambiguous tracks approved one-by-one in review queue
- [ ] Files physically moved (not copied) from imports directory to organised path
- [ ] `output_path` updated in DB to new location
- [ ] `previous_output_path` records the pre-move path
- [ ] Empty directories cleaned up after moves
- [ ] Source files never touched (`source_path` unchanged)
- [ ] Path collision handled with `_1`, `_2` suffixes

### Organisation pipeline
- [ ] Proposal generates without moving any files
- [ ] Proposal stored in DB (`proposed_path`, `organisation_confidence`, `organisation_status`)
- [ ] SSE progress events for both proposing and moving phases
- [ ] Per-track error isolation (one failure doesn't stop the batch)
- [ ] Cancellation support
- [ ] Re-proposal possible (re-run on already-organised tracks with confirmation)

### UI
- [ ] "Organise Library" button in toolbar
- [ ] Proposal summary showing auto-approved / needs review / failed counts
- [ ] Review queue with accept / edit / skip actions per track
- [ ] "Remember this decision" checkbox creates preference rule
- [ ] Preference rules panel for viewing and deleting rules
- [ ] Organisation progress bar (two-phase: proposing → moving)
- [ ] New filter modes: unorganised, organised, review_needed

### Data integrity
- [ ] `organisation_status` transitions correctly: unorganised → proposed → organised (or review_needed)
- [ ] `proposed_path` populated during proposal, cleared after move or skip
- [ ] `previous_output_path` populated on move
- [ ] Preference rules normalise keys to lowercase for consistent matching
- [ ] Moved files verified to exist at new path after move

---

## Out of Scope

- **Near-duplicate detection** (same track, different encode/bitrate) — requires audio fingerprinting. Exact duplicates already caught by Phase 1 SHA-256 hash.
- **Auto-organise on import** — deferred. Phase 2b is batch-only, triggered explicitly by the user.
- **Undo/revert for file moves** — `previous_output_path` is recorded for potential future implementation, but no undo feature in Phase 2b. The dry-run/approval flow is the safety net.
- **Regex-based preference rules** — rules are simple key-value lookups, not pattern matching. Sufficient for common cases; complex rules can be added later if needed.
- **Manual preference rule creation UI** — rules are created organically from review queue decisions. The API supports direct creation for power users, but no dedicated UI.
- **Folder template editor UI** — template is set in Settings as a string. A visual editor with variable picker is a Phase 6 polish item.
- **Nested template conditionals** — no `{if genre then genre/ else ""}` syntax. Keep it simple: variables with fallbacks.
- **Album art in folders** — no `folder.jpg` generation. Deferred.
- **Rekordbox XML path updates** — Phase 4 reads paths from DB, so organised paths will be picked up automatically. No special integration needed.

---

## Dependencies

- **Phase 3 infrastructure** — `ClaudeClient` for Claude reasoning, token tracking.
- **Phase 1 infrastructure** — `naming.py` collision handling pattern (reused, not imported — Phase 2b has its own path construction).
- **All metadata from Phases 1–3** — the template engine resolves against Track model fields populated by earlier phases.

---

## DB Schema Changes

### Track model additions

| Column | Type | Purpose |
|---|---|---|
| `proposed_path` | String, nullable | Path proposed by the organiser (before approval) |
| `previous_output_path` | String, nullable | Path before organisation move (for audit/potential revert) |
| `organisation_status` | String | Status: `"unorganised"` (default), `"proposed"`, `"organised"`, `"review_needed"` |
| `organisation_confidence` | Float, nullable | Confidence score for the proposed path (0.0–1.0) |
| `organisation_reasoning` | Text, nullable | Explanation of path choice (template resolution or Claude reasoning) |

### New model: PreferenceRule (`backend/models/preference_rule.py`)

| Column | Type | Purpose |
|---|---|---|
| `id` | Integer, primary key | Auto-increment |
| `rule_type` | String, not null | `"artist_folder"`, `"va_handling"`, `"custom_path"` |
| `key` | String, not null | Normalised lookup key (lowercase, trimmed) |
| `value` | String, not null | Rule value (canonical name, handling strategy, or explicit path) |
| `created_at` | DateTime | When the rule was created |

Unique constraint on `(rule_type, key)` — one rule per type per key.

---

## Decisions (Finalised)

All decisions were discussed and agreed before implementation.

| # | Decision | Resolution |
|---|---|---|
| 1 | Default template | `{artist}/{album}/{title}` — artist-first hierarchy. Genre is a metadata attribute, not a filesystem attribute. Configurable via `folder_template` setting. |
| 2 | Fallback strategy | Cascading fallbacks with `{variable\|"literal"}` syntax. Multiple fallbacks in one path → flag as ambiguous. |
| 3 | Ambiguity criteria | Missing fields (no fallback resolved), multiple fallbacks used, VA detected, low AI confidence, bootleg/edit indicators, missing genre post-AI. Scored with configurable threshold (default 0.7). |
| 4 | Claude reasoning | Optional, ambiguous tracks only. Reuses Phase 3 ClaudeClient. Suggestions shown alongside template proposals in review queue. |
| 5 | Preference engine | Simple lookup tables from user decisions: `artist_folder`, `va_handling`, `custom_path`. No metadata overrides — rules only govern filesystem decisions. |
| 6 | File moves | Move (not copy). Dry-run default. Batch approval for auto-approved, individual review for ambiguous. |
| 7 | Batch vs incremental | Batch-only for Phase 2b. Auto-organise on import deferred. |
| 8 | Undo | No undo in Phase 2b. `previous_output_path` recorded for potential future revert. Dry-run/approval flow is the safety net. |
| 9 | Near-duplicate detection | Out of scope. Exact duplicates caught by Phase 1 SHA-256 hash. Path collisions handled by `_1`, `_2` suffix. Audio fingerprinting deferred. |
| 10 | Path sanitisation | Strip unsafe chars for macOS/Windows. Preserve unicode. Trim to 255 chars per component. |

---

## TDD Candidates

Per CLAUDE.md convention — pure logic functions with clearly defined inputs/outputs, written test-first:

| Function | Location | Why TDD |
|---|---|---|
| `parse_template()` | `template_engine.py` | String → typed segments. Handles variables, fallbacks, chained fallbacks, literals, escaping. |
| `resolve_template()` | `template_engine.py` | Template + Track → resolved path with fallback tracking. Full truth table: all resolved, single fallback, multiple fallbacks, unresolved. Highest-value TDD target. |
| `sanitise_path_component()` | `template_engine.py` | String → sanitised string. Unsafe chars, dots, spaces, length limits. |
| `score_track()` | `confidence_scorer.py` | Track + ResolvedPath + rules → confidence score. Full truth table of scoring criteria. |
| `detect_va_compilation()` | `confidence_scorer.py` | Track → bool. Test with various artist/album_artist combinations. |
| `detect_bootleg_indicators()` | `confidence_scorer.py` | Track → list of matched indicators. Test with various title/filename patterns. |
| `apply_rules()` | `preference_store.py` | Track + ResolvedPath + rules → modified path. Test each rule type and priority ordering. |
| `build_organisation_prompt()` | `claude_reasoner.py` | Track + template + context → prompt strings. Pure string construction. |
| `parse_placement_result()` | `claude_reasoner.py` | Tool use JSON → PlacementSuggestion. Validate fields, handle missing/malformed data. |

**Write tests after implementation** (framework integration, I/O-dependent):
- File mover (filesystem operations)
- Organisation pipeline orchestration
- API route handlers
- SSE event streaming
- Frontend components
- Preference store DB operations

---

## Commit Breakdown

### Commit 1: Dependencies and config
- Add `organise_confidence_threshold` (float, default 0.7) and `folder_template` (str, default `"{artist}/{album}/{title}"`) to Settings in config.py
- Add `organise_unknown_fallback` (str, default `"Unsorted"`) to Settings
- Add `OrganisationError` to exceptions.py
- Commit: "Add Phase 2b configuration and exception types"

### Commit 2: Track model updates and PreferenceRule model
- Add to Track model: `proposed_path`, `previous_output_path`, `organisation_status` (default "unorganised"), `organisation_confidence`, `organisation_reasoning`
- Create `backend/models/preference_rule.py` with PreferenceRule model
- Add unique constraint on `(rule_type, key)`
- Update `backend/models/__init__.py`
- Update any existing model tests
- Commit: "Add organisation columns to Track and PreferenceRule model"

### Commit 3: Template engine (TDD)
- Create `backend/services/template_engine.py`
- WRITE TESTS FIRST in `backend/tests/test_template_engine.py`:
  - Test `parse_template()`: simple variables, fallbacks, chained fallbacks, literal separators, edge cases (empty template, no variables, consecutive variables)
  - Test `resolve_template()`: all variables resolved, single fallback triggered, multiple fallbacks, unresolved variable, chained fallback resolution order, None vs empty string handling
  - Test `sanitise_path_component()`: unsafe characters, leading/trailing dots, multiple spaces, unicode, empty string, very long strings
  - Test `build_output_path()`: full pipeline with output dir and extension
- Then implement all functions
- This is pure logic — no I/O, no DB
- Commit: "Add template engine with fallback resolution and path sanitisation (TDD)"

### Commit 4: Confidence scorer (TDD)
- Create `backend/services/confidence_scorer.py`
- WRITE TESTS FIRST in `backend/tests/test_confidence_scorer.py`:
  - Test `score_track()`: full metadata (high score), sparse metadata (low score), VA compilation penalty, bootleg penalty, preference rule boost, AI confidence effects, threshold boundary cases
  - Test `detect_va_compilation()`: various artist/album_artist combos, "Various Artists", "VA", "V/A", case insensitivity
  - Test `detect_bootleg_indicators()`: "bootleg", "edit", "mashup", "vs", "VIP" in title and filename, case insensitivity, no false positives on normal track names
- Then implement all functions
- Pure logic — no I/O, no DB
- Commit: "Add confidence scorer with VA and bootleg detection (TDD)"

### Commit 5: Preference store
- Create `backend/services/preference_store.py`
- WRITE TESTS FIRST for `apply_rules()`:
  - Test `custom_path` rule overrides everything
  - Test `artist_folder` rule replaces artist component
  - Test `va_handling` strategies: "use_album_artist", "use_album", "use_literal"
  - Test rule priority ordering
  - Test normalised key matching (case insensitive)
- Then implement all CRUD functions and `apply_rules()`
- Tests for DB operations (create, get, list, delete) after implementation
- Commit: "Add preference store with rule application logic (TDD for apply_rules)"

### Commit 6: Claude reasoner
- Create `backend/services/claude_reasoner.py`
- WRITE TESTS FIRST for `build_organisation_prompt()` and `parse_placement_result()`:
  - Test prompt construction includes template, track metadata, and ambiguity flags
  - Test result parsing: valid response, missing fields, invalid confidence
- Then implement:
  - `build_organisation_prompt()`
  - `suggest_placement()` — calls ClaudeClient
  - `suggest_placements_batch()` — batches multiple tracks
  - `parse_placement_result()`
- Tests with mocked ClaudeClient for API call flow
- Commit: "Add Claude reasoner for ambiguous track placement (TDD for prompt/parsing)"

### Commit 7: File mover
- Create `backend/services/file_mover.py`
- Implement:
  - `move_file()` — move single file, update DB
  - `move_files_batch()` — batch moves with per-file error isolation
  - `cleanup_empty_dirs()` — recursive empty directory removal
- Tests:
  - Move to new location, verify file exists at destination
  - Path collision handling (suffix applied)
  - Source doesn't exist → graceful failure
  - Empty directory cleanup
  - `output_path` and `previous_output_path` updated in DB
- Commit: "Add file mover with collision handling and directory cleanup"

### Commit 8: Organisation pipeline
- Create `backend/services/organiser.py`
- Implement:
  - `propose_organisation()` — full proposal flow: resolve templates, score confidence, optionally call Claude, store proposals in DB
  - `execute_organisation()` — move approved files, clean up directories
  - SSE event emission for both phases
  - Cancellation support
  - Per-track error isolation
- Tests with mocked dependencies (template engine, scorer, Claude reasoner, file mover)
- Commit: "Add organisation pipeline with proposal and execution phases"

### Commit 9: API routes
- Create `backend/routes/organise.py`
- Implement all endpoints from the architecture section
- Extend `GET /api/tracks` with organisation fields
- Register routes in main.py
- Test all endpoints with httpx async client
- Commit: "Add organisation API routes with proposal, approval, and preferences"

### Commit 10: Frontend
- Create components:
  - `OrganiseControls.tsx` — toolbar with Organise button, progress, summary
  - `ProposalSummary.tsx` — auto-approved / review / failed counts
  - `ReviewQueue.tsx` — ambiguous track review with accept/edit/skip and preference creation
  - `PreferenceRulesPanel.tsx` — rule list with delete
- Extend TrackTable: `organisation_status` column, new filter modes
- Extend API client: organisation endpoints, preference endpoints, SSE consumer
- Commit: "Add organisation UI with review queue and preference management"

### Commit 11: Integration tests and cleanup
- End-to-end test (mocked Claude): ingest → analyse → AI tag → propose organisation → approve → verify files moved
- Template resolution edge cases with real Track data
- Preference rule creation from review queue flow
- Re-organisation flow (already-organised tracks)
- Review all TODO comments
- Update CLAUDE.md with Phase 2b status
- Commit: "Add integration tests and update project docs for Phase 2b"

---

## Claude Code Prompt

The following prompt is designed to be given to Claude Code at the start of the implementation session. Copy it verbatim.

---

```
You are implementing Phase 2b (File Organisation & Structure) of rekordbot.

Read these files first:
- CLAUDE.md (project conventions, architecture, coding standards)
- docs/features/phase-2b-file-organisation.md (the feature brief — this is your specification)
- backend/models/track.py (existing Track model — you'll need to extend it)
- backend/config.py (existing Settings — you'll add new config fields)
- backend/exceptions.py (existing exception hierarchy — add new types as needed)
- backend/main.py (existing FastAPI app — you'll register new routes here)
- backend/services/ai_tagger.py (Phase 3 pipeline — reference for batch processing and SSE patterns)
- backend/services/claude_client.py (Phase 3 client — you'll reuse this for Claude reasoning)
- backend/services/prompt_builder.py (Phase 3 prompt builder — reference for tool use patterns)
- backend/services/naming.py (Phase 1 naming — reference for collision handling pattern)
- backend/routes/ai_tagging.py (Phase 3 routes — reference for SSE endpoint patterns)
- frontend/src/TrackTable.tsx (existing track table — you'll add organisation columns)
- frontend/src/AnalysisControls.tsx (existing toolbar — you'll add Organise button)
- frontend/src/api/client.ts (existing API client — you'll extend with organisation endpoints)

## What you're building

A file organisation pipeline that:
1. Parses a configurable folder template ({artist}/{album}/{title}) with fallback syntax
2. Resolves templates against track metadata from Phases 1–3
3. Scores confidence for each proposed path (flags ambiguous cases for review)
4. Optionally sends ambiguous tracks to Claude for placement suggestions
5. Stores proposals in DB for user review before any files move
6. Executes approved moves (physically moves files, updates DB paths)
7. Learns from user decisions via a preference rule engine
8. Reports progress via SSE

This pipeline is SEPARATE from Phase 1's ingestion, Phase 2's analysis, and Phase 3's AI tagging. Do not modify their service code.

## Build order (follow this exactly)

### Step 1: Dependencies and config
- Add to Settings in config.py:
  - folder_template: str (default "{artist}/{album}/{title}")
  - organise_confidence_threshold: float (default 0.7)
  - organise_unknown_fallback: str (default "Unsorted")
- Add OrganisationError to exceptions.py
- Commit: "Add Phase 2b configuration and exception types"

### Step 2: Track model updates and PreferenceRule model
- Add to Track model: proposed_path (String, nullable), previous_output_path (String, nullable), organisation_status (String, default "unorganised"), organisation_confidence (Float, nullable), organisation_reasoning (Text, nullable)
- Create backend/models/preference_rule.py with PreferenceRule model (id, rule_type, key, value, created_at)
- Unique constraint on (rule_type, key)
- Update __init__.py
- Commit: "Add organisation columns to Track and PreferenceRule model"

### Step 3: Template engine (TDD)
- Create backend/services/template_engine.py
- WRITE TESTS FIRST:
  - parse_template(): variables, fallbacks, chained fallbacks, edge cases
  - resolve_template(): all resolved, single fallback, multiple fallbacks, unresolved, None vs empty
  - sanitise_path_component(): unsafe chars, dots, spaces, unicode, length limits
  - build_output_path(): full pipeline
- Then implement. Pure logic — no I/O, no DB.
- Commit: "Add template engine with fallback resolution and path sanitisation (TDD)"

### Step 4: Confidence scorer (TDD)
- Create backend/services/confidence_scorer.py
- WRITE TESTS FIRST:
  - score_track(): full metadata (high), sparse (low), VA penalty, bootleg penalty, preference boost, AI confidence effects, threshold boundaries
  - detect_va_compilation(): artist/album_artist combos, "Various Artists", "VA", "V/A"
  - detect_bootleg_indicators(): title/filename patterns, case insensitivity
- Then implement. Pure logic.
- Commit: "Add confidence scorer with VA and bootleg detection (TDD)"

### Step 5: Preference store
- Create backend/services/preference_store.py
- WRITE TESTS FIRST for apply_rules():
  - custom_path overrides everything
  - artist_folder replaces artist component
  - va_handling strategies
  - Rule priority, normalised key matching
- Then implement all CRUD and apply_rules()
- Commit: "Add preference store with rule application logic (TDD for apply_rules)"

### Step 6: Claude reasoner
- Create backend/services/claude_reasoner.py
- WRITE TESTS FIRST for build_organisation_prompt() and parse_placement_result()
- Then implement suggest_placement() and suggest_placements_batch() using existing ClaudeClient
- Tests with mocked ClaudeClient
- Commit: "Add Claude reasoner for ambiguous track placement (TDD for prompt/parsing)"

### Step 7: File mover
- Create backend/services/file_mover.py
- Implement move_file(), move_files_batch(), cleanup_empty_dirs()
- Tests: move, collision handling, missing source, empty dir cleanup, DB updates
- Commit: "Add file mover with collision handling and directory cleanup"

### Step 8: Organisation pipeline
- Create backend/services/organiser.py
- Implement propose_organisation() and execute_organisation()
- SSE events, cancellation, per-track error isolation
- Tests with mocked dependencies
- Commit: "Add organisation pipeline with proposal and execution phases"

### Step 9: API routes
- Create backend/routes/organise.py
- Implement all endpoints: propose, progress (SSE), cancel, proposal, approve, resolve/{id}, preferences CRUD
- Extend GET /api/tracks with organisation fields
- Register in main.py
- Test all endpoints
- Commit: "Add organisation API routes with proposal, approval, and preferences"

### Step 10: Frontend
- Create: OrganiseControls, ProposalSummary, ReviewQueue, PreferenceRulesPanel
- Extend TrackTable: organisation_status column, filter modes
- Extend API client: all organisation and preference endpoints
- Commit: "Add organisation UI with review queue and preference management"

### Step 11: Integration tests and cleanup
- End-to-end: ingest → analyse → AI tag → propose → approve → verify files moved
- Preference rule creation from review flow
- Re-organisation test
- Update CLAUDE.md
- Commit: "Add integration tests and update project docs for Phase 2b"

## Constraints
- Follow all conventions in CLAUDE.md (type hints, docstrings, error handling, logging, etc.)
- File moves via shutil.move wrapped in asyncio.to_thread()
- Do NOT modify Phase 1, 2, or 3 service code
- Dry-run (propose) is the default — nothing moves without explicit approval
- Source files (source_path) are NEVER touched — only output files are moved
- All exceptions should be RekordBotError subclasses
- Every service module gets its own logger via logging.getLogger(__name__)
- Use %s string formatting in log calls (not f-strings)
- Preference rules are created from user actions in the review queue — not pre-populated

## Important
- Do NOT implement auto-organise on import — batch-only, user-triggered
- Do NOT implement undo/revert for file moves (previous_output_path is recorded for future use)
- Do NOT implement near-duplicate detection (audio fingerprinting is out of scope)
- Do NOT implement a visual template editor (template is a string in Settings)
- Do NOT implement regex-based preference rules — simple key-value lookups only
- Source files are NEVER moved, modified, or deleted
- Files are NEVER moved without explicit user approval
```

### Continuation Prompt

If the session is interrupted and you need to resume in a new Claude Code session, use this:

```
We are continuing Phase 2b (File Organisation & Structure) of rekordbot.

Read these files for context:
- CLAUDE.md (project conventions and current status)
- SESSIONS.md (latest entry has where we left off and what's next)
- docs/features/phase-2b-file-organisation.md (the feature specification)

Pick up from where we left off. Check SESSIONS.md for the last completed step
and what was identified as the next task. Confirm what you think the next step
is before writing any code.
```

---

## Notes

- The template engine's fallback syntax uses `|` as a separator, which is also a filesystem-unsafe character. This is fine because the `|` only appears in the template string (which is parsed, not used as a path), and the resolved path components go through `sanitise_path_component()` before being used as filesystem paths.
- The preference store's `apply_rules()` function modifies a `ResolvedPath` — it doesn't operate on raw strings. This ensures the resolved components dict stays in sync with the actual path.
- The file mover's `cleanup_empty_dirs()` should only clean within the output directory. It must NEVER traverse above the output directory root. Implement a safety check that verifies every directory being removed is a child of `output_directory`.
- The Claude reasoner batches ambiguous tracks to reduce API calls, but the batch size should be smaller than Phase 3's genre tagging (default 5 instead of 20) because the prompt per track is more detailed (includes template, resolved path, confidence factors, and flags).
- When re-organising already-organised tracks, the pipeline should use the current `output_path` (not `previous_output_path`) as the source for the move. The `previous_output_path` is updated to the current path before the new move.
- Integration tests should use `tmp_path` fixtures for file operations rather than creating files in the project directory.
