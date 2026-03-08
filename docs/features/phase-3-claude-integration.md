# Feature: Claude AI Integration
**Branch:** `feature/phase-3-claude`
**Status:** Not Started
**Phase:** 3
**Depends on:** Phase 2 (complete)

---

## Goal

Use Claude to enrich every track in the rekordbot library with genre, subgenre, mood, and energy — metadata that algorithms can't reliably infer but that a language model can reason about from track titles, artist names, labels, BPM, key, and other contextual signals.

The AI tagging pipeline is **separate from both ingestion (Phase 1) and analysis (Phase 2)**. It operates on tracks that already have algorithmic metadata (BPM, key, existing tags). This means:
- Phase 1's conversion pipeline is untouched
- Phase 2's analysis pipeline is untouched
- Tracks can exist in the library without AI tags
- AI tags can be re-run at any time (new model, better prompts, changed preferences)
- Users review AI suggestions before anything is written to files
- The operation requires an Anthropic API key and costs money — this must be transparent

---

## Inputs

- Tracks already in the SQLite database with Phase 2 analysis complete (or at minimum, tag reader has populated existing metadata fields)
- Per-track data sent to Claude (structured summary, not audio):
  - `title`, `artist`, `album`, `album_artist`, `label`, `year`, `genre` (existing tag), `comment`
  - `bpm`, `key_display` (Camelot notation from Phase 2)
  - Source filename (often contains useful info: remix names, "bootleg", label codes, catalogue numbers)
  - `source_format`, `source_bitrate` (marginal signal, but context)
- User preferences (from settings, persisted in config):
  - `anthropic_api_key`: str — required, validated before first use
  - `ai_model`: str (default `"claude-sonnet-4-20250514"`) — model to use for AI tagging
  - `ai_batch_size`: int (default `20`) — tracks per API request
  - `ai_max_requests_per_minute`: int (default `10`) — rate limiting

## Outputs

- Updated `Track` records in SQLite with:
  - `genre` — AI-inferred genre (overwrites existing, original preserved in `source_genre`)
  - `subgenre` — more specific classification (new column)
  - `mood` — descriptive mood label (new column)
  - `energy` — numerical energy score 1–10 (new column)
  - `ai_confidence` — Claude's self-assessed confidence: "high", "medium", "low" (new column)
  - `ai_reasoning` — one-line explanation of why Claude chose these tags (new column)
  - `source_genre` — original genre tag value preserved for revert (new column)
  - `ai_status` — tracks AI tagging state: "untagged", "ai_tagged", "ai_tags_written" (new column)
