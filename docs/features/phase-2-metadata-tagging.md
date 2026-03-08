# Feature: Metadata & Tagging
**Branch:** `feature/phase-2-tagger`
**Status:** Complete ✅
**Phase:** 2
**Depends on:** Phase 1 (complete)

---

## Goal

Enrich every track in the rekordbot library with clean, accurate metadata: read existing tags from source files, detect BPM and musical key using librosa, preserve original tag values for comparison, and write CDJ-compatible ID3v2.3 tags to the output files — all with user review before any tag is written.

The tagging pipeline is **separate from the ingestion pipeline** (Phase 1). Tracks are ingested first, then analysed and tagged as a distinct operation. This means:
- Phase 1's conversion pipeline is untouched
- Tracks can exist in the library without tags (just format/quality metadata)
- Tags can be re-analysed or reverted at any time
- Users with their own existing tagging workflow are not overridden silently

---

## Inputs

- Tracks already in the SQLite database (ingested via Phase 1)
- Output audio files in `{output_directory}/imports/{YYYY-MM-DD}/` (AIFF, MP3, or M4A)
- User preferences (from settings, persisted in config):
  - `bpm_range_min`: int (default `70`) — floor for BPM auto-correction
  - `bpm_range_max`: int (default `180`) — ceiling for BPM auto-correction
  - `confidence_threshold`: float (default `0.6`) — below this, flag for review
  - `default_key_notation`: str (default `"camelot"`) — display format: `"camelot"`, `"open_key"`, or `"classical"`

## Outputs

- Updated `Track` records in SQLite with:
  - Tags read from source file (title, artist, album, genre, year, etc.)
  - Detected BPM (float, 2 decimal places) with confidence score
  - Detected key (integer 1–24, Camelot mapping) with confidence score
  - Original source tag values preserved (`source_bpm`, `source_key`)
  - Analysis status tracking (`unanalysed` → `analysed` → `tags_written`)
- ID3v2.3 tags written to output AIFF and MP3 files, MP4 atoms written to M4A files (on user action, not automatic)
- A tag review UI with Rekordbox-style sortable table, column visibility toggle, and inline editing

---

## Architecture & Key Components

### 1. Tag Reader (`backend/services/tag_reader.py`)

Wraps mutagen to read existing ID3 tags from audio files. Runs on the **output** file (not the source) because ffmpeg preserves tags during conversion, and the output file is the one we manage.

**Responsibilities:**
- Open file with mutagen (auto-detect format: AIFF → mutagen.aiff, MP3 → mutagen.mp3, M4A → mutagen.mp4)
- Extract tag values into a typed `TagData` dataclass:
  ```
  TagData:
    title: str | None
    artist: str | None
    album: str | None
    album_artist: str | None
    genre: str | None
    year: int | None
    track_number: int | None
    comment: str | None
    label: str | None
    bpm: float | None          # existing BPM tag (TBPM frame)
    key: str | None             # existing key tag (TKEY frame), raw string
    rating: int | None          # POPM frame, 0-255
    duration: float | None      # from audio info, seconds
  ```
- Handle format-specific tag access:
  - AIFF and MP3: ID3v2 frames (TIT2, TPE1, TALB, TPE2, TCON, TDRC/TYER, TRCK, COMM, TPUB, TBPM, TKEY, POPM)
  - M4A: MP4 atoms (©nam, ©ART, ©alb, aART, ©gen, ©day, trkn, ©cmt, ©pub, tmpo, ----:com.apple.iTunes:INITIALKEY)
- Return `TagData` with None for any missing field (never raise on missing tags)

**Edge cases:**
- File with no tags at all → return TagData with all None fields
- File with ID3v1 only → read what's available, but don't write ID3v1 back
- Corrupt tag data → log warning, return None for affected field, continue
- TYER (v2.3) vs TDRC (v2.4) year frames → read both, prefer TDRC if both present
- TRCK as "3/12" format → parse to integer 3

### 2. BPM Detector (`backend/services/bpm_detector.py`)

Uses librosa to detect the tempo of an audio file.

**Responsibilities:**
- Load audio file with `librosa.load()` (mono, default sample rate 22050)
- Compute onset envelope with `librosa.onset.onset_strength()`
- Estimate tempo with `librosa.feature.tempo()` → returns BPM as float
- Apply half/double-time auto-correction based on user's BPM range settings
- Compute confidence score from onset autocorrelation peak strength
- Return `BPMResult` dataclass:
  ```
  BPMResult:
    bpm: float                 # detected BPM, rounded to 2 decimal places
    raw_bpm: float             # BPM before auto-correction
    confidence: float          # 0.0–1.0
    was_corrected: bool        # True if half/double-time correction was applied
    correction_factor: int     # 1 (no correction), 2 (doubled), or -2 (halved)
  ```

**Auto-correction logic:**
1. Detect raw BPM from librosa
2. If raw BPM is within `[bpm_range_min, bpm_range_max]` → accept as-is
3. If raw BPM < bpm_range_min → try doubling: if doubled value is in range, use it
4. If raw BPM > bpm_range_max → try halving: if halved value is in range, use it
5. If still out of range after one correction → flag as low confidence, use raw value

**Confidence derivation:**
- Compute the onset autocorrelation at the detected tempo lag
- Normalise to 0.0–1.0 range
- Strong, clear beat → high confidence; ambiguous or weak rhythm → low confidence
- This will need empirical tuning — start with a simple normalisation and adjust

**Performance consideration:** librosa.load() decodes the entire audio file into memory. For a typical 5-minute track at 22050 Hz mono, that's ~13 MB. This is fine for individual files but the analysis service should process one file at a time (not load everything simultaneously). The analysis queue handles concurrency.

### 3. Key Detector (`backend/services/key_detector.py`)

Uses librosa's chroma features with the Krumhansl-Schmuckler algorithm to detect musical key.

