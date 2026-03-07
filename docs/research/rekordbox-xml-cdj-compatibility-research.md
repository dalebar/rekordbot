# CrateAI — Rekordbox XML & CDJ Tag Compatibility Research

*Research compiled March 2026*
*Sources: Pioneer DJ official spec (xml_format_list.pdf), Pioneer DJ community forums, pyrekordbox documentation, CDJ hardware manuals, DJ community knowledge*

---

## 1. Rekordbox XML Format Reference

### 1.1 Top-Level Structure

The Rekordbox XML file follows a fixed structure defined in Pioneer's official specification (version 1.0.0). The XML declaration must be `<?xml version="1.0" encoding="UTF-8" ?>` — UTF-8 encoding is mandatory.

```xml
<?xml version="1.0" encoding="UTF-8" ?>
<DJ_PLAYLISTS Version="1.0.0">
  <PRODUCT Name="rekordbox" Version="7.x.x" Company="Pioneer DJ"/>
  <COLLECTION Entries="1234">
    <TRACK TrackID="1" Name="..." ... >
      <TEMPO .../>
      <POSITION_MARK .../>
    </TRACK>
    ...
  </COLLECTION>
  <PLAYLISTS>
    <NODE Type="0" Name="ROOT" Count="...">
      ...
    </NODE>
  </PLAYLISTS>
</DJ_PLAYLISTS>
```

There are three top-level elements inside `<DJ_PLAYLISTS>`:

1. **PRODUCT** — identifies the software that generated the XML (Name, Version, Company). When we generate XML, we should set this to our own product name (e.g. `Name="CrateAI"`). Rekordbox displays this in the UI.
2. **COLLECTION** — contains all `<TRACK>` elements. The `Entries` attribute is a count of tracks. The official spec notes that tracks not included in any playlist are technically unnecessary, but in practice Rekordbox exports all collection tracks here.
3. **PLAYLISTS** — contains the playlist/folder tree as nested `<NODE>` elements.

### 1.2 TRACK Element — Complete Attribute Reference

Every attribute on a `<TRACK>` element, based on the official Pioneer specification:

| Attribute | Type | Description | Notes |
|-----------|------|-------------|-------|
| **TrackID** | signed int | Unique identifier for the track | Internal counter; assigned sequentially by Rekordbox |
| **Name** | UTF-8 string | Track title | |
| **Artist** | UTF-8 string | Artist name | |
| **Composer** | UTF-8 string | Composer or producer | |
| **Album** | UTF-8 string | Album name | |
| **Grouping** | UTF-8 string | Grouping tag | |
| **Genre** | UTF-8 string | Genre | Free text, no controlled vocabulary |
| **Kind** | UTF-8 string | File type description | e.g. "MP3 File", "WAV File", "AIFF File", "FLAC File" |
| **Size** | signed 64-bit int | File size in bytes (octets) | |
| **TotalTime** | 64-bit float | Duration in seconds | Integer value (no decimals) despite float type |
| **DiscNumber** | signed 32-bit int | Disc number in album | 0 if not set |
| **TrackNumber** | signed 32-bit int | Track number in album | 0 if not set |
| **Year** | signed 32-bit int | Release year | 0 if not set |
| **AverageBpm** | 64-bit float | Average BPM | Two decimal places (e.g. "134.00") |
| **DateModified** | UTF-8 string | Last modification date | Format: `yyyy-mm-dd` |
| **DateAdded** | UTF-8 string | Date added to collection | Format: `yyyy-mm-dd` |
| **BitRate** | signed 32-bit int | Encoding bitrate in Kbps | For lossless, this is the raw data rate (e.g. 2116 for 16-bit 44.1kHz stereo WAV) |
| **SampleRate** | 64-bit float | Sample rate in Hz | e.g. 44100 |
| **Comments** | UTF-8 string | Comments field | Used by "My Tag" feature to store tags (delimited by `/* */`) |
| **PlayCount** | signed 32-bit int | Play count | |
| **LastPlayed** | UTF-8 string | Last played date | Format: `yyyy-mm-dd` |
| **Rating** | signed 32-bit int | Star rating | Non-linear scale: 0=0★, 51=1★, 102=2★, 153=3★, 204=4★, 255=5★ |
| **Location** | UTF-8 string (URI) | File path as URI | **Critical field** — see section 1.3 |
| **Remixer** | UTF-8 string | Remixer name | |
| **Tonality** | UTF-8 string | Musical key | **Critical field** — see section 1.4 |
| **Label** | UTF-8 string | Record label | |
| **Mix** | UTF-8 string | Mix name | e.g. "Original Mix", "Radio Edit" |
| **Colour** | UTF-8 string | Track colour | RGB hex format, e.g. "0xFF007F" for Rose |

