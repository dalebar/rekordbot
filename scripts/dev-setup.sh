#!/usr/bin/env bash
set -euo pipefail

# One-command development environment setup for rekordbot.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "=== rekordbot dev setup ==="

# Python environment
echo "Creating Python virtual environment..."
uv venv

echo "Installing Python dependencies..."
uv sync --all-extras

# Pre-commit hooks
echo "Installing pre-commit hooks..."
uv run pre-commit install

# Frontend dependencies
if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
    echo "Installing frontend dependencies..."
    cd frontend
    npm install
    cd "$PROJECT_ROOT"
else
    echo "Skipping frontend setup (not yet scaffolded)"
fi

# Check for ffmpeg
if command -v ffmpeg &> /dev/null; then
    echo "ffmpeg found: $(which ffmpeg)"
else
    echo "WARNING: ffmpeg not found. Install with: brew install ffmpeg"
fi

# Check for Rust toolchain
if command -v rustc &> /dev/null; then
    echo "Rust found: $(rustc --version)"
else
    echo "WARNING: Rust not found. Install from: https://rustup.rs/"
fi

echo "=== Setup complete ==="
