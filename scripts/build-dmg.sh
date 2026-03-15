#!/usr/bin/env bash
set -euo pipefail

# Build the complete .dmg distributable for rekordbot.
#
# Pipeline:
#   1. Build Python sidecar with PyInstaller (--onedir)
#   2. Build Tauri .app bundle (frontend + Rust shell)
#   3. Inject PyInstaller _internal/ into .app as Contents/MacOS/sidecar/
#   4. Create .dmg from the .app
#
# The sidecar is placed in a sidecar/ subdirectory inside Contents/MacOS/
# to prevent PyInstaller's bootloader from detecting .app bundle mode,
# which would change library resolution paths and break the sidecar.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
TAURI_DIR="$FRONTEND_DIR/src-tauri"
BINARIES_DIR="$TAURI_DIR/binaries"
APP_NAME="rekordbot"
APP_BUNDLE="$TAURI_DIR/target/release/bundle/macos/${APP_NAME}.app"
DMG_DIR="$TAURI_DIR/target/release/bundle/dmg"
VERSION="0.1.0"

# Determine architecture
ARCH=$(uname -m)
case "$ARCH" in
    arm64) RUST_ARCH="aarch64" ;;
    x86_64) RUST_ARCH="x86_64" ;;
    *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac
DMG_NAME="${APP_NAME}_${VERSION}_${RUST_ARCH}.dmg"

echo "=== Step 1: Building Python sidecar ==="
"$SCRIPT_DIR/build-backend.sh"

echo ""
echo "=== Step 2: Building Tauri .app ==="
cd "$FRONTEND_DIR" && npm run tauri build

echo ""
echo "=== Step 3: Injecting PyInstaller _internal/ into .app bundle ==="
SIDECAR_DIR="$APP_BUNDLE/Contents/MacOS/sidecar"
mkdir -p "$SIDECAR_DIR"

# Copy the sidecar executable (Tauri already placed one at Contents/MacOS/,
# but we need a second copy in the sidecar/ subdirectory)
cp "$APP_BUNDLE/Contents/MacOS/rekordbot-server" "$SIDECAR_DIR/rekordbot-server"

# Copy PyInstaller's _internal/ directory
echo "Copying _internal/ (~200MB)..."
cp -R "$BINARIES_DIR/_internal" "$SIDECAR_DIR/_internal"

echo "Sidecar directory created at: $SIDECAR_DIR"
ls "$SIDECAR_DIR" | head -5
echo "..."

echo ""
echo "=== Step 4: Creating .dmg ==="
mkdir -p "$DMG_DIR"
DMG_PATH="$DMG_DIR/$DMG_NAME"

# Remove existing .dmg if present
rm -f "$DMG_PATH"

# Create .dmg with Applications shortcut
hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$APP_BUNDLE" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

echo ""
echo "=== Build complete ==="
echo ".app: $APP_BUNDLE"
echo ".dmg: $DMG_PATH"
