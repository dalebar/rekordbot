# Feature: Rekordbox XML Export
**Branch:** `feature/phase-4-rekordbox`
**Status:** Complete ✅
**Phase:** 4
**Depends on:** Phase 2b (complete)

---

## Goal

Export the rekordbot library as a Rekordbox-compatible XML file that can be imported into Rekordbox via File → Import Library, and used to prepare USB drives for CDJ playback. The XML contains the full track collection with all metadata from Phases 1–3, using the final organised file paths from Phase 2b.

This is export-only. Importing an existing Rekordbox XML into rekordbot is deferred to Phase 4b.

---

## Inputs

- All tracks in the SQLite database with metadata from Phases 1–3 and organised paths from Phase 2b
- User preferences (from settings):
  - `rekordbox_xml_path`: str — where to write the XML file (default: `{output_directory}/rekordbox.xml`)
  - `default_key_notation`: str — how to write the Tonality field (already exists)
- Research document: `docs/research/rekordbox-xml-cdj-compatibility.md`

## Outputs

- A `rekordbox.xml` file conforming to Pioneer's XML format spec (Version 1.0.0)
- Track entries with all metadata mapped to Rekordbox's TRACK attribute schema
- Playlist structure: "All Tracks" playlist + one playlist per top-level artist folder
- Export summary showing tracks exported, skipped, warnings

---

## Architecture & Key Components

### 1. Location Encoder (`backend/services/location_encoder.py`)

Converts absolute file paths to Rekordbox-compatible `file://localhost/` URIs. Pure logic — TDD candidate.

**Encoding rules (from research doc §1.3):**
- Prefix: `file://localhost/` (macOS — no drive letter)
- Path separator: `/` (forward slash always, even on Windows)
- Percent-encode each path component individually — `/` separators must NOT be encoded
- Characters to encode: spaces → `%20`, `#` → `%23`, `&` → `%26`, and any other non-unreserved characters per RFC 3986
- Unicode characters are percent-encoded as UTF-8 bytes (e.g. `Â` → `%C3%82`)
- The result is then XML-attribute-safe (ElementTree handles `&` → `&amp;` automatically)

**Examples:**
```
/Users/daleb/rekordbot/library/Calibre/Shelflife 6/Falls to You.aiff
→ file://localhost/Users/daleb/rekordbot/library/Calibre/Shelflife%206/Falls%20to%20You.aiff

/Users/daleb/rekordbot/library/Âme/Rej.aiff
→ file://localhost/Users/daleb/rekordbot/library/%C3%82me/Rej.aiff
```

**Functions:**
- `encode_location(absolute_path: str) -> str` — full path → Rekordbox Location URI
- `encode_path_component(component: str) -> str` — single path component → percent-encoded string

**Implementation note:** Python's `urllib.parse.quote()` with `safe=""` handles RFC 3986 encoding per-component. Split the path on `/`, encode each component, rejoin with `/`, then prepend `file://localhost/`.

### 2. Schema Mapper (`backend/services/xml_schema_mapper.py`)

Maps Track model fields to Rekordbox XML TRACK element attributes. Pure logic — TDD candidate.

**Rekordbox TRACK attribute mapping (from research doc §1.2):**