**Colour values defined by Rekordbox:** Rose (0xFF007F), Red (0xFF0000), Orange (0xFFA500), Lemon (0xFFFF00), Green (0x00FF00), Turquoise (0x25FDE9), Blue (0x0000FF), Violet (0x660099).

**Rating scale:** This is a gotcha. The values are not 0-5; they are 0, 51, 102, 153, 204, 255. We must map to/from this scale.

### 1.3 Location Field — File Path Encoding

The `Location` field is the most critical attribute and the most likely source of bugs.

**Format:** `file://localhost/` followed by the absolute path to the file.

**Rules:**
- Always prefixed with `file://localhost/`
- Always uses forward slashes, even on Windows (e.g. `file://localhost/D:/Music/track.mp3`)
- Paths are URI-encoded: spaces become `%20`, special characters are percent-encoded
- Standard XML entity encoding applies for the attribute value (`&` → `&amp;`, etc.)
- On macOS, paths typically start with `/Users/...` or `/Volumes/...`
- On Windows, drive letters are included: `file://localhost/C:/Users/...`

**Example (macOS):**
```
file://localhost/Users/daleb/Music/DJ/Artist%20Name/Track%20Title.aiff
```

**Example (Windows):**
```
file://localhost/D:/Music/DJ%20Library/Artist/Track.mp3
```

This is the primary way tracks are identified when importing XML back into Rekordbox. If the path doesn't resolve to a real file, the track will appear as "missing" in Rekordbox.

### 1.4 Tonality (Key) Field

The `Tonality` field stores the musical key as a free-text string. Rekordbox's own key analysis writes in **classical notation** with minor indicated by a lowercase `m` suffix:

- Major keys: `C`, `Db`, `D`, `Eb`, `E`, `F`, `F#`, `G`, `Ab`, `A`, `Bb`, `B`
- Minor keys: `Cm`, `Dbm`, `Dm`, `Ebm`, `Em`, `Fm`, `F#m`, `Gm`, `Abm`, `Am`, `Bbm`, `Bm`

**Important nuances:**
- Rekordbox uses flats (♭ as `b`) rather than sharps (♯ as `#`) for most keys, except `F#` and `F#m`
- Since version 5.4.3, Rekordbox offers two display modes: "Classic" (e.g. `Abm`, `B`, `Ebm`) and "Alphanumeric" (Camelot-style: `1A`, `1B`, `2A`, etc.)
- The field is free-text: you can write Camelot notation (e.g. `8A`) directly into it, and it will display on CDJs. The CDJ traffic light / related-key system will still work with Camelot notation on Nexus and later models.
- CDJs and Rekordbox are case-sensitive for key matching: `B` (major) and `Bm` (minor) are distinguished by the `m` suffix, not by case.

### 1.5 TEMPO Element (Beat Grid)

Tracks can contain multiple `<TEMPO>` child elements to describe the beat grid:

| Attribute | Type | Description |
|-----------|------|-------------|
| **Inizio** | 64-bit float | Start position of beat grid in seconds |
| **Bpm** | 64-bit float | BPM value at this point (with decimals) |
| **Metro** | UTF-8 string | Time signature (e.g. "4/4", "3/4", "7/8") |
| **Battito** | signed 32-bit int | Beat number in bar (1-4 for 4/4 time) |

Multiple TEMPO elements allow for tracks with BPM changes. For most electronic music, there will be a single TEMPO element.

### 1.6 POSITION_MARK Element (Cue Points, Loops)

Tracks can contain multiple `<POSITION_MARK>` child elements:

