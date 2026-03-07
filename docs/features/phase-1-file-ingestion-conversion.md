# Feature: File Ingestion & Conversion
**Branch:** `feature/phase-1-converter`
**Status:** Not Started
**Phase:** 1
**Depends on:** Phase 0 (complete)

---

## Goal

Drop audio files into rekordbot and get CDJ-ready outputs: lossless files converted to AIFF, lossy files left as-is (or converted to MP3 if AAC and user opts in), with quality metadata recorded for every track, duplicate detection, and progress reporting — all without any silent or lossy-to-lossy conversion the user didn't ask for.

---

## Inputs

- One or more audio files, provided by either:
  - **Drag-and-drop** onto a drop zone in the frontend
  - **Folder selection** via a file/folder dialog (Tauri IPC)
- Supported input formats: WAV, FLAC, ALAC, AIFF, MP3, M4A (containing either ALAC or AAC)
- User preferences (from settings, persisted in config):
  - `convert_aac_to_mp3`: bool (default `false`) — whether AAC files should be transcoded to MP3
  - `output_directory`: str — where converted/imported files are written

## Outputs

- Converted audio files written to the output directory:
  - Lossless sources (WAV, FLAC, ALAC) → AIFF
  - AIFF → copied as-is (already target format)
  - MP3 → copied as-is
  - M4A/ALAC → AIFF
  - M4A/AAC → copied as-is (default) or converted to MP3 (if user preference enabled)
- A `Track` record in SQLite for every successfully processed file, including:
  - `source_format`, `source_codec`, `source_bitrate`, `source_path`
  - `output_format`, `output_path`
  - `file_hash` (SHA-256 of source file)
  - `quality_warning` flag (true if lossy and below 192 kbps)
  - `conversion_action` taken (e.g. `"converted_to_aiff"`, `"copied_as_is"`, `"converted_to_mp3"`)
- SSE progress events for each file: queued → processing → complete/failed
- API responses with per-file status (success, skipped as duplicate, failed with reason)

---

## Architecture & Key Components

### 1. Format Inspector (`backend/services/format_inspector.py`)

Wraps `ffprobe` to determine the true format and codec of a file. This is the first thing that runs on every ingested file — we never trust the file extension alone.

**Responsibilities:**
- Run `ffprobe -v quiet -print_format json -show_format -show_streams <file>`
- Parse the JSON output into a typed `FileInfo` dataclass:
  ```
  FileInfo:
    path: Path
    container: str          # e.g. "wav", "flac", "mov,mp4,m4a", "aiff", "mp3"
    codec: str              # e.g. "pcm_s16le", "flac", "alac", "aac", "mp3"
    sample_rate: int        # e.g. 44100, 48000
    bit_depth: int | None   # e.g. 16, 24 (None for lossy)
    bitrate: int            # kbps (from format-level or stream-level)
    duration: float         # seconds
    channels: int           # 1 or 2
    is_lossless: bool       # derived from codec
  ```
- Determine `is_lossless` from codec name (explicit allowlist: `pcm_*`, `flac`, `alac`)
- Flag quality warning if lossy and bitrate < 192 kbps