| XML Attribute | Source | Format | Notes |
|---|---|---|---|
| `TrackID` | sequential int | int | Assigned at export time, 1-indexed |
| `Name` | Track.title | string | XML-escaped. Fallback to filename stem if None |
| `Artist` | Track.artist | string | XML-escaped. Fallback to "Unknown Artist" if None |
| `Composer` | Track.composer | string | Omit if None |
| `Album` | Track.album | string | XML-escaped. Empty string if None |
| `AlbumArtist` | Track.album_artist | string | Omit if None |
| `Grouping` | Track.grouping | string | Omit if None |
| `Genre` | Track.genre | string | XML-escaped |
| `Kind` | derived from output_path extension | string | "AIFF File", "MP3 File", "M4A File" |
| `Size` | file size in bytes | int | Read from filesystem at export time. 0 if missing |
| `TotalTime` | Track.duration | int | Integer seconds (truncated, not rounded) |
| `DiscNumber` | Track.disc_number | int | 0 if None |
| `TrackNumber` | Track.track_number | int | 0 if None |
| `Year` | Track.year | int | 0 if None |
| `AverageBpm` | Track.bpm | string | Two-decimal float: "128.00". "0.00" if None |
| `DateModified` | file mtime | string | Format: "yyyy-mm-dd" |
| `DateAdded` | Track.imported_at | string | Format: "yyyy-mm-dd" |
| `BitRate` | Track.bitrate | int | kbps. 0 if None |
| `SampleRate` | Track.sample_rate | int | Hz. 0 if None |
| `Comments` | Track.comment | string | XML-escaped. Empty string if None |
| `PlayCount` | 0 | int | rekordbot doesn't track play counts |
| `Rating` | Track.rating | int | Non-linear: 0→0, 1→51, 2→102, 3→153, 4→204, 5→255 |
| `Location` | Track.output_path → URI | string | Via location_encoder. The critical field |
| `Remixer` | Track.remixer | string | Omit if None |
| `Tonality` | Track.key → notation string | string | Via key_notation module, using user's preferred notation |
| `Label` | Track.label | string | XML-escaped. Omit if None |
| `Mix` | Track.mix_name | string | Omit if None |
| `Colour` | "0" | string | Default — colour coding deferred |

**Attributes NOT exported (deferred):**
- `TEMPO` elements (beatgrid) — requires waveform analysis
- `POSITION_MARK` elements (cue points, loops) — requires manual setting or import
- Artwork path — not tracked in DB

**Functions:**
- `track_to_xml_attrs(track: Track, output_directory: str) -> TrackXmlResult` — map a Track to XML attribute dict
- `format_bpm(bpm: float | None) -> str` — "128.00" format, "0.00" if None
- `format_rating(rating: int | None) -> str` — 0–5 → non-linear scale string
- `format_kind(output_path: str) -> str` — derive "AIFF File" / "MP3 File" from extension
- `format_date(dt: datetime | None) -> str` — datetime → "yyyy-mm-dd", empty string if None
- `get_file_size(path: str) -> int` — file size in bytes, 0 if file not found

**Return type:**
```
TrackXmlResult:
    attrs: dict[str, str]       # all attributes as strings, ready for ElementTree
    warnings: list[str]         # issues: missing file, null required field, etc.
```

### 3. XML Builder (`backend/services/xml_builder.py`)

Generates the complete Rekordbox XML document using `xml.etree.ElementTree`.

**XML structure (from research doc §1.1):**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <PRODUCT Name="rekordbot" Version="0.1.0" Company=""/>
  <COLLECTION Entries="150">
    <TRACK TrackID="1" Name="Falls to You" Artist="Calibre" ... />
    <TRACK TrackID="2" Name="Glue" Artist="Bicep" ... />
  </COLLECTION>
  <PLAYLISTS>
    <NODE Type="0" Name="ROOT" Count="1">
      <NODE Type="0" Name="rekordbot" Count="3">
        <NODE Type="1" Name="All Tracks" KeyType="0" Entries="150">
          <TRACK Key="1"/>
          <TRACK Key="2"/>
        </NODE>
        <NODE Type="1" Name="Calibre" KeyType="0" Entries="5">
          <TRACK Key="1"/>
        </NODE>
        <NODE Type="1" Name="Bicep" KeyType="0" Entries="3">
          <TRACK Key="2"/>
        </NODE>
      </NODE>
    </NODE>
  </PLAYLISTS>
