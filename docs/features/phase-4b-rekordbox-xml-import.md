# Feature: Rekordbox XML Import
**Branch:** `feature/phase-4b-xml-import`
**Status:** Not Started
**Phase:** 4b
**Depends on:** Phase 6a (complete)

---

## Goal

Import an existing Rekordbox XML library into rekordbot, so users can bring their existing track collection — with all metadata and playlist structure — into the app and immediately use AI tagging, crate building, and set planning on their existing library.

This is a read-only operation on the user's files. No audio files are moved, copied, or modified. Tracks are pointed at in-place on disk. Playlists are imported as crates. Tracks that already exist in rekordbot are matched and merged, with the user reviewing any metadata conflicts.

---

## Inputs

- A Rekordbox XML file (exported via File → Export Library in Rekordbox 6 or 7)
- The existing rekordbot Track database (may be empty or may contain tracks from prior ingestion)
- Research document: `docs/research/rekordbox-xml-cdj-compatibility.md`

## Outputs

- New Track records in the database for every importable track in the XML
- Metadata populated from XML attributes (title, artist, BPM, key, genre, rating, etc.)
- Imported tracks available to all downstream features (analysis, AI tagging, organisation, crates, sets, export)
- Playlists imported as crates with `assignment_method="imported"`
- Conflict review for tracks that match existing rekordbot records
- Import summary: tracks imported, tracks matched, tracks skipped (missing files), conflicts to review

---

## Decisions (Finalised)

| # | Question | Decision |
|---|---|---|
| 1 | What is the match strategy for duplicates? | File path matching as primary (decoded XML Location URI vs `output_path` in DB). SHA-256 file hash as secondary. If neither matches, create a new track. |
| 2 | What happens when a match is found? | Rekordbox values are imported as primary for all fields. If the matched rekordbot track has values that differ, those differences are flagged as conflicts for user review. |
| 3 | Who wins for BPM/key on matched tracks? | Rekordbox wins. Rekordbox BPM is authoritative because it determines the CDJ beat grid. If the user later runs analysis, the existing revert mechanism preserves the Rekordbox values in `source_bpm`/`source_key`. |
| 4 | Who wins for genre/rating/comments on matched tracks? | Rekordbox wins. These represent the user's manual curation. rekordbot's AI-generated values go to conflict review so the user can choose. |
| 5 | What about tracks in the XML whose files don't exist on disk? | Skipped with a warning. Not fatal — the import continues. Summary reports how many were skipped and why. |
| 6 | Are playlists imported? | Yes, as crates with `assignment_method="imported"`. Folder nodes in the XML become the crate name prefix (e.g. "My Folder/My Playlist"). |
| 7 | Does import trigger analysis or AI tagging? | No. Imported tracks enter the DB with `analysis_status="not_analysed"` and `ai_status="untagged"`. The user decides when to run those pipelines. |
| 8 | What status do imported tracks get? | A new `import_source` field on Track records the origin: `"rekordbox_xml"` for imported tracks, `null` for ingested tracks. Tracks also get `conversion_action="imported"` (no conversion was performed). |
| 9 | SSE progress? | Yes. Large libraries (10k+ tracks) need progress reporting. Same pattern as ingestion pipeline. |
| 10 | What about TEMPO and POSITION_MARK elements? | Ignored for now. We don't have beat grid or cue point support in the data model. Logged at DEBUG level for future reference. |

---

## Architecture & Key Components

### 1. XML Parser (`backend/services/xml_parser.py`)

Parses a Rekordbox XML file and extracts track data and playlist structure. Pure logic — TDD candidate.

**Parsing approach:** Use `xml.etree.ElementTree` (same library as the export side). Parse iteratively with `ET.iterparse()` for memory efficiency on large files.

**Functions:**