**Edge cases to handle:**
- M4A with ALAC vs AAC (same container, different codec — this is the whole reason ffprobe exists in our pipeline)
- Files with incorrect extensions (e.g. `.wav` that's actually MP3)
- Corrupt or unreadable files (ffprobe returns non-zero)
- Multi-stream files (take first audio stream)
- Files with no audio stream at all

### 2. Conversion Decision Engine (`backend/services/conversion.py`)

Pure logic function: given a `FileInfo`, returns a `ConversionAction` describing what to do. No side effects — this is the core of the quality-preserving principle and must be tested exhaustively.

**Decision table:**

| Source Codec | is_lossless | Action | Output Format | Output Bit Depth |
|---|---|---|---|---|
| pcm_s16le / pcm_s24le (WAV) | true | Convert to AIFF | AIFF | Preserve source (16 or 24) |
| pcm_s32le / float32 (WAV) | true | Convert to AIFF | AIFF | 24-bit (capped) |
| flac | true | Convert to AIFF | AIFF | Preserve source (16 or 24) |
| alac | true | Convert to AIFF | AIFF | Preserve source (16 or 24) |
| pcm_s16be / pcm_s24be (AIFF) | true | Copy as-is | AIFF | Unchanged |
| mp3 | false | Copy as-is | MP3 | N/A |
| aac (convert_aac_to_mp3=false) | false | Copy as-is | M4A | N/A |
| aac (convert_aac_to_mp3=true) | false | Convert to MP3 | MP3 | N/A (VBR V0) |

**Return type:**
```
ConversionAction:
  action: Literal["convert_to_aiff", "convert_to_mp3", "copy_as_is", "skip_duplicate", "reject"]
  reason: str              # Human-readable explanation of why this action was chosen
  output_format: str       # "aiff", "mp3", "m4a", or "" if rejected
  output_bit_depth: int | None  # 16 or 24 for AIFF conversions, None for lossy/copy
  quality_warning: bool    # True if lossy < 192kbps
  warning_detail: str      # e.g. "128 kbps AAC — below quality threshold"
```

### 3. Converter Service (`backend/services/converter.py`)

Executes the actual conversion or copy operation. Orchestrates the full pipeline for a single file: inspect → decide → execute → hash → store.

**Responsibilities:**
- Call format inspector to get `FileInfo`
- Call decision engine to get `ConversionAction`
- If converting: build and run ffmpeg command via `asyncio.create_subprocess_exec`
- If copying: `shutil.copy2` (preserves metadata timestamps)
- Compute SHA-256 hash of the **source** file (for duplicate detection — hash before conversion so we catch dupes regardless of output format)
- Check hash against existing tracks in DB
- On success: create `Track` record in DB
- On failure: log error, return failure status (do not raise — the queue needs to continue processing other files)

**ffmpeg command templates:**
- Lossless → AIFF (16-bit source): `ffmpeg -i <input> -c:a pcm_s16be -f aiff <o>`
- Lossless → AIFF (24-bit source): `ffmpeg -i <input> -c:a pcm_s24be -f aiff <o>`
- Lossless → AIFF (32-bit float): `ffmpeg -i <input> -c:a pcm_s24be -f aiff <o>` (capped at 24-bit)
- AAC → MP3: `ffmpeg -i <input> -c:a libmp3lame -q:a 0 <o>` (LAME VBR V0, ~245 kbps avg — best quality for lossy-to-lossy)

**Bit depth strategy:** Preserve source bit depth, capped at 24-bit.
- 16-bit source → `pcm_s16be` AIFF
- 24-bit source → `pcm_s24be` AIFF
- 32-bit float source → `pcm_s24be` AIFF (capped — 32-bit float is a production format with no CDJ support)

This is consistent with the quality-preserving principle. The format inspector must reliably extract bit depth from ffprobe output (`bits_per_raw_sample` field, or derived from codec name for PCM formats).

### 4. Processing Queue (`backend/services/queue.py`)

Manages batch processing of multiple files with concurrency control and progress reporting.

**Responsibilities:**
- Accept a list of file paths to process
- Process files through the converter service with bounded concurrency (`asyncio.Semaphore`, default 2 concurrent conversions)
- Emit SSE events for each file state transition: `queued` → `processing` → `complete` / `failed`
- Track overall batch progress (files completed / total)
- Support cancellation (set a flag that the processing loop checks between files)
- Return a batch summary when complete

**SSE event schema:**
```json
{
  "event": "file_progress",
  "data": {
    "file_path": "/path/to/original.flac",
    "status": "processing",
    "action": "convert_to_aiff",
    "progress_pct": null,
    "message": "Converting to AIFF...",
    "batch_progress": {"completed": 3, "total": 10, "failed": 0}
  }
}
```

Note: Per-file progress percentage (tracking ffmpeg's conversion progress via stderr parsing) is a nice-to-have. For Phase 1, file-level granularity (queued/processing/complete/failed) is sufficient. ffmpeg progress parsing can be added later without architectural changes.

### 5. Output File Naming (`backend/services/naming.py`)

Determines the output filename and path for each converted/copied file.

**Strategy for Phase 1 (pre-file-organisation):**
- Output directory: `{output_directory}/imports/{YYYY-MM-DD}/`
- Filename: preserve original filename, change extension to match output format
- If name collision: append `_1`, `_2`, etc.
- All paths recorded in DB so Phase 2b's file organiser can move them later

This is deliberately simple. Phase 2b introduces the full template-based organisation. Phase 1 just needs a sane, non-destructive landing zone.

### 6. API Routes (`backend/routes/ingest.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ingest` | Accept file paths, start processing queue |
| GET | `/api/ingest/progress` | SSE endpoint for progress events |
| POST | `/api/ingest/cancel` | Cancel current batch processing |
| GET | `/api/tracks` | List all tracks in DB (basic, for the library view stub) |

**POST `/api/ingest` request body:**
```json
{
  "paths": ["/path/to/file1.flac", "/path/to/folder/"],
  "options": {
    "convert_aac_to_mp3": false
  }
}
```

Paths can be individual files or directories (recursively scanned). The route handler expands directories, filters to supported audio extensions, and hands the list to the processing queue.

**POST `/api/ingest` response:**
```json
{
  "batch_id": "uuid",
  "total_files": 15,
  "message": "Processing started"
}
```

### 7. Frontend — Drop Zone & Processing Queue (`frontend/src/`)

- **DropZone component:** Drag-and-drop area + button to open folder dialog (Tauri `dialog.open`)
- **ProcessingQueue component:** Live-updating list showing each file's status, driven by SSE
- **Basic library list:** Simple table of processed tracks from `/api/tracks` — sortable by name, format, bitrate. Not the full library view (that's Phase 2+), just enough to confirm files were processed correctly.

---

## Acceptance Criteria

### Core conversion logic
- [ ] WAV file → converted to AIFF, source recorded as lossless
- [ ] FLAC file → converted to AIFF, source recorded as lossless
- [ ] ALAC file (inside .m4a container) → converted to AIFF, source recorded as lossless
- [ ] AIFF file → copied as-is, no conversion
- [ ] MP3 file → copied as-is, no conversion
- [ ] AAC file (inside .m4a) with `convert_aac_to_mp3=false` → copied as-is
- [ ] AAC file (inside .m4a) with `convert_aac_to_mp3=true` → converted to MP3
- [ ] Output files are playable and not corrupt (manual spot-check)

### Quality preservation principle
- [ ] No lossy-to-lossy conversion occurs unless the user has explicitly enabled AAC→MP3
- [ ] Lossy files below 192 kbps are flagged with a quality warning in the DB and UI
- [ ] Source format, codec, and bitrate are recorded in DB for every track

### Duplicate detection
- [ ] Ingesting the same file twice (identical SHA-256) → second attempt is skipped with "duplicate" status
- [ ] Duplicate detection works across formats (same source file won't be processed again even if the output was moved)

### Error handling
- [ ] Corrupt/unreadable file → logged as error, skipped, batch continues
- [ ] Unsupported format (e.g. .ogg, .wma) → rejected with clear reason, batch continues
- [ ] ffmpeg not found → clear error message at startup or first conversion attempt
- [ ] Output directory doesn't exist → created automatically
- [ ] Disk full / write permission error → error surfaced to user, batch stops gracefully

### Progress & UX
- [ ] SSE progress events emitted for each file state change
- [ ] Frontend drop zone accepts drag-and-drop files
- [ ] Frontend drop zone accepts folder selection via dialog
- [ ] Processing queue shows live status of each file
- [ ] Batch summary shown when processing completes (X succeeded, Y failed, Z duplicates)

### Data integrity
- [ ] Every successfully processed file has a corresponding `Track` record in SQLite
- [ ] Track record includes: source_path, source_format, source_codec, source_bitrate, output_path, output_format, file_hash, quality_warning, conversion_action, created_at
- [ ] Track list API (`/api/tracks`) returns all processed tracks

---

## Out of Scope

- **Tag reading/writing** — Phase 2 (mutagen integration). Phase 1 does NOT read or write any ID3 tags.
- **File organisation / folder structure** — Phase 2b. Phase 1 writes to a flat `imports/{date}/` directory.
- **BPM / key detection** — Phase 2.
- **Claude AI enrichment** — Phase 3.
- **Rekordbox XML export** — Phase 4.
- **Hot folder / watch mode** — deferred (architectural decision not yet made; see project plan open questions).
- **Per-file ffmpeg progress** — nice-to-have, not required for Phase 1. File-level status is sufficient.
- **Waveform generation** — not in scope for any current phase.

---

## Dependencies

- **ffmpeg** and **ffprobe** — must be available on PATH or at the configured `ffmpeg_path`. Confirmed available in dev environment (Session 2).
- **Phase 0 infrastructure** — FastAPI app, SQLAlchemy models, config system, exception hierarchy, SSE capability (not yet implemented — needs adding).
- **Track model** — exists from Phase 0 but will need new columns (see DB Changes below).

---

## DB Schema Changes

The Phase 0 `Track` model was designed with Rekordbox-compatible fields. Phase 1 needs to add ingestion-specific columns that track the source file's provenance. Review the existing model and add:

| Column | Type | Purpose |
|---|---|---|
| `source_path` | String | Original file path before conversion |
| `source_format` | String | Container format (e.g. "wav", "flac", "m4a") |
| `source_codec` | String | Actual codec (e.g. "pcm_s16le", "alac", "aac") |
| `source_bitrate` | Integer | Source file bitrate in kbps |
| `source_bit_depth` | Integer, nullable | Source bit depth (16, 24, 32) — null for lossy |
| `file_hash` | String(64) | SHA-256 hex digest of source file, unique index |
| `quality_warning` | Boolean | True if lossy < 192 kbps |
| `conversion_action` | String | Action taken: "convert_to_aiff", "copy_as_is", etc. |
| `imported_at` | DateTime | When the file was processed |

Some of these may already exist in the Phase 0 Track model under different names — check and reconcile rather than blindly adding.

---

## Decisions (Finalised)

All decisions were discussed and agreed before implementation.

| # | Decision | Resolution |
|---|---|---|
| 1 | **AIFF bit depth** | Preserve source bit depth, capped at 24-bit. 16-bit → 16-bit AIFF, 24-bit → 24-bit AIFF, 32-bit float → 24-bit AIFF. Quality-preserving principle: don't discard information. |
| 2 | **Output directory structure** | `{output_directory}/imports/{YYYY-MM-DD}/`. Simple date-batched folders. Phase 2b relocates them later. |
| 3 | **Source files after processing** | Never touch source files. rekordbot writes to its output directory only. |
| 4 | **Concurrency level** | Default 2 concurrent ffmpeg conversions. Configurable via `REKORDBOT_MAX_CONCURRENT_CONVERSIONS`. |
| 5 | **Files already in AIFF** | Always copy to output directory. Consistency over efficiency — all managed files live in one place. |
| 6 | **SSE implementation** | Use `sse-starlette` package. Lightweight, handles reconnection and formatting. |
| 7 | **AAC → MP3 conversion** | Optional, user-controlled. Global default in Settings (`convert_aac_to_mp3`, default `false`). Per-ingest override available in POST `/api/ingest`. When enabled, uses LAME VBR V0 (`-q:a 0`, ~245 kbps avg) for best quality. |
| 8 | **Test audio fixtures** | Committed as small files in `backend/tests/fixtures/audio/`. Generated once with a script, ~1 second of silence each. Faster tests, no ffmpeg dependency for test suite. |

---

## TDD Candidates

Per CLAUDE.md convention, these are the pure logic functions with clearly defined inputs/outputs that should be written test-first:

| Function | Location | Why TDD |
|---|---|---|
| `parse_ffprobe_output()` | `format_inspector.py` | Pure parsing: JSON in → `FileInfo` out. Clear edge cases (multi-stream, no audio, corrupt output). |
| `determine_lossless()` | `format_inspector.py` | Codec string → bool. Explicit allowlist, truth table. |
| `get_quality_warning()` | `format_inspector.py` | Bitrate + is_lossless → warning flag + message. Simple threshold logic. |
| `decide_conversion()` | `conversion.py` | `FileInfo` + user prefs → `ConversionAction`. This IS the decision table above. Highest-value TDD target in the whole phase. |
| `build_ffmpeg_command()` | `converter.py` | `FileInfo` + `ConversionAction` → list of ffmpeg args. Deterministic, testable. |
| `generate_output_path()` | `naming.py` | Source path + output dir + format → output path. Collision handling. |
| `compute_file_hash()` | `converter.py` | File path → SHA-256 hex string. (Simple, but good to have a test confirming it's stable.) |

Functions that should be tested **after** implementation (framework integration, I/O-dependent):
- Route handlers (POST `/api/ingest`, GET `/api/tracks`)
- SSE event streaming
- Actual ffmpeg subprocess execution
- Database operations (Track creation, duplicate lookup)
- Frontend components

---

## Commit Breakdown

Proposed order of implementation. Each commit is a logical, self-contained unit that leaves the codebase in a working state.

### Commit 1: Add new dependencies and config
- Add `sse-starlette` to pyproject.toml
- Add `max_concurrent_conversions` and `output_directory` to Settings
- Update uv.lock

### Commit 2: Track model updates
- Review existing Track model against Phase 1 needs
- Add missing columns (source_path, source_format, source_codec, source_bitrate, file_hash, quality_warning, conversion_action, imported_at)
- Add unique index on file_hash
- Update existing tests if model fixture changes

### Commit 3: Format inspector (TDD)
- Write tests first for `parse_ffprobe_output`, `determine_lossless`, `get_quality_warning`
- Implement `FileInfo` dataclass
- Implement `format_inspector.py` with ffprobe subprocess call
- Include test fixtures: sample ffprobe JSON outputs for each format (WAV, FLAC, ALAC-in-M4A, AAC-in-M4A, MP3, AIFF, corrupt file, no audio stream)

### Commit 4: Conversion decision engine (TDD)
- Write tests first covering the full decision table (every row, plus edge cases)
- Implement `ConversionAction` dataclass
- Implement `decide_conversion()` in `conversion.py`
- This commit is pure logic — no I/O, no subprocess, no DB

### Commit 5: Output naming (TDD)
- Write tests for `generate_output_path` including collision handling
- Implement `naming.py`

### Commit 6: Converter service
- Implement `build_ffmpeg_command()` (TDD — write test first for command construction)
- Implement `compute_file_hash()` (test with a known test file)
- Implement `convert_file()` — the orchestrator that calls inspector → decision → ffmpeg/copy → hash → DB store
- Integration tests with actual ffmpeg (needs sample audio files in test fixtures — small WAV, FLAC, MP3)

### Commit 7: Processing queue
- Implement `queue.py` with asyncio Semaphore-based concurrency
- Implement SSE event emission
- Implement batch processing with per-file error isolation
- Tests for queue logic (mock the converter to test concurrency and error handling)

### Commit 8: API routes
- Implement POST `/api/ingest` (path expansion, validation, queue dispatch)
- Implement GET `/api/ingest/progress` (SSE endpoint)
- Implement POST `/api/ingest/cancel`
- Implement GET `/api/tracks` (basic track listing)
- Route handler tests with httpx async client

### Commit 9: Frontend — drop zone and processing queue
- DropZone component (drag-and-drop + Tauri dialog integration)
- ProcessingQueue component (SSE consumer, live status list)
- Basic track list view (table from `/api/tracks`)
- Wire into App.tsx layout

### Commit 10: Integration test and cleanup
- End-to-end test: drop files via API → verify conversion → verify DB records → verify SSE events
- Add sample test audio files to `backend/tests/fixtures/` (small files, ~1 second each, one per format)
- Review all TODO comments, remove or track
- Update CLAUDE.md with Phase 1 status

---

## Claude Code Prompt

The following prompt is designed to be given to Claude Code at the start of the implementation session. Copy it verbatim.

---

```
You are implementing Phase 1 (File Ingestion & Conversion) of rekordbot.

Read these files first:
- CLAUDE.md (project conventions, architecture, coding standards)
- docs/features/phase-1-file-ingestion-conversion.md (the feature brief — this is your specification)
- backend/models/track.py (existing Track model from Phase 0 — you'll need to extend it)
- backend/config.py (existing Settings — you'll need to add new config fields)
- backend/exceptions.py (existing exception hierarchy — add new exception types as needed)
- backend/main.py (existing FastAPI app — you'll register new routes here)

## What you're building

A file ingestion and conversion pipeline that:
1. Inspects audio files with ffprobe to determine true format/codec/bitrate/bit_depth
2. Makes a quality-preserving conversion decision (lossless → AIFF preserving bit depth; lossy left as-is; AAC → MP3 optional)
3. Executes conversion via ffmpeg or copies files as-is
4. Detects duplicates via SHA-256 hash
5. Records everything in SQLite
6. Reports progress via SSE
7. Exposes it all through REST API endpoints

## Build order (follow this exactly)

### Step 1: Dependencies and config
- Add sse-starlette to pyproject.toml and update uv.lock
- Add to Settings in config.py:
  - output_directory: str (default: "~/rekordbot/library")
  - max_concurrent_conversions: int (default: 2)
  - convert_aac_to_mp3: bool (default: false)
  - ffprobe_path: str (default: "ffprobe")
- Commit: "Add Phase 1 dependencies and configuration"

### Step 2: Track model updates
- Review existing Track model columns against the feature brief's DB Schema Changes section
- Add missing columns: source_path, source_format, source_codec, source_bitrate, source_bit_depth (nullable), file_hash (unique index), quality_warning, conversion_action, imported_at
- Reconcile with any existing columns that overlap — don't duplicate
- Update any existing model tests
- Commit: "Extend Track model with ingestion-specific columns"

### Step 3: Format inspector (TDD)
- Create backend/services/format_inspector.py
- WRITE TESTS FIRST in backend/tests/test_format_inspector.py:
  - Test parse_ffprobe_output() with sample JSON for: WAV 16-bit, WAV 24-bit, FLAC 16-bit, FLAC 24-bit, ALAC in M4A, AAC in M4A, MP3, AIFF 16-bit, AIFF 24-bit, corrupt/missing audio, multi-stream
  - Test determine_lossless() for every codec in the allowlist + some lossy codecs
  - Test get_quality_warning() at boundary: 191kbps (warn), 192kbps (no warn), lossless (no warn regardless of bitrate)
- Then implement:
  - FileInfo dataclass
  - parse_ffprobe_output(json_output: dict) -> FileInfo
  - determine_lossless(codec: str) -> bool
  - get_quality_warning(bitrate: int, is_lossless: bool) -> tuple[bool, str]
  - inspect_file(path: Path) -> FileInfo (runs ffprobe subprocess)
- Commit: "Add format inspector with ffprobe integration (TDD)"

### Step 4: Conversion decision engine (TDD)
- Create backend/services/conversion.py
- WRITE TESTS FIRST in backend/tests/test_conversion.py:
  - Test every row of the decision table from the feature brief
  - Include bit depth preservation: 16-bit → pcm_s16be, 24-bit → pcm_s24be, 32-bit float → pcm_s24be (capped)
  - Test the AAC toggle both ways (convert_aac_to_mp3 true and false)
  - Test quality warning propagation
- Then implement:
  - ConversionAction dataclass
  - decide_conversion(file_info: FileInfo, convert_aac_to_mp3: bool) -> ConversionAction
- This is pure logic. No I/O, no subprocess, no DB.
- Commit: "Add conversion decision engine (TDD)"

### Step 5: Output naming (TDD)
- Create backend/services/naming.py
- WRITE TESTS FIRST:
  - Basic path generation: source.flac → {output_dir}/imports/2026-03-07/source.aiff
  - Extension mapping: .flac → .aiff, .wav → .aiff, .m4a (ALAC) → .aiff, .m4a (AAC) → .mp3 or .m4a
  - Collision handling: if source.aiff exists, generate source_1.aiff, source_2.aiff, etc.
  - Path with special characters (spaces, unicode)
- Then implement:
  - generate_output_path(source_path: Path, output_dir: Path, output_format: str) -> Path
- Commit: "Add output path generation with collision handling (TDD)"

### Step 6: Converter service
- Create backend/services/converter.py
- WRITE TESTS FIRST for build_ffmpeg_command():
  - 16-bit lossless → AIFF: should produce [ffmpeg, -i, input, -c:a, pcm_s16be, -f, aiff, output]
  - 24-bit lossless → AIFF: should produce [ffmpeg, -i, input, -c:a, pcm_s24be, -f, aiff, output]
  - 32-bit float → AIFF: should produce pcm_s24be (capped)
  - AAC → MP3: should produce [ffmpeg, -i, input, -c:a, libmp3lame, -q:a, 0, output]
- Write test for compute_file_hash() with a known test file
- Then implement:
  - build_ffmpeg_command(input_path: Path, output_path: Path, action: ConversionAction, file_info: FileInfo) -> list[str]
  - compute_file_hash(path: Path) -> str
  - convert_file(path: Path, db_session, settings) -> TrackResult (the full orchestrator: inspect → decide → execute → hash → check duplicate → store)
- Add ConversionError to exceptions.py if not already present
- Commit: "Add converter service with ffmpeg execution pipeline"

### Step 7: Processing queue
- Create backend/services/queue.py
- Implement:
  - ProcessingQueue class with asyncio.Semaphore for concurrency control
  - process_batch(paths: list[Path], options, db_session, settings) -> BatchResult
  - SSE event emission using sse-starlette's EventSourceResponse pattern
  - Per-file error isolation (one failure doesn't stop the batch)
  - Cancellation support via asyncio.Event
- Test queue logic by mocking the converter (test concurrency, error handling, cancellation)
- Commit: "Add processing queue with concurrency control and SSE"

### Step 8: API routes
- Create backend/routes/ingest.py
- Implement:
  - POST /api/ingest — accept paths (files or dirs), expand dirs recursively, filter to supported extensions, dispatch to queue
  - GET /api/ingest/progress — SSE endpoint streaming file progress events
  - POST /api/ingest/cancel — cancel current batch
  - GET /api/tracks — list all tracks (basic pagination: limit/offset)
- Register routes in main.py
- Test all endpoints with httpx async client
- Commit: "Add ingestion API routes with SSE progress"

### Step 9: Frontend
- Create frontend components:
  - DropZone.tsx — drag-and-drop area + folder dialog button (use Tauri dialog API)
  - ProcessingQueue.tsx — SSE consumer showing live file status
  - TrackList.tsx — simple table of processed tracks from /api/tracks
- Add API methods to frontend/src/api/client.ts
- Wire into App.tsx layout
- Commit: "Add drop zone, processing queue, and track list UI"

### Step 10: Test fixtures and integration test
- Generate small test audio files (~1 second silence, one per format: WAV 16-bit, WAV 24-bit, FLAC, MP3, AIFF, M4A/ALAC, M4A/AAC) using ffmpeg
- Commit them to backend/tests/fixtures/audio/
- Write an end-to-end test: POST files to /api/ingest → poll or consume SSE → verify Track records in DB → verify output files exist
- Write a script to generate the fixtures: scripts/generate-test-fixtures.sh
- Review all TODO comments in new code
- Commit: "Add test fixtures and integration tests"

## Constraints
- Follow all conventions in CLAUDE.md (type hints, docstrings, error handling, logging, etc.)
- Use async/await for route handlers. Blocking I/O (ffmpeg, file hashing, file copy) via asyncio.to_thread() or asyncio.create_subprocess_exec
- Never silently swallow exceptions — log and surface
- The Track model is sync SQLAlchemy (not async) per CLAUDE.md
- Every service module gets its own logger via logging.getLogger(__name__)
- All exceptions should be RekordBotError subclasses with proper error codes

## Important
- Do NOT read or write ID3 tags — that's Phase 2
- Do NOT organise files into genre/artist folders — that's Phase 2b
- Do NOT implement hot folder / watch mode
- Output goes to {output_directory}/imports/{YYYY-MM-DD}/ only
- Source files are NEVER modified, moved, or deleted
```

---

## Notes

- The Track model from Phase 0 was designed to be Rekordbox-compatible. The implementation must review it carefully before adding Phase 1 columns — some fields may already exist or need renaming rather than adding.
- Test audio fixtures are committed (not generated at test time). A generation script in `scripts/generate-test-fixtures.sh` documents how they were created.
- The `convert_aac_to_mp3` option has a global default in Settings and a per-ingest override in the POST body. If the POST body doesn't specify it, the global setting is used.