</DJ_PLAYLISTS>
```

**Playlist structure for Phase 4:**
- Root NODE (Type=0, Name="ROOT")
  - "rekordbot" folder NODE (Type=0)
    - "All Tracks" playlist NODE (Type=1) — every exported track
    - One playlist per top-level folder from organised paths (typically artist names)
- Playlists reference tracks by TrackID using KeyType="0" (research doc §1.7)
- Track Key values must match TrackID values in COLLECTION

**NODE types (research doc §1.7):**
- Type=0: folder (contains other NODEs)
- Type=1: playlist (contains TRACK references)
- KeyType=0: tracks referenced by TrackID

**Functions:**
- `build_xml(tracks: list[Track], output_directory: str) -> ElementTree` — build complete XML tree
- `build_collection(tracks: list[Track], output_directory: str) -> tuple[Element, dict[int, int]]` — COLLECTION element + mapping of DB track ID → XML TrackID
- `build_playlists(tracks: list[Track], track_id_map: dict[int, int], output_directory: str) -> Element` — PLAYLISTS element with auto-generated structure
- `write_xml(tree: ElementTree, output_path: Path) -> None` — write to file with declaration and UTF-8 encoding
- `generate_playlist_structure(tracks: list[Track], track_id_map: dict[int, int], output_directory: str) -> Element` — derive folder-based playlists from organised paths

**XML writing rules (research doc §1.10):**
- XML declaration mandatory: `<?xml version="1.0" encoding="UTF-8"?>`
- UTF-8 encoding, no BOM
- Self-closing TRACK tags (no child elements in Phase 4)
- Empty strings for unset text fields (matches Rekordbox's own output)
- Entries counts must be accurate
- Numeric fields are locale-independent (dot decimal separator, no thousands separators)

### 4. Export Service (`backend/services/xml_exporter.py`)

Orchestrates the full export flow.

**Export flow:**
1. Load all tracks from DB (or specified subset via track_ids)
2. Filter to only tracks with a valid `output_path` (skip tracks still in ingestion)
3. Map each track to XML attributes via schema mapper
4. Collect warnings (missing files, null required fields)
5. Auto-generate playlist structure from organised folder hierarchy
6. Build complete XML tree via xml_builder
7. Write to configured output path
8. Return export summary

**Functions:**
- `export_library(db_session, settings, track_ids: list[int] | None = None, output_path: str | None = None) -> ExportResult`

**Return type:**
```
ExportResult:
    tracks_exported: int
    tracks_skipped: int             # missing file, no output_path
    playlists_created: int
    warnings: list[str]             # per-track warnings
    output_path: str