- `parse_rekordbox_xml(file_path: Path) -> ParsedLibrary` — parse the full XML, return structured data
- `parse_track_element(element: Element) -> ParsedTrack | None` — extract metadata from a single TRACK element, returns None if Location is missing
- `parse_playlists(playlists_node: Element) -> list[ParsedPlaylist]` — extract playlist structure from PLAYLISTS node
- `decode_location(location_uri: str) -> str | None` — convert `file://localhost/...` URI back to absolute file path. Returns None if the URI format is unrecognised.
- `parse_bpm(value: str | None) -> float | None` — "128.00" → 128.0
- `parse_rating(value: str | None) -> int | None` — non-linear scale (0/51/102/153/204/255) → 0–5
- `parse_tonality(value: str | None) -> int | None` — key string (any notation) → integer 1–24 (via existing `key_notation.py`)
- `validate_xml_structure(file_path: Path) -> tuple[bool, str]` — check that the file is valid Rekordbox XML (has DJ_PLAYLISTS root, COLLECTION, PLAYLISTS). Returns (valid, error_message).

**Data classes:**

```python
@dataclass
class ParsedTrack:
    """A track extracted from Rekordbox XML."""
    location: str               # Decoded absolute file path
    title: str | None
    artist: str | None
    album: str | None
    genre: str | None
    bpm: float | None
    key: int | None             # Integer 1–24 (Camelot mapping)
    rating: int | None          # 0–5 (converted from non-linear scale)
    duration: int | None        # Seconds
    bitrate: int | None         # kbps
    sample_rate: int | None     # Hz
    comment: str | None
    label: str | None
    remixer: str | None
    composer: str | None
    album_artist: str | None
    grouping: str | None
    year: int | None
    track_number: int | None
    disc_number: int | None
    date_added: str | None      # "yyyy-mm-dd"
    mix_name: str | None
    colour: str | None
    size: int | None            # Bytes (from XML, not verified against disk)
    kind: str | None            # "AIFF File", "MP3 File" etc.

@dataclass
class ParsedPlaylist:
    """A playlist extracted from Rekordbox XML."""
    name: str                   # Full path name e.g. "My Folder/Deep House"
    track_locations: list[str]  # Decoded file paths for tracks in this playlist

@dataclass
class ParsedLibrary:
    """Complete parsed Rekordbox library."""
    product_name: str | None
    product_version: str | None
    tracks: list[ParsedTrack]
    playlists: list[ParsedPlaylist]
```

**Location decoding rules (inverse of location_encoder.py):**
- Strip `file://localhost/` prefix
- Percent-decode each path component (`%20` → space, `%C3%82` → `Â`, etc.)
- Use `urllib.parse.unquote()` for decoding
- Validate the result is an absolute path (starts with `/` on macOS)

**Tonality parsing:**
- Rekordbox exports key in various formats depending on how it was set
- The existing `key_notation.py` module already handles parsing from Camelot ("8A"), Open Key ("6m"), and classical ("Am") notations
- A new `parse_key_string(value: str) -> int | None` function wraps the existing conversion, trying each notation and returning the integer 1–24 or None if unrecognised

### 2. Track Matcher (`backend/services/track_matcher.py`)

Determines whether a parsed track already exists in the rekordbot database. Pure logic (with DB queries) — TDD candidate for matching logic, tests-after for DB integration.

**Match strategy (ordered):**
1. **Path match:** Compare `ParsedTrack.location` against `Track.output_path` (case-sensitive exact match after path normalisation)
2. **Hash match:** If no path match and the file exists on disk, compute SHA-256 and compare against `Track.file_hash`
3. **No match:** Create as a new track

**Functions:**

- `find_match(parsed_track: ParsedTrack, db: Session) -> MatchResult` — run the match strategy, return result
- `find_path_match(location: str, db: Session) -> Track | None` — query by output_path
- `find_hash_match(file_path: str, db: Session) -> Track | None` — compute hash, query by file_hash
- `compute_file_hash(file_path: str) -> str` — SHA-256 hash (reuse existing logic from `converter.py`)
- `detect_conflicts(parsed: ParsedTrack, existing: Track) -> list[FieldConflict]` — compare fields, return list of differences

**Data classes:**

