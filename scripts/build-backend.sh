#!/usr/bin/env bash
set -euo pipefail

# Build the Python backend with PyInstaller in --onedir mode
# and place the executable + _internal in the Tauri binaries directory.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$PROJECT_ROOT/dist"
TAURI_BIN_DIR="$PROJECT_ROOT/frontend/src-tauri/binaries"

# Determine target triple
ARCH=$(uname -m)
OS=$(uname -s | tr '[:upper:]' '[:lower:]')

case "$ARCH" in
    arm64) RUST_ARCH="aarch64" ;;
    x86_64) RUST_ARCH="x86_64" ;;
    *) echo "Unsupported architecture: $ARCH"; exit 1 ;;
esac

case "$OS" in
    darwin) RUST_TARGET="${RUST_ARCH}-apple-darwin" ;;
    linux) RUST_TARGET="${RUST_ARCH}-unknown-linux-gnu" ;;
    *) echo "Unsupported OS: $OS"; exit 1 ;;
esac

SIDECAR_NAME="rekordbot-server-${RUST_TARGET}"

echo "Building backend for target: $RUST_TARGET"

# Run PyInstaller
cd "$PROJECT_ROOT"
uv run pyinstaller \
    --onedir \
    --name rekordbot-server \
    --noconfirm \
    --clean \
    --add-data "backend/alembic.ini:backend" \
    --add-data "backend/alembic:backend/alembic" \
    backend/main.py

# Create Tauri binaries directory
mkdir -p "$TAURI_BIN_DIR"

# Copy the executable with target-triple name (Tauri externalBin requirement)
cp "$DIST_DIR/rekordbot-server/rekordbot-server" "$TAURI_BIN_DIR/$SIDECAR_NAME"

# Copy the _internal directory alongside it (PyInstaller --onedir dependencies)
rm -r "$TAURI_BIN_DIR/_internal" 2>/dev/null || true
cp -r "$DIST_DIR/rekordbot-server/_internal" "$TAURI_BIN_DIR/_internal"

echo "Backend built successfully: $TAURI_BIN_DIR/$SIDECAR_NAME"