```

**Error handling:**
- Track with missing output file → skip with warning, continue export
- Track with no title → use filename stem as fallback
- Track with no artist → use "Unknown Artist" as fallback
- Any individual track failure → skip, don't abort the export
- Output directory not writable → raise ExportError before starting

### 5. API Routes (`backend/routes/export.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/export/rekordbox` | Trigger XML export |
| GET | `/api/export/rekordbox/status` | Current export status and last result |

**POST `/api/export/rekordbox` request body:**
```json
{
  "options": {
    "track_ids": null,
    "output_path": null
  }
}
```
If `track_ids` is null, export all tracks. If `output_path` is null, use the configured default.

**POST `/api/export/rekordbox` response:**
```json
{
  "tracks_exported": 148,
  "tracks_skipped": 2,
  "playlists_created": 25,
  "output_path": "/Users/daleb/rekordbot/library/rekordbox.xml",
  "warnings": ["Track 42: file not found at /library/..."]
}
```

**GET `/api/export/rekordbox/status` response:**
```json
{
  "status": "idle",
  "last_export": {
    "timestamp": "2026-03-08T14:30:00Z",
    "tracks_exported": 148,
    "output_path": "/Users/daleb/rekordbot/library/rekordbox.xml"
  }
}
```

**Design note:** XML export for a typical DJ library (hundreds to low thousands of tracks) completes in under a second. SSE progress is not needed. If profiling later shows large libraries (10k+ tracks) take noticeable time, SSE can be added without architectural changes.

### 6. Frontend — Export UI (`frontend/src/`)

**Components:**

- **ExportControls.tsx** — Toolbar section alongside existing OrganiseControls/AnalysisControls.
  - "Export XML" button (orange/amber to distinguish from blue/purple/emerald)
  - Disabled if no tracks in library
  - Shows last export timestamp and track count after successful export
  - Warning count displayed if any tracks were skipped
  - Click on warning count expands a brief list of issues

- **TrackTable extension:**
  - No new columns needed — export uses existing data

- **API client extension:**
  - `exportRekordboxXml(options?)` — POST to export endpoint
  - `getExportStatus()` — GET status endpoint
  - Types: `ExportResult`, `ExportStatus`

---

## Acceptance Criteria

### XML structure
- [ ] Generated XML has correct declaration: `<?xml version="1.0" encoding="UTF-8"?>`
- [ ] Root element is `<DJ_PLAYLISTS Version="1.0.0">`
- [ ] `<PRODUCT Name="rekordbot" Version="0.1.0" Company=""/>` present
- [ ] `<COLLECTION Entries="N">` count matches actual track count
- [ ] Every track is a self-closing `<TRACK ... />` element

### Track attribute mapping
- [ ] TrackID assigned sequentially from 1
- [ ] Name, Artist, Album correctly mapped and XML-escaped
- [ ] Genre, Label, Comments correctly mapped and XML-escaped
- [ ] Kind derived correctly: "AIFF File", "MP3 File"
- [ ] Size read from actual file on disk
- [ ] TotalTime is integer seconds
- [ ] AverageBpm formatted as two-decimal float string ("128.00")
- [ ] Tonality written in user's preferred key notation
- [ ] Rating uses non-linear scale (0/51/102/153/204/255)
- [ ] DateAdded formatted as "yyyy-mm-dd"
- [ ] BitRate and SampleRate correctly mapped
- [ ] Tracks with missing required fields use sensible fallbacks (filename for title, "Unknown Artist" for artist)

### Location encoding
- [ ] Paths prefixed with `file://localhost/`
- [ ] Spaces encoded as `%20`
- [ ] Special characters (`#`, `&`, etc.) percent-encoded
- [ ] Unicode characters percent-encoded as UTF-8 bytes
- [ ] Forward slash separators preserved (not encoded)
- [ ] Each path component encoded individually
- [ ] Generated URIs resolve to correct files when decoded

### Playlist structure
- [ ] ROOT node present (Type=0, Name="ROOT")
- [ ] "rekordbot" folder node containing playlists
- [ ] "All Tracks" playlist contains every exported track
- [ ] Artist playlists generated from top-level folder hierarchy
- [ ] Playlist TRACK Key values match TrackID in COLLECTION
- [ ] KeyType="0" on all playlist nodes
- [ ] Entries counts accurate on all nodes

### Export pipeline
- [ ] Export produces valid XML file at configured path
- [ ] Tracks with missing output files skipped with warning (not fatal)
- [ ] Export result reports tracks_exported, tracks_skipped, warnings
- [ ] Export creates output directory if it doesn't exist
- [ ] Re-export overwrites previous XML file

### API
- [ ] POST /api/export/rekordbox triggers export and returns result
- [ ] GET /api/export/rekordbox/status returns current state
- [ ] Export with no tracks returns 0 exported (not an error)

### UI
- [ ] "Export XML" button in toolbar
- [ ] Last export info shown after successful export
- [ ] Warning count visible if tracks were skipped

### Rekordbox compatibility
- [ ] Generated XML can be imported into Rekordbox via File → Import Library (manual verification)
- [ ] All tracks appear in Rekordbox collection after import
- [ ] Metadata fields display correctly in Rekordbox (title, artist, album, BPM, key, genre)
- [ ] Playlist structure appears in Rekordbox sidebar
- [ ] Track locations resolve (tracks are playable in Rekordbox)