| Attribute | Type | Description |
|-----------|------|-------------|
| **Name** | UTF-8 string | Name of the marker |
| **Type** | signed 32-bit int | 0=Cue, 1=Fade-In, 2=Fade-Out, 3=Load, 4=Loop |
| **Start** | 64-bit float | Start position in seconds |
| **End** | 64-bit float | End position in seconds (for loops) |
| **Num** | signed 32-bit int | Marker number. Hot Cues: 0 (A), 1 (B), 2 (C). Memory Cue: -1 |

### 1.7 PLAYLISTS Structure

The playlist tree is built from nested `<NODE>` elements:

**Folder node (Type=0):**
```xml
<NODE Type="0" Name="My Folder" Count="3">
  <!-- child NODE elements -->
</NODE>
```

**Playlist node (Type=1):**
```xml
<NODE Name="My Playlist" Type="1" KeyType="0" Entries="56">
  <TRACK Key="1"/>
  <TRACK Key="2"/>
</NODE>
```

**KeyType** determines how tracks are referenced within the playlist:
- `KeyType="0"` — tracks referenced by `TrackID` (the `Key` attribute matches a `TrackID` in the COLLECTION)
- `KeyType="1"` — tracks referenced by `Location` (the `Key` attribute is a file path URI)

The root node is always `Type="0"` with `Name="ROOT"`.

**Nesting:** Playlists can be nested inside folders to arbitrary depth. Folders contain other folders or playlists; playlists contain `<TRACK>` references.

**Important:** In Rekordbox 6+, there have been community reports that the `Key` values in playlists using `KeyType="0"` don't always match `TrackID` values in the COLLECTION when viewing an exported XML. This may be related to Rekordbox's internal ID management. When generating XML, using `KeyType="0"` with matching `TrackID` values is the safest approach.

### 1.8 DJ Playlists (History)

The official spec does not define a separate history structure. Play history in Rekordbox is stored in its internal database, not in the XML export. The XML is purely for collection and playlist interchange.

### 1.9 ID System

TrackID is a simple sequential integer counter. It is not a hash, not path-based — just an incrementing ID. When generating XML, we assign our own IDs starting from 1. Rekordbox will reassign its own internal IDs on import, so the exact values don't matter as long as they are unique within the XML and consistent between the COLLECTION and PLAYLISTS sections.

### 1.10 Known Quirks and Gotchas

1. **XML declaration is mandatory.** Must be `<?xml version="1.0" encoding="UTF-8" ?>`.
2. **Encoding:** All strings must be UTF-8 with standard XML entity encoding (`&amp;`, `&lt;`, `&gt;`, `&apos;`, `&quot;`).
3. **Location encoding:** Must be a valid URI with `file://localhost/` prefix. Spaces as `%20`. Forward slashes only.
4. **Numeric fields must be locale-independent.** No thousands separators. Decimal separator is a dot, not comma.
5. **Empty attributes:** Rekordbox exports empty strings for unset text fields (e.g. `Genre=""`). It is safe to omit optional attributes, but including them as empty strings matches Rekordbox's own output and is safer.
6. **Entries count must be accurate.** The `Entries` attribute on `COLLECTION` and playlist `NODE` elements should match the actual count of child elements.
7. **No BOM.** The XML file should not have a byte-order mark.
8. **Self-closing TRACK tags:** Tracks without child elements (no TEMPO or POSITION_MARK) are self-closing: `<TRACK ... />`. Tracks with children use open/close tags: `<TRACK ...> ... </TRACK>`.
9. **Rating scale is non-linear** (0, 51, 102, 153, 204, 255) — easy to get wrong.
10. **Rekordbox re-analysis:** When importing from XML, Rekordbox may re-analyse tracks (waveforms, etc.) unless the user specifically imports via the XML library browser. The XML does not contain waveform data.

---

## 2. CDJ Tag Compatibility Matrix

### 2.1 Audio Format Support by CDJ Model