```python
@dataclass
class FieldConflict:
    """A metadata difference between Rekordbox and rekordbot."""
    field: str                  # e.g. "bpm", "genre", "rating"
    rekordbox_value: Any        # Value from the XML
    rekordbot_value: Any        # Value currently in the DB
    recommended: str            # "rekordbox" or "rekordbot" — which we recommend keeping

@dataclass
class MatchResult:
    """Result of attempting to match a parsed track to the database."""
    match_type: str             # "path", "hash", or "new"
    existing_track: Track | None
    conflicts: list[FieldConflict]
```

**Conflict detection rules:**
- BPM: flag if difference > 0.5 BPM. Recommend: "rekordbox" (beat grid authority).
- Key: flag if different. Recommend: "rekordbox" (consistency with CDJ display).
- Genre: flag if different and rekordbot value is AI-generated (`ai_status != "untagged"`). Recommend: "rekordbox" (user's manual curation).
- Rating: flag if different. Recommend: "rekordbox".
- Comments: flag if different and both non-empty. Recommend: "rekordbox".
- Title/artist/album: flag if different. Recommend: "rekordbox".
- Fields where both sides are None/empty: no conflict.
- Fields where only one side has a value: no conflict — take the non-empty value.

### 3. Import Service (`backend/services/xml_importer.py`)

Orchestrates the full import flow with SSE progress reporting.

**Import flow:**
1. Validate XML structure (`validate_xml_structure()`)
2. Parse XML (`parse_rekordbox_xml()`)
3. For each parsed track:
   a. Check file exists on disk — skip with warning if not
   b. Run match strategy (`find_match()`)
   c. If new: create Track record with all metadata from XML
   d. If matched with no conflicts: update any empty fields from XML (fill gaps only)
   e. If matched with conflicts: queue for user review
   f. Emit SSE progress event
4. Import playlists as crates
5. Return import summary

**New Track creation from XML data:**

```python
# Fields populated directly from XML
track = Track(
    title=parsed.title,
    artist=parsed.artist,
    album=parsed.album,
    genre=parsed.genre,
    bpm=parsed.bpm,
    key=parsed.key,
    rating=parsed.rating,
    duration=parsed.duration,
    comment=parsed.comment,
    label=parsed.label,
    remixer=parsed.remixer,
    composer=parsed.composer,
    album_artist=parsed.album_artist,
    grouping=parsed.grouping,
    year=parsed.year,
    track_number=parsed.track_number,
    disc_number=parsed.disc_number,
    mix_name=parsed.mix_name,
    sample_rate=parsed.sample_rate,
    source_bitrate=parsed.bitrate,

    # File identity
    output_path=parsed.location,    # Actual file path on disk
    file_hash=computed_hash,        # SHA-256 computed during import
    source_path=parsed.location,    # Same as output_path for imports (no conversion)

    # Import metadata
    import_source="rekordbox_xml",
    conversion_action="imported",
    imported_at=datetime.utcnow(),

    # Format detection (derived from file extension / Kind attribute)
    source_codec=derived_from_kind,  # e.g. "aiff", "mp3"

    # Status fields — imported tracks have not been through rekordbot pipelines
    analysis_status="not_analysed",
    ai_status="untagged",
    organisation_status="unorganised",
)
```

**Playlist → Crate import:**
- Each playlist node (Type=1) in the XML becomes a Crate
- Folder nodes (Type=0) are used as name prefixes: "Folder/Subfolder/Playlist Name"
- The ROOT node and the product name node (e.g. "rekordbox") are excluded from the prefix
- Crate fields:
  - `name`: playlist name (with folder prefix if nested)
  - `description`: "Imported from Rekordbox XML"
  - `auto_refresh`: False (imported crates are static snapshots)
- Track assignments use `assignment_method="imported"`
- If a crate with the same name already exists, skip it with a warning (don't merge)

**SSE events:**
- `xml_import_progress`: `{processed: int, total: int, imported: int, matched: int, skipped: int, conflicts: int}`
- `xml_import_complete`: `{summary: ImportSummary}`
- `xml_import_error`: `{error: str, detail: str}`

**Data classes:**

```python
@dataclass
class ImportSummary:
    """Result of an XML import operation."""
    tracks_total: int           # Total tracks in XML
    tracks_imported: int        # New tracks created
    tracks_matched: int         # Existing tracks found (no conflicts)
    tracks_conflict: int        # Existing tracks with conflicts (pending review)
    tracks_skipped: int         # Tracks skipped (file not found, etc.)
    skipped_reasons: list[str]  # Why each track was skipped
    playlists_imported: int     # Playlists converted to crates
    playlists_skipped: int      # Playlists skipped (duplicate name, etc.)

@dataclass
class ImportConflict:
    """A track with metadata conflicts pending user review."""
    track_id: int               # DB track ID of the matched track
    parsed_track: ParsedTrack   # The XML data
    conflicts: list[FieldConflict]
```

### 4. Conflict Resolver (`backend/services/conflict_resolver.py`)

Handles user decisions on metadata conflicts.

**Functions:**
- `get_pending_conflicts(db: Session) -> list[ImportConflict]` — load all unresolved conflicts
- `resolve_conflict(track_id: int, resolutions: dict[str, str], db: Session) -> Track` — apply user's choices. `resolutions` maps field names to "rekordbox" or "rekordbot".
- `resolve_all_rekordbox(db: Session) -> int` — bulk resolve: accept Rekordbox values for all conflicts. Returns count resolved.
- `resolve_all_rekordbot(db: Session) -> int` — bulk resolve: keep rekordbot values for all conflicts. Returns count resolved.

**Conflict storage:**
Conflicts are stored as JSON in a new `import_conflicts` column on the Track model (`Text`, nullable). This is a temporary field — once resolved, it's set to None. Format:

```json
[
    {"field": "bpm", "rekordbox_value": 128.0, "rekordbot_value": 127.5, "recommended": "rekordbox"},
    {"field": "genre", "rekordbox_value": "Deep House", "rekordbot_value": "House", "recommended": "rekordbox"}
]
```

This avoids a separate conflicts table and keeps the resolution logic simple — resolved means `import_conflicts IS NULL`.

### 5. Import API Routes (`backend/routes/import_xml.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/import/rekordbox` | Start XML import (accepts file path in body) |
| GET | `/api/import/progress` | SSE stream for import progress |
| POST | `/api/import/cancel` | Cancel in-progress import |
| GET | `/api/import/conflicts` | Get all pending conflicts |
| POST | `/api/import/conflicts/{track_id}/resolve` | Resolve a single track's conflicts |
| POST | `/api/import/conflicts/resolve-all` | Bulk resolve all conflicts |

**POST `/api/import/rekordbox` request:**
```json
{
    "file_path": "/Users/daleb/Music/rekordbox.xml"
}
```

**POST `/api/import/conflicts/{track_id}/resolve` request:**
```json
{
    "resolutions": {
        "bpm": "rekordbox",
        "genre": "rekordbot"
    }
}
```

**POST `/api/import/conflicts/resolve-all` request:**
```json
{
    "strategy": "rekordbox"   // or "rekordbot"
}
```

### 6. Track Model Changes

**New fields on Track:**
- `import_source: str | None` — `"rekordbox_xml"` for imported tracks, `None` for ingested tracks
- `import_conflicts: str | None` — JSON array of unresolved conflicts (see §4), `None` when resolved or no conflicts

**No new model classes.** Conflicts are stored on the Track itself because they're temporary and tightly coupled to the track they belong to.

### 7. Frontend — Import UI

**ImportControls.tsx** — New toolbar section alongside ExportControls.

- "Import XML" button (teal/cyan — visually distinct from other toolbar actions)
- Click opens a file picker dialog (Tauri) filtered to `.xml` files
- On file selection, starts the import and shows progress bar
- On completion, shows summary: "Imported 1,234 tracks, 56 matched, 12 conflicts to review, 8 skipped"
- If conflicts exist, shows "Review Conflicts" button

**ConflictReviewPanel.tsx** — Conflict resolution UI.

- Table showing tracks with conflicts
- Per-track: expand to see field-by-field comparison (rekordbox value vs rekordbot value, recommended choice highlighted)
- Per-field toggle: "Use Rekordbox" / "Use rekordbot"
- Per-track: "Apply" button to resolve that track
- Bulk actions at top: "Accept All Rekordbox" / "Keep All rekordbot"
- Count of remaining conflicts shown

**CrateSidebar.tsx** — No structural changes needed. Imported crates appear automatically alongside existing crates.

**API client extension:**
- `importRekordboxXml(filePath: string)` — POST to import endpoint
- `getImportProgress()` — SSE consumer
- `cancelImport()` — POST cancel
- `getImportConflicts()` — GET conflicts
- `resolveConflict(trackId: number, resolutions: Record<string, string>)` — POST resolve
- `resolveAllConflicts(strategy: string)` — POST resolve-all
- Types: `ImportSummary`, `ImportConflict`, `FieldConflict`, `ImportProgress`

---

## Acceptance Criteria

### XML parsing
- [ ] Valid Rekordbox XML (v6 and v7 exports) parsed successfully
- [ ] All TRACK attributes extracted correctly
- [ ] Location URIs decoded to absolute file paths
- [ ] Percent-encoded characters decoded correctly (spaces, unicode, special chars)
- [ ] BPM parsed from "128.00" format to float
- [ ] Rating converted from non-linear scale (0/51/102/153/204/255) to 0–5
- [ ] Key/Tonality parsed from any notation (Camelot, Open Key, classical) to integer 1–24
- [ ] Playlist tree structure extracted with folder path prefixes
- [ ] Malformed XML returns clear error, not a crash
- [ ] TEMPO and POSITION_MARK elements ignored without error

### Track matching
- [ ] Path match: decoded Location vs output_path in DB
- [ ] Hash match: SHA-256 computed for unmatched tracks with files on disk
- [ ] New tracks created when no match found
- [ ] Matched tracks with no differences: only empty fields filled from XML
- [ ] Matched tracks with differences: conflicts queued for review

### Conflict detection
- [ ] BPM difference > 0.5 flagged as conflict
- [ ] Key difference flagged as conflict
- [ ] Genre difference flagged (only if rekordbot value is AI-generated)
- [ ] Rating difference flagged
- [ ] Title/artist/album difference flagged
- [ ] Both-empty fields: no conflict
- [ ] One-side-only values: auto-merged (no conflict)

### Conflict resolution
- [ ] Per-track, per-field resolution works
- [ ] Bulk "accept all Rekordbox" works
- [ ] Bulk "keep all rekordbot" works
- [ ] Resolved conflicts clear the `import_conflicts` field
- [ ] Resolved tracks reflect the chosen values

### Import pipeline
- [ ] Tracks with missing files skipped with warning
- [ ] Import creates Track records with correct metadata
- [ ] Import sets `import_source="rekordbox_xml"` and `conversion_action="imported"`
- [ ] Imported tracks have `analysis_status="not_analysed"` and `ai_status="untagged"`
- [ ] File hash computed and stored during import
- [ ] Source codec derived from file extension / Kind attribute
- [ ] SSE progress events emitted during import
- [ ] Import is cancellable
- [ ] Import summary accurate (counts match reality)

### Playlist import
- [ ] XML playlists become crates with `assignment_method="imported"`
- [ ] Folder hierarchy preserved in crate names (prefix)
- [ ] Root and product-name nodes excluded from prefix
- [ ] Track assignments reference correct DB track IDs
- [ ] Duplicate crate names skipped with warning
- [ ] Empty playlists imported (crate with no tracks)

### Frontend
- [ ] Import button opens file picker for .xml files
- [ ] Progress bar during import
- [ ] Summary shown on completion
- [ ] Conflict review panel shows all unresolved conflicts
- [ ] Per-field comparison with toggle
- [ ] Bulk resolve actions work
- [ ] Imported crates visible in sidebar

### Round-trip
- [ ] Import tracks → export XML → import into Rekordbox → all metadata intact
- [ ] Import tracks → run analysis → export → Rekordbox BPM matches original (via revert)

---

## Out of Scope

- **TEMPO elements (beat grid)** — not supported in rekordbot's data model
- **POSITION_MARK elements (cue points, loops)** — not supported in data model
- **Artwork import** — not tracked in DB
- **Colour import** — stored but not surfaced in UI
- **History/play count import** — not tracked by rekordbot
- **Merging playlists with existing crates** — duplicate names are skipped, not merged
- **Automatic re-analysis of imported tracks** — user decides when to analyse
- **Windows path support** — Mac-first, Windows paths deferred
- **Drag-and-drop XML import** — file picker only
- **Multiple XML file import** — one file at a time
- **Rekordbox database import (.edb)** — XML only

---

## TDD Candidates

| Module | Reason |
|---|---|
| `xml_parser.py` — `decode_location()` | URI decoding is the inverse of location_encoder, pure string logic |
| `xml_parser.py` — `parse_track_element()` | Attribute extraction with type conversion, many edge cases |
| `xml_parser.py` — `parse_bpm()`, `parse_rating()`, `parse_tonality()` | Pure conversion functions |
| `xml_parser.py` — `parse_playlists()` | Tree traversal with name prefixing |
| `track_matcher.py` — `detect_conflicts()` | Pure comparison logic with threshold rules |
| `conflict_resolver.py` — `resolve_conflict()` | Field-level resolution logic |

---

## Build Order

### Step 1: Track model changes
- Add `import_source` and `import_conflicts` fields to Track model
- Tests for new fields (nullable, default None)
- Commit: "Add import_source and import_conflicts fields to Track model"

### Step 2: XML parser (TDD)
- Create `backend/services/xml_parser.py`
- WRITE TESTS FIRST for: `decode_location()`, `parse_bpm()`, `parse_rating()`, `parse_tonality()`, `parse_track_element()`, `parse_playlists()`, `validate_xml_structure()`
- Create test XML fixtures (minimal valid XML, large collection, malformed XML, nested playlists)
- Commit: "Add Rekordbox XML parser with location decoding and metadata extraction (TDD)"

### Step 3: Track matcher (TDD for conflict detection)
- Create `backend/services/track_matcher.py`
- WRITE TESTS FIRST for `detect_conflicts()` — the pure comparison logic
- Implement `find_match()`, `find_path_match()`, `find_hash_match()`
- Tests for matching strategies (path match, hash match, no match)
- Commit: "Add track matcher with path/hash matching and conflict detection"

### Step 4: Conflict resolver
- Create `backend/services/conflict_resolver.py`
- Implement `resolve_conflict()`, `resolve_all_rekordbox()`, `resolve_all_rekordbot()`, `get_pending_conflicts()`
- Tests for per-field resolution, bulk resolution, conflict clearing
- Commit: "Add conflict resolver for import metadata conflicts"

### Step 5: Import service
- Create `backend/services/xml_importer.py`
- Implement full import pipeline with SSE progress
- Playlist → crate import logic
- Tests: import new tracks, import with matches, import with conflicts, skip missing files, playlist import, cancellation
- Commit: "Add XML import service with SSE progress and playlist-to-crate conversion"

### Step 6: Import API routes
- Create `backend/routes/import_xml.py`
- Implement all 6 endpoints
- Register in main.py
- Tests for all endpoints
- Commit: "Add Rekordbox XML import API routes"

### Step 7: Frontend — Import UI
- Create `ImportControls.tsx` with file picker and progress
- Create `ConflictReviewPanel.tsx` with per-field comparison and bulk actions
- Extend API client with import types and endpoints
- Wire into App.tsx toolbar
- Commit: "Add Rekordbox XML import UI with conflict review"

### Step 8: Integration tests and docs
- End-to-end: parse XML → import → verify DB records → resolve conflicts → export → verify round-trip
- Large XML file handling (synthetic 1000-track XML)
- Playlist structure preservation
- Match strategy coverage (path, hash, new)
- Update CLAUDE.md with Phase 4b status
- Update SESSIONS.md
- Commit: "Add integration tests and update project docs for Phase 4b"

---

## Claude Code Prompt

```
You are implementing Phase 4b (Rekordbox XML Import) of rekordbot.

Read these files first:
- CLAUDE.md (project conventions, architecture, coding standards)
- docs/features/phase-4b-rekordbox-xml-import.md (the feature brief — this is your specification)
- docs/research/rekordbox-xml-cdj-compatibility.md (Rekordbox XML format research)
- backend/models/track.py (Track model — you'll add import_source and import_conflicts fields)
- backend/services/location_encoder.py (existing Location encoding — your parser is the inverse)
- backend/services/key_notation.py (existing key conversion — reuse for tonality parsing)
- backend/services/converter.py (existing SHA-256 hash logic — reuse for hash matching)
- backend/services/xml_schema_mapper.py (existing schema mapper — reference for attribute names)
- backend/services/xml_builder.py (existing XML builder — reference for XML structure)
- backend/services/crate_manager.py (existing crate CRUD — reuse for playlist import)
- backend/models/crate.py (Crate and CrateTrack models)
- backend/routes/ (all existing route files — reference for patterns)
- frontend/src/ExportControls.tsx (reference for toolbar pattern)
- frontend/src/api/client.ts (existing API client — you'll extend)

## What you're building

A Rekordbox XML import pipeline that:
1. Parses a Rekordbox XML file and extracts all track metadata and playlist structure
2. Matches parsed tracks against the existing database (by file path, then SHA-256 hash)
3. Creates new Track records for unmatched tracks (pointing at existing files on disk)
4. Detects metadata conflicts for matched tracks and queues them for user review
5. Imports playlists as crates with assignment_method="imported"
6. Reports progress via SSE and provides a summary on completion
7. Provides a conflict review UI for resolving metadata differences

## Build order (follow this exactly)

### Step 1: Track model changes
- Add import_source (String, nullable) and import_conflicts (Text, nullable) to Track model
- Tests for new fields
- Commit: "Add import_source and import_conflicts fields to Track model"

### Step 2: XML parser (TDD)
- Create backend/services/xml_parser.py
- WRITE TESTS FIRST for all pure logic: decode_location, parse_bpm, parse_rating, parse_tonality, parse_track_element, parse_playlists, validate_xml_structure
- Create test XML fixtures
- Commit: "Add Rekordbox XML parser with location decoding and metadata extraction (TDD)"

### Step 3: Track matcher (TDD for conflict detection)
- Create backend/services/track_matcher.py
- WRITE TESTS FIRST for detect_conflicts() — the pure comparison logic
- Implement find_match, find_path_match, find_hash_match
- Reuse SHA-256 hash computation from converter.py
- Commit: "Add track matcher with path/hash matching and conflict detection"

### Step 4: Conflict resolver
- Create backend/services/conflict_resolver.py
- Implement resolve_conflict, resolve_all_rekordbox, resolve_all_rekordbot, get_pending_conflicts
- Tests for per-field resolution, bulk resolution, conflict clearing
- Commit: "Add conflict resolver for import metadata conflicts"

### Step 5: Import service
- Create backend/services/xml_importer.py
- Full import pipeline: validate → parse → match → create/update → import playlists
- SSE progress events, cancellation support
- Playlist → crate conversion with folder path prefixing
- Tests: new tracks, matches, conflicts, missing files, playlists, cancel
- Commit: "Add XML import service with SSE progress and playlist-to-crate conversion"

### Step 6: Import API routes
- Create backend/routes/import_xml.py
- POST /api/import/rekordbox, GET progress (SSE), POST cancel, GET conflicts, POST resolve, POST resolve-all
- Register in main.py
- Tests for all endpoints
- Commit: "Add Rekordbox XML import API routes"

### Step 7: Frontend — Import UI
- ImportControls.tsx (file picker, progress bar, summary)
- ConflictReviewPanel.tsx (per-field comparison, per-track resolve, bulk actions)
- Extend API client with import types and endpoints
- Wire into App.tsx
- Commit: "Add Rekordbox XML import UI with conflict review"

### Step 8: Integration tests and docs
- End-to-end: parse → import → conflicts → resolve → export → verify round-trip
- Large XML handling, playlist structure, match strategies
- Update CLAUDE.md and SESSIONS.md
- Commit: "Add integration tests and update project docs for Phase 4b"

## Constraints
- Follow all conventions in CLAUDE.md
- Do NOT modify any Phase 1/2/2b/3/4/5a/5b/6a service code (except reusing existing functions)
- Reuse existing exception hierarchy — add ImportError as a new RekordBotError subclass
- XML parsing uses stdlib xml.etree.ElementTree — no lxml
- Location decoding uses stdlib urllib.parse.unquote — no custom decoding
- SHA-256 hashing reuses the existing pattern from converter.py
- Key parsing reuses existing key_notation.py functions
- Crate creation reuses existing Crate/CrateTrack models
- All new backend modules get their own logger via logging.getLogger(__name__)
- Use %s string formatting in log calls (not f-strings)
- Use sync SQLAlchemy (not async)

## Important
- Do NOT import TEMPO or POSITION_MARK elements
- Do NOT move or copy any audio files — tracks point at existing files in-place
- Do NOT auto-trigger analysis or AI tagging on imported tracks
- Do NOT merge playlists with existing crates (skip duplicates)
- Do NOT implement Windows path support
- Do NOT implement Rekordbox .edb database import
- Rekordbox BPM is authoritative — it determines the CDJ beat grid
- Conflict review is the PRIMARY mechanism for metadata differences — no auto-overwrite
- Imported tracks enter with analysis_status="not_analysed" and ai_status="untagged"
- Playlist folder structure is flattened into crate name prefixes (not nested crates)
```

### Continuation Prompt

```
We are continuing Phase 4b (Rekordbox XML Import) of rekordbot.

Read these files for context:
- CLAUDE.md (project conventions and current status)
- SESSIONS.md (latest entry has where we left off and what's next)
- docs/features/phase-4b-rekordbox-xml-import.md (the feature specification)
- docs/research/rekordbox-xml-cdj-compatibility.md (Rekordbox XML format research)

Pick up from where we left off. Check SESSIONS.md for the last completed step
and what was identified as the next task. Confirm what you think the next step
is before writing any code.
```

---

## Notes

- The `decode_location()` function is the exact inverse of `encode_location()` in `location_encoder.py`. We should verify round-trip behaviour: `decode_location(encode_location(path)) == path` for all our test paths.
- File hashing during import is potentially slow for large libraries (thousands of tracks). The hash is only computed when path matching fails, so in practice most tracks will match on path and skip the hash entirely. For the remaining unmatched tracks, hashing runs during the import loop which already has SSE progress reporting.
- The `import_conflicts` JSON column is intentionally denormalised. Conflicts are temporary (resolved once during import review, then the field is cleared) and tightly coupled to their track. A separate conflicts table would add join complexity for minimal benefit.
- Imported tracks get `source_path = output_path` because from rekordbot's perspective, the file at that location is both the "source" (where we found it) and the "output" (where it lives). There was no conversion step.
- The `source_codec` field is derived from the Kind attribute ("AIFF File" → "aiff", "MP3 File" → "mp3") or by inspecting the file extension if Kind is missing. This doesn't run ffprobe — it's a string derivation.
- Genre conflict detection has a special case: if the rekordbot value was set by AI tagging (`ai_status != "untagged"`), it's flagged as a conflict because the user's manual Rekordbox genre should take precedence over AI inference. If the rekordbot genre was manually set by the user (imported or edited), it's still flagged but with a "rekordbot" recommendation instead.