---

## Out of Scope

- **TEMPO elements (beatgrid)** — requires waveform analysis not yet implemented
- **POSITION_MARK elements (cue points, loops)** — requires manual cue setting or import from existing Rekordbox data
- **Rekordbox XML import** — deferred to Phase 4b. Merging an existing Rekordbox library adds significant complexity
- **Album art in XML** — artwork path attribute exists but we don't track artwork in DB
- **Colour assignment** — exported as "0" (default). Colour management deferred
- **Play count / last played** — not tracked by rekordbot
- **Mix name** — not tracked in current Track model (field exists in Rekordbox spec)
- **Windows path support** — Mac-first. Windows `file://localhost/C:/...` encoding deferred to Phase 6
- **Incremental export** — full export every time. Diffing against previous export deferred
- **SSE progress** — not needed for typical library sizes. Can be added later if needed

---

## Dependencies

- **Phase 2b output** — organised file paths in `Track.output_path` are the primary input for Location encoding
- **Phase 2 key_notation module** — `key_to_open_key_str()`, `key_to_camelot_str()`, `camelot_to_classical()` for Tonality field
- **Research document** — `docs/research/rekordbox-xml-cdj-compatibility.md` (completed Session 1)
- **No new Python packages** — `xml.etree.ElementTree` and `urllib.parse` are stdlib

---

## DB Schema Changes

### Track model — no changes needed

All fields required for XML export already exist in the Track model from Phases 0–3. The mapping uses: title, artist, album, album_artist, genre, label, comment, year, track_number, disc_number, bpm, key, rating, duration, bitrate, sample_rate, output_path, imported_at, composer, remixer, grouping.

### Settings additions

| Setting | Type | Default | Purpose |
|---|---|---|---|
| `rekordbox_xml_path` | str | `""` | Export path. Empty = `{output_directory}/rekordbox.xml` |

### Exceptions

- `ExportError(RekordBotError)` — raised on export failures (unwritable path, etc.)

---

## Decisions (Finalised)