| Model (Year) | MP3 | AAC | WAV | AIFF | FLAC | ALAC |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| CDJ-400 (2007) | ✅ | — | — | — | — | — |
| CDJ-2000 (2009) | ✅ | ✅ | ✅ | ✅ | — | — |
| CDJ-900 (2009) | ✅ | ✅ | ✅ | ✅ | — | — |
| CDJ-850 (2010) | ✅ | ✅ | ✅ | ✅ | — | — |
| CDJ-350 (2010) | ✅ | ✅ | ✅ | ✅ | — | — |
| CDJ-2000NXS (2012) | ✅ | ✅ | ✅ | ✅ | — | — |
| XDJ-1000 (2014) | ✅ | ✅ | ✅ | ✅ | — | — |
| XDJ-700 (2015) | ✅ | ✅ | ✅ | ✅ | — | — |
| CDJ-2000NXS2 (2016) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| XDJ-1000MK2 (2016) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| XDJ-XZ (2019) | ✅ | ✅ | ✅ | ✅ | — | — |
| CDJ-3000 (2020) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**Key takeaways:**
- **AIFF and MP3 are universally supported** across all USB-capable CDJs (2009+). This confirms our converter design: AIFF for lossless, MP3 for lossy.
- **FLAC/ALAC support is limited** to flagship models (NXS2, CDJ-3000, XDJ-1000MK2). The XDJ-XZ notably does *not* support FLAC despite being a high-end unit.
- **WAV is universally supported** but has poor metadata support (no official tag spec), making AIFF the strictly better lossless choice.
- All USB-capable models support 16-bit and 24-bit depth, 44.1kHz and 48kHz sample rate for lossless formats. **32-bit is not supported on any model.**
- Lossy formats support sampling rates of 32kHz, 44.1kHz, and 48kHz.

### 2.2 Tag Format Support

**MP3 files:**
- CDJs support ID3v1, ID3v1.1, ID3v2.2, ID3v2.3, and ID3v2.4 tags.
- This is confirmed in multiple CDJ manuals (CDJ-900NXS, XDJ-XZ, CDJ-3000).
- Rekordbox itself reportedly reads and writes ID3v2.4, but the Pioneer community forums indicate it also reads v2.3 without issue.
- **Gotcha:** When both ID3v1 and ID3v2 tags are present, Rekordbox has been observed to sometimes prefer the ID3v1 `COMM` (comment) field over v2, which is non-standard behaviour. Community reports suggest this has been inconsistent across Rekordbox versions.

**AIFF files:**
- AIFF files use ID3v2 tags embedded in an `ID3` chunk within the AIFF container.
- Both ID3v2.3 and ID3v2.4 are accepted by Rekordbox and CDJs. A Pioneer support rep confirmed that a file with ID3v2.4 imported without issue where v2.3 had also worked.
- **AIFF is the recommended lossless format** for DJ use precisely because it supports ID3 tags (unlike WAV, which has no official tag spec).
- Historical issues: very early Rekordbox versions (pre-1.6) had incomplete AIFF tag/artwork support, but this has been fully resolved for many years.

**WAV files:**
- WAV has no official metadata tagging specification. It uses RIFF INFO chunks, which Rekordbox can read to some extent, but tag support is significantly more limited than AIFF or MP3.
- Artwork is not supported in WAV tags on CDJs.
- **Recommendation: avoid WAV as an output format.** AIFF provides identical audio quality with full tag support.

**M4A (AAC/ALAC) files:**
- Use MP4/iTunes-style metadata (not ID3). Rekordbox reads these via "meta tags."
- On CDJ hardware, metadata display from M4A files is generally reliable for the core fields.

**FLAC files:**
- Use Vorbis Comments for metadata.
- Only relevant on models that support FLAC playback (see format table above).

### 2.3 Field-by-Field Tag Compatibility

For MP3 and AIFF files (the two formats we care about most):

