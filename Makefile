.PHONY: dev-backend dev-frontend build-backend build build-dmg test lint format

dev-backend:
	uv run uvicorn backend.main:app --reload --port 8420

dev-frontend:
	cd frontend && npm run tauri dev

build-backend:
	bash scripts/build-backend.sh

build: build-backend
	cd frontend && npm run tauri build

build-dmg:
	@echo "Building Python sidecar..."
	./scripts/build-backend.sh
	@echo "Building Tauri app + DMG..."
	cd frontend && npm run tauri build
	@echo "DMG ready at frontend/src-tauri/target/release/bundle/dmg/"

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy backend/

format:
	uv run ruff format .
	uv run ruff check --fix .