**Responsibilities:**
- Accept audio data (pre-loaded by the analysis pipeline — avoid loading the file twice)
- Separate harmonic component with `librosa.effects.hpss()` (improves key detection accuracy by removing percussive elements)
- Compute constant-Q chromagram with `librosa.feature.chroma_cqt()`
- Sum chroma values across time to get pitch class distribution
- Correlate against Krumhansl-Schmuckler major and minor key profiles for all 12 starting pitches (24 correlations total)
- Return the key with highest correlation, plus confidence metric
- Return `KeyResult` dataclass:
  ```
  KeyResult:
    key: int                   # 1–24 (Camelot wheel mapping)
    key_name: str              # e.g. "A♭ minor", "B major"
    confidence: float          # 0.0–1.0
    correlation_scores: dict   # all 24 key correlations (for advanced UI, future use)
    second_best_key: int       # runner-up key (useful for ambiguous cases)
    second_best_confidence: float
  ```

**Krumhansl-Schmuckler profiles (hardcoded constants):**
```
Major: [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
Minor: [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
```
These represent the perceptual stability of each pitch class within a key, starting from the tonic. For each candidate key, rotate the profile to align with the candidate tonic and compute Pearson correlation with the observed chroma distribution.

**Confidence derivation:**
- Primary metric: difference between the top correlation and second-best correlation
- Large gap → high confidence; small gap → ambiguous key
- Normalise to 0.0–1.0 (empirical tuning needed)
- Known issue: relative major/minor pairs (e.g. C major / A minor) will often have similar correlations — this is inherent to the algorithm and is the main source of key detection uncertainty

### 4. Camelot Mapping (`backend/services/key_notation.py`)

Pure logic module for converting between key representations. This is a TDD candidate — the mapping is a fixed truth table.

**Internal representation:** Integer 1–24, following the Camelot wheel:

| Internal | Camelot | Open Key | Classical |
|---|---|---|---|
| 1 | 1A | 6m | A♭ minor |
| 2 | 1B | 6d | B major |
| 3 | 2A | 7m | E♭ minor |
| 4 | 2B | 7d | F♯ major |
| 5 | 3A | 8m | B♭ minor |
| 6 | 3B | 8d | D♭ major |
| 7 | 4A | 9m | F minor |
| 8 | 4B | 9d | A♭ major |
| 9 | 5A | 10m | C minor |
| 10 | 5B | 10d | E♭ major |
| 11 | 6A | 11m | G minor |
| 12 | 6B | 11d | B♭ major |
| 13 | 7A | 12m | D minor |
| 14 | 7B | 12d | F major |
| 15 | 8A | 1m | A minor |
| 16 | 8B | 1d | C major |
| 17 | 9A | 2m | E minor |
| 18 | 9B | 2d | G major |
| 19 | 10A | 3m | B minor |
| 20 | 10B | 3d | D major |
| 21 | 11A | 4m | F♯ minor |
| 22 | 11B | 4d | A major |
| 23 | 12A | 5m | D♭ minor |
| 24 | 12B | 5d | E major |

**Functions:**
- `classical_to_camelot(key_name: str) -> int` — e.g. "A♭ minor" → 1, "Abm" → 1, "G#m" → 1
- `camelot_to_classical(key_int: int) -> str` — e.g. 1 → "A♭ minor"
- `key_to_camelot_str(key_int: int) -> str` — e.g. 1 → "1A", 2 → "1B"
- `key_to_open_key_str(key_int: int) -> str` — e.g. 1 → "6m", 2 → "6d"
- `key_to_display(key_int: int, notation: str) -> str` — e.g. `key_to_display(1, "camelot")` → "1A"
- `parse_key_tag(tag_value: str) -> int | None` — parse a TKEY tag value (could be Camelot, Open Key, classical, or Rekordbox numeric) into internal int. Returns None if unparseable.

**TKEY tag writing:** Rekordbox reads the TKEY frame and expects Open Key notation (e.g. "6m", "6d") or classical (e.g. "Abm", "B"). We write Open Key notation by default, as it's the most widely compatible format across DJ software.

### 5. Tag Writer (`backend/services/tag_writer.py`)

Wraps mutagen to write tags to output audio files. Only called when the user explicitly triggers tag writing — never automatic.

**Responsibilities:**
- Open file with mutagen
- Write tags from the Track model's active values
- **AIFF and MP3 (ID3v2.3):**
  - Standard text frames: TIT2, TPE1, TALB, TPE2, TCON, TYER, TRCK, TPUB
  - Comment: COMM (with lang='eng', desc='')
  - BPM: TBPM (as string of the float, e.g. "128.00")
  - Key: TKEY (Open Key notation, e.g. "6m")
  - Rating: POPM (if present)
  - Ensure ID3v2.3 output (not v2.4) for CDJ compatibility
  - **Do NOT write ID3v1 tags** — they cause Rekordbox comment field issues (documented in CLAUDE.md)
- **M4A (MP4 atoms via mutagen.mp4):**
  - Standard atoms: ©nam, ©ART, ©alb, aART, ©gen, ©day, trkn, ©cmt, ©pub
  - BPM: tmpo atom (integer)
  - Key: `----:com.apple.iTunes:INITIALKEY` freeform atom (Open Key notation)
- For AIFF files: use `mutagen.aiff.AIFF` — mutagen handles ID3-in-AIFF natively
- For MP3 files: use `mutagen.mp3.MP3` — standard ID3 handling
- For M4A files: use `mutagen.mp4.MP4` — atom-based tags
- Return a `TagWriteResult` indicating success/failure per field

**Edge cases:**
- File is read-only → raise TagWriteError
- File doesn't exist (moved/deleted since import) → raise TagWriteError
- Existing tags on file that we're not managing (e.g. album art, custom frames) → preserve them, don't overwrite
- M4A BPM is integer-only (tmpo atom) — round to nearest integer for M4A, keep two-decimal float for AIFF/MP3