| Metadata Field | ID3v2 Frame | Rekordbox Reads | CDJ Displays | Notes |
|---|---|:---:|:---:|---|
| Title | TIT2 | ✅ | ✅ | Universal |
| Artist | TPE1 | ✅ | ✅ | Universal |
| Album | TALB | ✅ | ✅ | Universal |
| Genre | TCON | ✅ | ✅ | Free text preferred; avoid ID3v1 numeric genre codes |
| BPM | TBPM | ✅ | ✅ | Integer string in ID3; Rekordbox stores its own analysis separately |
| Key | TKEY | ✅ | ✅ | See section on key notation |
| Year | TYER (v2.3) / TDRC (v2.4) | ✅ | ✅ | Use TYER for v2.3 compatibility |
| Comment | COMM | ✅ | ✅ | Gotcha: multiple COMM frames cause issues (see section 2.2) |
| Track Number | TRCK | ✅ | ✅ | |
| Disc Number | TPOS | ✅ | ✅ | |
| Composer | TCOM | ✅ | ✅ | |
| Remixer | TPE4 | ✅ | ✅ | |
| Label | TPUB | ✅ | ✅* | *Display on CDJ varies by model/firmware; stored in Rekordbox DB |
| Grouping | TIT1 | ✅ | ✅ | |
| Album Art | APIC | ✅ | ✅ | See artwork section |

**Fields that are Rekordbox-database-only (not in ID3 tags):**
- Colour/color assignment
- Cue points, loops, hot cues
- Beat grid data
- Waveform analysis
- Play count (Rekordbox tracks its own count; ID3 PCNT is separate)
- Rating (not reliably written back to file by Rekordbox)
- My Tags (appended to comment field for CDJ export)

### 2.4 Key Notation

**What Rekordbox writes internally:** Classical notation with `m` suffix for minor (e.g. `Abm`, `F#`, `Eb`).

**What CDJs display:** Whatever is in the key field — the Tonality/TKEY field is displayed as-is. If you write Camelot notation (`8A`, `11B`, etc.), CDJs will display Camelot notation.

