# Rekordbox Import Test — Step-by-Step Guide

Test folder: `/Volumes/collection/music/import_test`
Output directory: `/Volumes/collection/music/rekordbot_library`
Project directory: `~/Documents/projects/rekordbot`

---

## Prerequisites

Ensure your `.env` file at the project root contains:

```
REKORDBOT_PORT=8420
REKORDBOT_DB_URL=sqlite:///rekordbot_dev.db
REKORDBOT_LOG_LEVEL=INFO
REKORDBOT_FFMPEG_PATH=ffmpeg
REKORDBOT_OUTPUT_DIRECTORY=/Volumes/collection/music/rekordbot_library
REKORDBOT_ANTHROPIC_API_KEY=your-key-here
```

The API key is only needed if you want to run the AI tagging step. The test is valid without it.

---

## Step 0: Apply the AIFF metadata bugfix

There is a known bug where ffmpeg drops metadata tags during lossless → AIFF conversion because the `-write_id3v2 1` flag is missing. This must be fixed before re-ingesting.

Run a Claude Code session with this prompt:

```
There is a bug in backend/services/converter.py — the AIFF conversion command
does not include the -write_id3v2 1 flag, so ffmpeg silently drops all metadata
tags when converting lossless files (FLAC, WAV, ALAC) to AIFF. Only a bare
title survives.

Fix:
1. In build_ffmpeg_command(), add "-write_id3v2", "1" to the AIFF conversion
   command, before the output path argument.

2. Add a test in the existing converter test file that verifies the
   -write_id3v2 flag is present in the generated AIFF command. The
   build_ffmpeg_command tests already exist — add a case that asserts
   "-write_id3v2" and "1" appear in the returned command list for
   convert_to_aiff actions.

3. Add a note to CLAUDE.md Known Issues:
   "ffmpeg AIFF muxer does not write ID3v2 tags by default — converter
   explicitly passes -write_id3v2 1 to preserve source metadata during
   lossless conversion."

Commit message: "Fix AIFF conversion dropping metadata tags (add -write_id3v2 flag)"

Do NOT modify any other files. This is a targeted bugfix.
```

Verify the fix:

```bash
make test
```

---

## Step 1: Clean slate

Delete the dev database and clear the output directory so we start fresh.

```bash
cd ~/Documents/projects/rekordbot
rm -f rekordbot_dev.db
rm -rf /Volumes/collection/music/rekordbot_library/*
```

---

## Step 2: Start the backend

```bash
make dev-backend
```

Wait for uvicorn to report it's running on port 8420.

---

## Step 3: Ingest

```bash
curl -X POST http://localhost:8420/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"paths": ["/Volumes/collection/music/import_test"]}'
```

**Expected:** 15 files processed (7 FLAC → AIFF, 1 AIF → AIFF, 6 MP3 copy, 1 M4A copy). Check uvicorn logs for errors.

**Verify output exists:**

```bash
ls /Volumes/collection/music/rekordbot_library/imports/2026-03-08/
```

**Verify AIFF metadata was preserved (the bugfix):**

```bash
ffprobe -v quiet -print_format json -show_format \
  "/Volumes/collection/music/rekordbot_library/imports/2026-03-08/01 - Goodbye Horses.aiff" \
  2>/dev/null | python3 -m json.tool | grep -A10 '"tags"'
```

You should see artist, album, genre etc. — not just a bare title. If tags are still missing, the bugfix didn't work. Stop and investigate.

---

## Step 4: Analyse

```bash
curl -X POST http://localhost:8420/api/tracks/analyse \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Expected:** 15 tracks analysed with BPM and key values. Takes 1–2 minutes. Watch uvicorn logs for progress.

---

## Step 5: AI tag (optional)

Only if you have `REKORDBOT_ANTHROPIC_API_KEY` set in `.env`:

```bash
curl -X POST http://localhost:8420/api/tracks/ai-tag \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Expected:** Tracks enriched with genre, subgenre, mood, energy. Watch uvicorn logs for token usage.

Skip this step if you don't have an API key — the test is valid without it.

---

## Step 6: Organise

### 6a: Propose

```bash
curl -X POST http://localhost:8420/api/organise/propose \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 6b: Check the proposal

```bash
curl http://localhost:8420/api/organise/proposal | python3 -m json.tool
```

Review the proposed paths. If any tracks are `review_needed`, check whether they have artist/album metadata:

```bash
curl http://localhost:8420/api/tracks | python3 -m json.tool \
  | grep -E '"(id|title|artist|album|organisation_status)"'
```

### 6c: Resolve review-needed tracks (if any)

For each track that needs review, you can resolve it manually:

```bash
curl -X POST http://localhost:8420/api/organise/resolve/{TRACK_ID} \
  -H "Content-Type: application/json" \
  -d '{"proposed_path": "Q Lazzarus/Goodbye Horses/Goodbye Horses.aiff"}'
```

### 6d: Approve

```bash
curl -X POST http://localhost:8420/api/organise/approve \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Expected:** All tracks moved to organised folder structure.

**Verify:**

```bash
ls /Volumes/collection/music/rekordbot_library/
```

You should see artist folders (Q Lazzarus, Sun Electric, Depeche Mode, etc.), not just the imports directory.

---

## Step 7: Export XML

```bash
curl -X POST http://localhost:8420/api/export/rekordbox \
  -H "Content-Type: application/json" \
  -d '{}'
```

**Expected:** XML file created. Response shows exported count and any warnings.

**Verify the XML:**

```bash
head -30 /Volumes/collection/music/rekordbot_library/rekordbox.xml
```

Check for: XML declaration, `DJ_PLAYLISTS` root, `PRODUCT Name="rekordbot"`, `COLLECTION Entries="15"`.

---

## Step 8: Import into Rekordbox

1. Open Rekordbox (6 or 7)
2. **File → Import Library**
3. Select `/Volumes/collection/music/rekordbot_library/rekordbox.xml`
4. A new library source appears in the left sidebar (labelled "rekordbot")
5. Click into it to browse the imported collection

---

## Step 9: Verify in Rekordbox

### Critical (pass/fail)

- [ ] Tracks are **not** greyed out / missing — Location encoding works
- [ ] You can **play** at least one track — file path resolves end to end

### Metadata fields (check 3+ tracks)

- [ ] Title displays correctly (including special characters)
- [ ] Artist displays correctly
- [ ] Album displays correctly (or blank if none)
- [ ] BPM shows correct value with decimal precision
- [ ] Key displays in correct notation (Camelot or classical)
- [ ] Genre displays correctly
- [ ] Rating shows correct star count (if any rated)
- [ ] Label displays correctly (if populated)
- [ ] Comment displays correctly (if populated)
- [ ] Duration is correct (not zero, not wildly off)

### Playlists

- [ ] "All Tracks" playlist exists and contains all tracks
- [ ] Per-artist playlists exist with correct tracks
- [ ] Playlist track counts are accurate

### Bug indicators

| Symptom | Likely cause |
|---------|-------------|
| Tracks greyed out / missing | Location encoding bug |
| BPM showing 0.00 | format_bpm issue |
| Key blank when should be populated | Key notation conversion issue |
| Garbled characters | XML encoding issue |
| Wrong star count | Non-linear rating scale wrong |
| All metadata null on AIFF tracks | -write_id3v2 bugfix didn't take |

---

## Step 10: Record results

Update `SESSIONS.md` with:
- Date
- Pass/fail for each checklist item
- Any issues found
- Screenshots if helpful

If everything passes, Phase 4 is clear to merge.