### 6. Analysis Pipeline (`backend/services/analysis.py`)

Orchestrates the full analysis flow for a single track or batch of tracks. This is the equivalent of Phase 1's converter service — it coordinates the tag reader, BPM detector, key detector, and DB updates.

**Single track flow:**
1. Load track record from DB
2. Read existing tags from output file via tag reader → populate tag fields in DB
3. Load audio with librosa (once — shared between BPM and key detection)
4. Detect BPM → store in `bpm` column, original tag BPM in `source_bpm`, confidence in `bpm_confidence`
5. Detect key → store in `key` column (as int 1–24), original tag key in `source_key`, confidence in `key_confidence`
6. Update `analysis_status` to `"analysed"`
7. Commit to DB

**Batch processing:**
- Uses the same `asyncio.Semaphore` pattern as Phase 1's processing queue
- Default concurrency: 1 (librosa analysis is CPU-intensive and memory-hungry — parallelism here risks memory pressure)
- Configurable via `max_concurrent_analyses` setting
- Emits SSE progress events: `analysis_queued` → `analysis_processing` → `analysis_complete` / `analysis_failed`
- Per-track error isolation (one failure doesn't stop the batch)

**Tag writing flow (separate from analysis):**
1. User selects tracks in the review UI and clicks "Write Tags"
2. For each selected track: call tag writer with current active values from DB
3. Update `analysis_status` to `"tags_written"`
4. Emit SSE events for progress

**Return types:**
```
AnalysisResult:
  track_id: int
  status: Literal["success", "failed"]
  bpm_result: BPMResult | None
  key_result: KeyResult | None
  tags_read: TagData | None
  error: str | None

BatchAnalysisResult:
  total: int
  succeeded: int
  failed: int
  results: list[AnalysisResult]
```

### 7. API Routes (`backend/routes/tagging.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/tracks/analyse` | Start analysis on selected tracks (or all unanalysed) |
| GET | `/api/tracks/analyse/progress` | SSE endpoint for analysis progress events |
| POST | `/api/tracks/analyse/cancel` | Cancel current analysis batch |
| POST | `/api/tracks/write-tags` | Write tags to files for selected tracks |
| PUT | `/api/tracks/{id}` | Update a single track's metadata (inline editing) |
| PUT | `/api/tracks/{id}/revert/{field}` | Revert a field to its original source value |
| PUT | `/api/tracks/{id}/bpm-multiply` | Double or halve BPM (body: `{"factor": 2}` or `{"factor": 0.5}`) |
| GET | `/api/tracks` | (Existing, enhanced) List tracks with analysis metadata, sortable/filterable |

**POST `/api/tracks/analyse` request body:**
```json
{
  "track_ids": [1, 2, 3],
  "options": {
    "bpm_range_min": 70,
    "bpm_range_max": 180,
    "skip_if_analysed": true
  }
}
```
If `track_ids` is empty or absent, analyse all tracks with `analysis_status = "unanalysed"`.

**PUT `/api/tracks/{id}` request body:**
```json
{
  "title": "New Title",
  "artist": "New Artist",
  "bpm": 128.00,
  "key": 16
}
```
Partial update — only fields present in the body are updated.

**PUT `/api/tracks/{id}/revert/{field}` — field options:**
`bpm` → reverts `bpm` to `source_bpm`; `key` → reverts `key` to `source_key`. Returns 404 if no source value exists.

**PUT `/api/tracks/{id}/bpm-multiply` request body:**
```json
{
  "factor": 2
}
```
Multiplies current BPM by factor. Only accepts `2` or `0.5`. Returns the updated BPM.

**Enhanced GET `/api/tracks` response:**
```json
{
  "tracks": [
    {
      "id": 1,
      "title": "Track Name",
      "artist": "Artist Name",
      "album": "Album",
      "genre": "House",
      "bpm": 128.00,
      "key": 16,
      "key_display": "8B",
      "duration": 342.5,
      "bitrate": 320,
      "quality_warning": false,
      "analysis_status": "analysed",
      "bpm_confidence": 0.92,
      "key_confidence": 0.78,
      "source_bpm": 127.5,
      "source_key": 16,
      "has_bpm_conflict": false,
      "has_key_conflict": false,
      "imported_at": "2026-03-08T14:30:00",
      ...
    }
  ],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

### 8. Frontend — Tag Review UI (`frontend/src/`)

Replaces the basic Phase 1 `TrackList.tsx` with a Rekordbox-style library view.

**Components:**

- **TrackTable.tsx** — Main component. Sortable, filterable table with configurable columns.
  - Default visible columns: Title, Artist, Album, Genre, BPM, Key, Duration, Bitrate, Quality Warning, Date Added
  - Hidden by default (toggle via right-click header): Album Artist, Year, Label, Track Number, Rating, Comment, Source Format, Conversion Action, BPM Confidence, Key Confidence, Analysis Status
  - Column header right-click → context menu to show/hide columns
  - Click column header to sort (asc/desc toggle)
  - Row selection (single click, shift-click for range, ctrl/cmd-click for multi)
  - Inline editing: double-click a cell to edit (text fields, BPM, key)
  - BPM cell: shows value + ×2/÷2 buttons on hover/focus
  - Key cell: shows value in user's preferred notation (Camelot by default)
  - Confidence indicators: low-confidence BPM/key highlighted (amber background or icon)
  - Conflict indicators: if detected value differs from source tag, show a small indicator

- **AnalysisControls.tsx** — Toolbar above the table.
  - "Analyse Selected" button (or "Analyse All Unanalysed" if nothing selected)
  - "Write Tags" button (writes tags to files for selected tracks)
  - Analysis progress bar (driven by SSE)
  - Filter controls: show all / unanalysed only / low confidence only / conflicts only

- **ColumnMenu.tsx** — Right-click context menu for column visibility toggle.
  - Checkbox list of all available columns
  - "Reset to Default" option

- **TrackDetailPanel.tsx** — Optional side panel or modal showing full detail for a selected track.
  - All fields visible
  - Source vs detected comparison for BPM and key
  - "Revert to original" buttons per field
  - Full edit capability

---

## Acceptance Criteria

### Tag reading
- [ ] Title, artist, album, album_artist, genre, year, track_number, comment, label read from AIFF files
- [ ] Title, artist, album, album_artist, genre, year, track_number, comment, label read from MP3 files
- [ ] BPM and key read from existing tags (if present)
- [ ] Files with no tags → all fields None, no error
- [ ] Files with partial tags → available fields populated, missing fields None
- [ ] TYER and TDRC both handled for year extraction
- [ ] TRCK "3/12" format parsed to integer 3

### BPM detection
- [ ] BPM detected for AIFF files using librosa
- [ ] BPM detected for MP3 files using librosa
- [ ] BPM rounded to 2 decimal places
- [ ] Half-time auto-correction: track at 64 BPM → corrected to 128 (given default range 70–180)
- [ ] Double-time auto-correction: track at 256 BPM → corrected to 128
- [ ] BPM range configurable via settings (bpm_range_min, bpm_range_max)
- [ ] Confidence score stored (0.0–1.0)
- [ ] Low-confidence BPM flagged (below threshold)
- [ ] ×2 and ÷2 quick-fix available in UI

### Key detection
- [ ] Key detected using librosa chroma + Krumhansl-Schmuckler
- [ ] Key stored as integer 1–24 (Camelot wheel mapping)
- [ ] Key displayed in user's preferred notation (Camelot, Open Key, or classical)
- [ ] Confidence score stored (0.0–1.0)
- [ ] Low-confidence key flagged (below threshold)
- [ ] Harmonic separation (HPSS) applied before chroma analysis

### Key notation
- [ ] All 24 keys correctly mapped between internal int, Camelot, Open Key, and classical
- [ ] Key tag parser handles: Camelot ("8B"), Open Key ("1d"), classical ("C", "Cm", "C major", "C minor"), sharp/flat variants
- [ ] Unparseable key tags → None (not an error)

### Tag writing
- [ ] Tags written to AIFF files as ID3v2.3
- [ ] Tags written to MP3 files as ID3v2.3
- [ ] Tags written to M4A files as MP4 atoms
- [ ] No ID3v1 tags written (AIFF/MP3)
- [ ] Existing tags not managed by rekordbot (album art, custom frames) are preserved
- [ ] BPM written to TBPM frame for AIFF/MP3 (e.g. "128.00"), tmpo atom for M4A (integer)
- [ ] Key written to TKEY frame (AIFF/MP3) or INITIALKEY freeform atom (M4A) in Open Key notation
- [ ] Tag writing only happens on explicit user action (never automatic)

### Original value preservation
- [ ] Original BPM from source tags stored in `source_bpm`
- [ ] Original key from source tags stored in `source_key`
- [ ] Revert-to-original available per field via API and UI
- [ ] Detected values are active by default

### Analysis pipeline
- [ ] Analysis runs as separate operation from ingestion
- [ ] Batch analysis with concurrency control
- [ ] SSE progress events for analysis (queued → processing → complete/failed)
- [ ] Per-track error isolation (one failure doesn't stop batch)
- [ ] Analysis can be cancelled mid-batch
- [ ] Re-analysis possible (re-run on already-analysed tracks)

### UI
- [ ] Rekordbox-style sortable table with configurable column visibility
- [ ] Right-click column header → show/hide columns
- [ ] Default columns match specified list
- [ ] Inline editing for text fields, BPM, key
- [ ] BPM ×2/÷2 buttons accessible from BPM cell
- [ ] Low-confidence values visually highlighted
- [ ] Conflict between detected and source values indicated
- [ ] "Analyse" and "Write Tags" actions accessible from toolbar
- [ ] Analysis progress visible in UI

### Data integrity
- [ ] Every analysed track has bpm, key, bpm_confidence, key_confidence in DB
- [ ] analysis_status correctly transitions: unanalysed → analysed → tags_written
- [ ] Partial updates via PUT /api/tracks/{id} only modify specified fields

---

## Out of Scope

- **Genre/mood/energy inference** — Phase 3 (Claude AI). Phase 2 reads existing genre tags but does not infer new ones.
- **File organisation / folder structure** — Phase 2b. Files stay in their Phase 1 output location.
- **Album art reading/writing** — deferred. Not needed for core DJ workflow.
- **Waveform generation** — not in scope for any current phase.
- **Batch tag editing** — edit one track at a time in Phase 2. Batch editing (apply same genre to 50 tracks) can be added later.
- **Tag reading from source files vs output files** — Phase 2 reads from the output file. ffmpeg preserves most tags during conversion. If we later need to read from sources specifically, that's a separate enhancement.
- **Rekordbox XML export** — Phase 4. Phase 2 just writes tags to audio files.
- **Advanced BPM detection (variable tempo, time signature detection)** — librosa's basic beat_track is sufficient for Phase 2.

---

## Dependencies

- **librosa** — audio analysis (BPM detection, chroma features for key detection). Pulls in numpy, scipy, numba, soundfile, etc.
- **mutagen** — tag reading and writing for AIFF, MP3 (ID3), and M4A (MP4 atoms).
- **Phase 1 infrastructure** — Track model, processing queue patterns, SSE capability, API client.
- **ffmpeg** — already available (Phase 1). Needed by librosa for loading certain audio formats.

---

## DB Schema Changes

The Phase 1 Track model has Rekordbox-compatible fields (title, artist, album, etc.) plus ingestion fields (source_path, source_codec, etc.). Phase 2 needs to add analysis-specific columns:

| Column | Type | Purpose |
|---|---|---|
| `source_bpm` | Float, nullable | Original BPM from source file tags (preserved for comparison/revert) |
| `source_key` | Integer, nullable | Original key from source file tags, as internal int 1–24 |
| `bpm_confidence` | Float, nullable | Confidence score for detected BPM (0.0–1.0) |
| `key_confidence` | Float, nullable | Confidence score for detected key (0.0–1.0) |
| `analysis_status` | String | Status: "unanalysed", "analysed", "tags_written" |

**Existing columns to populate (already in Track model from Phase 0):**
- `title`, `artist`, `album`, `album_artist`, `genre`, `year`, `track_number`, `comment`, `label`, `rating` — populated by tag reader
- `bpm` — populated by BPM detector (active value)
- `key` — populated by key detector (active value, as integer 1–24)
- `duration` — populated by tag reader or librosa (whichever is more reliable)

**Review existing columns before adding:** Check whether `bpm`, `key`, `duration`, `bitrate`, and `rating` already have the right types. The Track model was designed for Rekordbox compatibility — `bpm` should be Float, `key` should be Integer, `duration` should be Float (seconds). Adjust types if needed.

---

## Decisions (Finalised)

| # | Decision | Resolution |
|---|---|---|
| 1 | **Detection library** | librosa from day 1 (not aubio). Heavier dependency but better accuracy for both BPM and key detection. |
| 2 | **Tag scope** | Read standard ID3 fields from output files. BPM/key detected by librosa replace originals as active values. Originals preserved in source_* columns. Non-detection fields (title, artist, etc.) read and stored directly. |
| 3 | **Tagging pipeline** | Separate from ingestion (Option B). New analysis service operates on tracks already in DB. Phase 1 pipeline untouched. |
| 4 | **BPM precision** | Float rounded to 2 decimal places. Matches Rekordbox format. Half/double-time auto-correction applied based on configurable BPM range. |
| 5 | **BPM range** | Configurable min/max (default 70–180). Auto-correction doubles or halves detected BPM to fit range. If still out of range after one correction, flag as low confidence. |
| 6 | **BPM quick-fix** | ×2 and ÷2 buttons in UI for manual half/double-time correction. Common DJ need. |
| 7 | **Key detection** | librosa chroma_cqt + HPSS + Krumhansl-Schmuckler algorithm. 24 possible keys (12 major + 12 minor). |
| 8 | **Key internal representation** | Integer 1–24, Camelot wheel mapping. Display in Camelot by default, configurable to Open Key or classical. |
| 9 | **Key tag writing** | Open Key notation in TKEY frame (e.g. "6m", "6d"). Most widely compatible across DJ software. |
| 10 | **Confidence scores** | Stored as float 0.0–1.0 for both BPM and key. Threshold-based flagging (default 0.6, configurable). Advisory, not blocking. |
| 11 | **Original value preservation** | Source tag values stored in source_bpm, source_key. Detected values are active by default. Per-field revert available. |
| 12 | **Tag writing timing** | Only on explicit user action ("Write Tags" button). Never automatic. Respects users with existing tagging workflows. |
| 13 | **Tag format** | ID3v2.3 for AIFF and MP3 (no ID3v1). MP4 atoms for M4A. All three output formats supported. |
| 14 | **UI style** | Rekordbox-style sortable table with right-click column visibility toggle. Polished from the start. |
| 15 | **Analysis concurrency** | Default 1 concurrent analysis (CPU/memory intensive). Configurable via `max_concurrent_analyses`. |
| 16 | **Audio loading** | Load audio once per track, share between BPM and key detection. Avoid double-loading. |

---

## TDD Candidates

Per CLAUDE.md convention — pure logic functions with clearly defined inputs/outputs, written test-first:

| Function | Location | Why TDD |
|---|---|---|
| `parse_tag_value()` helpers | `tag_reader.py` | TRCK "3/12" → 3, TYER/TDRC handling, edge cases with missing/malformed data |
| `correct_bpm_range()` | `bpm_detector.py` | Pure logic: raw BPM + min/max range → corrected BPM + correction factor. Truth table with clear edge cases. |
| `compute_key_correlations()` | `key_detector.py` | Pure math: chroma vector + K-S profiles → 24 correlation scores. Deterministic, testable with known inputs. |
| `select_best_key()` | `key_detector.py` | Pure logic: 24 correlation scores → best key int + confidence. |
| `classical_to_camelot()` | `key_notation.py` | String → int mapping. Full 24-key truth table + all alias variants (sharp/flat, abbreviated). Highest-value TDD target. |
| `camelot_to_classical()` | `key_notation.py` | Int → string mapping. Inverse of above. |
| `key_to_camelot_str()` | `key_notation.py` | Int → Camelot string. Simple lookup but worth testing all 24. |
| `key_to_open_key_str()` | `key_notation.py` | Int → Open Key string. Same. |
| `parse_key_tag()` | `key_notation.py` | String → int. Must handle Camelot, Open Key, classical, Rekordbox notation, and garbage input. |
| `key_to_display()` | `key_notation.py` | Int + notation preference → display string. |
| `compute_bpm_confidence()` | `bpm_detector.py` | Onset autocorrelation data → confidence float. Testable with synthetic data. |
| `compute_key_confidence()` | `key_detector.py` | Top two correlation scores → confidence float. Simple gap metric. |

**Write tests after implementation** (framework integration, I/O-dependent):
- Tag reader integration (actual mutagen file I/O)
- Tag writer integration (actual mutagen file I/O)
- librosa BPM/key detection on real audio files
- API route handlers
- SSE event streaming
- Frontend components

---

## Commit Breakdown

### Commit 1: Dependencies and config
- Add `librosa` and `mutagen` to pyproject.toml, update uv.lock
- Add to Settings in config.py:
  - `bpm_range_min: int = 70`
  - `bpm_range_max: int = 180`
  - `confidence_threshold: float = 0.6`
  - `max_concurrent_analyses: int = 1`
  - `default_key_notation: str = "camelot"`
- Add `AnalysisError`, `TagReadError`, `TagWriteError` to exceptions.py (if not already present)
- Commit: "Add Phase 2 dependencies and configuration"

### Commit 2: Track model updates
- Review existing Track model columns against Phase 2 needs
- Add: `source_bpm` (Float, nullable), `source_key` (Integer, nullable), `bpm_confidence` (Float, nullable), `key_confidence` (Float, nullable), `analysis_status` (String, default "unanalysed")
- Verify types of existing columns: `bpm` (Float), `key` (Integer), `duration` (Float), `rating` (Integer)
- Update any existing model tests
- Commit: "Extend Track model with analysis-specific columns"

### Commit 3: Key notation module (TDD)
- Create `backend/services/key_notation.py`
- WRITE TESTS FIRST in `backend/tests/test_key_notation.py`:
  - Test all 24 keys for `camelot_to_classical()`, `key_to_camelot_str()`, `key_to_open_key_str()`
  - Test `classical_to_camelot()` with all standard names + sharp/flat aliases + abbreviated forms
  - Test `parse_key_tag()` with Camelot ("8B"), Open Key ("1d"), classical ("C", "Cm", "C major", "C minor", "C#m", "Db", "Dbm"), and garbage input
  - Test `key_to_display()` with all three notation preferences
  - Test edge cases: None input, empty string, numeric strings
- Then implement all functions
- Commit: "Add key notation mapping with Camelot/Open Key/classical conversion (TDD)"

### Commit 4: Tag reader
- Create `backend/services/tag_reader.py`
- WRITE TESTS FIRST for tag value parsing helpers (TRCK format, year frame handling)
- Then implement:
  - `TagData` dataclass
  - `read_tags(path: Path) -> TagData` — reads tags using mutagen
  - Format-specific handling for AIFF, MP3, M4A
- Integration tests with test fixtures (use Phase 1's existing test audio files — they're short but have tags we can write to them for testing)
- Commit: "Add tag reader with mutagen integration"

### Commit 5: BPM detector (TDD for correction logic)
- Create `backend/services/bpm_detector.py`
- WRITE TESTS FIRST in `backend/tests/test_bpm_detector.py`:
  - Test `correct_bpm_range()`: 128 in [70,180] → no correction; 64 in [70,180] → doubled to 128; 256 in [70,180] → halved to 128; 32 in [70,180] → doubled to 64, still out of range → flag; edge cases at boundaries
  - Test `compute_bpm_confidence()` with synthetic autocorrelation data
- Then implement:
  - `BPMResult` dataclass
  - `correct_bpm_range(raw_bpm: float, bpm_min: int, bpm_max: int) -> tuple[float, bool, int]`
  - `compute_bpm_confidence(onset_env, tempo, sr, hop_length) -> float`
  - `detect_bpm(path: Path, bpm_min: int, bpm_max: int) -> BPMResult` — full detection pipeline
- Integration test with a test audio fixture (detect BPM on a known-tempo file)
- Commit: "Add BPM detector with librosa integration and auto-correction (TDD)"

### Commit 6: Key detector (TDD for correlation logic)
- Create `backend/services/key_detector.py`
- WRITE TESTS FIRST in `backend/tests/test_key_detector.py`:
  - Test `compute_key_correlations()` with a synthetic chroma vector that strongly matches a known key profile
  - Test `select_best_key()`: clear winner → high confidence; close scores → low confidence
  - Test `compute_key_confidence()` gap metric
- Then implement:
  - `KeyResult` dataclass
  - `compute_key_correlations(chroma_values: list[float]) -> dict[int, float]` — correlate against all 24 K-S profiles
  - `select_best_key(correlations: dict[int, float]) -> tuple[int, float, int, float]` — returns (best_key, confidence, second_key, second_confidence)
  - `detect_key(y: np.ndarray, sr: int) -> KeyResult` — full detection pipeline (HPSS + chroma + K-S)
- Integration test with test audio fixture
- Commit: "Add key detector with librosa chroma and Krumhansl-Schmuckler (TDD)"

### Commit 7: Tag writer
- Create `backend/services/tag_writer.py`
- Implement:
  - `TagWriteResult` dataclass
  - `write_tags(path: Path, track: Track) -> TagWriteResult` — writes tags to audio files
  - AIFF and MP3: ID3v2.3 (no v2.4, no v1)
  - M4A: MP4 atoms (©nam, ©ART, tmpo, INITIALKEY freeform atom, etc.)
  - Preservation of unmanaged tags (album art, custom frames)
- Integration tests: write tags to test file, read back and verify (all three formats)
- Commit: "Add tag writer with ID3v2.3 for AIFF/MP3 and MP4 atoms for M4A"

### Commit 8: Analysis pipeline
- Create `backend/services/analysis.py`
- Implement:
  - `analyse_track(track_id: int, db_session, settings) -> AnalysisResult` — full orchestrator
  - `analyse_batch(track_ids: list[int], options, db_session, settings) -> BatchAnalysisResult`
  - Concurrency control via asyncio.Semaphore
  - SSE event emission for analysis progress
  - Per-track error isolation
  - Cancellation support
- Test pipeline with mocked detectors (test orchestration, error handling, concurrency)
- Commit: "Add analysis pipeline with batch processing and SSE progress"

### Commit 9: API routes
- Create `backend/routes/tagging.py`
- Implement:
  - POST `/api/tracks/analyse` — trigger analysis
  - GET `/api/tracks/analyse/progress` — SSE endpoint
  - POST `/api/tracks/analyse/cancel` — cancel analysis
  - POST `/api/tracks/write-tags` — write tags to files
  - PUT `/api/tracks/{id}` — update track metadata
  - PUT `/api/tracks/{id}/revert/{field}` — revert to source value
  - PUT `/api/tracks/{id}/bpm-multiply` — ×2 or ÷2 BPM
- Enhance existing GET `/api/tracks` with analysis fields, key_display, conflict flags
- Register routes in main.py
- Test all endpoints with httpx async client
- Commit: "Add tagging API routes with analysis, editing, and revert endpoints"

### Commit 10: Frontend — Tag review UI
- Replace `TrackList.tsx` with new `TrackTable.tsx` (Rekordbox-style)
- Create components:
  - `TrackTable.tsx` — sortable table with configurable columns
  - `ColumnMenu.tsx` — right-click column visibility context menu
  - `AnalysisControls.tsx` — toolbar with Analyse/Write Tags buttons and progress
  - `TrackDetailPanel.tsx` — detailed view for selected track with revert options
  - `BPMCell.tsx` — BPM display with ×2/÷2 buttons
  - `KeyCell.tsx` — key display in preferred notation
  - `ConfidenceIndicator.tsx` — visual indicator for low-confidence values
- Add API methods to `client.ts` for analysis, tag writing, track editing, revert, BPM multiply
- Wire SSE for analysis progress
- Commit: "Add Rekordbox-style tag review UI with inline editing"

### Commit 11: Integration tests and cleanup
- End-to-end test: ingest file → analyse → verify DB fields → write tags → verify tags on file
- Verify tag round-trip: write tags with mutagen → read back → values match
- Test revert flow: analyse → revert BPM → verify source_bpm restored
- Test BPM ×2/÷2: analyse → multiply → verify new value
- Review all TODO comments in new code
- Update CLAUDE.md with Phase 2 status
- Commit: "Add integration tests and update project docs for Phase 2"

---

## Claude Code Prompt

The following prompt is designed to be given to Claude Code at the start of the implementation session. Copy it verbatim.

---

```
You are implementing Phase 2 (Metadata & Tagging) of rekordbot.

Read these files first:
- CLAUDE.md (project conventions, architecture, coding standards)
- docs/features/phase-2-metadata-tagging.md (the feature brief — this is your specification)
- backend/models/track.py (existing Track model — you'll need to extend it)
- backend/config.py (existing Settings — you'll add new config fields)
- backend/exceptions.py (existing exception hierarchy — add new types as needed)
- backend/main.py (existing FastAPI app — you'll register new routes here)
- backend/services/queue.py (Phase 1 queue — reference for batch processing and SSE patterns)
- backend/routes/ingest.py (Phase 1 routes — reference for SSE endpoint patterns)

## What you're building

A metadata and tagging pipeline that:
1. Reads existing tags from output audio files using mutagen
2. Detects BPM using librosa (with configurable half/double-time auto-correction)
3. Detects musical key using librosa chroma features + Krumhansl-Schmuckler algorithm
4. Stores everything in SQLite with original values preserved for comparison/revert
5. Writes clean tags to AIFF, MP3, and M4A output files on explicit user action
6. Provides a Rekordbox-style tag review UI with inline editing, confidence indicators, and BPM ×2/÷2 quick-fix
7. Reports analysis progress via SSE

This pipeline is SEPARATE from Phase 1's ingestion pipeline. Tracks are ingested first, then analysed and tagged as a distinct operation. Do not modify Phase 1's converter or queue code.

## Build order (follow this exactly)

### Step 1: Dependencies and config
- Add librosa and mutagen to pyproject.toml and update uv.lock
- Add to Settings in config.py:
  - bpm_range_min: int (default 70)
  - bpm_range_max: int (default 180)
  - confidence_threshold: float (default 0.6)
  - max_concurrent_analyses: int (default 1)
  - default_key_notation: str (default "camelot")
- Add AnalysisError, TagReadError, TagWriteError to exceptions.py if not already present
- Commit: "Add Phase 2 dependencies and configuration"

### Step 2: Track model updates
- Review existing Track model columns against the feature brief's DB Schema Changes section
- Add: source_bpm (Float, nullable), source_key (Integer, nullable), bpm_confidence (Float, nullable), key_confidence (Float, nullable), analysis_status (String, default "unanalysed")
- Verify existing column types: bpm (Float), key (Integer), duration (Float), rating (Integer)
- Commit: "Extend Track model with analysis-specific columns"

### Step 3: Key notation module (TDD)
- Create backend/services/key_notation.py
- WRITE TESTS FIRST in backend/tests/test_key_notation.py:
  - Test all 24 keys for camelot_to_classical(), key_to_camelot_str(), key_to_open_key_str()
  - Test classical_to_camelot() with standard names + sharp/flat aliases + abbreviated forms
  - Test parse_key_tag() with Camelot, Open Key, classical, and garbage input
  - Test key_to_display() with all three notation preferences
  - Edge cases: None, empty string, numeric strings
- Then implement all functions
- This is pure logic — no I/O, no dependencies beyond Python stdlib
- Commit: "Add key notation mapping with Camelot/Open Key/classical conversion (TDD)"

### Step 4: Tag reader
- Create backend/services/tag_reader.py
- Write tests first for tag value parsing helpers (TRCK "3/12" format, TYER/TDRC, etc.)
- Implement TagData dataclass and read_tags() function
- Handle AIFF (mutagen.aiff), MP3 (mutagen.mp3), M4A (mutagen.mp4)
- Integration tests with Phase 1's test audio fixtures
- Commit: "Add tag reader with mutagen integration"

### Step 5: BPM detector (TDD for pure logic)
- Create backend/services/bpm_detector.py
- WRITE TESTS FIRST for:
  - correct_bpm_range(): test the full truth table (in range, double, halve, out-of-range-after-correction, boundary values)
  - compute_bpm_confidence(): test with synthetic data
- Then implement BPMResult dataclass, correction logic, and detect_bpm() orchestrator
- Integration test: detect BPM on a Phase 1 test fixture, verify reasonable result
- Commit: "Add BPM detector with librosa and auto-correction (TDD)"

### Step 6: Key detector (TDD for pure logic)
- Create backend/services/key_detector.py
- WRITE TESTS FIRST for:
  - compute_key_correlations(): synthetic chroma vector → expected correlations
  - select_best_key(): clear winner vs ambiguous case
  - compute_key_confidence(): gap-based metric
- Then implement KeyResult dataclass, correlation logic, and detect_key() orchestrator
- Integration test: detect key on a test fixture
- Commit: "Add key detector with librosa chroma and Krumhansl-Schmuckler (TDD)"

### Step 7: Tag writer
- Create backend/services/tag_writer.py
- Implement write_tags() for AIFF, MP3 (ID3v2.3, no v1), and M4A (MP4 atoms)
- Write BPM to TBPM (AIFF/MP3) or tmpo atom (M4A), key to TKEY or INITIALKEY freeform atom (Open Key notation)
- Preserve existing unmanaged tags (album art, custom frames)
- Integration tests: write → read back → verify (all three formats)
- Commit: "Add tag writer with ID3v2.3 for AIFF/MP3 and MP4 atoms for M4A"

### Step 8: Analysis pipeline
- Create backend/services/analysis.py
- Implement analyse_track() and analyse_batch() orchestrators
- Follow Phase 1's queue.py patterns for concurrency and SSE
- Load audio once with librosa, pass to both BPM and key detectors
- Per-track error isolation, cancellation support
- Commit: "Add analysis pipeline with batch processing and SSE progress"

### Step 9: API routes
- Create backend/routes/tagging.py
- Implement all endpoints from the feature brief
- Enhance existing GET /api/tracks with analysis fields
- Register in main.py
- Test all endpoints
- Commit: "Add tagging API routes with analysis, editing, and revert endpoints"

### Step 10: Frontend — Tag review UI
- Replace basic TrackList with Rekordbox-style TrackTable
- Implement: TrackTable, ColumnMenu, AnalysisControls, TrackDetailPanel, BPMCell, KeyCell, ConfidenceIndicator
- Add API methods to client.ts
- Wire SSE for analysis progress
- Commit: "Add Rekordbox-style tag review UI with inline editing"

### Step 11: Integration tests and cleanup
- End-to-end: ingest → analyse → verify DB → write tags → verify file tags
- Tag round-trip test
- Revert and BPM multiply flows
- Update CLAUDE.md
- Commit: "Add integration tests and update project docs for Phase 2"

## Constraints
- Follow all conventions in CLAUDE.md (type hints, docstrings, error handling, logging, etc.)
- librosa.load() and analysis functions are CPU-intensive — run via asyncio.to_thread()
- Do NOT modify Phase 1's converter, queue, or ingest routes
- Tag writing ONLY happens on explicit user action — never automatic
- ID3v2.3 for AIFF/MP3 — no v2.4, no v1. MP4 atoms for M4A.
- Key stored as integer 1–24 internally, displayed in user's preferred notation
- All exceptions should be RekordBotError subclasses

## Important
- Do NOT infer genre, mood, or energy — that's Phase 3 (Claude AI)
- Do NOT organise files into folders — that's Phase 2b
- Do NOT read/write album art
- Do NOT implement batch tag editing (apply same value to multiple tracks)
- Source files are NEVER modified — tags are written to output files only
- The analysis pipeline is SEPARATE from ingestion — do not merge them
```

### Continuation Prompt

If the session is interrupted and you need to resume in a new Claude Code session, use this:

```
We are continuing Phase 2 (Metadata & Tagging) of rekordbot.

Read these files for context:
- CLAUDE.md (project conventions and current status)
- SESSIONS.md (latest entry has where we left off and what's next)
- docs/features/phase-2-metadata-tagging.md (the feature specification)

Pick up from where we left off. Check SESSIONS.md for the last completed step
and what was identified as the next task. Confirm what you think the next step
is before writing any code.
```

---

## Notes

- librosa does not have built-in key detection. We implement Krumhansl-Schmuckler ourselves on top of librosa's chroma features. The implementation is straightforward (Pearson correlation of chroma vector against 24 rotated key profiles) and well-documented in the references below.
- The Krumhansl-Schmuckler profiles are the original 1990 values. Alternative profiles exist (Temperley, Albrecht-Shanahan) and could be tested if accuracy is insufficient, but K-S is the standard starting point.
- librosa.load() defaults to mono, 22050 Hz. This is fine for analysis — we don't need full-resolution audio for BPM/key detection. It also reduces memory usage significantly compared to loading at native sample rate.
- The confidence threshold (default 0.6) is a starting value. It should be tuned empirically during implementation by running detection on a set of tracks with known BPM/key values. This tuning is part of the implementation, not a pre-decision.
- M4A tag writing uses mutagen's MP4 support. Unlike AIFF/MP3 (which use ID3 frames), M4A uses MP4 atoms — a different tag system. The tmpo atom stores BPM as an integer (no decimal places), so M4A BPM will be rounded. Key is stored as a freeform iTunes atom (`----:com.apple.iTunes:INITIALKEY`).

### References
- [Krumhansl-Schmuckler key-finding algorithm](https://github.com/jackmcarthur/musical-key-finder) — reference implementation using librosa
- [librosa beat_track documentation](https://librosa.org/doc/main/generated/librosa.beat.beat_track.html)
- [librosa chroma_cqt documentation](https://librosa.org/doc/main/generated/librosa.feature.chroma_cqt.html)