| # | Decision | Resolution |
|---|---|---|
| 1 | Tonality notation in XML | Use the user's `default_key_notation` setting. Research confirms CDJs display whatever is in the field, and the traffic light system works with both Camelot and classical notation. |
| 2 | PRODUCT element | `Name="rekordbot"`, `Version="0.1.0"`, `Company=""`. Rekordbox displays this in the UI. |
| 3 | Playlist structure | Auto-generated from folder hierarchy. "All Tracks" + one playlist per top-level artist folder. Phase 5 adds user-created crates. |
| 4 | SSE progress | Not needed. XML generation for typical DJ libraries (hundreds to low thousands of tracks) is sub-second. Add SSE later if profiling shows it's needed for large libraries. |
| 5 | Track model changes | None. All required fields already exist. |
| 6 | Empty attributes | Include empty strings for unset text fields (matches Rekordbox's own export behaviour, per research doc §1.10). |
| 7 | Empirical testing | Manual Rekordbox import test is part of the acceptance criteria. Generate XML, import into Rekordbox, verify fields display correctly. Not automated — done manually by Dale. |
| 8 | Windows paths | Deferred to Phase 6. Mac-only Location encoding for now. |
| 9 | Export trigger | Manual only (button click). No auto-export after organisation or tagging changes. |

---

## TDD Candidates

| Function | Location | Why TDD |
|---|---|---|
| `encode_location()` | `location_encoder.py` | Path → URI encoding. Precise RFC 3986 rules, unicode handling, component-level encoding. Highest-value TDD target — this is where bugs cause Rekordbox import failures. |
| `encode_path_component()` | `location_encoder.py` | Single component encoding. Spaces, special chars, unicode, already-safe chars. |
| `format_bpm()` | `xml_schema_mapper.py` | Float → "128.00" string. None handling, rounding. |
| `format_rating()` | `xml_schema_mapper.py` | 0–5 → non-linear scale. Fixed truth table. |
| `format_kind()` | `xml_schema_mapper.py` | Extension → "AIFF File" / "MP3 File". |
| `format_date()` | `xml_schema_mapper.py` | datetime → "yyyy-mm-dd". None handling. |
| `track_to_xml_attrs()` | `xml_schema_mapper.py` | Full mapping with fallbacks and warning collection. |
| `generate_playlist_structure()` | `xml_builder.py` | Tracks → folder-based playlist tree. Grouping logic, count accuracy. |

**Write tests after implementation** (framework integration, I/O):
- XML builder (ElementTree construction, file writing)
- Export service (DB queries, orchestration)
- API routes
- Frontend

---

## Commit Breakdown

### Commit 1: Dependencies and config
- Add `rekordbox_xml_path` to Settings in config.py
- Add `ExportError` to exceptions.py
- Commit: "Add Phase 4 configuration and exception types"

### Commit 2: Location encoder (TDD)
- Create `backend/services/location_encoder.py`
- WRITE TESTS FIRST in `backend/tests/test_location_encoder.py`:
  - `encode_path_component()`: spaces, `#`, `&`, unicode chars, already-safe chars, empty string
  - `encode_location()`: simple path, path with spaces, path with unicode, path with special chars, macOS path structure
- Then implement
- Pure logic — no I/O, no DB
- Commit: "Add Rekordbox location encoder with percent-encoding (TDD)"

### Commit 3: Schema mapper (TDD)
- Create `backend/services/xml_schema_mapper.py`
- WRITE TESTS FIRST in `backend/tests/test_xml_schema_mapper.py`:
  - `format_bpm()`: normal float, None, zero, high precision
  - `format_rating()`: all 6 values (0–5), None, out of range
  - `format_kind()`: .aiff, .mp3, .m4a, unknown extension
  - `format_date()`: normal datetime, None
  - `track_to_xml_attrs()`: full metadata track, sparse metadata track (fallbacks used), missing file (warning generated)
- Then implement
- Mostly pure logic — `get_file_size()` touches filesystem
- Commit: "Add XML schema mapper with track attribute mapping (TDD)"

### Commit 4: XML builder
- Create `backend/services/xml_builder.py`
- Implement:
  - `build_xml()` — complete XML tree construction
  - `build_collection()` — COLLECTION element
  - `build_playlists()` — PLAYLISTS element with folder-based structure
  - `generate_playlist_structure()` — derive playlists from organised paths
  - `write_xml()` — write to file
- Tests:
  - XML structure validation (root element, PRODUCT, COLLECTION, PLAYLISTS)
  - Track count matches Entries attribute
  - Playlist structure: ROOT → rekordbot → All Tracks + artist playlists
  - TrackID consistency between COLLECTION and PLAYLISTS
  - File output is valid XML (parse back with ElementTree)
- Commit: "Add XML builder with collection and playlist generation"

### Commit 5: Export service
- Create `backend/services/xml_exporter.py`
- Implement:
  - `export_library()` — full orchestration
- Tests with mocked dependencies:
  - Export all tracks
  - Export specific track_ids
  - Skip tracks with missing files
  - Fallbacks for missing title/artist
  - ExportResult counts correct
  - Output file created
- Commit: "Add export service orchestrating XML generation pipeline"

### Commit 6: API routes
- Create `backend/routes/export.py`
- Implement:
  - POST /api/export/rekordbox
  - GET /api/export/rekordbox/status
- Register routes in main.py
- Tests:
  - Successful export returns result
  - Export with no tracks
  - Status endpoint returns last export info
- Commit: "Add Rekordbox XML export API routes"

### Commit 7: Frontend
- Create `ExportControls.tsx`
- Extend API client with export types and endpoints
- Wire into App.tsx alongside existing toolbar sections
- Commit: "Add Rekordbox XML export UI"

### Commit 8: Integration tests and cleanup
- End-to-end: create tracks → export XML → parse XML → verify attributes
- Location encoding round-trip with various path patterns
- Playlist structure verification
- Re-export after metadata changes
- Update CLAUDE.md with Phase 4 status
- Manual Rekordbox import verification (documented in SESSIONS.md, not automated)
- Commit: "Add integration tests and update project docs for Phase 4"

---

## Claude Code Prompt

The following prompt is designed to be given to Claude Code at the start of the implementation session. Copy it verbatim.

---

```
You are implementing Phase 4 (Rekordbox XML Export) of rekordbot.

Read these files first:
- CLAUDE.md (project conventions, architecture, coding standards)
- docs/features/phase-4-rekordbox-xml-export.md (the feature brief — this is your specification)
- docs/research/rekordbox-xml-cdj-compatibility.md (Rekordbox XML format research — reference for attribute specs, encoding rules, and quirks)
- backend/models/track.py (existing Track model — you'll read from it)
- backend/config.py (existing Settings — you'll add new config fields)
- backend/exceptions.py (existing exception hierarchy — add new types as needed)
- backend/main.py (existing FastAPI app — you'll register new routes here)
- backend/services/key_notation.py (Phase 2 key notation — you'll use this for Tonality field)
- backend/services/template_engine.py (Phase 2b template engine — reference for path handling patterns)
- backend/routes/organise.py (Phase 2b routes — reference for route patterns)
- frontend/src/AnalysisControls.tsx (existing toolbar — reference for toolbar section pattern)
- frontend/src/OrganiseControls.tsx (Phase 2b toolbar — reference for toolbar section pattern)
- frontend/src/api/client.ts (existing API client — you'll extend with export endpoints)

## What you're building

A Rekordbox XML export pipeline that:
1. Maps Track model fields to Rekordbox XML TRACK attributes
2. Encodes file paths as file://localhost/ URIs with RFC 3986 percent-encoding
3. Builds a complete DJ_PLAYLISTS XML document with COLLECTION and PLAYLISTS sections
4. Auto-generates playlists from the organised folder hierarchy (All Tracks + per-artist)
5. Writes the XML file to disk
6. Provides API endpoints and UI for triggering export

This pipeline is SEPARATE from Phase 1's ingestion, Phase 2's analysis, Phase 2b's organisation, and Phase 3's AI tagging. Do not modify their service code.

## Build order (follow this exactly)

### Step 1: Dependencies and config
- Add to Settings in config.py:
  - rekordbox_xml_path: str (default "")
- Add ExportError to exceptions.py
- Commit: "Add Phase 4 configuration and exception types"

### Step 2: Location encoder (TDD)
- Create backend/services/location_encoder.py
- WRITE TESTS FIRST:
  - encode_path_component(): spaces, special chars (#, &, etc.), unicode, safe chars, empty string
  - encode_location(): simple path, spaces, unicode, special chars, macOS path format
- Then implement. Pure logic — no I/O, no DB.
- Commit: "Add Rekordbox location encoder with percent-encoding (TDD)"

### Step 3: Schema mapper (TDD)
- Create backend/services/xml_schema_mapper.py
- WRITE TESTS FIRST:
  - format_bpm(): normal, None, zero, precision
  - format_rating(): all 6 values (0–5), None, out of range
  - format_kind(): .aiff, .mp3, .m4a, unknown
  - format_date(): normal datetime, None
  - track_to_xml_attrs(): full track, sparse track with fallbacks, missing file warning
- Then implement.
- Commit: "Add XML schema mapper with track attribute mapping (TDD)"

### Step 4: XML builder
- Create backend/services/xml_builder.py
- Implement build_xml(), build_collection(), build_playlists(), generate_playlist_structure(), write_xml()
- Tests: structure validation, Entries counts, TrackID consistency, playlist structure, valid XML output
- Commit: "Add XML builder with collection and playlist generation"

### Step 5: Export service
- Create backend/services/xml_exporter.py
- Implement export_library()
- Tests: export all, export subset, skip missing files, fallbacks, result counts
- Commit: "Add export service orchestrating XML generation pipeline"

### Step 6: API routes
- Create backend/routes/export.py
- POST /api/export/rekordbox, GET /api/export/rekordbox/status
- Register in main.py
- Test all endpoints
- Commit: "Add Rekordbox XML export API routes"

### Step 7: Frontend
- Create ExportControls.tsx
- Extend API client with export types and endpoints
- Commit: "Add Rekordbox XML export UI"

### Step 8: Integration tests and cleanup
- End-to-end: create tracks → export → parse → verify
- Location encoding round-trip tests
- Playlist structure verification
- Update CLAUDE.md
- Commit: "Add integration tests and update project docs for Phase 4"

## Constraints
- Follow all conventions in CLAUDE.md (type hints, docstrings, error handling, logging, etc.)
- Do NOT modify Phase 1, 2, 2b, or 3 service code
- Use xml.etree.ElementTree (stdlib) — no lxml or other XML libraries
- Use urllib.parse.quote() for percent-encoding — no custom encoding
- All exceptions should be RekordBotError subclasses
- Every service module gets its own logger via logging.getLogger(__name__)
- Use %s string formatting in log calls (not f-strings)
- Include empty strings for unset text attributes (matches Rekordbox convention)
- TrackID assigned sequentially from 1 (not using DB track IDs directly)
- Self-closing TRACK tags (no child elements in Phase 4)

## Important
- Do NOT implement TEMPO or POSITION_MARK elements (beatgrid/cue points out of scope)
- Do NOT implement XML import (Phase 4b)
- Do NOT implement SSE progress for export (not needed for typical library sizes)
- Do NOT implement Windows path support (Mac-first, deferred to Phase 6)
- Do NOT implement incremental/diff export (full export every time)
- Do NOT implement colour assignment (exported as "0")
- The Location field is the #1 source of bugs — test it thoroughly
```

### Continuation Prompt

If the session is interrupted and you need to resume in a new Claude Code session, use this:

```
We are continuing Phase 4 (Rekordbox XML Export) of rekordbot.

Read these files for context:
- CLAUDE.md (project conventions and current status)
- SESSIONS.md (latest entry has where we left off and what's next)
- docs/features/phase-4-rekordbox-xml-export.md (the feature specification)
- docs/research/rekordbox-xml-cdj-compatibility.md (Rekordbox XML format research)

Pick up from where we left off. Check SESSIONS.md for the last completed step
and what was identified as the next task. Confirm what you think the next step
is before writing any code.
```

---

## Notes

- The research doc uses the old project name "CrateAI" in examples — the correct name is "rekordbot".
- TrackID in the XML is sequential starting from 1 and does NOT need to match the DB's Track.id. Rekordbox reassigns its own internal IDs on import (research doc §1.9). However, the IDs must be consistent between COLLECTION and PLAYLISTS within a single XML file.
- The `key_notation.py` module already has all the conversion functions needed for the Tonality field. The export just needs to call the right one based on `default_key_notation` setting.
- `xml.etree.ElementTree` handles XML entity encoding automatically for attribute values — no need to manually escape `&`, `<`, `>` etc.
- File size must be read from disk at export time, not stored in DB, because the file may have been modified (tags written) since ingestion.
- The playlist auto-generation derives structure from `output_path` relative to `output_directory`. For example, if `output_path` is `/library/Calibre/Shelflife 6/Falls to You.aiff` and `output_directory` is `/library/`, the top-level folder is "Calibre" and the track goes into the "Calibre" playlist.