- Genre written to TCON frame (AIFF/MP3) or ©gen atom (M4A) via existing tag writer when user clicks "Write Tags"
- Mood, energy, subgenre, and AI reasoning stored in DB only (no ID3 frame — these are for rekordbot's internal use: crate building, set planning, file organisation)
- SSE progress events for AI tagging batches
- Token usage and estimated cost logged per batch

---

## Architecture & Key Components

### 1. Prompt Builder (`backend/services/prompt_builder.py`)

Pure logic module that constructs prompts for Claude. No SDK dependency, no I/O — this is a TDD candidate.

**Responsibilities:**
- Build the system prompt with genre guidance, mood vocabulary, and energy scale definition
- Build per-track summaries from Track model data
- Group tracks into batches of configurable size
- Define the tool schema for structured output

**System prompt content:**

```
You are a music metadata specialist helping a DJ organise their library. For each track, infer the genre, subgenre, mood, and energy level based on the available metadata.

## Genre Guidelines
Use genre labels commonly recognised by DJs. Prefer specific subgenres over broad categories. For example, use "Melodic Techno" rather than "Electronic" or "Dance".

Common electronic music genres (use these as a starting point, but you may use others when appropriate):
- House: Deep House, Tech House, Progressive House, Acid House, Minimal House, Afro House, Melodic House, Funky House, Soulful House, Jackin House
- Techno: Melodic Techno, Acid Techno, Hard Techno, Industrial Techno, Minimal Techno, Detroit Techno, Dub Techno, Peak Time Techno
- Drum & Bass: Liquid DnB, Jungle, Neurofunk, Jump Up, Minimal DnB
- Trance: Progressive Trance, Psytrance, Uplifting Trance, Acid Trance, Tech Trance
- Bass Music: Dubstep, Future Bass, Riddim, UK Bass
- Garage: UK Garage, 2-Step, Speed Garage, Bassline
- Breakbeat: Breaks, Big Beat, Electro Breaks
- Ambient & Downtempo: Ambient, Downtempo, Chillout, IDM, Balearic
- Disco: Nu-Disco, Italo Disco, Cosmic Disco, Disco Edits
- Electro: Electro, Electronica
- Other: Hip-Hop, Trip-Hop, Funk, Soul, R&B, Reggae, Dub, Afrobeats, Amapiano, UK Funky, Grime

If the track doesn't fit neatly into electronic music (e.g. it's a rock or pop track a DJ might play), use an appropriate genre label from the broader music world.

## Mood
Use a single descriptive word or short phrase. Examples: Euphoric, Dark, Hypnotic, Uplifting, Melancholic, Aggressive, Dreamy, Groovy, Energetic, Mysterious, Anthemic, Soulful, Atmospheric, Driving, Funky, Playful, Intense, Ethereal, Raw, Warm, Blissful, Haunting, Gritty, Nostalgic, Meditative.

## Energy Scale (1–10)
1–2: Ambient, minimal, barely there. Intro/outro material.
3–4: Downtempo, chillout, warm-up. Gentle groove.
5–6: Mid-energy, cruising. Solid groove, not pushing.
7–8: Driving, building. Strong dancefloor energy.
9–10: Peak time, relentless. Maximum intensity.

## Confidence
Rate your confidence as "high", "medium", or "low":
- High: You recognise the artist/label/track or the metadata gives strong signals.
- Medium: Reasonable inference from available clues but some uncertainty.
- Low: Limited metadata, ambiguous signals, or unfamiliar artist/label.

## Instructions
- Use the tag_tracks tool to return your results.
- Provide a brief reasoning for each track (one sentence explaining your classification).
- If existing genre tags are present, consider them as a signal but don't blindly trust them — they are often wrong or overly broad.
- BPM and key are strong genre signals (e.g. 170+ BPM suggests DnB or hard techno; 120-126 BPM with minor key suggests deep/tech house).
- Artist and label names are often the strongest signals. Use your knowledge of the music industry.
- When unsure between two genres, pick the more specific one and note your uncertainty in the reasoning.
```

**Track summary format:**

```
Track #{id}:
  Title: {title}
  Artist: {artist}
  Album: {album}
  Label: {label}
  Year: {year}
  Existing Genre: {genre}
  BPM: {bpm}
  Key: {key_display}
  Filename: {filename}
  Comment: {comment}
```

Fields that are None/empty are omitted (less noise for Claude).

**Tool schema:**

```python
TOOL_SCHEMA = {
    "name": "tag_tracks",
    "description": "Apply genre, mood, and energy tags to a batch of tracks based on analysis of their metadata.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tracks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "track_id": {
                            "type": "integer",
                            "description": "The track ID from the input"
                        },
                        "genre": {
                            "type": "string",
                            "description": "Primary genre (e.g. 'Tech House', 'Melodic Techno', 'Liquid DnB')"
                        },
                        "subgenre": {
                            "type": "string",
                            "description": "More specific subgenre if applicable, or empty string if genre is already specific enough"
                        },
                        "mood": {
                            "type": "string",
                            "description": "Single word or short phrase describing the mood"
                        },
                        "energy": {
                            "type": "integer",
                            "description": "Energy level from 1 (ambient) to 10 (peak time)"
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "Your confidence in this classification"
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "One sentence explaining your classification"
                        }
                    },
                    "required": ["track_id", "genre", "subgenre", "mood", "energy", "confidence", "reasoning"]
                }
            }
        },
        "required": ["tracks"]
    }
}
```

**Batch grouping strategy:**
- Group tracks by artist first (tracks by the same artist in the same batch helps consistency)
- If an artist has more tracks than `ai_batch_size`, split across multiple batches
- Fill remaining batch slots with tracks grouped by album, then by label
- Fall back to arbitrary grouping for diverse libraries
- This is a best-effort optimisation, not a hard requirement — any grouping works

**Functions:**
- `build_system_prompt() -> str` — returns the full system prompt (pure logic, testable)
- `build_track_summary(track: Track) -> str` — format a single track for the prompt
- `build_batch_message(tracks: list[Track]) -> str` — format a batch of track summaries as the user message
- `get_tool_schema() -> dict` — returns the tool schema definition
- `group_tracks_into_batches(tracks: list[Track], batch_size: int) -> list[list[Track]]` — intelligent batch grouping
- `parse_tool_result(tool_input: dict, batch_track_ids: list[int]) -> list[AiTagResult]` — parse and validate Claude's tool use response

**Return type:**
```
AiTagResult:
    track_id: int
    genre: str
    subgenre: str          # empty string if not applicable
    mood: str
    energy: int            # 1–10, clamped
    confidence: str        # "high", "medium", "low"
    reasoning: str
```

### 2. Claude Client (`backend/services/claude_client.py`)

Thin wrapper around the Anthropic Python SDK. Handles API calls, rate limiting, retries, and token tracking.

**Responsibilities:**
- Initialise the Anthropic client with the API key from Settings
- Validate the API key on first use (lightweight API call)
- Send messages with tool use and parse tool call responses
- Rate limiting: respect `ai_max_requests_per_minute` via a simple token bucket or sleep-based throttle
- Retry logic: exponential backoff on 429 (rate limit) and 529 (overloaded) errors, up to 3 retries
- Track token usage per request (input_tokens, output_tokens from the response)
- Log estimated cost per request (based on model pricing)

**Functions:**
- `validate_api_key(api_key: str) -> bool` — make a minimal API call to verify the key works
- `tag_batch(system_prompt: str, user_message: str, tool_schema: dict, model: str) -> ClaudeResponse` — send a single batch request, return parsed response
- `get_token_usage() -> TokenUsage` — cumulative token usage for the current session

**Return types:**
```
ClaudeResponse:
    results: list[AiTagResult]     # parsed from tool use
    input_tokens: int
    output_tokens: int
    model: str
    request_duration: float        # seconds

TokenUsage:
    total_input_tokens: int
    total_output_tokens: int
    total_requests: int
    estimated_cost_usd: float
```

**Rate limiting implementation:**
Simple approach: track the timestamp of each request. Before sending a new request, check if we've hit the per-minute limit. If so, sleep until the window resets. This is sufficient for a single-user desktop app — no need for a sophisticated token bucket.

```python
import time

class RateLimiter:
    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self.timestamps: list[float] = []

    async def acquire(self):
        now = time.time()
        # Remove timestamps older than 60 seconds
        self.timestamps = [t for t in self.timestamps if now - t < 60]
        if len(self.timestamps) >= self.max_per_minute:
            sleep_time = 60 - (now - self.timestamps[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        self.timestamps.append(time.time())
```

**Retry logic:**
```python
RETRY_STATUS_CODES = {429, 529}
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds

async def _call_with_retry(self, ...) -> Message:
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await asyncio.to_thread(self.client.messages.create, ...)
        except anthropic.RateLimitError:
            if attempt == MAX_RETRIES:
                raise
            backoff = INITIAL_BACKOFF * (2 ** attempt)
            logger.warning("Rate limited, retrying in %.1fs (attempt %d/%d)", backoff, attempt + 1, MAX_RETRIES)
            await asyncio.sleep(backoff)
```

**Error handling:**
- `anthropic.AuthenticationError` → raise `AiTagError` with clear "invalid API key" message
- `anthropic.RateLimitError` → retry with backoff, then raise if exhausted
- `anthropic.APIError` → log full error, raise `AiTagError`
- Tool use response missing or malformed → log warning, skip affected tracks, continue batch

### 3. AI Tagging Pipeline (`backend/services/ai_tagger.py`)

Orchestrates the full AI tagging flow for a single batch or multiple batches. Equivalent of Phase 1's queue.py and Phase 2's analysis.py — coordinates prompt building, Claude calls, DB updates, and SSE progress.

**Single batch flow:**
1. Build track summaries for the batch
2. Build user message
3. Call Claude via claude_client with system prompt and tool schema
4. Parse tool use response into `AiTagResult` list
5. For each result:
   - Load track from DB
   - If track has an existing genre and `source_genre` is not yet set, preserve it: `source_genre = genre`
   - Update: `genre`, `subgenre`, `mood`, `energy`, `ai_confidence`, `ai_reasoning`
   - Set `ai_status = "ai_tagged"`
6. Commit to DB
7. Emit SSE progress event

**Full pipeline flow:**
1. Load tracks to tag (either specified IDs or all with `ai_status = "untagged"`)
2. Group into batches via `group_tracks_into_batches()`
3. Process batches sequentially (one at a time — rate limiting handles pacing)
4. Per-batch: call Claude → parse → update DB → emit SSE
5. Per-batch error isolation: if one batch fails, log error, continue with next batch
6. Track cumulative token usage across all batches
7. Emit batch summary when complete (total tagged, failed, token usage, estimated cost)
8. Support cancellation via asyncio.Event

**Processing is sequential, not concurrent.** Unlike Phase 1 (ffmpeg, I/O-bound) and Phase 2 (librosa, CPU-bound), AI tagging is API-bound and rate-limited. Running multiple concurrent API calls would just hit rate limits faster. Sequential processing with rate limiting is simpler and more predictable.

**SSE event schema:**
```json
{
  "event": "ai_tag_batch_progress",
  "data": {
    "batch_number": 3,
    "total_batches": 8,
    "tracks_tagged": 52,
    "tracks_total": 150,
    "tracks_failed": 2,
    "token_usage": {
      "input_tokens": 12500,
      "output_tokens": 3200,
      "estimated_cost_usd": 0.05
    }
  }
}
```

**Return types:**
```
AiTagBatchResult:
    batch_number: int
    tracks_tagged: int
    tracks_failed: int
    input_tokens: int
    output_tokens: int
    errors: list[str]

AiTagPipelineResult:
    total_tracks: int
    succeeded: int
    failed: int
    total_batches: int
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float
    errors: list[str]
```

### 4. API Routes (`backend/routes/ai_tagging.py`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/tracks/ai-tag` | Start AI tagging on selected tracks (or all untagged) |
| GET | `/api/tracks/ai-tag/progress` | SSE endpoint for AI tagging progress events |
| POST | `/api/tracks/ai-tag/cancel` | Cancel current AI tagging batch |
| GET | `/api/tracks/ai-tag/status` | Get current AI tagging status (idle, running, token usage) |
| POST | `/api/tracks/ai-tag/validate-key` | Validate the configured API key |

**POST `/api/tracks/ai-tag` request body:**
```json
{
  "track_ids": [1, 2, 3],
  "options": {
    "skip_if_tagged": true,
    "model": "claude-sonnet-4-20250514"
  }
}
```
If `track_ids` is empty or absent, tag all tracks with `ai_status = "untagged"`.
If `skip_if_tagged` is true (default), skip tracks with `ai_status != "untagged"`.

**POST `/api/tracks/ai-tag` response:**
```json
{
  "batch_id": "uuid",
  "total_tracks": 150,
  "total_batches": 8,
  "message": "AI tagging started"
}
```

**GET `/api/tracks/ai-tag/status` response:**
```json
{
  "status": "idle",
  "token_usage": {
    "total_input_tokens": 45000,
    "total_output_tokens": 12000,
    "total_requests": 8,
    "estimated_cost_usd": 0.18
  }
}
```

**POST `/api/tracks/ai-tag/validate-key` response:**
```json
{
  "valid": true,
  "model": "claude-sonnet-4-20250514"
}
```
Returns 200 with `"valid": false` and an error message if the key is invalid (not a 4xx — the key validation endpoint itself always succeeds).

**Enhanced GET `/api/tracks` response (additional fields):**
```json
{
  "tracks": [
    {
      "...existing fields...",
      "subgenre": "Liquid DnB",
      "mood": "Euphoric",
      "energy": 7,
      "ai_confidence": "high",
      "ai_reasoning": "Calibre is a well-known liquid DnB producer; 174 BPM confirms DnB tempo range.",
      "source_genre": "Drum & Bass",
      "ai_status": "ai_tagged"
    }
  ]
}
```

**Extending existing endpoints:**
- `PUT /api/tracks/{id}` — extend to accept `genre`, `subgenre`, `mood`, `energy` in the update body (already accepts `genre` but now also the new fields)
- `PUT /api/tracks/{id}/revert/genre` — revert `genre` to `source_genre` value (extend the existing revert endpoint to handle the `genre` field alongside `bpm` and `key`)

### 5. Frontend Changes

Phase 3 frontend work extends the existing TrackTable and AnalysisControls rather than building new views.

**Cleanup (first commit):**
- Delete `TrackList.tsx` — dead code, superseded by TrackTable in Phase 2
- Add `album_artist` to the Track interface in `client.ts`

**TrackTable extensions:**
- New column configs added to DEFAULT_COLUMNS:
  - `subgenre` (visible: false by default)
  - `mood` (visible: true by default)
  - `energy` (visible: true by default)
  - `ai_confidence` (visible: false by default)
  - `ai_status` (visible: false by default)
- Genre column: already exists and visible — now populated by AI
- Inline editing for genre, subgenre, mood, energy (same double-click pattern as existing fields)
- Energy cell: render as a compact visual (number with a subtle colour gradient — 1–3 cool blue, 4–6 neutral, 7–8 warm amber, 9–10 hot red)
- AI confidence cell: render as coloured text (high = green, medium = amber, low = red)
- Reasoning tooltip: hover over genre cell shows `ai_reasoning` as a tooltip

**AnalysisControls extensions:**
- New "AI Tag" button alongside existing "Analyse" and "Write Tags" buttons
  - Disabled if no API key is configured
  - Shows count: "AI Tag Selected (5)" or "AI Tag All Untagged"
- AI tagging progress bar (same pattern as analysis progress bar)
- New filter options added: "AI Tagged", "Not AI Tagged" alongside existing filters
- Token usage summary shown after AI tagging completes (e.g. "Tagged 150 tracks · $0.18 estimated cost")

**API client extensions (`client.ts`):**
- `postAiTag(body: AiTagRequest): Promise<AiTagResponse>` — start AI tagging
- `postAiTagCancel(): Promise<{status, message}>` — cancel
- `getAiTagStatus(): Promise<AiTagStatus>` — current status and token usage
- `postValidateApiKey(): Promise<{valid, model?, error?}>` — validate key
- `connectAiTagProgress(onEvent, onComplete): EventSource` — SSE consumer
- Add new fields to Track interface: `subgenre`, `mood`, `energy`, `ai_confidence`, `ai_reasoning`, `source_genre`, `ai_status`
- Extend TrackUpdate interface with: `subgenre`, `mood`, `energy`
- Extend FilterMode type with: `"ai_tagged"`, `"not_ai_tagged"`

---

## Acceptance Criteria

### AI tagging core
- [ ] Tracks tagged with genre, subgenre, mood, and energy via Claude API
- [ ] Tool use (function calling) produces structured JSON output — no fragile text parsing
- [ ] Tracks batched in groups of ~20 (configurable via `ai_batch_size`)
- [ ] Batch grouping prefers tracks by same artist/album together
- [ ] Each result includes confidence ("high"/"medium"/"low") and reasoning (one sentence)
- [ ] Energy scores clamped to 1–10 range
- [ ] Subgenre can be empty string when genre is already specific enough

### Genre guidance
- [ ] System prompt includes ~40 electronic music genres as guidance
- [ ] Claude can use genres outside the guidance list when appropriate
- [ ] Specific subgenres preferred over broad categories (e.g. "Melodic Techno" not "Electronic")
- [ ] BPM and key used as genre signals in the prompt

### API key management
- [ ] API key validated before first AI tagging request
- [ ] Clear error message if key is missing or invalid
- [ ] Validate-key endpoint available for frontend to check

### Rate limiting and cost
- [ ] Configurable max requests per minute (default 10)
- [ ] Rate limiter enforced between batch requests
- [ ] Retry with exponential backoff on 429/529 errors (up to 3 retries)
- [ ] Token usage (input + output) tracked per request and cumulatively
- [ ] Estimated cost logged and surfaced in SSE events and API responses

### Original value preservation
- [ ] Existing genre tag preserved in `source_genre` before AI overwrites
- [ ] Revert-to-original available for genre via API (`PUT /api/tracks/{id}/revert/genre`)
- [ ] If no existing genre, `source_genre` stays null

### Tag writing
- [ ] Genre written to TCON frame (AIFF/MP3) or ©gen atom (M4A) via existing tag writer when user clicks "Write Tags"
- [ ] Subgenre, mood, energy, reasoning are DB-only — not written to file tags
- [ ] Existing "Write Tags" button works for AI-enriched tracks with no code changes to tag_writer.py (genre is already a standard field it writes)

### Pipeline
- [ ] AI tagging runs as separate operation from ingestion and analysis
- [ ] Batches processed sequentially with rate limiting
- [ ] SSE progress events emitted per batch
- [ ] Per-batch error isolation (one batch failing doesn't stop the pipeline)
- [ ] Cancellation support
- [ ] Token usage summary in batch complete event

### UI
- [ ] "AI Tag" button in toolbar (disabled if no API key)
- [ ] AI tagging progress bar
- [ ] New columns: mood, energy visible by default; subgenre, ai_confidence, ai_status hidden by default
- [ ] Energy rendered with colour coding (cool → warm → hot)
- [ ] AI confidence rendered with colour coding (high → medium → low)
- [ ] Genre cell tooltip shows ai_reasoning on hover
- [ ] Filter modes extended: "AI Tagged" and "Not AI Tagged"
- [ ] Token usage summary shown after AI tagging completes
- [ ] TrackList.tsx deleted (dead code cleanup)
- [ ] `album_artist` added to Track type in client.ts

### Data integrity
- [ ] Every AI-tagged track has genre, mood, energy, ai_confidence, ai_reasoning, ai_status in DB
- [ ] ai_status correctly transitions: untagged → ai_tagged → ai_tags_written (when Write Tags used)
- [ ] Partial updates via PUT /api/tracks/{id} work for new fields (subgenre, mood, energy)
- [ ] Model name logged with each request for traceability

### Error handling
- [ ] Missing API key → clear error before any requests are made
- [ ] Invalid API key → clear error message, no charge
- [ ] Rate limit hit → automatic retry with backoff, transparent to user
- [ ] Claude returns malformed tool use → skip affected tracks, log warning, continue
- [ ] Claude returns track_id not in the batch → log warning, ignore
- [ ] Network error → retry, then fail batch gracefully, continue pipeline
- [ ] Empty library / no tracks to tag → clear message, no error

---

## Out of Scope

- **Genre taxonomy enforcement** — Phase 3 uses free-form genre labels with prompt guidance. A controlled vocabulary / genre picker can be added later if consistency is a problem in practice.
- **Tag correction** (e.g. capitalisation of artist names) — deferred. Complex edge cases with intentionally lowercase/stylised names.
- **Audio-based genre detection** — Claude receives metadata only, not audio. Audio-based genre ML is a potential future enhancement.
- **File organisation** — Phase 2b. Phase 3 populates the metadata that Phase 2b will use for organisation.
- **Crate building** — Phase 5. Phase 3 provides the genre/mood/energy data that crate logic will use.
- **Collapsible drop zone** — Phase 6 UI polish.
- **Pagination for large libraries** — Phase 6 UI polish.
- **User-facing error toasts/notifications** — Phase 6 UI polish.
- **Sidebar navigation** — Phase 6 UI polish.
- **API key management UI** (settings panel) — Phase 6. For Phase 3, the key is set via `.env` / environment variable.
- **Token/subscription management** — deferred. Users provide their own API key for now.
- **Album art reading/writing** — not in scope for any current phase.
- **Batch tag editing** (apply same genre to 50 tracks at once) — deferred.

---

## Dependencies

- **anthropic** — Anthropic Python SDK for Claude API calls.
- **Phase 2 infrastructure** — Track model with analysis fields, tag writer, SSE capability, API client patterns.
- **Anthropic API key** — user must have a valid key. No default/bundled key.

---

## DB Schema Changes

Phase 2's Track model has metadata fields (title, artist, genre, etc.) plus analysis fields (bpm, key, confidence, etc.). Phase 3 adds AI-specific columns:

| Column | Type | Purpose |
|---|---|---|
| `subgenre` | String, nullable | AI-inferred subgenre (e.g. "Liquid DnB") |
| `mood` | String, nullable | AI-inferred mood (e.g. "Euphoric") |
| `energy` | Integer, nullable | AI-inferred energy score 1–10 |
| `ai_confidence` | String, nullable | Claude's self-assessed confidence: "high"/"medium"/"low" |
| `ai_reasoning` | Text, nullable | One-line explanation of classification |
| `source_genre` | String, nullable | Original genre tag value, preserved for revert |
| `ai_status` | String | AI tagging state: "untagged" (default), "ai_tagged", "ai_tags_written" |

**Existing columns used:**
- `genre` — already exists. AI value overwrites it (original preserved in `source_genre`)
- All other metadata fields are read by the prompt builder but not modified by AI tagging

---

## Decisions (Finalised)

All decisions were discussed and agreed before implementation.

| # | Decision | Resolution |
|---|---|---|
| 1 | **Data sent to Claude** | Structured metadata summary per track (title, artist, album, label, year, genre, BPM, key, filename, comment). No audio data. |
| 2 | **Batch size** | Default 20 tracks per API request. Configurable via `ai_batch_size`. Tracks grouped by artist/album for better context. |
| 3 | **Output fields** | Genre, subgenre, mood, energy (1–10), confidence (high/medium/low), reasoning (one sentence). |
| 4 | **Tag correction** | Out of scope for Phase 3. Complex edge cases with stylised artist names. |
| 5 | **Genre taxonomy** | Free-form with prompt guidance (~40 electronic genres listed). Claude can go outside the list. Users can always edit. |
| 6 | **Structured output** | Tool use (function calling) via Anthropic SDK. Eliminates parsing issues. |
| 7 | **Rate limiting** | Configurable max requests per minute (default 10). Simple timestamp-based throttle. |
| 8 | **Cost management** | Track token usage per request. Log estimated cost. Surface in UI after completion. |
| 9 | **Tag writing** | Genre → TCON frame via existing tag writer. Mood/energy/subgenre/reasoning are DB-only. |
| 10 | **Original value preservation** | Existing genre preserved in `source_genre`. AI genre becomes active. Per-field revert available. Same pattern as BPM/key in Phase 2. |
| 11 | **Model** | Default `claude-sonnet-4-20250514`. Configurable via `ai_model` setting. Sonnet is the right balance of capability and cost for classification. |
| 12 | **API key** | User provides their own key via `.env` / environment variable. Validated before first use. Settings UI deferred to Phase 6. Subscription/bundled key model deferred. |
| 13 | **Concurrency** | Sequential batch processing (not concurrent). API-bound, rate-limited — concurrency adds complexity for no benefit. |

---

## TDD Candidates

Per CLAUDE.md convention — pure logic functions with clearly defined inputs/outputs, written test-first:

| Function | Location | Why TDD |
|---|---|---|
| `build_system_prompt()` | `prompt_builder.py` | Pure string construction. Verify genre list, mood vocabulary, energy scale, and tool instructions are all present. |
| `build_track_summary()` | `prompt_builder.py` | Track data → formatted string. Test with full data, partial data (missing fields), and edge cases (None values, empty strings, unicode). |
| `build_batch_message()` | `prompt_builder.py` | List of tracks → user message string. Test batching, track numbering. |
| `group_tracks_into_batches()` | `prompt_builder.py` | List of tracks + batch size → grouped batches. Test artist grouping, overflow, single-track batches, empty list. |
| `parse_tool_result()` | `prompt_builder.py` | Tool use JSON → list of AiTagResult. Test valid input, missing fields, extra fields, wrong track IDs, energy out of range, invalid confidence values. Highest-value TDD target. |
| `validate_energy()` | `prompt_builder.py` | Clamp energy to 1–10 range. |
| `validate_confidence()` | `prompt_builder.py` | Verify confidence is one of "high"/"medium"/"low", default to "low" otherwise. |

**Write tests after implementation** (SDK integration, I/O-dependent):
- Claude client API calls (mock the SDK)
- Rate limiter timing
- AI tagger pipeline orchestration
- API route handlers
- SSE event streaming
- Frontend components

---

## Commit Breakdown

### Commit 1: Dependencies, config, and cleanup
- Add `anthropic` to pyproject.toml and update uv.lock
- Add to Settings in config.py:
  - `ai_model: str = "claude-sonnet-4-20250514"`
  - `ai_batch_size: int = 20`
  - `ai_max_requests_per_minute: int = 10`
- Add `AiTagError` to exceptions.py
- Delete `frontend/src/TrackList.tsx` (dead code)
- Add `album_artist` to Track interface in `frontend/src/api/client.ts`
- Commit: "Add Phase 3 dependencies, config, and frontend cleanup"

### Commit 2: Track model updates
- Review existing Track model columns against Phase 3 needs
- Add: `subgenre` (String, nullable), `mood` (String, nullable), `energy` (Integer, nullable), `ai_confidence` (String, nullable), `ai_reasoning` (Text, nullable), `source_genre` (String, nullable), `ai_status` (String, default "untagged")
- Update any existing model tests
- Commit: "Extend Track model with AI tagging columns"

### Commit 3: Prompt builder (TDD)
- Create `backend/services/prompt_builder.py`
- WRITE TESTS FIRST in `backend/tests/test_prompt_builder.py`:
  - Test `build_system_prompt()` — verify key content sections are present
  - Test `build_track_summary()` — full data, partial data, None handling, unicode
  - Test `build_batch_message()` — multiple tracks, proper formatting
  - Test `group_tracks_into_batches()` — artist grouping, batch size limits, empty list, overflow
  - Test `parse_tool_result()` — valid JSON, missing fields, wrong track IDs, energy clamping, invalid confidence fallback. This is the highest-value TDD target.
  - Test `validate_energy()` and `validate_confidence()` — boundary cases
- Then implement:
  - `AiTagResult` dataclass
  - All functions listed in the architecture section
- This is pure logic — no I/O, no SDK, no DB.
- Commit: "Add prompt builder with track summarisation and result parsing (TDD)"

### Commit 4: Claude client
- Create `backend/services/claude_client.py`
- Implement:
  - `ClaudeClient` class wrapping the Anthropic SDK
  - `validate_api_key()` — lightweight validation call
  - `tag_batch()` — send messages with tool use, parse response
  - `RateLimiter` class with timestamp-based throttling
  - Retry logic with exponential backoff for 429/529
  - Token usage tracking (`ClaudeResponse`, `TokenUsage` dataclasses)
- Tests with mocked Anthropic client:
  - Test successful tool use response parsing
  - Test retry on rate limit errors
  - Test authentication error handling
  - Test malformed response handling
  - Test rate limiter timing
- Commit: "Add Claude client with rate limiting and retry logic"

### Commit 5: AI tagger pipeline
- Create `backend/services/ai_tagger.py`
- Implement:
  - `tag_tracks(track_ids, db_session, settings) -> AiTagPipelineResult` — full orchestrator
  - Source genre preservation logic
  - SSE event emission per batch
  - Cancellation support via asyncio.Event
  - Per-batch error isolation
  - Token usage accumulation
- Tests with mocked Claude client:
  - Test pipeline orchestration (correct number of batches)
  - Test source_genre preservation (existing genre preserved, no-genre track stays null)
  - Test ai_status transitions
  - Test error isolation (one batch fails, others continue)
  - Test cancellation
- Commit: "Add AI tagger pipeline with batch processing and SSE progress"

### Commit 6: API routes
- Create `backend/routes/ai_tagging.py`
- Implement:
  - POST `/api/tracks/ai-tag` — start AI tagging
  - GET `/api/tracks/ai-tag/progress` — SSE endpoint
  - POST `/api/tracks/ai-tag/cancel` — cancel
  - GET `/api/tracks/ai-tag/status` — current status and token usage
  - POST `/api/tracks/ai-tag/validate-key` — validate API key
- Extend existing endpoints:
  - `PUT /api/tracks/{id}` — accept subgenre, mood, energy in update body
  - `PUT /api/tracks/{id}/revert/genre` — extend revert to handle genre field
  - `GET /api/tracks` — include new AI fields in response
- Register routes in main.py
- Test all endpoints with httpx async client
- Commit: "Add AI tagging API routes with progress, cancellation, and key validation"

### Commit 7: Frontend
- Extend TrackTable:
  - Add new column configs (subgenre, mood, energy, ai_confidence, ai_status)
  - Energy cell with colour coding
  - AI confidence cell with colour coding
  - Genre cell tooltip showing ai_reasoning
  - Inline editing for genre, subgenre, mood, energy
- Extend AnalysisControls:
  - "AI Tag" button with selection count
  - AI tagging progress bar (SSE)
  - New filter modes: "AI Tagged", "Not AI Tagged"
  - Token usage summary display after completion
- Extend API client:
  - Add AI tagging endpoints
  - Add new fields to Track and TrackUpdate interfaces
  - Add SSE consumer for AI tag progress
- Commit: "Extend UI with AI tagging controls, columns, and progress"

### Commit 8: Integration tests and cleanup
- End-to-end test (with mocked Claude API):
  - Ingest file → analyse → AI tag → verify DB fields → write tags → verify genre on file
- Test genre revert flow: AI tag → revert genre → verify source_genre restored
- Test re-tagging: AI tag → AI tag again → verify values updated
- Test with missing API key → clear error
- Review all TODO comments in new code
- Update CLAUDE.md with Phase 3 status
- Commit: "Add integration tests and update project docs for Phase 3"

---

## Claude Code Prompt

The following prompt is designed to be given to Claude Code at the start of the implementation session. Copy it verbatim.

---

```
You are implementing Phase 3 (Claude AI Integration) of rekordbot.

Read these files first:
- CLAUDE.md (project conventions, architecture, coding standards)
- docs/features/phase-3-claude-integration.md (the feature brief — this is your specification)
- backend/models/track.py (existing Track model — you'll need to extend it)
- backend/config.py (existing Settings — you'll add new config fields)
- backend/exceptions.py (existing exception hierarchy — add new types as needed)
- backend/main.py (existing FastAPI app — you'll register new routes here)
- backend/services/analysis.py (Phase 2 pipeline — reference for batch processing and SSE patterns)
- backend/routes/tagging.py (Phase 2 routes — reference for SSE endpoint patterns and track update/revert logic)
- backend/services/tag_writer.py (Phase 2 tag writer — genre is already written to TCON, no changes needed)
- frontend/src/TrackTable.tsx (existing track table — you'll extend with new columns)
- frontend/src/AnalysisControls.tsx (existing toolbar — you'll add AI Tag button)
- frontend/src/api/client.ts (existing API client — you'll extend with AI tagging endpoints)

## What you're building

An AI tagging pipeline that:
1. Sends structured track metadata to Claude in batches of ~20
2. Uses tool use (function calling) for structured output — no text parsing
3. Gets back genre, subgenre, mood, energy (1–10), confidence, and reasoning per track
4. Stores results in SQLite with original genre preserved for revert
5. Reports progress via SSE with token usage tracking
6. Enforces rate limiting and retry logic on API calls
7. Extends the existing TrackTable UI with new columns and an "AI Tag" button

This pipeline is SEPARATE from Phase 1's ingestion and Phase 2's analysis pipeline. Do not modify Phase 1 or Phase 2 service code. The existing tag writer already writes genre to TCON — no changes needed there.

## Build order (follow this exactly)

### Step 1: Dependencies, config, and cleanup
- Add anthropic to pyproject.toml and update uv.lock
- Add to Settings in config.py:
  - ai_model: str (default "claude-sonnet-4-20250514")
  - ai_batch_size: int (default 20)
  - ai_max_requests_per_minute: int (default 10)
- Add AiTagError to exceptions.py
- Delete frontend/src/TrackList.tsx (dead code — superseded by TrackTable in Phase 2)
- Add album_artist field to Track interface in frontend/src/api/client.ts
- Commit: "Add Phase 3 dependencies, config, and frontend cleanup"

### Step 2: Track model updates
- Review existing Track model columns against the feature brief's DB Schema Changes section
- Add: subgenre (String, nullable), mood (String, nullable), energy (Integer, nullable), ai_confidence (String, nullable), ai_reasoning (Text, nullable), source_genre (String, nullable), ai_status (String, default "untagged")
- Update any existing model tests
- Commit: "Extend Track model with AI tagging columns"

### Step 3: Prompt builder (TDD)
- Create backend/services/prompt_builder.py
- WRITE TESTS FIRST in backend/tests/test_prompt_builder.py:
  - Test build_system_prompt() — key sections present
  - Test build_track_summary() — full data, partial data, None/empty handling
  - Test build_batch_message() — multiple tracks
  - Test group_tracks_into_batches() — artist grouping, batch size, empty list
  - Test parse_tool_result() — valid JSON, missing fields, wrong IDs, energy clamping, confidence fallback. This is the highest-value TDD target.
- Then implement:
  - AiTagResult dataclass
  - All prompt builder functions
- Pure logic. No I/O, no SDK, no DB.
- Commit: "Add prompt builder with track summarisation and result parsing (TDD)"

### Step 4: Claude client
- Create backend/services/claude_client.py
- Implement:
  - ClaudeClient class wrapping Anthropic SDK
  - validate_api_key() — lightweight validation
  - tag_batch() — messages with tool use, parse response
  - RateLimiter class (timestamp-based throttle)
  - Retry with exponential backoff on 429/529
  - Token usage tracking
- Test with mocked Anthropic client (mock anthropic.Anthropic)
- Commit: "Add Claude client with rate limiting and retry logic"

### Step 5: AI tagger pipeline
- Create backend/services/ai_tagger.py
- Implement:
  - tag_tracks() orchestrator
  - Source genre preservation
  - SSE event emission per batch
  - Cancellation support
  - Per-batch error isolation
  - Token usage accumulation
- Test with mocked Claude client
- Commit: "Add AI tagger pipeline with batch processing and SSE progress"

### Step 6: API routes
- Create backend/routes/ai_tagging.py
- Implement:
  - POST /api/tracks/ai-tag
  - GET /api/tracks/ai-tag/progress (SSE)
  - POST /api/tracks/ai-tag/cancel
  - GET /api/tracks/ai-tag/status
  - POST /api/tracks/ai-tag/validate-key
- Extend existing endpoints in routes/tagging.py:
  - PUT /api/tracks/{id} — accept subgenre, mood, energy
  - PUT /api/tracks/{id}/revert/genre — handle genre revert
  - GET /api/tracks — include AI fields in response
- Register routes in main.py
- Test all endpoints
- Commit: "Add AI tagging API routes with progress, cancellation, and key validation"

### Step 7: Frontend
- Extend TrackTable: new columns (subgenre, mood, energy, ai_confidence, ai_status), energy colour coding, confidence colour coding, genre tooltip with reasoning
- Extend AnalysisControls: "AI Tag" button, progress bar, filter modes, token summary
- Extend API client: AI tagging endpoints, new Track/TrackUpdate fields, SSE consumer
- Commit: "Extend UI with AI tagging controls, columns, and progress"

### Step 8: Integration tests and cleanup
- End-to-end test (mocked Claude API): ingest → analyse → AI tag → verify DB → write tags → verify file
- Genre revert flow test
- Re-tagging test
- Missing API key test
- Update CLAUDE.md
- Commit: "Add integration tests and update project docs for Phase 3"

## Constraints
- Follow all conventions in CLAUDE.md (type hints, docstrings, error handling, logging, etc.)
- Claude API calls via asyncio.to_thread() (the SDK is synchronous)
- Do NOT modify Phase 1's converter, queue, or ingest routes
- Do NOT modify Phase 2's analysis pipeline, tag reader, or tag writer
- The existing tag writer already writes genre to TCON — no changes to tag_writer.py needed
- Mood, energy, subgenre, reasoning are DB-only — not written to file tags
- All exceptions should be RekordBotError subclasses
- Every service module gets its own logger via logging.getLogger(__name__)
- Use %s string formatting in log calls (not f-strings)

## Important
- Do NOT implement file organisation — that's Phase 2b
- Do NOT implement crate building — that's Phase 5
- Do NOT read or modify audio files — Claude receives metadata only
- Do NOT implement a settings UI for the API key — that's Phase 6
- Do NOT implement genre taxonomy enforcement — free-form with prompt guidance only
- Do NOT implement tag correction (artist name capitalisation etc.) — deferred
- Source files are NEVER modified
- AI tagging is user-triggered only — never automatic
```

### Continuation Prompt

If the session is interrupted and you need to resume in a new Claude Code session, use this:

```
We are continuing Phase 3 (Claude AI Integration) of rekordbot.

Read these files for context:
- CLAUDE.md (project conventions and current status)
- SESSIONS.md (latest entry has where we left off and what's next)
- docs/features/phase-3-claude-integration.md (the feature specification)

Pick up from where we left off. Check SESSIONS.md for the last completed step
and what was identified as the next task. Confirm what you think the next step
is before writing any code.
```

---

## Notes

- The Anthropic Python SDK's `messages.create()` is synchronous. Wrap in `asyncio.to_thread()` for non-blocking execution in the FastAPI async context. The SDK's async client (`anthropic.AsyncAnthropic`) is an alternative but adds complexity — sync + to_thread is consistent with how we handle ffmpeg and librosa.
- Tool use responses come back as `ToolUseBlock` objects in `response.content`. The tool input is already parsed JSON (a dict), not a string — no JSON.loads needed. The `parse_tool_result()` function receives this dict directly.
- The system prompt is long but well within Claude's context window. With 20 tracks per batch, the total prompt (system + user) will be roughly 3,000–5,000 tokens. Sonnet handles this comfortably.
- Cost estimation: Sonnet pricing is approximately $3/MTok input, $15/MTok output (verify current pricing at time of implementation). For 150 tracks in 8 batches: ~40K input tokens + ~12K output tokens ≈ $0.30 total. Very affordable for a library-sized operation.
- The `ai_status` field is separate from `analysis_status` (Phase 2). A track can be `analysis_status = "tags_written"` and `ai_status = "untagged"` — they're independent pipelines.
- When the user clicks "Write Tags" after AI tagging, the genre field (now containing the AI value) is written to TCON by the existing tag writer. The `ai_status` should transition to `"ai_tags_written"` at this point. This requires a small hook in the write-tags endpoint to update `ai_status` alongside `analysis_status`.
- Integration tests should mock the Anthropic SDK, not make real API calls. Use `unittest.mock.patch` to replace `anthropic.Anthropic` with a mock that returns pre-defined tool use responses.
