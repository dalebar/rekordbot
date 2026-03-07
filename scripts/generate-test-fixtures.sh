#!/bin/bash
# Generate small test audio fixtures (~1 second silence) for each supported format.
# Run this script once; output is committed to backend/tests/fixtures/audio/.

set -euo pipefail

OUTDIR="backend/tests/fixtures/audio"
mkdir -p "$OUTDIR"

echo "Generating test audio fixtures..."

# WAV 16-bit PCM
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -c:a pcm_s16le "$OUTDIR/silence_16bit.wav" 2>/dev/null
echo "  silence_16bit.wav"

# WAV 24-bit PCM
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -c:a pcm_s24le "$OUTDIR/silence_24bit.wav" 2>/dev/null
echo "  silence_24bit.wav"

# FLAC 16-bit
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -c:a flac -sample_fmt s16 "$OUTDIR/silence_16bit.flac" 2>/dev/null
echo "  silence_16bit.flac"

# AIFF 16-bit
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -c:a pcm_s16be -f aiff "$OUTDIR/silence_16bit.aiff" 2>/dev/null
echo "  silence_16bit.aiff"

# MP3 (320 kbps)
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -c:a libmp3lame -b:a 320k "$OUTDIR/silence_320k.mp3" 2>/dev/null
echo "  silence_320k.mp3"

# MP3 (128 kbps — below quality threshold)
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -c:a libmp3lame -b:a 128k "$OUTDIR/silence_128k.mp3" 2>/dev/null
echo "  silence_128k.mp3"

# M4A with ALAC
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -c:a alac "$OUTDIR/silence_alac.m4a" 2>/dev/null
echo "  silence_alac.m4a"

# M4A with AAC
ffmpeg -y -f lavfi -i anullsrc=r=44100:cl=stereo -t 1 -c:a aac -b:a 256k "$OUTDIR/silence_aac.m4a" 2>/dev/null
echo "  silence_aac.m4a"

echo "Done. Generated $(ls "$OUTDIR" | wc -l | tr -d ' ') fixtures in $OUTDIR/"