**Traffic light / related-key system:**
- Available on CDJ-2000NXS and later when linked via Pro DJ Link
- Works with classical notation by default
- Community-confirmed to also work with Camelot notation (the system understands the harmonic relationships)
- Does NOT work with Open Key notation (Traktor's `1d`, `2m` system)

**Rekordbox display options (v5.4.3+):**
- "Classic" mode: `Abm`, `B`, `Ebm`, `F#`
- "Alphanumeric" mode: `1A`, `1B`, `2A`, `2B` (Camelot-style)

**Recommendation for CrateAI:** Store keys internally in a normalised form (e.g. integer 1-24 mapping to the Camelot wheel), and convert to the user's preferred notation on display/export. Support both classical and Camelot output.

### 2.5 Character Encoding

- All CDJ models from the CDJ-2000 onwards support UTF-8 for tag display.
- The XML spec mandates UTF-8 encoding.
- Standard XML entity encoding for special characters.
- No known issues with non-Latin characters on modern CDJs, though older models (CDJ-1000 era) had limited character set support.
- **Safe practice:** Use UTF-8 throughout. Avoid exotic Unicode characters in filenames (stick to ASCII for paths where possible, for maximum cross-platform compatibility).

### 2.6 Album Art

**Embedding format:** JPEG (.jpg/.jpeg) or PNG (.png) embedded as an APIC frame in ID3v2 tags.

**Size constraints:**
- The CDJ-900NXS manual specifies a maximum of 800x800 pixels for display.
- When Rekordbox exports to USB, it creates resized copies: 80x80 (for legacy hardware compatibility) and 240x240 (for newer displays like CDJ-3000).
- Source artwork can be larger (600x600 or 800x800 is common from stores like Beatport).
- **Recommendation:** Embed artwork at 600x600 JPEG. This is a good balance between quality and file size, and Rekordbox will create its own scaled versions on USB export.

**AIFF artwork notes:** Rekordbox has historically had some issues reading embedded artwork from AIFF files, though this was largely resolved in later versions. Writing artwork via mutagen's AIFF support should work, but this is an area to test empirically.

### 2.7 Model-by-Model Generational Differences

Rather than listing every model, the meaningful generational shifts are:

**Pre-USB era (CDJ-1000 and earlier):** CD playback only. Not relevant to us.

**Generation 1 — USB basics (CDJ-2000, CDJ-900, CDJ-850, 2009-2012):**
- MP3, AAC, WAV, AIFF via USB
- ID3 tag reading for basic fields
- No key display or related-tracks feature
- 16/24 bit, 44.1/48kHz

**Generation 2 — Nexus (CDJ-2000NXS, CDJ-900NXS, 2012-2015):**
- Added: key display, traffic light system for harmonic mixing
- Pro DJ Link with metadata sharing between linked players
- Beat sync, improved waveform display
- Same format support as Gen 1

**Generation 3 — NXS2 (CDJ-2000NXS2, XDJ-1000MK2, 2016):**
- Added: FLAC and ALAC support
- Improved tag handling
- Track Filter / My Tag support (added via firmware)
- Higher resolution displays for artwork

**Generation 4 — CDJ-3000 (2020+):**
- Added: exFAT USB support, improved Touch Strip
- Track Filter with My Tag natively
- 9" touch screen, much higher resolution artwork display
- Same broad format support as NXS2

**The practical implication:** The differences that matter for our tag-writing strategy are minimal. The core tag fields (title, artist, BPM, key, genre, comment, album, label) work consistently across all USB-capable CDJs. The main variable is FLAC/ALAC support (flagship-only).

---

## 3. Design Recommendations

### 3.1 Database Schema — Tracks Table

Based on the Rekordbox XML track schema, here is the recommended `tracks` table design. Fields are grouped by source.

**Core identification:**
- `id` — INTEGER PRIMARY KEY (our internal ID)
- `file_path` — TEXT NOT NULL (absolute path on disk; converted to URI on XML export)
- `file_hash` — TEXT (SHA-256 hash for duplicate detection)

**Audio properties (from ffprobe, stored on ingest):**
- `source_format` — TEXT (original format: "mp3", "aiff", "wav", "flac", "alac", "aac")
- `output_format` — TEXT (format after conversion: "aiff", "mp3", or same as source if left as-is)
- `codec` — TEXT (actual codec, important for M4A inspection: "alac", "aac", "pcm_s16le", etc.)
- `bit_rate` — INTEGER (Kbps)
- `sample_rate` — INTEGER (Hz, e.g. 44100)
- `bit_depth` — INTEGER (16, 24, or NULL for lossy)
- `duration` — REAL (seconds)
- `file_size` — INTEGER (bytes)
- `channels` — INTEGER (should be 2 for stereo)
- `is_lossy` — BOOLEAN (derived: True for MP3/AAC, False for AIFF/WAV/FLAC/ALAC)
- `quality_warning` — TEXT (NULL, or "low_bitrate" for <192kbps lossy)

**Metadata (from tags, user edits, or AI enrichment):**
- `title` — TEXT
- `artist` — TEXT
- `album` — TEXT
- `genre` — TEXT
- `composer` — TEXT
- `remixer` — TEXT
- `label` — TEXT
- `mix_name` — TEXT (maps to Rekordbox "Mix" field, e.g. "Original Mix")
- `grouping` — TEXT
- `year` — INTEGER
- `track_number` — INTEGER
- `disc_number` — INTEGER
- `comment` — TEXT
- `key` — INTEGER (normalised 1-24 Camelot mapping; NULL if unknown) — see 3.2
- `key_text` — TEXT (the string representation, written to tags and XML: "Am", "8A", etc.)
- `bpm` — REAL (float, two decimal places to match Rekordbox precision)
- `rating` — INTEGER (0-5 stars internally; convert to 0/51/102/153/204/255 on XML export)
- `colour` — TEXT (hex RGB string, or NULL)

**AI enrichment fields (Module C):**
- `energy` — INTEGER (1-10 scale)
- `mood` — TEXT
- `ai_genre` — TEXT (AI-inferred genre/subgenre)
- `ai_confidence` — REAL (0.0-1.0)
- `ai_tags` — TEXT (JSON blob for additional AI-generated descriptors)

**Operational fields:**
- `date_added` — TEXT (yyyy-mm-dd)
- `date_modified` — TEXT (yyyy-mm-dd)
- `play_count` — INTEGER DEFAULT 0
- `last_played` — TEXT (yyyy-mm-dd, or NULL)
- `conversion_status` — TEXT ("pending", "converted", "skipped", "error")
- `organisation_status` — TEXT ("pending", "proposed", "confirmed", "error")

### 3.2 Key Storage Strategy

Store key as a normalised integer (1-24) internally, where:

| Internal | Camelot | Classical |
|:---:|:---:|:---:|
| 1 | 1A | Abm |
| 2 | 1B | B |
| 3 | 2A | Ebm |
| 4 | 2B | F# |
| 5 | 3A | Bbm |
| 6 | 3B | Db |
| 7 | 4A | Fm |
| 8 | 4B | Ab |
| 9 | 5A | Cm |
| 10 | 5B | Eb |
| 11 | 6A | Gm |
| 12 | 6B | Bb |
| 13 | 7A | Dm |
| 14 | 7B | F |
| 15 | 8A | Am |
| 16 | 8B | C |
| 17 | 9A | Em |
| 18 | 9B | G |
| 19 | 10A | Bm |
| 20 | 10B | D |
| 21 | 11A | F#m |
| 22 | 11B | A |
| 23 | 12A | Dbm |
| 24 | 12B | E |

This gives us:
- Easy harmonic compatibility calculations (adjacent numbers on the wheel = compatible keys; A/B at same number = relative major/minor)
- Clean conversion to any display format (Camelot, classical, Open Key)
- A user preference to choose display notation
- On XML export, write the `Tonality` field in the user's chosen notation (or Rekordbox classical by default)
- On ID3 tag write, write the `TKEY` frame in the same chosen notation

Also store `key_text` as the string that was actually written to tags/XML, for round-trip fidelity.

### 3.3 Tag Writing Strategy

**Primary target: ID3v2.3.**

Rationale:
- ID3v2.3 is the most broadly compatible version across all CDJ hardware, Rekordbox, and other DJ software (Serato, Traktor).
- ID3v2.4 is also supported, but v2.3 avoids any edge cases with older software or CDJ firmware.
- The differences between v2.3 and v2.4 that matter to us are minimal (TYER vs TDRC for year, mostly). Mutagen handles the conversion cleanly.
- Pioneer's own documentation for the XDJ-XZ confirms support for "ID3 tags (v1, v1.1, v2.2.0, v2.3.0 and v2.4.0)", so v2.3 is within the supported range everywhere.

**Implementation with mutagen:**
- For AIFF files: use `mutagen.aiff.AIFF` which embeds ID3v2 tags in the AIFF container
- For MP3 files: use `mutagen.mp3.MP3` with standard ID3v2 tags
- Call `tag.update_to_v23()` before saving with `v2_version=3`
- Do NOT write ID3v1 tags (set `v1=0` on save) — they cause more problems than they solve with Rekordbox

**Tag frame mapping:**

| Our Field | ID3v2 Frame | Notes |
|---|---|---|
| title | TIT2 | |
| artist | TPE1 | |
| album | TALB | |
| genre | TCON | Write as free text, not numeric genre ID |
| year | TYER (v2.3) | Four-digit year string |
| track_number | TRCK | Format: "N" or "N/Total" |
| disc_number | TPOS | Format: "N" or "N/Total" |
| bpm | TBPM | Integer string (round to nearest whole) |
| key | TKEY | User-preferred notation string |
| comment | COMM | Single COMM frame with empty description and `eng` language |
| composer | TCOM | |
| remixer | TPE4 | |
| label | TPUB | |
| grouping | TIT1 | |
| album art | APIC | JPEG, type 3 (Cover/Front), 600x600 recommended |

**"Target CDJ generation" setting:**

I'd recommend keeping this simple. Given the research findings, a binary setting is sufficient:

- **"Maximum compatibility" (default):** Write ID3v2.3, AIFF for lossless, MP3 for lossy. This works on every CDJ from 2009 onwards.
- **"Flagship features":** Same as above, but allows FLAC/ALAC pass-through without conversion (for users who know their venue has NXS2/CDJ-3000/XDJ-1000MK2).

There isn't enough variation in tag handling between models to justify a per-model compatibility dropdown. The format support is the real variable, not the tag handling.

### 3.4 XML Generation Approach

**Use Python's `xml.etree.ElementTree`** as planned in the project spec. It's sufficient for this task and has no dependencies.

**Generation rules:**

1. Write the XML declaration: `<?xml version="1.0" encoding="UTF-8" ?>`
2. Set `PRODUCT` to `Name="CrateAI"` with our version and company
3. For each track in our DB, generate a `<TRACK>` element with all attributes. Include empty strings for unset text fields (matches Rekordbox's own output).
4. Generate `Location` by: taking the absolute file path, converting to forward slashes, URL-encoding path components (but not the slashes), prepending `file://localhost/`
5. Convert our internal key integer to the user's preferred notation for `Tonality`
6. Convert our 0-5 star rating to the 0/51/102/153/204/255 scale for `Rating`
7. Format `AverageBpm` with two decimal places (e.g. "128.00")
8. Format dates as `yyyy-mm-dd`
9. Build the PLAYLISTS tree from our crates, using `KeyType="0"` with `TrackID` references
10. Ensure `Entries` counts are accurate

**Pitfalls to avoid:**
- Don't forget to XML-entity-encode attribute values (ElementTree handles this automatically)
- Don't forget to URI-encode the Location path
- Don't use `tostring()` without `xml_declaration=True` and `encoding="UTF-8"`
- Match Rekordbox's attribute ordering if possible (it makes diffs cleaner, though ordering doesn't affect functionality)
- Validate that the generated XML can be loaded by Rekordbox before considering the XML module complete — this requires actual empirical testing

### 3.5 Scope of CDJ Compatibility Work

**This is a "write ID3v2.3 and you're 95%+ covered" situation.**

The research clearly shows that CDJ tag handling is highly consistent across models. The meaningful differences are about format support (FLAC/ALAC on flagship only), not tag interpretation. All models that support USB playback support the same ID3v2 tag frames for the fields we care about.

The only real fragmentation is:
1. **FLAC/ALAC support** — handled by our converter (convert to AIFF)
2. **The comment field gotcha** with multiple COMM frames — handled by writing a single, clean COMM frame
3. **Key notation preferences** — handled by our configurable key display setting
4. **WAV metadata limitations** — handled by converting WAV to AIFF

**We do NOT need a compatibility layer from day one.** The combination of AIFF + ID3v2.3 + clean single-frame tags covers every realistic scenario.

---

## 4. Open Questions

These could not be fully resolved through research and need empirical testing:

### 4.1 Must Test Empirically

1. **Rekordbox XML import round-trip:** Generate a minimal test XML with a few tracks, load it into Rekordbox, and verify all fields are read correctly. This is the single most important validation before building the full XML module.

2. **AIFF artwork via mutagen:** Verify that artwork embedded in AIFF files via mutagen's `AIFF` class displays correctly in both Rekordbox and on CDJ hardware. Historical issues have been reported, though they should be resolved in current versions.

3. **Location path encoding edge cases:** Test paths with spaces, accents, apostrophes, ampersands, and non-ASCII characters to confirm our URI encoding matches what Rekordbox expects.

4. **TEMPO and POSITION_MARK generation:** If we want to export beat grid or cue points from our analysis, we need to test that our TEMPO/POSITION_MARK elements are accepted by Rekordbox. For Phase 4, we may want to start with just track metadata and add beat grid/cue export later.

5. **Rekordbox version compatibility:** Test our generated XML with both Rekordbox 6 and Rekordbox 7 to confirm compatibility across versions.

### 4.2 Design Decisions to Make

6. **Should we parse existing Rekordbox XML on import?** The project plan includes "Parse existing `rekordbox.xml`" in Phase 4. If we do, we need to handle the case where a user's existing Rekordbox library contains tracks we're also managing — merge strategy, conflict resolution, etc. This is a significant design decision.

7. **BPM precision:** Our analysis (librosa/aubio) will produce float BPM values. Rekordbox stores `AverageBpm` as a float with two decimal places, but the ID3 `TBPM` frame is an integer string. Should we write the rounded integer to ID3 and the precise float to XML? (Recommendation: yes.)

8. **Hot cue / memory cue colours:** The XML supports `POSITION_MARK` elements but the colour of cue points is not in the official spec — it's stored in Rekordbox's ANLZ binary files and database. We should confirm whether cue point colours can be set via XML import at all.

9. **exFAT vs FAT32:** The CDJ-3000 supports exFAT USB drives, but older models require FAT32. This isn't directly a tag/XML issue, but it affects the file organisation module — if users target older hardware, we may need to warn about the 4GB file size limit on FAT32 (relevant for very long lossless recordings).
